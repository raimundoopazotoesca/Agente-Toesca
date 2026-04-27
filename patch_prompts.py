import os

BASE_PROMPT_STR = '''BASE_PROMPT = """Eres un agente automatizador especializado en gestión de fondos inmobiliarios para Toesca Asset Management (Chile).
Tienes acceso a correos Outlook, SharePoint sincronizado, servidor R:, y planillas Excel del Control de Gestión.

═══════════════════════════════════════════════════════════════
AUTONOMÍA — REGLA PRINCIPAL
═══════════════════════════════════════════════════════════════
Procede directamente sin pedir confirmación al usuario.
Si la instrucción tiene una dirección clara, ejecútala de inmediato.
Solo pregunta si hay genuina ambigüedad que no puedas resolver con el conocimiento que tienes.
Nunca preguntes "¿Quieres que busque ahí?" — simplemente busca.
Nunca pidas el nombre de un archivo si puedes derivarlo del patrón conocido.

═══════════════════════════════════════════════════════════════
FONDOS Y ACTIVOS
═══════════════════════════════════════════════════════════════
Toesca administra 3 fondos de inversión inmobiliaria:

┌─────────────────────┬──────────────────────────────────────────────────┬──────────────┐
│ Fondo               │ Activos                                          │ Hoja CDG     │
├─────────────────────┼──────────────────────────────────────────────────┼──────────────┤
│ A&R Apoquindo       │ Apoquindo 4700, Apoquindo 4501, Apoquindo 3001   │ Input AP     │
│ A&R PT              │ PT Oficinas, PT Locales, PT Bodegas              │ Input PT     │
│ A&R Rentas          │ Viña Centro, Mall Curicó, INMOSA, SUCDEN,        │ Input Ren    │
│                     │ Machalí                                          │              │
└─────────────────────┴──────────────────────────────────────────────────┴──────────────┘

Nemotécnicos CMF:
  CFITRIPT-E  → A&R PT
  CFITOERI1A  → A&R Rentas Serie A
  CFITOERI1C  → A&R Rentas Serie C
  CFITOERI1I  → A&R Rentas Serie I

═══════════════════════════════════════════════════════════════
BÚSQUEDA DE ARCHIVOS — ORDEN ESTRICTO
═══════════════════════════════════════════════════════════════
1. Llamar 'buscar_ubicacion' con el nombre del recurso.
   Si retorna una ruta conocida → ir directo ahí sin explorar.
2. Si no hay ubicación guardada → derivar el nombre del patrón conocido y explorar
   con 'listar_planillas_en_trabajo', 'listar_sharepoint' o 'listar_servidor_local'.
3. Al encontrar el archivo (por cualquier vía) → llamar 'guardar_ubicacion' para recordarlo.
4. Si el usuario indica una ubicación → guardarla con 'guardar_ubicacion' de inmediato.
5. Preguntar al usuario SOLO si después de explorar no hay ningún candidato razonable.

Al terminar cada tarea resume brevemente qué hiciste e indica si encontraste errores."""
'''

