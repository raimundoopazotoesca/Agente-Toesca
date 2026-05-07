import json
import re
import time
import random
import sys
import threading
import itertools
import unicodedata
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


def _drop_api_nulls(value):
    """Convierte objetos del SDK a dict/list simples y elimina campos None."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return {
            key: _drop_api_nulls(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_drop_api_nulls(item) for item in value if item is not None]
    return value


def _sanitize_messages_for_api(messages: list) -> list:
    """Normaliza historial para proveedores OpenAI-compatible que rechazan null."""
    clean = []
    for message in messages:
        item = _drop_api_nulls(message)
        if isinstance(item, dict) and item.get("role") in {"system", "user", "assistant", "tool"}:
            item.setdefault("content", "")
        clean.append(item)
    return clean


def _sanitize_kwargs_for_api(kwargs: dict) -> dict:
    clean = {
        key: _drop_api_nulls(value)
        for key, value in kwargs.items()
        if value is not None
    }
    if "messages" in kwargs:
        clean["messages"] = _sanitize_messages_for_api(kwargs["messages"])
    return clean


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

    for attempt in range(8):
        try:
            response = client.chat.completions.create(**_sanitize_kwargs_for_api(kwargs))
            _last_call_at = time.time()
            return response
        except Exception as e:
            msg = str(e).lower()
            is_retryable = (
                "429" in msg or "503" in msg or "502" in msg or "overload" in msg
                or "quota" in msg or "rate" in msg or "resource" in msg
                or "unavailable" in msg or "high demand" in msg
            )
            if is_retryable:
                wait = min((2 ** attempt) * 2 + random.uniform(0, 2), 120)
                code = "429" if "429" in msg else "503"
                print(f"  [{code}] API no disponible — esperando {wait:.0f}s (intento {attempt + 1}/8)...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Límite de reintentos alcanzado (8/8 intentos con error de API).")


BASE_PROMPT = """Eres un agente automatizador especializado en gestión de fondos inmobiliarios para Toesca Asset Management (Chile).
Tienes acceso a correos Outlook, SharePoint sincronizado (OneDrive), y planillas Excel del Control de Gestión.

═══════════════════════════════════════════════════════════════
ESTILO DE RESPUESTA
═══════════════════════════════════════════════════════════════
Responde siempre en Markdown claro y agradable de leer.
Esta regla aplica a TODAS las respuestas finales: consultas simples, explicaciones, resultados de herramientas, errores, bloqueos, resúmenes y preguntas al usuario.
Usa títulos breves con ## o ### cuando la respuesta tenga varias partes.
Usa **negrita** para estados, resultados clave, nombres de archivos/fondos y advertencias importantes.
Usa _cursiva_ para notas secundarias, matices o contexto breve.
Usa listas con viñetas cuando haya varios elementos, y tablas cuando compares datos.
Usa `código inline` para rutas, nombres técnicos, funciones, celdas, hojas y archivos.
Puedes usar emojis de forma moderada para mejorar lectura visual:
  ✅ encontrado/listo, ❌ faltante/error, ⚠️ advertencia, 📎 adjuntos,
  📁 ruta/carpeta, 📬 correo, 📊 CDG/datos, 🚫 bloqueo.
No abuses de emojis ni de títulos: la prioridad es que sea fácil de escanear.
Para respuestas cortas, basta una frase bien formateada.

═══════════════════════════════════════════════════════════════
RESULTADOS DE HERRAMIENTAS — REGLA ABSOLUTA
═══════════════════════════════════════════════════════════════
JAMÁS inventes resultados de herramientas. Si no llamaste a una herramienta, no muestres resultados.
Si llamaste a una herramienta, usa SOLO lo que retornó: no agregues datos, no elimines datos relevantes y no alteres valores, rutas, fechas, nombres ni estados.
Sí puedes reorganizar y formatear la presentación en Markdown para que sea fácil de leer, manteniendo fielmente el contenido factual.
Si una instrucción específica dice "copiar literalmente" o "mostrar resultado completo", conserva todo el contenido y solo mejora el formato visual si no cambia el texto sustantivo.
Esto aplica especialmente a rutas de archivos: NUNCA generes una ruta que no vino de una herramienta.
Si el usuario pregunta dónde está o dónde subir un archivo: llamar leer_wiki("sharepoint/index") primero.

SEGUIMIENTO DE CORREOS:
Si el usuario pregunta si una persona respondió un mail enviado (ej. "¿Cantillana respondió?"),
busca por contacto con revisar_respuestas_contacto. No inventes ni asumas un asunto. No busques por "CDG",
"Control de Gestión" u otro tema salvo que el usuario lo mencione explícitamente en esa pregunta.

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

