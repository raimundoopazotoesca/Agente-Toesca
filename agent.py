import json
from openai import OpenAI
from dotenv import load_dotenv

from tools.email_tools import (
    list_emails_with_attachments,
    download_email_attachment,
    send_email,
    search_emails_by_subject,
)
from tools.sharepoint_tools import (
    list_sharepoint_files,
    copy_from_sharepoint,
    save_to_sharepoint,
)
from tools.local_tools import (
    list_local_excel_files,
    copy_from_local,
    save_to_local,
)
from tools.excel_tools import (
    read_excel_file,
    validate_excel_file,
    update_excel_cell,
    list_work_files,
)
from tools.gestion_renta_tools import (
    crear_planilla_mes,
    actualizar_fecha_pendientes,
    agregar_vr_bursatil_pt,
    agregar_vr_bursatil_rentas,
    agregar_vr_contable_pt,
    agregar_vr_contable_rentas,
    agregar_vr_contable_apoquindo,
    agregar_dividendo_pt,
    agregar_dividendo_rentas,
    agregar_dividendo_apoquindo,
    agregar_aporte_pt,
    agregar_aporte_rentas,
    agregar_aporte_apoquindo,
    info_siguiente_accion,
)
from tools.eeff_tools import (
    listar_eeff_disponibles,
    leer_eeff,
)
from tools.web_bursatil_tools import (
    obtener_precio_cuota,
    obtener_precios_mes,
)
from config import GEMINI_API_KEY

load_dotenv()

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """Eres un agente automatizador especializado en gestión de correos Outlook y planillas Excel en entorno Microsoft 365.

Tienes acceso a:
- Correos Outlook (vía la aplicación instalada en la PC)
- Archivos en SharePoint (carpeta sincronizada en la PC)
- Archivos en servidor local o red corporativa (unidad R:)
- Procesamiento de planillas Excel

Flujo típico:
1. Buscar correos o archivos con planillas Excel
2. Copiar/descargar la planilla al directorio de trabajo
3. Leer y validar la planilla
4. Procesar o actualizar según lo solicitado
5. Guardar el resultado en SharePoint o servidor
6. Enviar correo con el resultado si es necesario

Al terminar cada tarea resume brevemente qué hiciste e indica si encontraste errores.
Si falta información para completar la tarea, pregunta antes de proceder."""