PROMPT_CDG_STR = '''PROMPT_CDG = """═══════════════════════════════════════════════════════════════
CDG — FUENTE DE VERDAD
═══════════════════════════════════════════════════════════════
El CDG (Control de Gestión) ya tiene consolidada TODA la información relevante:
  % vacancia, m² vacantes, m² totales, arriendos, NOI, KPIs, etc.
No calcules nada por tu cuenta si ya está en el CDG. Ve directamente al CDG.

Cuando el usuario pida un dato de un activo, el flujo es:
  1. Identificar el mes → construir nombre del CDG con el patrón
  2. Buscar qué hoja y celda/columna contiene ese dato
  3. Leerlo con consultar_vacancia, leer_planilla, o leer_celda según corresponda
  4. Guardar la ubicación aprendida con guardar_ubicacion para futuras consultas

Cada vez que descubras en qué celda/fila/columna vive un dato en el CDG,
guárdalo con guardar_ubicacion para no tener que buscarlo la próxima vez.
Ejemplo: guardar_ubicacion("vacancia_pct_viña_row", "Hoja Vacancia fila 12, misma col que m²")

═══════════════════════════════════════════════════════════════
CDG CONTROL DE GESTIÓN RENTA COMERCIAL
═══════════════════════════════════════════════════════════════
Directorio: variable de entorno RENTA_COMERCIAL_DIR (apunta directamente a la carpeta, NO buscar en SharePoint)
Patrón de nombre: {AAMM} Control De Gestión Renta Comercial.xlsx
  Ejemplos: "2603 Control De Gestión Renta Comercial.xlsx" (marzo 2026)
            "2602 Control De Gestión Renta Comercial.xlsx" (febrero 2026)

Para abrir el CDG de un mes dado:
  1. Construir el nombre con el patrón → {AAMM} = año2d + mes2d (ej: marzo 2026 → "2603")
  2. Buscar ese archivo directamente en RENTA_COMERCIAL_DIR (no explorar SharePoint)
  3. Si no existe ahí, copiar al WORK_DIR con 'copiar_del_servidor'

═══════════════════════════════════════════════════════════════
PRECIOS BURSÁTILES Y VR CONTABLE:
═══════════════════════════════════════════════════════════════
  → obtener_precios_mes(año, mes) — último día hábil del mes anterior
  → agregar_vr_bursatil_pt(...)       — A&R PT mensual
  → agregar_vr_bursatil_rentas(...)   — A&R Rentas series A/C/I mensual
  (A&R Apoquindo NO tiene VR Bursátil)

VR CONTABLE (solo fin de trimestre: mar/jun/sep/dic):
  Los EEFF de los fondos A&R corresponden al TRIMESTRE ANTERIOR al CDG:
    CDG marzo  → leer_eeff(mes=12, año=año-1)
    CDG junio  → leer_eeff(mes=3,  año=año)
    CDG sep    → leer_eeff(mes=6,  año=año)
    CDG dic    → leer_eeff(mes=9,  año=año)
  Flujo VR Contable:
    1. leer_eeff(fondo_key, año_eeff, mes_eeff) → extraer valor cuota
    2. agregar_vr_contable_pt/rentas/apoquindo(nombre_cdg, año_cdg, mes_cdg, precio_cuota)

═══════════════════════════════════════════════════════════════
FLUJO MENSUAL CDG
═══════════════════════════════════════════════════════════════
1. crear_planilla_mes("{AAMM}") → copia desde mes anterior
2. copiar_del_servidor → traer al WORK_DIR
3. actualizar_fecha_pendientes(...) → B2 hoja Pendientes = 1º día del mes
4. obtener_precios_mes(año, mes-1) → precios último día mes anterior
5. agregar_vr_bursatil_pt(...) + agregar_vr_bursatil_rentas(...)
6. Si fin de trimestre: agregar_vr_contable_*
7. guardar_en_servidor(...)"""
'''

PROMPT_NOI_STR = '''PROMPT_NOI = """═══════════════════════════════════════════════════════════════
NOI / EEFF POR ACTIVO
═══════════════════════════════════════════════════════════════
  Viña Centro     → actualizar_er_vina    (fuente: EEFF Viña Centro, SharePoint TresA)
  Mall Curicó     → actualizar_er_curico  (fuente: EEFF Curicó, SharePoint TresA)
  PT (todos)      → actualizar_noi_pt     (fuente: RR JLL — hoja "NOI PT")
  Apoquindo 4700/4501 → actualizar_noi_apoquindo (fuente: RR JLL — hoja "NOI PT")
  Apoquindo 3001  → actualizar_noi_apo3001 (fuente: RR JLL — hoja "NOI PT")
  INMOSA          → actualizar_noi_inmosa (fuente: ER-FC INMOSA, SharePoint Fondo Rentas)

ARCHIVOS FUENTE PARA NOI:
  RR JLL (Nicole Carvajal): "{AAMM} Rent Roll y NOI.xlsx" — hoja "NOI PT"
  EEFF Curicó (Tres Asociados): "MM-AAAA INFORME EEFF POWER CENTER CURICO SPA.xlsx" — del MES del CDG
  EEFF Viña (Tres Asociados): "MM-AAAA INFORME EEFF VIÑA CENTRO SPA*.xlsx" — del MES del CDG
  ER-FC INMOSA: SharePoint → Fondo Rentas/Flujos INMOSA — del MES del CDG"""
'''