Fondos operativos y hojas CDG:
  - Toesca Rentas Inmobiliarias Apoquindo -> hoja Input AP.
    Activos principales: Apoquindo 4501 y Apoquindo 4700.
  - Toesca Rentas Inmobiliarias PT -> hoja Input PT.
    Activos principales: Parque Titanium, separado operativamente en PT Oficinas, PT Locales y PT Bodegas.
  - Toesca Rentas Inmobiliarias -> hoja Input Ren.
    Alias habituales: TRI, Rentas Inmobiliarias, Rentas.
    Activos principales vigentes: Viña Centro, Power Center Paseo Curicó, INMOSA, SUCDEN/Bodegas Maipú,
    Apoquindo 3001, participación en Toesca Rentas Inmobiliarias PT y participación en Toesca Rentas
    Inmobiliarias Apoquindo.

Estructura de Toesca Rentas Inmobiliarias según diagrama validado por el usuario el 2026-05-06:
  - 100% Inmobiliaria Machalí Ltda -> Strip Center Paseo Machalí.
    Estado: liquidado / ya no forma parte del fondo. No considerarlo como activo vigente ni en pesos actuales.
  - 100% Inmobiliaria Chañarcillo Ltda -> Bodegas Maipú (Sucden).
  - 100% Inmobiliaria Chañarcillo Ltda -> 68,5% de Apoquindo 3001.
  - 100% Inmobiliaria VC SpA -> 100% Inmobiliaria Viña Centro SpA -> Mall Paseo Viña Centro.
  - 80% Power Center Curicó SpA -> Power Center Paseo Curicó.
  - 43% Inmobiliaria e Inversiones Senior Assist Chile S.A. -> 6 residencias de adulto mayor (INMOSA).
  - 33,3% Fondo Toesca Rentas Inmobiliarias PT -> Torre A S.A. e Inmobiliaria Boulevard PT SpA
    -> Torre A y Boulevard Parque Titanium.
  - 30% Fondo Toesca Rentas Inmobiliarias Apoquindo -> Inmobiliaria Apoquindo SpA -> Apoquindo 4501 y 4700.

Pesos de referencia del diagrama original, no actualizados:
  - Machalí 4%; Bodegas Maipú/Sucden 5%; Apoquindo 3001 6%; Viña Centro 34%; Curicó 6%;
    INMOSA 12%; Parque Titanium 16%; Apoquindo 4501/4700 17%.

Pesos pro forma recalculados excluyendo Machalí liquidado (rebase sobre 96%; usar solo como referencia si
no hay una fuente más reciente como CDG, fact sheet o EEFF):
  - Bodegas Maipú/Sucden: 5/96 = 5,21%
  - Apoquindo 3001: 6/96 = 6,25%
  - Viña Centro: 34/96 = 35,42%
  - Power Center Paseo Curicó: 6/96 = 6,25%
  - INMOSA / Senior Assist Chile: 12/96 = 12,50%
  - Parque Titanium vía Fondo Toesca Rentas Inmobiliarias PT: 16/96 = 16,67%
  - Apoquindo 4501 y 4700 vía Fondo Toesca Rentas Inmobiliarias Apoquindo: 17/96 = 17,71%

Regla: si el usuario pregunta por pesos, explicar si se está usando el peso histórico del diagrama, el peso
pro forma sin Machalí, o una fuente actualizada leída desde CDG/fact sheet/EEFF. No presentar los pesos del
diagrama como actuales.

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
Ubicación: SharePoint → Control de Gestión/CDG Mensual/{YYYY}/
Patrón de nombre: {AAMM} Control De Gestión Renta Comercial.xlsx
  Ejemplos: "2603 Control De Gestión Renta Comercial.xlsx" (marzo 2026)
            "2602 Control De Gestión Renta Comercial.xlsx" (febrero 2026)

Para abrir el CDG de un mes dado:
  1. Construir el nombre con el patrón → {AAMM} = año2d + mes2d (ej: marzo 2026 → "2603")
  2. Usar buscar_en_sharepoint(keyword="{AAMM}") para encontrar la ruta exacta
  3. Copiar al WORK_DIR con copiar_de_sharepoint(nombre_archivo, subcarpeta)

