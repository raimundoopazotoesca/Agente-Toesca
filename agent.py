import json
import re
import time
import random
import sys
import threading
import itertools
from openai import OpenAI
from dotenv import load_dotenv
from config import GEMINI_API_KEY
from tools.registry import TOOL_DEFINITIONS, _dispatch, _select_tools

load_dotenv()

_THINKING_PHRASES = {
    "generic": [
        "Pensando",
        "Un momento",
        "Procesando",
        "Analizando tu solicitud",
    ],
    "cdg": [
        "Consultando el Control de Gestión",
        "Calibrando precios de cuota",
        "Calculando valores bursátiles",
        "Reconciliando balances contables",
        "Verificando dividendos distribuidos",
        "Consolidando información de activos",
    ],
    "noi": [
        "Evaluando NOI del trimestre",
        "Cruzando datos de Parque Titanium",
        "Procesando datos INMOSA",
        "Procesando datos de Viña Centro",
        "Analizando ocupación de Mall Curicó",
        "Leyendo EEFF de los fondos",
    ],
    "caja": [
        "Revisando flujos de caja",
        "Cuadrando el saldo de caja",
        "Procesando movimientos de caja",
    ],
    "rentroll": [
        "Revisando el rent roll",
        "Calculando vacancia por activo",
        "Analizando absorción de espacios",
    ],
    "factsheet": [
        "Preparando el fact sheet",
        "Calculando TIR del portafolio",
        "Analizando rendimientos del fondo",
    ],
}


def _thinking_phrase(grupos: set = None) -> str:
    if grupos:
        for g in ("cdg", "noi", "caja", "rentroll", "factsheet"):
            if g in grupos:
                return random.choice(_THINKING_PHRASES[g])
    return random.choice(_THINKING_PHRASES["generic"])

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class _Thinking:
    """Muestra un spinner animado con una frase temática mientras el LLM procesa."""

    def __init__(self, phrase: str = None):
        self._phrase = phrase or random.choice(_THINKING_PHRASES)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        try:
            frames = itertools.cycle(_SPINNER_FRAMES)
        except Exception:
            frames = itertools.cycle(["|", "/", "-", "\\"])
        while not self._stop.is_set():
            sys.stdout.write(f"\r  {next(frames)} {self._phrase}...")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(self._phrase) + 12) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop.set()
        self._thread.join()


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

┌──────────────────────────────────────┬──────────────────────────────────────────────────┬──────────────┐
│ Fondo                                │ Activos                                          │ Hoja CDG     │
├──────────────────────────────────────┼──────────────────────────────────────────────────┼──────────────┤
│ Toesca Rentas Inmobiliarias Apoquindo│ Apoquindo 4700, Apoquindo 4501, Apoquindo 3001   │ Input AP     │
│ Toesca Rentas Inmobiliarias PT       │ PT Oficinas, PT Locales, PT Bodegas              │ Input PT     │
│ Toesca Rentas Inmobiliarias          │ Viña Centro, Mall Curicó, INMOSA, SUCDEN,        │ Input Ren    │
│                                      │ Machalí                                          │              │
└──────────────────────────────────────┴──────────────────────────────────────────────────┴──────────────┘

Nota interna: En el Control de Gestión (CDG) y herramientas técnicas, estos fondos se identifican con el prefijo "A&R" (Aportes y Repartos), por ejemplo "A&R PT" o "A&R Rentas". NUNCA menciones "A&R" al usuario, usa siempre los nombres reales.

Nemotécnicos CMF:
  CFITRIPT-E  → Toesca Rentas Inmobiliarias PT
  CFITOERI1A  → Toesca Rentas Inmobiliarias Serie A
  CFITOERI1C  → Toesca Rentas Inmobiliarias Serie C
  CFITOERI1I  → Toesca Rentas Inmobiliarias Serie I