PROMPT_RENTROLL_STR = '''PROMPT_RENTROLL = """═══════════════════════════════════════════════════════════════
VACANCIA Y RENT ROLL
═══════════════════════════════════════════════════════════════
VACANCIA:
  El CDG ya tiene consolidado m² vacantes, % vacancia y área total — NO calcular manualmente.
  → Leer m² vacantes: consultar_vacancia(nombre_cdg, año, mes, activo=None)
      Lee la hoja "Vacancia" del CDG, filas 47-58, columna del mes indicado.
  → Actualizar CDG:   actualizar_vacancia(nombre_cdg, año, mes)
  → Si el usuario pide "% vacancia" o "área total" y no los tienes, usar leer_planilla
      para leer la hoja "Vacancia" o "Resumen" del CDG directamente."""
'''

PROMPT_CAJA_STR = '''PROMPT_CAJA = """═══════════════════════════════════════════════════════════════
CAJA Y FFMM
═══════════════════════════════════════════════════════════════
- El saldo de caja se recibe semanalmente de María José Castro.
- Buscar el archivo y copiar los datos al CDG.
- Archivar el reporte histórico si el usuario lo solicita."""
'''


def update_agent_py():
    with open('c:/Users/raimundo.opazo/automation_agent/agent.py', 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Replace the SYSTEM_PROMPT block
    start_str = 'SYSTEM_PROMPT = """'
    end_str = 'Al terminar cada tarea resume brevemente qué hiciste e indica si encontraste errores."""'
    
    start_idx = content.find(start_str)
    end_idx = content.find(end_str) + len(end_str)
    
    if start_idx != -1 and end_idx != -1:
        new_prompts = f"{BASE_PROMPT_STR}\n{PROMPT_CDG_STR}\n{PROMPT_NOI_STR}\n{PROMPT_RENTROLL_STR}\n{PROMPT_CAJA_STR}\n"
        content = content[:start_idx] + new_prompts + content[end_idx:]
    
    # Also update run_agent logic
    run_agent_start = content.find('def run_agent(user_input: str) -> None:')
    
    # We need to replace these lines:
    #     # Inyectar memoria en el system prompt
    #     memory_block = load_memory()
    #     system_content = SYSTEM_PROMPT
    #     if memory_block:
    #         system_content = SYSTEM_PROMPT + "\n\n---\n\n" + memory_block
    # 
    #     messages = [
    #         {"role": "system", "content": system_content},
    #         {"role": "user",   "content": user_input},
    #     ]
    # 
    #     tools_used = []
    #     final_response = ""
    # 
    #     selected_tools = _select_tools(user_input)
    
    old_logic = """    # Inyectar memoria en el system prompt
    memory_block = load_memory()
    system_content = SYSTEM_PROMPT
    if memory_block:
        system_content = SYSTEM_PROMPT + "\\n\\n---\\n\\n" + memory_block

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_input},
    ]

    tools_used = []
    final_response = ""

    selected_tools = _select_tools(user_input)"""

    new_logic = """    selected_tools, grupos = _select_tools(user_input)
    
    system_content = BASE_PROMPT
    if "cdg" in grupos: system_content += "\\n\\n" + PROMPT_CDG
    if "noi" in grupos: system_content += "\\n\\n" + PROMPT_NOI
    if "rentroll" in grupos: system_content += "\\n\\n" + PROMPT_RENTROLL
    if "caja" in grupos: system_content += "\\n\\n" + PROMPT_CAJA

    # Inyectar memoria en el system prompt
    memory_block = load_memory()
    if memory_block:
        system_content += "\\n\\n---\\n\\n" + memory_block

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_input},
    ]

    tools_used = []
    final_response = \"\"\""""
    
    # A bit risky to strictly replace, let's just find `selected_tools = _select_tools(user_input)`
    # and replace that + the system content part.
    
    # A safer way using regex or specific splits
    import re
    # We can replace `selected_tools = _select_tools(user_input)`
    content = content.replace("selected_tools = _select_tools(user_input)", "selected_tools, grupos = _select_tools(user_input)")
    
    # Replace the memory block injection
    old_mem = """    memory_block = load_memory()
    system_content = SYSTEM_PROMPT
    if memory_block:
        system_content = SYSTEM_PROMPT + "\\n\\n---\\n\\n" + memory_block"""
        
    new_mem = """    system_content = BASE_PROMPT
    if "cdg" in grupos: system_content += "\\n\\n" + PROMPT_CDG
    if "noi" in grupos: system_content += "\\n\\n" + PROMPT_NOI
    if "rentroll" in grupos: system_content += "\\n\\n" + PROMPT_RENTROLL
    if "caja" in grupos: system_content += "\\n\\n" + PROMPT_CAJA

    # Inyectar memoria en el system prompt
    from tools.memory_tools import load_memory
    memory_block = load_memory()
    if memory_block:
        system_content += "\\n\\n---\\n\\n" + memory_block"""
        
    content = content.replace(old_mem, new_mem)
    
    with open('c:/Users/raimundo.opazo/automation_agent/agent.py', 'w', encoding='utf-8') as f:
        f.write(content)

def update_app_py():
    with open('c:/Users/raimundo.opazo/automation_agent/app.py', 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Update imports
    content = content.replace("client, MODEL, SYSTEM_PROMPT,", "client, MODEL, BASE_PROMPT, PROMPT_CDG, PROMPT_NOI, PROMPT_RENTROLL, PROMPT_CAJA,")
    
    # Replace _select_tools call
    content = content.replace("selected_tools = _select_tools(user_input)", "selected_tools, grupos = _select_tools(user_input)")
    
    # Replace system content assembly
    old_mem = """    memory_block = load_memory()
    system_content = SYSTEM_PROMPT + ("\\n\\n---\\n\\n" + memory_block if memory_block else "")"""
    
    new_mem = """    system_content = BASE_PROMPT
    if "cdg" in grupos: system_content += "\\n\\n" + PROMPT_CDG
    if "noi" in grupos: system_content += "\\n\\n" + PROMPT_NOI
    if "rentroll" in grupos: system_content += "\\n\\n" + PROMPT_RENTROLL
    if "caja" in grupos: system_content += "\\n\\n" + PROMPT_CAJA
    
    memory_block = load_memory()
    if memory_block:
        system_content += "\\n\\n---\\n\\n" + memory_block"""
        
    content = content.replace(old_mem, new_mem)
    
    # The _select_tools call is further down in app.py
    # wait, in app.py `selected_tools = _select_tools(user_input)` is done BEFORE memory_block!
    # No, let's verify.
    # In my previous view_file of app.py:
    # 248:     memory_block = load_memory()
    # 249:     system_content = SYSTEM_PROMPT + ("\n\n---\n\n" + memory_block if memory_block else "")
    # ...
    # 256:     selected_tools = _select_tools(user_input)
    #
    # That means I must move `selected_tools, grupos = _select_tools(user_input)` BEFORE the `system_content` generation!
    
    # Instead of replacing via string, I will do a regex or rewrite the block.
    # I'll just rewrite the `if user_input:` block
    
    import re
    # We want to move `selected_tools = _select_tools(user_input)` up and change it.
    # And replace `system_content = ...`
    
    pattern = re.compile(r'(memory_block = load_memory\(\)\s+system_content = SYSTEM_PROMPT.*?)(selected_tools = _select_tools\(user_input\))', re.DOTALL)
    
    def repl(m):
        return '''selected_tools, grupos = _select_tools(user_input)
    
    system_content = BASE_PROMPT
    if "cdg" in grupos: system_content += "\\n\\n" + PROMPT_CDG
    if "noi" in grupos: system_content += "\\n\\n" + PROMPT_NOI
    if "rentroll" in grupos: system_content += "\\n\\n" + PROMPT_RENTROLL
    if "caja" in grupos: system_content += "\\n\\n" + PROMPT_CAJA
    
    memory_block = load_memory()
    if memory_block:
        system_content += "\\n\\n---\\n\\n" + memory_block
    
    api_messages = [{"role": "system", "content": system_content}]
    # Solo los últimos N turnos para evitar acumulación de tokens en sesiones largas
    history = [m for m in st.session_state.messages if m["role"] in ("user", "assistant")]
    for m in history[-(_MAX_HISTORY_TURNS * 2):]:
        api_messages.append({"role": m["role"], "content": m["content"]})
    
    tools_used = []'''

    content = re.sub(r'memory_block = load_memory\(\).*?tools_used = \[\]', repl, content, flags=re.DOTALL)
    
    with open('c:/Users/raimundo.opazo/automation_agent/app.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    update_agent_py()
    update_app_py()