BALANCES CONSOLIDADOS RENTAS PT / APOQUINDO:
  La regla general del wiki MANDA sobre los defaults:
  1. Para cada hoja y seccion (balance / EERR), mirar el mismo periodo del ano anterior en la planilla.
  2. Si todos los inputs terminan en 000, la fuente es EEFF PDF en M$ y se multiplica por 1.000.
  3. Si algun input no termina en 000, la fuente es planilla Analisis en pesos directos.
  4. Para PT y Apoquindo, usar primero la tabla fija por quarter definida en la herramienta/wiki; fue derivada del historico 2025.
  5. Usar inferencia historica/defaults documentados solo si no hay tabla fija para esa hoja/seccion.
  6. Si la regla pide una fuente que la herramienta aun no sabe parsear, detener esa seccion y reportarlo; no inventar datos.
  Herramientas:
    - actualizar_balance_consolidado_pt(mes, año)
    - actualizar_balance_consolidado_apoquindo(mes, año)

═══════════════════════════════════════════════════════════════
VERIFICACIÓN DE ARCHIVOS — REGLA OBLIGATORIA
═══════════════════════════════════════════════════════════════
Cuando el usuario pregunta '¿tienes todo?', '¿qué te falta?', '¿puedes actualizar el CDG?' o similar:
  → SIEMPRE llamar verificar_archivos_cdg(año, mes) PRIMERO.
  → Copiar el resultado LITERALMENTE, sin resumir ni reformular.
  → El resultado tiene dos secciones: "Archivos encontrados" Y "Archivos faltantes".
  → NUNCA omitir la sección de encontrados — el usuario necesita ver ambas.
  → Si hay archivos faltantes, la herramienta agregará la pregunta para enviar mails o hacer seguimiento.
NUNCA inventes qué archivos están disponibles — si la herramienta no lo encontró, no está.

Correos por archivos faltantes:
  → Si el usuario confirma que quiere enviar los mails, usar enviar_correos_solicitud_cdg(año, mes).
  → Si el usuario pide redactar/preparar/ver antes de enviar, usar previsualizar_correos_solicitud_cdg(año, mes).
  → Si ya se habían solicitado archivos para ese período, usar el modo seguimiento automático de esas herramientas.
  → Si el usuario excluye un contacto o archivo (ej: "no envíes JLL"), pasar excluir=["jll"] o el item correspondiente.
  → Copiar literalmente el resultado de estas herramientas; no digas que se envió si la herramienta reporta error.

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
1. verificar_archivos_cdg(año, mes) → confirmar que están todos los archivos
2. crear_planilla_mes("{AAMM}") → copia desde mes anterior en SharePoint
3. copiar_de_sharepoint → traer al WORK_DIR
4. actualizar_fecha_pendientes(...) → B2 hoja Pendientes = 1º día del mes
5. obtener_precios_mes(año, mes-1) → precios último día mes anterior
6. agregar_vr_bursatil_pt(...) + agregar_vr_bursatil_rentas(...)
7. Si fin de trimestre: agregar_vr_contable_*
8. guardar_cdg(...)"""

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
  ER-FC INMOSA: SharePoint → Fondos/Rentas TRI/Activos/INMOSA/Flujos/{YYYY}/ — del MES del CDG

RUTAS SHAREPOINT: Para saber la ruta exacta de cualquier archivo en SharePoint,
  llamar leer_wiki("sharepoint/index") — contiene árbol completo y patrones de nombre.
  NUNCA inventar rutas — si no está en la wiki, usar buscar_en_sharepoint()."""

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
        r"input\s*(ap|pt|ren)|hoja\s*input|balance\s*consolidado|rentas\s*(pt|apoquindo)|"
        r"vagente|vf\b|analisis|an[aá]lisis",
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
        r"rent\s*roll|\brr\b|tres\s*a(sociados?)?\b|vacancia|absorci[oó]n|\bm[²2]\b|"
        r"metros\s*(cuadrados?)?|ocupaci[oó]n|arrendatario|superficie",
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

_VERIFICAR_CDG_RE = re.compile(
    r"(tienes?\s+todo|qu[eé]\s+te\s+falta|qu[eé]\s+archivos?\s+(tienes?|te\s+faltan?)|"
    r"puedes?\s+actualizar\s+(el\s+)?cdg|tenemos?\s+todo|est[aá](s|n)?\s+listo)"
    r".*(?:cdg|control\s+de\s+gesti[oó]n)",
    re.I,
)

_MES_NOMBRES = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
}


def _norm_text(text: str) -> str:
    text = str(text or "").casefold()
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    return " ".join(text.replace("_", " ").replace("-", " ").split())


_RESPUESTA_MAIL_RE = re.compile(
    r"(respondi[oó]|respondio|contest[oó]|contesto|respuesta).*(mail|correo)|"
    r"(mail|correo).*(respondi[oó]|respondio|contest[oó]|contesto|respuesta)",
    re.I,
)