# ─── Definición de herramientas ───────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_correos_con_planillas",
            "description": "Busca los últimos correos Outlook que tienen archivos Excel adjuntos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limite": {"type": "integer", "description": "Cuántos correos revisar (por defecto 20)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_correos_por_asunto",
            "description": "Busca correos cuyo asunto contenga una palabra o frase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "palabra_clave": {"type": "string", "description": "Texto a buscar en el asunto"},
                    "limite": {"type": "integer", "description": "Número máximo de resultados"},
                },
                "required": ["palabra_clave"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "descargar_adjunto_correo",
            "description": "Descarga un archivo Excel adjunto de un correo al directorio de trabajo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id":         {"type": "string",  "description": "ID del correo"},
                    "attachment_index": {"type": "integer", "description": "Número del adjunto"},
                    "nombre_archivo":   {"type": "string",  "description": "Nombre con que guardar el archivo"},
                },
                "required": ["entry_id", "attachment_index", "nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_correo",
            "description": "Envía un correo desde Outlook con o sin archivo adjunto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destinatario":    {"type": "string", "description": "Dirección de correo"},
                    "asunto":          {"type": "string", "description": "Asunto del correo"},
                    "cuerpo":          {"type": "string", "description": "Texto del mensaje"},
                    "archivo_adjunto": {"type": "string", "description": "Nombre del archivo a adjuntar (opcional)"},
                },
                "required": ["destinatario", "asunto", "cuerpo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_sharepoint",
            "description": "Lista los archivos Excel en la carpeta de SharePoint sincronizada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subcarpeta": {"type": "string", "description": "Subcarpeta dentro de SharePoint (opcional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copiar_de_sharepoint",
            "description": "Copia un archivo de SharePoint al directorio de trabajo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del archivo"},
                    "subcarpeta":     {"type": "string", "description": "Subcarpeta en SharePoint (opcional)"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "guardar_en_sharepoint",
            "description": "Guarda un archivo del directorio de trabajo en SharePoint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":     {"type": "string", "description": "Nombre del archivo a guardar"},
                    "subcarpeta_destino": {"type": "string", "description": "Subcarpeta destino (opcional)"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_servidor_local",
            "description": "Lista los archivos Excel en el servidor local o unidad de red (R:).",
            "parameters": {
                "type": "object",
                "properties": {
                    "subcarpeta": {"type": "string", "description": "Subcarpeta en el servidor (opcional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copiar_del_servidor",
            "description": "Copia un archivo del servidor local (R:) al directorio de trabajo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del archivo"},
                    "subcarpeta":     {"type": "string", "description": "Subcarpeta en el servidor (opcional)"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "guardar_en_servidor",
            "description": "Guarda un archivo del directorio de trabajo en el servidor local (R:).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":     {"type": "string", "description": "Nombre del archivo"},
                    "subcarpeta_destino": {"type": "string", "description": "Subcarpeta destino (opcional)"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_planilla",
            "description": "Lee y muestra el contenido de una planilla Excel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del archivo Excel"},
                    "hoja":           {"type": "string", "description": "Nombre de la hoja (opcional)"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validar_planilla",
            "description": "Valida una planilla Excel detectando errores, celdas vacías y duplicados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":      {"type": "string", "description": "Nombre del archivo"},
                    "columnas_requeridas": {"type": "string", "description": "Columnas obligatorias separadas por coma (ej: 'RUT,Nombre,Monto')"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_celda",
            "description": "Actualiza el valor de una celda en una planilla Excel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string",  "description": "Nombre del archivo"},
                    "hoja":           {"type": "string",  "description": "Nombre de la hoja"},
                    "celda":          {"type": "string",  "description": "Referencia de celda (ej: 'A1', 'C5')"},
                    "valor":          {"type": "string",  "description": "Nuevo valor"},
                },
                "required": ["nombre_archivo", "hoja", "celda", "valor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_planillas_en_trabajo",
            "description": "Lista los archivos Excel disponibles en el directorio de trabajo actual.",
            "parameters": {"type": "object", "properties": {}},
        },
    },

    # ── Gestión Renta Comercial ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "crear_planilla_mes",
            "description": "Crea la planilla mensual de Control de Gestión Renta Comercial copiando la del mes anterior en R:\\.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mes_code_nuevo": {"type": "string", "description": "Código AAMM del nuevo mes (ej: '2604' para abril 2026)"},
                },
                "required": ["mes_code_nuevo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_fecha_pendientes",
            "description": "Actualiza la fecha en la hoja Pendientes de la planilla al primer día del mes indicado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del archivo en WORK_DIR"},
                    "año":            {"type": "integer", "description": "Año (ej: 2026)"},
                    "mes":            {"type": "integer", "description": "Mes (ej: 4)"},
                },
                "required": ["nombre_archivo", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "info_siguiente_accion",
            "description": "Lee el estado de las hojas A&R de la planilla y reporta la última fecha registrada y la próxima fila disponible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del archivo en WORK_DIR"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_precio_cuota",
            "description": "Obtiene el valor cuota bursátil de un fondo (nemotécnico) para el último día de un mes, desde CMF o Larraín Vial.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {"type": "string", "description": "Ej: 'CFITRIPT-E', 'CFITOERI1A'"},
                    "año":         {"type": "integer", "description": "Año"},
                    "mes":         {"type": "integer", "description": "Mes"},
                },
                "required": ["nemotecnico", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_precios_mes",
            "description": "Obtiene todos los precios bursátiles necesarios para el mes (CFITRIPT-E y CFITOERI1A/C/I).",
            "parameters": {
                "type": "object",
                "properties": {
                    "año": {"type": "integer", "description": "Año"},
                    "mes": {"type": "integer", "description": "Mes"},
                },
                "required": ["año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_vr_bursatil_pt",
            "description": "Agrega la fila mensual de VR Bursátil en la hoja A&R PT de la planilla.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                    "precio_cuota":   {"type": "number", "description": "Valor cuota bursátil (CFITRIPT-E)"},
                },
                "required": ["nombre_archivo", "año", "mes", "precio_cuota"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_vr_bursatil_rentas",
            "description": "Agrega las 3 filas mensuales de VR Bursátil en la hoja A&R Rentas (series A, C, I).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                    "precio_a":       {"type": "number", "description": "Precio Serie A (CFITOERI1A)"},
                    "precio_c":       {"type": "number", "description": "Precio Serie C (CFITOERI1C)"},
                    "precio_i":       {"type": "number", "description": "Precio Serie I (CFITOERI1I)"},
                },
                "required": ["nombre_archivo", "año", "mes", "precio_a", "precio_c", "precio_i"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_vr_contable_pt",
            "description": "Agrega la fila trimestral de VR Contable en la hoja A&R PT.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                    "precio_cuota":   {"type": "number"},
                },
                "required": ["nombre_archivo", "año", "mes", "precio_cuota"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_vr_contable_rentas",
            "description": "Agrega las 3 filas trimestrales de VR Contable en la hoja A&R Rentas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                    "precio_a":       {"type": "number"},
                    "precio_c":       {"type": "number"},
                    "precio_i":       {"type": "number"},
                },
                "required": ["nombre_archivo", "año", "mes", "precio_a", "precio_c", "precio_i"],
            },
        },
    },
    # ── EEFF (Estados Financieros) ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "listar_eeff_disponibles",
            "description": "Lista los trimestres de EEFF disponibles en disco para un fondo y año.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {"type": "string", "description": "Nombre del fondo: 'A&R Apoquindo', 'A&R PT' o 'A&R Rentas'"},
                    "año":       {"type": "integer", "description": "Año (ej: 2025)"},
                },
                "required": ["fondo_key", "año"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_eeff",
            "description": (
                "Lee el PDF de EEFF de un fondo para el trimestre indicado. "
                "Extrae valor cuota libro por serie y detecta dividendos/aportes. "
                "Si la extracción automática falla, retorna el texto relevante del PDF "
                "para que puedas identificar los valores manualmente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {"type": "string", "description": "'A&R Apoquindo', 'A&R PT' o 'A&R Rentas'"},
                    "año":       {"type": "integer", "description": "Año del trimestre"},
                    "mes":       {"type": "integer", "description": "Mes de cierre del trimestre (3, 6, 9 o 12)"},
                },
                "required": ["fondo_key", "año", "mes"],
            },
        },
    },
    # ── Dividendos y Aportes ────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "agregar_dividendo_pt",
            "description": "Agrega una fila de Dividendo en la hoja A&R PT.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":   {"type": "string"},
                    "año":              {"type": "integer"},
                    "mes":              {"type": "integer"},
                    "monto_por_cuota":  {"type": "number", "description": "Monto del dividendo por cuota"},
                },
                "required": ["nombre_archivo", "año", "mes", "monto_por_cuota"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_dividendo_rentas",
            "description": "Agrega filas de Dividendo en A&R Rentas (series A, C, I).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                    "monto_a":        {"type": "number"},
                    "monto_c":        {"type": "number"},
                    "monto_i":        {"type": "number"},
                },
                "required": ["nombre_archivo", "año", "mes", "monto_a", "monto_c", "monto_i"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_dividendo_apoquindo",
            "description": "Agrega una fila de Dividendo en la hoja A&R Apoquindo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":   {"type": "string"},
                    "año":              {"type": "integer"},
                    "mes":              {"type": "integer"},
                    "monto_por_cuota":  {"type": "number"},
                },
                "required": ["nombre_archivo", "año", "mes", "monto_por_cuota"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_aporte_pt",
            "description": "Agrega una fila de Aporte en la hoja A&R PT.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":   {"type": "string"},
                    "año":              {"type": "integer"},
                    "mes":              {"type": "integer"},
                    "monto_por_cuota":  {"type": "number"},
                },
                "required": ["nombre_archivo", "año", "mes", "monto_por_cuota"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_aporte_rentas",
            "description": "Agrega filas de Aporte en A&R Rentas (series A, C, I).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                    "monto_a":        {"type": "number"},
                    "monto_c":        {"type": "number"},
                    "monto_i":        {"type": "number"},
                },
                "required": ["nombre_archivo", "año", "mes", "monto_a", "monto_c", "monto_i"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_aporte_apoquindo",
            "description": "Agrega una fila de Aporte en la hoja A&R Apoquindo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":   {"type": "string"},
                    "año":              {"type": "integer"},
                    "mes":              {"type": "integer"},
                    "monto_por_cuota":  {"type": "number"},
                },
                "required": ["nombre_archivo", "año", "mes", "monto_por_cuota"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_vr_contable_apoquindo",
            "description": "Agrega la fila trimestral de VR Contable en la hoja A&R Apoquindo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                    "precio_cuota":   {"type": "number"},
                },
                "required": ["nombre_archivo", "año", "mes", "precio_cuota"],
            },
        },
    },
]


