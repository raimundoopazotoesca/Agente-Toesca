import json
import time
import random
from openai import OpenAI
from dotenv import load_dotenv
from config import GEMINI_API_KEY
from tools.registry import TOOL_DEFINITIONS, _dispatch, _select_tools

load_dotenv()

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

MODEL = "gemini-2.5-flash"
_MAX_TOOL_ITERS     = 20      # máximo de rondas tool-call por tarea (anti-loop-infinito)
_MIN_CALL_INTERVAL  = 1.5     # segundos mínimos entre llamadas a la API (suaviza RPM)
_last_call_at: float = 0.0    # timestamp de la última llamada exitosa


def _llm_call(**kwargs):
    """
    Llama a la API con:
      - throttle mínimo entre llamadas (_MIN_CALL_INTERVAL)
      - exponential backoff en 429 / quota exceeded (hasta 5 reintentos)
    """
    global _last_call_at
    # Throttle: esperar si la llamada anterior fue hace menos de _MIN_CALL_INTERVAL
    if _last_call_at > 0:
        since = time.time() - _last_call_at
        if since < _MIN_CALL_INTERVAL:
            time.sleep(_MIN_CALL_INTERVAL - since)

    for attempt in range(5):
        try:
            response = client.chat.completions.create(**kwargs)
            _last_call_at = time.time()
            return response
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "quota" in msg or "rate" in msg or "resource" in msg:
                wait = min((2 ** attempt) + random.uniform(0, 1), 60)
                print(f"  [429] Rate limit — esperando {wait:.0f}s (intento {attempt + 1}/5)...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Límite de reintentos alcanzado (5/5 intentos con error 429).")


BASE_PROMPT = """Eres un agente automatizador especializado en gestión de fondos inmobiliarios para Toesca Asset Management (Chile).
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

PROMPT_CDG = """═══════════════════════════════════════════════════════════════
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

PROMPT_NOI = """═══════════════════════════════════════════════════════════════
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

PROMPT_RENTROLL = """═══════════════════════════════════════════════════════════════
VACANCIA Y RENT ROLL
═══════════════════════════════════════════════════════════════
VACANCIA:
  El CDG ya tiene consolidado m² vacantes, % vacancia y área total — NO calcular manualmente.
  → Leer m² vacantes: consultar_vacancia(nombre_cdg, año, mes, activo=None)
      Lee la hoja "Vacancia" del CDG, filas 47-58, columna del mes indicado.
  → Actualizar CDG:   actualizar_vacancia(nombre_cdg, año, mes)
  → Si el usuario pide "% vacancia" o "área total" y no los tienes, usar leer_planilla
      para leer la hoja "Vacancia" o "Resumen" del CDG directamente."""

PROMPT_CAJA = """═══════════════════════════════════════════════════════════════
CAJA Y FFMM
═══════════════════════════════════════════════════════════════
- El saldo de caja se recibe semanalmente de María José Castro.
- Buscar el archivo y copiar los datos al CDG.
- Archivar el reporte histórico si el usuario lo solicita."""









# Herramientas que siempre se incluyen (archivos, memoria, utilidades generales)
# ─── Runner principal ─────────────────────────────────────────────────────────


def get_intent_groups(history_text: str) -> set:
    prompt = f"""Dado el historial de chat con un asistente que automatiza tareas de un fondo de inversión inmobiliario, clasifica la intención del usuario.
Responde ÚNICAMENTE con una lista JSON válida de strings (ejemplo: ["cdg", "noi"]).
Las categorías permitidas son:
- "cdg" (Control de Gestión, planillas, archivos, actualizar control, tirar reportes)
- "noi" (NOI, Viña, Curicó, JLL, INMOSA, Apoquindo)
- "caja" (Saldo Caja, FFMM, archivar caja)
- "rentroll" (Rent Roll, vacancia, absorción)
- "factsheet" (Fact Sheet, FS, presentación del fondo, actualizar fact sheet, generar fact sheet)
Si no aplica ninguna, responde [].