═══════════════════════════════════════════════════════════════
CUÁNDO PEDIR AYUDA (preguntar_usuario)
═══════════════════════════════════════════════════════════════
Usa preguntar_usuario() SOLO cuando estés genuinamente bloqueado:
• No encuentras el archivo después de buscar en todas las ubicaciones conocidas y derivadas
• Hay ambigüedad real que no puedes resolver (el usuario dijo algo que admite varias interpretaciones)
• Una operación falla repetidamente y agotaste las alternativas disponibles
• Necesitas un dato que no puedes derivar del contexto (nombre exacto, ruta, período, fondo)

JAMÁS uses preguntar_usuario() para:
• Confirmar si ejecutar algo — simplemente hazlo
• Preguntar si buscas en un lugar — simplemente busca
• Pedir aprobación de pasos intermedios de lectura o consulta

Cuando la llames: una sola pregunta, concisa. Llámala sola o como última herramienta del turno.

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


_INTENT_PATTERNS: dict[str, re.Pattern] = {
    "cdg": re.compile(
        r"control\s*de\s*gesti[oó]n|planilla|\bcdg\b|vr\s*(burs[aá]til|contable)|"
        r"precio(s)?\s*(de\s*)?cuota|burs[aá]til|dividendo|\baporte\b|reparto|"
        r"crear.*mes|mes\s*anterior|actualizar.*fecha|precios?\s*del?\s*mes|"
        r"input\s*(ap|pt|ren)|hoja\s*input",
        re.I,
    ),
    "noi": re.compile(
        r"\bnoi\b|vi[nñ]a\s*(centro)?|mall\s*curic[oó]|curic[oó]|\bjll\b|"
        r"\binmosa\b|parque\s*titanium|\bapoquindo\b|"
        r"er\s*(vi[nñ]a|curic[oó])|rent\s*roll.*noi|\beef\b|eeff",
        re.I,
    ),
    "caja": re.compile(
        r"\bcaja\b|saldo\s*caja|\bffmm\b|mar[ií]a\s*jos[eé]|flujo(s)?\s*de\s*caja",
        re.I,
    ),
    "rentroll": re.compile(
        r"rent\s*roll|vacancia|absorci[oó]n|\bm[²2]\b|metros\s*(cuadrados?)?|"
        r"ocupaci[oó]n|arrendatario|superficie",
        re.I,
    ),
    "factsheet": re.compile(
        r"fact\s*sheet|factsheet|\bfs\b(?!\s*[a-z])|"
        r"presentaci[oó]n\s*del\s*fondo|valor\s*libro|rentabilidad|\btir\b",
        re.I,
    ),
}


def get_intent_groups(text: str) -> set:
    """Clasifica intención por regex (O(n), sin LLM). Cubre >95% de casos."""
    return {grupo for grupo, pat in _INTENT_PATTERNS.items() if pat.search(text)}


_MAX_CONTEXT_CHARS = 70_000  # umbral para comprimir mensajes de tools intermedios


def _trim_tool_messages(messages: list) -> list:
    """
    Recorta tool results antiguos cuando el contexto supera el umbral.
    Preserva el system prompt, el primer user message y los últimos 6 mensajes completos.
    """
    total = sum(
        len(str(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") or ""))
        for m in messages
    )
    if total <= _MAX_CONTEXT_CHARS:
        return messages

    keep_tail = 6  # últimos mensajes siempre completos
    result = []
    tail_start = max(1, len(messages) - keep_tail)

    for i, m in enumerate(messages):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "")
        if role == "system" or i == 1 or i >= tail_start:
            result.append(m)
        elif role == "tool":
            content = m.get("content", "") if isinstance(m, dict) else (getattr(m, "content", "") or "")
            if len(str(content)) > 300:
                result.append({**m, "content": str(content)[:300] + " …[truncado]"})
            else:
                result.append(m)
        else:
            result.append(m)
    return result

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

            messages = _trim_tool_messages(messages)
            with _Thinking(_thinking_phrase(grupos)):
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