# ─── Despachador de herramientas ──────────────────────────────────────────────

def _dispatch(name: str, args: dict) -> str:
    dispatch = {
        "buscar_correos_con_planillas": lambda a: list_emails_with_attachments(a.get("limite", 20)),
        "buscar_correos_por_asunto":    lambda a: search_emails_by_subject(a["palabra_clave"], a.get("limite", 10)),
        "descargar_adjunto_correo":     lambda a: download_email_attachment(a["entry_id"], a["attachment_index"], a["nombre_archivo"]),
        "enviar_correo":                lambda a: send_email(a["destinatario"], a["asunto"], a["cuerpo"], a.get("archivo_adjunto")),
        "listar_sharepoint":            lambda a: list_sharepoint_files(a.get("subcarpeta", "")),
        "copiar_de_sharepoint":         lambda a: copy_from_sharepoint(a["nombre_archivo"], a.get("subcarpeta", "")),
        "guardar_en_sharepoint":        lambda a: save_to_sharepoint(a["nombre_archivo"], a.get("subcarpeta_destino", "")),
        "listar_servidor_local":        lambda a: list_local_excel_files(a.get("subcarpeta", "")),
        "copiar_del_servidor":          lambda a: copy_from_local(a["nombre_archivo"], a.get("subcarpeta", "")),
        "guardar_en_servidor":          lambda a: save_to_local(a["nombre_archivo"], a.get("subcarpeta_destino", "")),
        "leer_planilla":                lambda a: read_excel_file(a["nombre_archivo"], a.get("hoja")),
        "validar_planilla":             lambda a: validate_excel_file(a["nombre_archivo"], a.get("columnas_requeridas")),
        "actualizar_celda":             lambda a: update_excel_cell(a["nombre_archivo"], a["hoja"], a["celda"], a["valor"]),
        "listar_planillas_en_trabajo":  lambda a: list_work_files(),
        # Gestión Renta Comercial
        "crear_planilla_mes":           lambda a: crear_planilla_mes(a["mes_code_nuevo"]),
        "actualizar_fecha_pendientes":  lambda a: actualizar_fecha_pendientes(a["nombre_archivo"], a["año"], a["mes"]),
        "info_siguiente_accion":        lambda a: info_siguiente_accion(a["nombre_archivo"]),
        "obtener_precio_cuota":         lambda a: obtener_precio_cuota(a["nemotecnico"], a["año"], a["mes"]),
        "obtener_precios_mes":          lambda a: obtener_precios_mes(a["año"], a["mes"]),
        "agregar_vr_bursatil_pt":       lambda a: agregar_vr_bursatil_pt(a["nombre_archivo"], a["año"], a["mes"], a["precio_cuota"]),
        "agregar_vr_bursatil_rentas":   lambda a: agregar_vr_bursatil_rentas(a["nombre_archivo"], a["año"], a["mes"], a["precio_a"], a["precio_c"], a["precio_i"]),
        "agregar_vr_contable_pt":       lambda a: agregar_vr_contable_pt(a["nombre_archivo"], a["año"], a["mes"], a["precio_cuota"]),
        "agregar_vr_contable_rentas":   lambda a: agregar_vr_contable_rentas(a["nombre_archivo"], a["año"], a["mes"], a["precio_a"], a["precio_c"], a["precio_i"]),
        "agregar_vr_contable_apoquindo": lambda a: agregar_vr_contable_apoquindo(a["nombre_archivo"], a["año"], a["mes"], a["precio_cuota"]),
        # EEFF
        "listar_eeff_disponibles":      lambda a: listar_eeff_disponibles(a["fondo_key"], a["año"]),
        "leer_eeff":                    lambda a: leer_eeff(a["fondo_key"], a["año"], a["mes"]),
        # Dividendos y Aportes
        "agregar_dividendo_pt":         lambda a: agregar_dividendo_pt(a["nombre_archivo"], a["año"], a["mes"], a["monto_por_cuota"]),
        "agregar_dividendo_rentas":     lambda a: agregar_dividendo_rentas(a["nombre_archivo"], a["año"], a["mes"], a["monto_a"], a["monto_c"], a["monto_i"]),
        "agregar_dividendo_apoquindo":  lambda a: agregar_dividendo_apoquindo(a["nombre_archivo"], a["año"], a["mes"], a["monto_por_cuota"]),
        "agregar_aporte_pt":            lambda a: agregar_aporte_pt(a["nombre_archivo"], a["año"], a["mes"], a["monto_por_cuota"]),
        "agregar_aporte_rentas":        lambda a: agregar_aporte_rentas(a["nombre_archivo"], a["año"], a["mes"], a["monto_a"], a["monto_c"], a["monto_i"]),
        "agregar_aporte_apoquindo":     lambda a: agregar_aporte_apoquindo(a["nombre_archivo"], a["año"], a["mes"], a["monto_por_cuota"]),
    }
    fn = dispatch.get(name)
    if fn is None:
        return f"Error: herramienta '{name}' no reconocida."
    return fn(args)


# ─── Runner principal ─────────────────────────────────────────────────────────

def run_agent(user_input: str) -> None:
    print("\n" + "=" * 60)
    print(f"Instrucción: {user_input}")
    print("=" * 60)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_input},
    ]

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
        )

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            if msg.content:
                print(f"\nAgente: {msg.content}")
            break

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            print(f"\n  → Ejecutando: {name}({', '.join(f'{k}={v}' for k, v in args.items())})")

            result = _dispatch(name, args)
            print(f"  ✓ {result[:120]}{'...' if len(result) > 120 else ''}")

            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "content":      result,
            })


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