Historial de conversación:
{history_text}
"""
    try:
        response = _llm_call(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        msg_content = response.choices[0].message.content.strip()
        if msg_content.startswith("```json"): msg_content = msg_content[7:-3].strip()
        elif msg_content.startswith("```"): msg_content = msg_content[3:-3].strip()
        
        import json
        grupos_list = json.loads(msg_content)
        return set(grupos_list)
    except Exception as e:
        print(f"[LLM Router Error] {e}")
        return set()

def run_agent(user_input: str) -> None:
    print("\\n" + "=" * 60)
    print(f"Instrucción: {user_input}")
    print("=" * 60)

    grupos = get_intent_groups(user_input)
    selected_tools = _select_tools(grupos)

    system_content = BASE_PROMPT
    if "cdg" in grupos: system_content += "\\n\\n" + PROMPT_CDG
    if "noi" in grupos: system_content += "\\n\\n" + PROMPT_NOI
    if "rentroll" in grupos: system_content += "\\n\\n" + PROMPT_RENTROLL
    if "caja" in grupos: system_content += "\\n\\n" + PROMPT_CAJA

    from tools.memory_tools import load_memory
    memory_block = load_memory()
    if memory_block:
        system_content += "\\n\\n---\\n\\n" + memory_block

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_input},
    ]

    tools_used = []
    final_response = ""

    n_selected = len(selected_tools)
    n_total = len(TOOL_DEFINITIONS)
    if n_selected < n_total:
        print(f"  [tools] {n_selected}/{n_total} herramientas activas")

    try:
        iteration = 0
        while True:
            iteration += 1
            if iteration > _MAX_TOOL_ITERS:
                final_response = (
                    f"⚠️ Límite de {_MAX_TOOL_ITERS} rondas de herramientas alcanzado. "
                    "La tarea puede estar incompleta. Reformula la instrucción o divídela en pasos."
                )
                print(f"\n[WARN] Límite de iteraciones ({_MAX_TOOL_ITERS}) alcanzado.")
                break

            response = _llm_call(
                model=MODEL,
                messages=messages,
                tools=selected_tools,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            messages.append(msg)

            if not msg.tool_calls:
                if msg.content:
                    final_response = msg.content
                    print(f"\nAgente: {msg.content}")
                break

            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                print(f"\n  → Ejecutando: {name}({', '.join(f'{k}={v}' for k, v in args.items())})")

                result = _dispatch(name, args)
                print(f"  ✓ {result[:120]}{'...' if len(result) > 120 else ''}")

                if name not in tools_used:
                    tools_used.append(name)

                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      result,
                })

    except RuntimeError as e:
        final_response = f"⚠️ {e}"
        print(f"\n[ERROR] {e}")
    except Exception as e:
        final_response = f"⚠️ Error inesperado: {e}"
        print(f"\n[ERROR] Error inesperado: {e}")

    # Guardar tarea en historial
    if tools_used or final_response:
        resumen = final_response[:200] if final_response else "Tarea completada."
        guardar_tarea(user_input, tools_used, resumen)


def main() -> None:
    print("=" * 60)
    print("  AGENTE MICROSOFT 365  |  Outlook + SharePoint + Excel")
    print("=" * 60)
    print("Ejemplos:")
    print("  • Buscar correos nuevos con planillas adjuntas")
    print("  • Descargar y validar la planilla del último correo")
    print("  • Listar archivos Excel en R:\\")
    print("  • Copiar ventas_enero.xlsx del servidor y validarlo")
    print("  • 'salir' para terminar")
    print("-" * 60)

    while True:
        try:
            user_input = input("\n¿Qué deseas hacer? ").strip()
            if not user_input:
                continue
            if user_input.lower() in {"salir", "exit", "quit"}:
                print("¡Hasta luego!")
                break
            run_agent(user_input)

        except KeyboardInterrupt:
            print("\n\n¡Hasta luego!")
            break
        except Exception as e:
            print(f"\nError inesperado: {e}")


if __name__ == "__main__":
    main()