def _try_revisar_respuesta_contacto_directo(user_input: str):
    """Resuelve seguimientos personales de correo por contacto, sin mezclar asuntos de otros flujos."""
    if not _RESPUESTA_MAIL_RE.search(user_input):
        return None

    from tools.email_tools import KNOWN_EMAIL_CONTACTS, check_replies_from_contact

    normalized = _norm_text(user_input)
    for alias in sorted(KNOWN_EMAIL_CONTACTS, key=len, reverse=True):
        if _norm_text(alias) in normalized:
            return check_replies_from_contact(alias, KNOWN_EMAIL_CONTACTS[alias])

    m = re.search(r"^\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ.' -]{2,60}?)\s+(?:respondi[oó]|respondio|contest[oó]|contesto)\b", user_input, re.I)
    if m:
        contacto = m.group(1).strip(" ¿?.,;:")
        if contacto:
            return check_replies_from_contact(contacto)

    return None


def _try_verificar_cdg_directo(user_input: str):
    """Llama verificar_archivos_cdg directamente si la query es un chequeo de disponibilidad."""
    if not _VERIFICAR_CDG_RE.search(user_input):
        return None
    # Extraer año y mes de la query
    import datetime
    año = mes = None
    m_año = re.search(r"\b(202\d)\b", user_input)
    if m_año:
        año = int(m_año.group(1))
    for nombre, num in _MES_NOMBRES.items():
        if nombre in user_input.lower():
            mes = num
            break
    m_aamm = re.search(r"\b(\d{2})(\d{2})\b", user_input)
    if m_aamm and not (año and mes):
        año = 2000 + int(m_aamm.group(1))
        mes = int(m_aamm.group(2))
    if not (año and mes):
        hoy = datetime.date.today()
        año, mes = hoy.year, hoy.month
    from tools.gestion_renta_tools import verificar_archivos_cdg
    return verificar_archivos_cdg(año, mes)


def run_agent(user_input: str) -> str:
    print("\\n" + "=" * 60)
    print(f"Instrucción: {user_input}")
    print("=" * 60)

    resultado_respuesta_contacto = _try_revisar_respuesta_contacto_directo(user_input)
    if resultado_respuesta_contacto is not None:
        print(f"\nAgente: {resultado_respuesta_contacto}")
        from tools.memory_tools import guardar_tarea
        guardar_tarea(user_input, ["revisar_respuestas_contacto"], resultado_respuesta_contacto[:200])
        return resultado_respuesta_contacto

    # Intercepción directa para queries de verificación CDG — evita que Gemini alucine
    resultado_verificacion = _try_verificar_cdg_directo(user_input)
    if resultado_verificacion is not None:
        print(f"\\nAgente: {resultado_verificacion}")
        from tools.memory_tools import guardar_tarea
        guardar_tarea(user_input, ["verificar_archivos_cdg"], resultado_verificacion[:200])
        return resultado_verificacion

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
    _done = False  # flag para salir del while desde dentro del for

    n_selected = len(selected_tools)
    n_total = len(TOOL_DEFINITIONS)
    if n_selected < n_total:
        print(f"  [tools] {n_selected}/{n_total} herramientas activas")

    try:
        iteration = 0
        while True:
            if _done:
                break
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

                # Para verificar_archivos_cdg, usar el resultado directamente
                # sin que el modelo lo resuma (evita que Gemini omita los [OK])
                if name in {
                    "revisar_respuestas_contacto",
                    "verificar_archivos_cdg",
                    "ordenar_archivos_raw",
                    "previsualizar_correos_solicitud_cdg",
                    "enviar_correos_solicitud_cdg",
                }:
                    final_response = result
                    print(f"\nAgente: {result}")
                    _done = True
                    break

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

    return final_response


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


def start_server(port: int = 5000) -> None:
    try:
        from flask import Flask, request, jsonify
    except ImportError:
        print("Flask no instalado. Ejecuta: pip install flask")
        return

    app = Flask(__name__)

    @app.post("/run")
    def api_run():
        data = request.get_json(silent=True) or {}
        instruction = data.get("instruction", "").strip()
        if not instruction:
            return jsonify({"error": "Campo 'instruction' requerido"}), 400
        result = run_agent(instruction)
        return jsonify({"response": result or ""})

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    print(f"Servidor HTTP en http://localhost:{port}")
    print("  POST /run  — body: {\"instruction\": \"...\"}")
    print("  GET  /health")
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
        start_server(port)
    else:
        main()
