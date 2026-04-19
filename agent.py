import json
from openai import OpenAI
from dotenv import load_dotenv
from tools.memory_tools import (
    load_memory,
    guardar_tarea,
    leer_contexto,
    actualizar_contexto,
    leer_historial,
    registrar_kpi,
    consultar_kpi,
    resumen_kpis,
    comparar_periodos,
)

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
from tools.datos_fs_tools import (
    actualizar_fecha_ar,
    leer_rentabilidades_ar,
    pegar_rentabilidades_datos_fs,
    copiar_datos_tir_rentas,
    leer_tir_rentas_resumen,
)
from tools.caja_tools import (
    listar_hojas_saldo_caja,
    copiar_datos_saldo_caja,
    leer_celdas_caja,
    inspeccionar_caja_historica,
    agregar_fila_caja_historica,
    archivar_saldo_caja,
    listar_saldo_caja_archivados,
)
from tools.input_tools import (
    actualizar_balance_input,
    actualizar_fecha_bursatil_input,
    actualizar_fecha_contable_input,
    agregar_dividendo_input,
    inspeccionar_dividendos_input,
)
from tools.web_bursatil_tools import (
    obtener_precio_cuota,
    obtener_precios_mes,
)
from tools.rentroll_tools import (
    revisar_rent_rolls,
    enviar_emails_rent_roll,
    consolidar_rent_rolls,
    consolidar_absorcion,
)
from tools.vacancia_tools import (
    actualizar_vacancia,
    refrescar_tabla_rentas_2,
    consultar_vacancia,
)
from tools.noi_tools import (
    actualizar_er_vina,
    actualizar_er_curico,
    actualizar_noi_pt,
    actualizar_noi_apoquindo,
    actualizar_noi_apo3001,
    actualizar_noi_inmosa,
    inspeccionar_noi_rcsd,
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

Cuando no encuentres un archivo:
1. Antes de preguntar al usuario, usa 'listar_planillas_en_trabajo', 'listar_sharepoint' o 'listar_servidor_local' para explorar las carpetas relevantes.
2. Si encuentras archivos con nombres similares al que buscas, usa el más probable y continúa.
3. Solo pregunta al usuario si después de explorar sigue sin haber ningún candidato razonable.

Cuando el usuario te indique dónde encontrar un archivo, cómo se llama, o cualquier dato que no sabías, llama siempre a 'actualizar_contexto' para recordarlo en futuras sesiones."""


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

    # ── DATOS FS — Rentabilidad del Fondo (en UF) ─────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "actualizar_fecha_ar",
            "description": (
                "Actualiza la celda D2 (fecha EEFF) en la hoja A&R del fondo indicado. "
                "Usar antes de que el usuario abra Excel para recalcular XIRR. "
                "fecha_serial es el serial Excel (ej: 46112 = 31/03/2026)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Archivo en WORK_DIR"},
                    "fondo_key":      {"type": "string", "description": "'A&R PT', 'A&R Apoquindo' o 'A&R Rentas'"},
                    "fecha_serial":   {"type": "integer", "description": "Serial Excel de la fecha"},
                },
                "required": ["nombre_archivo", "fondo_key", "fecha_serial"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_rentabilidades_ar",
            "description": (
                "Lee los valores cacheados de rentabilidad contable (XIRR) desde la hoja A&R. "
                "PT/Apoquindo: N10 (inicio), O10 (YTD), P10 (12M). "
                "Rentas: P12/Q12 (Serie A), Y12/Z12 (Serie C), AH12/AI12 (Serie I). "
                "Si las celdas están vacías, se debe abrir Excel y guardar para recalcular."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "fondo_key":      {"type": "string", "description": "'A&R PT', 'A&R Apoquindo' o 'A&R Rentas'"},
                },
                "required": ["nombre_archivo", "fondo_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pegar_rentabilidades_datos_fs",
            "description": (
                "Escribe los valores de rentabilidad libro (en UF) en las celdas hardcoded de DATOS FS. "
                "Los valores deben ser decimales (0.05 = 5%). "
                "Para PT/Apoquindo: rentabilidades={\"null\": {\"inicio\": 0.05, \"ytd\": 0.03, \"12m\": 0.048}}. "
                "Para Rentas: rentabilidades={\"A\": {\"inicio\": 0.04, \"ytd\": 0.02, \"12m\": 0.038}, ...}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":  {"type": "string"},
                    "fondo_key":       {"type": "string", "description": "'A&R PT', 'A&R Apoquindo' o 'A&R Rentas'"},
                    "rentabilidades":  {"type": "object", "description": "Dict con valores por serie y métrica"},
                },
                "required": ["nombre_archivo", "fondo_key", "rentabilidades"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copiar_datos_tir_rentas",
            "description": (
                "Copia las columnas C:M de la hoja A&R Rentas (archivo CG) a las columnas B:L "
                "de la hoja 'TIR Fondo' en el archivo TIR. Necesario para que el archivo TIR "
                "calcule la rentabilidad desde inicio de cada serie."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_cg":  {"type": "string", "description": "Archivo Control de Gestión en WORK_DIR"},
                    "archivo_tir": {"type": "string", "description": "Archivo TIR Fondo Rentas en WORK_DIR"},
                },
                "required": ["archivo_cg", "archivo_tir"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_tir_rentas_resumen",
            "description": (
                "Lee la hoja 'Resumen' del archivo TIR Fondo Rentas para obtener la TIR "
                "desde inicio anualizada por serie (A, C, I). Muestra el contenido completo "
                "para que el agente identifique los valores correctos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_tir": {"type": "string", "description": "Archivo TIR Fondo Rentas en WORK_DIR"},
                },
                "required": ["archivo_tir"],
            },
        },
    },

    # ── Hoja Caja ──────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "archivar_saldo_caja",
            "description": (
                "Guarda una copia del archivo Saldo Caja en la carpeta de archivo histórico "
                "(SALDO_CAJA_DIR o WORK_DIR/saldo_caja/). No sobreescribe si ya existe. "
                "Llamar después de descargar el adjunto de María José Castro."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Archivo en WORK_DIR a archivar"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_saldo_caja_archivados",
            "description": "Lista todos los archivos Saldo Caja guardados en el archivo histórico.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_hojas_saldo_caja",
            "description": (
                "Lista las hojas del archivo 'Saldo Caja + FFMM Inmobiliario' (enviado "
                "por María José Castro los lunes). Las hojas tienen nombres de fecha; "
                "usar para elegir la más cercana al mes del CDG."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_saldo_caja": {"type": "string", "description": "Archivo en WORK_DIR"},
                },
                "required": ["archivo_saldo_caja"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copiar_datos_saldo_caja",
            "description": (
                "Copia las columnas A:I de la hoja indicada del archivo Saldo Caja "
                "a las columnas A:I de la hoja 'Caja' en el CDG. "
                "Limpia automáticamente números almacenados como texto con puntos (ej: '1.234.567'). "
                "Después de ejecutar, abrir el CDG en Excel y guardar para que R5/R22/R26 recalculen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_cg":          {"type": "string", "description": "Archivo CDG en WORK_DIR"},
                    "archivo_saldo_caja":  {"type": "string", "description": "Archivo Saldo Caja en WORK_DIR"},
                    "nombre_hoja":         {"type": "string", "description": "Nombre de la hoja a usar (ej: '02-02-2026')"},
                },
                "required": ["archivo_cg", "archivo_saldo_caja", "nombre_hoja"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_celdas_caja",
            "description": (
                "Lee los valores cacheados de R5, R22 y R26 de la hoja 'Caja' del CDG. "
                "Ejecutar después de haber abierto y guardado el CDG en Excel "
                "(para que las fórmulas recalculen con los datos pegados)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_cg": {"type": "string", "description": "Archivo CDG en WORK_DIR"},
                },
                "required": ["archivo_cg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspeccionar_caja_historica",
            "description": (
                "Muestra el contenido de las filas 28–40 de la hoja 'Caja' para identificar "
                "la estructura de la tabla Caja Histórica (cabeceras y columnas). "
                "Ejecutar antes de agregar_fila_caja_historica para saber qué columnas usar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_cg": {"type": "string", "description": "Archivo CDG en WORK_DIR"},
                },
                "required": ["archivo_cg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_fila_caja_historica",
            "description": (
                "Añade una nueva fila a la tabla Caja Histórica (comienza en fila 31). "
                "La fecha se calcula automáticamente como el último día del mes. "
                "Requiere saber qué columnas usar (llamar inspeccionar_caja_historica primero)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "archivo_cg":         {"type": "string"},
                    "año":                {"type": "integer", "description": "Año del CDG (ej: 2026)"},
                    "mes":                {"type": "integer", "description": "Mes del CDG (ej: 1 para enero)"},
                    "col_fecha":          {"type": "string", "description": "Columna de fecha (ej: 'A')"},
                    "col_r5":             {"type": "string", "description": "Columna del valor R5"},
                    "col_r22":            {"type": "string", "description": "Columna del valor R22"},
                    "col_r26":            {"type": "string", "description": "Columna del valor R26"},
                    "valor_r5":           {"type": "number", "description": "Valor numérico de celda R5"},
                    "valor_r22":          {"type": "number", "description": "Valor numérico de celda R22"},
                    "valor_r26":          {"type": "number", "description": "Valor numérico de celda R26"},
                    "fila_inicio_datos":  {"type": "integer", "description": "Primera fila de datos (default: 32)"},
                },
                "required": ["archivo_cg", "año", "mes", "col_fecha", "col_r5", "col_r22", "col_r26",
                             "valor_r5", "valor_r22", "valor_r26"],
            },
        },
    },
    # ── Input Tools ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "actualizar_balance_input",
            "description": (
                "Actualiza el balance trimestral en la hoja Input AP/PT/Ren del CDG. "
                "Escribe la fecha en B5 (como serial Excel) y los valores en C5:J5 "
                "(caja, activos circulantes, otros activos, pasivo circ, pasivo LP, "
                "interés minoritario, patrimonio). Usar después de leer el EEFF del trimestre."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo":  {"type": "string", "description": "Nombre del CDG en work/"},
                    "fondo_key":       {"type": "string", "description": "Clave del fondo: 'A&R Apoquindo', 'A&R PT' o 'A&R Rentas'"},
                    "año":             {"type": "integer"},
                    "mes":             {"type": "integer", "description": "Mes de cierre del trimestre (3, 6, 9 o 12)"},
                    "caja":            {"type": "number"},
                    "activos_circ":    {"type": "number"},
                    "otros_activos":   {"type": "number"},
                    "pasivo_circ":     {"type": "number"},
                    "pasivo_lp":       {"type": "number"},
                    "interes_min":     {"type": "number"},
                    "patrimonio":      {"type": "number"},
                },
                "required": ["nombre_archivo", "fondo_key", "año", "mes",
                             "caja", "activos_circ", "otros_activos",
                             "pasivo_circ", "pasivo_lp", "interes_min", "patrimonio"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_fecha_bursatil_input",
            "description": (
                "Actualiza la celda de fecha bursátil mensual en la hoja Input AP/PT/Ren. "
                "La celda varía por fondo: AP→D9, PT→C11, Ren→C10. "
                "Usar cada mes para registrar la fecha bursátil de valorización."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "fondo_key":      {"type": "string", "description": "'A&R Apoquindo', 'A&R PT' o 'A&R Rentas'"},
                    "fecha_serial":   {"type": "integer", "description": "Fecha como serial Excel (días desde 1899-12-30)"},
                },
                "required": ["nombre_archivo", "fondo_key", "fecha_serial"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_fecha_contable_input",
            "description": (
                "Actualiza la celda de fecha contable trimestral en la hoja Input AP/PT/Ren. "
                "La celda varía por fondo: AP→C9, PT→D11, Ren→D10. "
                "Usar cada trimestre cuando se publica el EEFF."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "fondo_key":      {"type": "string", "description": "'A&R Apoquindo', 'A&R PT' o 'A&R Rentas'"},
                    "fecha_serial":   {"type": "integer", "description": "Fecha como serial Excel (días desde 1899-12-30)"},
                },
                "required": ["nombre_archivo", "fondo_key", "fecha_serial"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_dividendo_input",
            "description": (
                "Agrega la fecha de un reparto de dividendos en la tabla de dividendos "
                "de la hoja Input AP/PT/Ren. Busca la primera fila vacía (B=0) y escribe "
                "la fecha; los montos son calculados automáticamente por fórmulas de Excel. "
                "Verifica duplicados antes de escribir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "fondo_key":      {"type": "string", "description": "'A&R Apoquindo', 'A&R PT' o 'A&R Rentas'"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                    "dia":            {"type": "integer", "description": "Día del mes (opcional, default=último día del mes)"},
                },
                "required": ["nombre_archivo", "fondo_key", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspeccionar_dividendos_input",
            "description": (
                "Muestra las filas de la tabla de dividendos de la hoja Input AP/PT/Ren "
                "para verificar qué fechas ya están registradas y qué filas están vacías. "
                "Útil antes de agregar un dividendo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string"},
                    "fondo_key":      {"type": "string", "description": "'A&R Apoquindo', 'A&R PT' o 'A&R Rentas'"},
                },
                "required": ["nombre_archivo", "fondo_key"],
            },
        },
    },
    # ── Vacancia y Tabla Rentas 2 ──────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "actualizar_vacancia",
            "description": (
                "Lee los m2 vacantes del período indicado desde la hoja Resumen del CDG "
                "y los escribe en la columna correspondiente de la hoja Vacancia (filas 47-58). "
                "Usar mensualmente después de consolidar el Rent Roll. "
                "Después de ejecutar, llamar a refrescar_tabla_rentas_2."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg": {"type": "string", "description": "Nombre del archivo CDG en WORK_DIR"},
                    "año":        {"type": "integer", "description": "Año del período (ej: 2026)"},
                    "mes":        {"type": "integer", "description": "Mes del período (1-12)"},
                },
                "required": ["nombre_cdg", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refrescar_tabla_rentas_2",
            "description": (
                "Refresca la tabla dinámica en la hoja 'Tabla Rentas 2' del CDG via Excel COM (solo Windows). "
                "Es necesario para que la hoja Facts Sheet tenga datos actualizados. "
                "Usar después de actualizar_vacancia y consolidar_rent_rolls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg": {"type": "string", "description": "Nombre del archivo CDG en WORK_DIR"},
                },
                "required": ["nombre_cdg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_vacancia",
            "description": (
                "Responde preguntas sobre vacancia: '¿cuál es la vacancia de Viña Centro para enero 2026?'. "
                "Lee los m2 vacantes de la hoja Vacancia del CDG para el período indicado. "
                "Puede filtrar por activo específico o retornar todos. "
                "Activos disponibles: INMOSA, Machalí, SUCDEN, PT Oficinas, PT Locales, PT Bodegas, "
                "Viña Centro, Apoquindo 4700, Apoquindo 4501, Fondo Apoquindo, Curicó, Apoquindo 3001."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg": {"type": "string", "description": "Nombre del archivo CDG en WORK_DIR"},
                    "año":        {"type": "integer", "description": "Año del período (ej: 2026)"},
                    "mes":        {"type": "integer", "description": "Mes del período (ej: 1 para Enero)"},
                    "activo":     {"type": "string",  "description": "Nombre parcial del activo a consultar (opcional). Ej: 'viña', 'curico', 'pt'. Si se omite retorna todos."},
                },
                "required": ["nombre_cdg", "año", "mes"],
            },
        },
    },
    # ── Rent Roll ──────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "revisar_rent_rolls",
            "description": (
                "Busca los archivos de Rent Roll del mes indicado en WORK_DIR "
                "(JLL y Tres Asociados), ejecuta las 4 validaciones "
                "(coherencia de vacantes, absorción, renta escalonada, contratos vencidos) "
                "y retorna el resumen de errores por proveedor. "
                "Usar cuando el usuario pida revisar los RR o el rent roll de un mes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año": {"type": "integer", "description": "Año del mes a revisar (ej: 2026)"},
                    "mes": {"type": "integer", "description": "Mes a revisar (1-12)"},
                },
                "required": ["año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consolidar_absorcion",
            "description": (
                "Sincroniza la hoja 'Absorcion' del CDG con las hojas Absorción de los "
                "proveedores (JLL y Tres A) del período indicado. "
                "Solo agrega entradas nuevas (deduplicación automática). "
                "Las nuevas filas se insertan al final del bloque del activo correspondiente. "
                "Usar después de consolidar el Rent Roll."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año":        {"type": "integer"},
                    "mes":        {"type": "integer"},
                    "nombre_cdg": {"type": "string"},
                },
                "required": ["año", "mes", "nombre_cdg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consolidar_rent_rolls",
            "description": (
                "Copia los datos de los Rent Rolls de proveedores (JLL y Tres A) "
                "a la hoja 'Rent Roll' del CDG. Usa (Activo2, Detalle Activo) como "
                "clave de matching — nunca mueve filas ni toca columnas calculadas. "
                "Usar después de revisar y corregir los RR, cuando el usuario pida consolidar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año":       {"type": "integer", "description": "Año del período (ej: 2026)"},
                    "mes":       {"type": "integer", "description": "Mes del período (1-12)"},
                    "nombre_cdg": {"type": "string", "description": "Nombre del archivo CDG en WORK_DIR (ej: '2601 Control De Gestión.xlsx')"},
                },
                "required": ["año", "mes", "nombre_cdg"],
            },
        },
    },
    # ── NOI-RCSD ───────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "inspeccionar_noi_rcsd",
            "description": (
                "Muestra las etiquetas y el último valor registrado para un activo "
                "en la hoja NOI-RCSD del CDG. Útil para entender la estructura antes "
                "de actualizar. activo: 'inmosa', 'pt', 'apoquindo' o 'apo3001'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg": {"type": "string"},
                    "activo":     {"type": "string", "description": "'inmosa' | 'pt' | 'apoquindo' | 'apo3001'"},
                },
                "required": ["nombre_cdg", "activo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_er_vina",
            "description": (
                "Lee el INFORME EEFF de Viña Centro (Tres Asociados) y agrega la columna "
                "del mes indicado en la hoja 'ER Viña' del CDG. Los valores se guardan en UF. "
                "La hoja NOI-RCSD se actualiza automáticamente por fórmulas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg":  {"type": "string", "description": "Nombre del CDG en WORK_DIR"},
                    "año":         {"type": "integer"},
                    "mes":         {"type": "integer"},
                    "nombre_eeff": {"type": "string", "description": "Nombre del INFORME EEFF en WORK_DIR (opcional, se busca automáticamente)"},
                },
                "required": ["nombre_cdg", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_er_curico",
            "description": (
                "Lee el INFORME EEFF de Curicó (Tres Asociados) y agrega la columna "
                "del mes indicado en la hoja 'ER Curico' del CDG. Los valores se guardan en CLP. "
                "La hoja NOI-RCSD se actualiza automáticamente por fórmulas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg":  {"type": "string", "description": "Nombre del CDG en WORK_DIR"},
                    "año":         {"type": "integer"},
                    "mes":         {"type": "integer"},
                    "nombre_eeff": {"type": "string", "description": "Nombre del INFORME EEFF en WORK_DIR (opcional, se busca automáticamente)"},
                },
                "required": ["nombre_cdg", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_noi_pt",
            "description": (
                "Copia datos de la hoja 'NOI PT' del RR JLL a las filas 335-379 del NOI-RCSD "
                "(sección Parque Titanium). Las celdas con fórmula no se modifican."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg":     {"type": "string"},
                    "nombre_rr_jll":  {"type": "string", "description": "Archivo RR JLL en WORK_DIR"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                },
                "required": ["nombre_cdg", "nombre_rr_jll", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_noi_apoquindo",
            "description": (
                "Copia datos de la hoja 'NOI PT' del RR JLL a las filas 426-456 del NOI-RCSD "
                "(sección Fondo Apoquindo). Las celdas con fórmula no se modifican."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg":     {"type": "string"},
                    "nombre_rr_jll":  {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                },
                "required": ["nombre_cdg", "nombre_rr_jll", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_noi_apo3001",
            "description": (
                "Copia datos de la hoja 'NOI PT' del RR JLL a las filas 468-476 del NOI-RCSD "
                "(sección Apoquindo 3001). Las celdas con fórmula no se modifican."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg":     {"type": "string"},
                    "nombre_rr_jll":  {"type": "string"},
                    "año":            {"type": "integer"},
                    "mes":            {"type": "integer"},
                },
                "required": ["nombre_cdg", "nombre_rr_jll", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_noi_inmosa",
            "description": (
                "Copia los valores de INMOSA desde la planilla ER-FC INMOSA "
                "a las filas 287-295 del NOI-RCSD. "
                "El archivo ER-FC INMOSA debe estar en WORK_DIR."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_cdg":       {"type": "string"},
                    "nombre_er_inmosa": {"type": "string", "description": "Nombre del archivo ER-FC INMOSA en WORK_DIR"},
                    "año":              {"type": "integer"},
                    "mes":              {"type": "integer"},
                },
                "required": ["nombre_cdg", "nombre_er_inmosa", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_emails_rent_roll",
            "description": (
                "Envía los correos con los errores de Rent Roll a Nicole (JLL) y Sebastián (Tres A), "
                "basándose en el resultado de la última revisión con 'revisar_rent_rolls'. "
                "Usar solo después de que el usuario confirme los errores."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    # ── Memoria ────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "leer_contexto",
            "description": "Lee el conocimiento acumulado del agente (context.md). Usar para consultar lo que ya sabe sobre el negocio, fondos, patrones históricos.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_contexto",
            "description": "Actualiza el conocimiento acumulado del agente. Usar cuando se aprende algo nuevo e importante: un patrón, un valor de referencia, una anomalía, contexto del negocio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contenido": {"type": "string", "description": "Contenido completo del nuevo contexto (reemplaza el anterior)"},
                },
                "required": ["contenido"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_historial",
            "description": "Muestra las últimas tareas completadas con sus herramientas y resúmenes. Útil para análisis de patrones o para retomar trabajo anterior.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Número de tareas a mostrar (default 20)"},
                },
            },
        },
    },

    # ── KPIs ───────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "registrar_kpi",
            "description": (
                "Registra un KPI financiero o operacional para un fondo y período. "
                "Usar después de obtener valores de: valor cuota bursátil/contable, NOI, RCSD, "
                "TIR, LTV, dividend yield, dividendo/aporte por cuota, vacancia, superficie vacante, "
                "ingresos de arriendo. El agente debe llamar esto proactivamente al procesar datos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo":   {"type": "string", "description": "Nombre del fondo o activo (ej: 'A&R PT', 'Viña Centro', 'Mall Curicó', 'Parque Titanium')"},
                    "periodo": {"type": "string", "description": "Período YYYY-MM (ej: '2026-03')"},
                    "kpi":     {"type": "string", "description": "Nombre del KPI: valor_cuota_bursatil, valor_cuota_contable, noi, rcsd, tir, ltv, dividend_yield, dividendo_por_cuota, aporte_por_cuota, vacancia, superficie_vacante, ingresos_arriendo"},
                    "valor":   {"type": "number", "description": "Valor numérico"},
                    "unidad":  {"type": "string", "description": "Unidad: CLP, %, m², UF (opcional)"},
                    "fuente":  {"type": "string", "description": "Origen del dato: CMF, EEFF, RR JLL, planilla CDG (opcional)"},
                },
                "required": ["fondo", "periodo", "kpi", "valor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_kpi",
            "description": "Muestra el historial de un KPI para un fondo con variación período a período. Usar para responder preguntas sobre evolución o tendencias.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo":      {"type": "string", "description": "Nombre del fondo o activo"},
                    "kpi":        {"type": "string", "description": "Nombre del KPI"},
                    "n_periodos": {"type": "integer", "description": "Cuántos períodos mostrar (default 12)"},
                },
                "required": ["fondo", "kpi"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resumen_kpis",
            "description": "Muestra todos los KPIs registrados para un fondo en un período específico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo":   {"type": "string", "description": "Nombre del fondo o activo"},
                    "periodo": {"type": "string", "description": "Período YYYY-MM"},
                },
                "required": ["fondo", "periodo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comparar_periodos",
            "description": "Compara todos los KPIs de un fondo entre dos períodos. Muestra variación porcentual. Útil para detectar anomalías o preparar reportes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo":          {"type": "string", "description": "Nombre del fondo o activo"},
                    "periodo_base":   {"type": "string", "description": "Período base YYYY-MM"},
                    "periodo_actual": {"type": "string", "description": "Período actual YYYY-MM"},
                },
                "required": ["fondo", "periodo_base", "periodo_actual"],
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
        # DATOS FS — Rentabilidad
        "actualizar_fecha_ar":          lambda a: actualizar_fecha_ar(a["nombre_archivo"], a["fondo_key"], a["fecha_serial"]),
        "leer_rentabilidades_ar":       lambda a: leer_rentabilidades_ar(a["nombre_archivo"], a["fondo_key"]),
        "pegar_rentabilidades_datos_fs": lambda a: pegar_rentabilidades_datos_fs(a["nombre_archivo"], a["fondo_key"], a["rentabilidades"]),
        "copiar_datos_tir_rentas":      lambda a: copiar_datos_tir_rentas(a["archivo_cg"], a["archivo_tir"]),
        "leer_tir_rentas_resumen":      lambda a: leer_tir_rentas_resumen(a["archivo_tir"]),
        # Caja
        "archivar_saldo_caja":          lambda a: archivar_saldo_caja(a["nombre_archivo"]),
        "listar_saldo_caja_archivados": lambda a: listar_saldo_caja_archivados(),
        "listar_hojas_saldo_caja":      lambda a: listar_hojas_saldo_caja(a["archivo_saldo_caja"]),
        "copiar_datos_saldo_caja":      lambda a: copiar_datos_saldo_caja(a["archivo_cg"], a["archivo_saldo_caja"], a["nombre_hoja"]),
        "leer_celdas_caja":             lambda a: leer_celdas_caja(a["archivo_cg"]),
        "inspeccionar_caja_historica":  lambda a: inspeccionar_caja_historica(a["archivo_cg"]),
        "agregar_fila_caja_historica":  lambda a: agregar_fila_caja_historica(
            a["archivo_cg"], a["año"], a["mes"],
            a["col_fecha"], a["col_r5"], a["col_r22"], a["col_r26"],
            a["valor_r5"], a["valor_r22"], a["valor_r26"],
            a.get("fila_inicio_datos", 32),
        ),
        # Input AP / PT / Ren
        "actualizar_balance_input":      lambda a: actualizar_balance_input(
            a["nombre_archivo"], a["fondo_key"], a["año"], a["mes"],
            a["caja"], a["activos_circ"], a["otros_activos"],
            a["pasivo_circ"], a["pasivo_lp"], a["interes_min"], a["patrimonio"],
        ),
        "actualizar_fecha_bursatil_input": lambda a: actualizar_fecha_bursatil_input(
            a["nombre_archivo"], a["fondo_key"], a["fecha_serial"],
        ),
        "actualizar_fecha_contable_input": lambda a: actualizar_fecha_contable_input(
            a["nombre_archivo"], a["fondo_key"], a["fecha_serial"],
        ),
        "agregar_dividendo_input":       lambda a: agregar_dividendo_input(
            a["nombre_archivo"], a["fondo_key"], a["año"], a["mes"], a.get("dia"),
        ),
        "inspeccionar_dividendos_input": lambda a: inspeccionar_dividendos_input(
            a["nombre_archivo"], a["fondo_key"],
        ),
        # Vacancia y Tabla Rentas 2
        "actualizar_vacancia":           lambda a: actualizar_vacancia(a["nombre_cdg"], a["año"], a["mes"]),
        "refrescar_tabla_rentas_2":      lambda a: refrescar_tabla_rentas_2(a["nombre_cdg"]),
        "consultar_vacancia":            lambda a: consultar_vacancia(a["nombre_cdg"], a["año"], a["mes"], a.get("activo")),
        # Rent Roll
        "revisar_rent_rolls":            lambda a: revisar_rent_rolls(a["año"], a["mes"]),
        "enviar_emails_rent_roll":       lambda a: enviar_emails_rent_roll(),
        "consolidar_rent_rolls":         lambda a: consolidar_rent_rolls(a["año"], a["mes"], a["nombre_cdg"]),
        "consolidar_absorcion":          lambda a: consolidar_absorcion(a["año"], a["mes"], a["nombre_cdg"]),
        # NOI-RCSD
        "inspeccionar_noi_rcsd":         lambda a: inspeccionar_noi_rcsd(a["nombre_cdg"], a["activo"]),
        "actualizar_er_vina":            lambda a: actualizar_er_vina(a["nombre_cdg"], a["año"], a["mes"], a.get("nombre_eeff")),
        "actualizar_er_curico":          lambda a: actualizar_er_curico(a["nombre_cdg"], a["año"], a["mes"], a.get("nombre_eeff")),
        "actualizar_noi_pt":             lambda a: actualizar_noi_pt(a["nombre_cdg"], a["nombre_rr_jll"], a["año"], a["mes"]),
        "actualizar_noi_apoquindo":      lambda a: actualizar_noi_apoquindo(a["nombre_cdg"], a["nombre_rr_jll"], a["año"], a["mes"]),
        "actualizar_noi_apo3001":        lambda a: actualizar_noi_apo3001(a["nombre_cdg"], a["nombre_rr_jll"], a["año"], a["mes"]),
        "actualizar_noi_inmosa":         lambda a: actualizar_noi_inmosa(a["nombre_cdg"], a["nombre_er_inmosa"], a["año"], a["mes"]),
        # Memoria
        "leer_contexto":                 lambda a: leer_contexto(),
        "actualizar_contexto":           lambda a: actualizar_contexto(a["contenido"]),
        "leer_historial":                lambda a: leer_historial(a.get("n", 20)),
        # KPIs
        "registrar_kpi":                 lambda a: registrar_kpi(a["fondo"], a["periodo"], a["kpi"], a["valor"], a.get("unidad", ""), a.get("fuente", "")),
        "consultar_kpi":                 lambda a: consultar_kpi(a["fondo"], a["kpi"], a.get("n_periodos", 12)),
        "resumen_kpis":                  lambda a: resumen_kpis(a["fondo"], a["periodo"]),
        "comparar_periodos":             lambda a: comparar_periodos(a["fondo"], a["periodo_base"], a["periodo_actual"]),
    }
    fn = dispatch.get(name)
    if fn is None:
        return f"Error: herramienta '{name}' no reconocida."
    return fn(args)


# ─── Selección dinámica de herramientas ───────────────────────────────────────

# Herramientas que siempre se incluyen (archivos, memoria, utilidades generales)
_TOOLS_GENERAL = {
    "buscar_correos_con_planillas", "buscar_correos_por_asunto",
    "descargar_adjunto_correo", "enviar_correo",
    "listar_sharepoint", "copiar_de_sharepoint", "guardar_en_sharepoint",
    "listar_servidor_local", "copiar_del_servidor", "guardar_en_servidor",
    "leer_planilla", "validar_planilla", "actualizar_celda",
    "listar_planillas_en_trabajo",
    "leer_contexto", "actualizar_contexto", "leer_historial",
    "registrar_kpi", "consultar_kpi", "resumen_kpis", "comparar_periodos",
}

_TOOLS_CDG = {
    "crear_planilla_mes", "actualizar_fecha_pendientes", "info_siguiente_accion",
    "agregar_vr_bursatil_pt", "agregar_vr_bursatil_rentas",
    "agregar_vr_contable_pt", "agregar_vr_contable_rentas", "agregar_vr_contable_apoquindo",
    "agregar_dividendo_pt", "agregar_dividendo_rentas", "agregar_dividendo_apoquindo",
    "agregar_aporte_pt", "agregar_aporte_rentas", "agregar_aporte_apoquindo",
    "obtener_precio_cuota", "obtener_precios_mes",
    "listar_eeff_disponibles", "leer_eeff",
    "actualizar_fecha_ar", "leer_rentabilidades_ar",
    "pegar_rentabilidades_datos_fs", "copiar_datos_tir_rentas", "leer_tir_rentas_resumen",
    "actualizar_balance_input", "actualizar_fecha_bursatil_input",
    "actualizar_fecha_contable_input", "agregar_dividendo_input", "inspeccionar_dividendos_input",
}

_TOOLS_NOI = {
    "actualizar_er_vina", "actualizar_er_curico",
    "actualizar_noi_pt", "actualizar_noi_apoquindo", "actualizar_noi_apo3001",
    "actualizar_noi_inmosa", "inspeccionar_noi_rcsd",
}

_TOOLS_CAJA = {
    "archivar_saldo_caja", "listar_saldo_caja_archivados",
    "listar_hojas_saldo_caja", "copiar_datos_saldo_caja",
    "leer_celdas_caja", "inspeccionar_caja_historica", "agregar_fila_caja_historica",
}

_TOOLS_RENTROLL = {
    "revisar_rent_rolls", "consolidar_absorcion", "consolidar_rent_rolls",
    "enviar_emails_rent_roll", "actualizar_vacancia", "refrescar_tabla_rentas_2", "consultar_vacancia",
}

_TOOL_INDEX = {t["function"]["name"]: t for t in TOOL_DEFINITIONS}


def _select_tools(user_input: str) -> list:
    """
    Selecciona el subset de herramientas relevante para la instrucción dada.
    Siempre incluye las herramientas generales. Agrega grupos según keywords.
    Si no hay match claro, devuelve todas (fallback seguro).
    """
    u = user_input.lower()

    keywords_noi = ["noi", "viña", "vina", "curicó", "curico", "inmosa",
                    "er vina", "er viña", "er curico", "estado de resultado",
                    "titanium", "apoquindo", "apo3001"]
    keywords_caja = ["caja", "saldo caja", "ffmm", "maría josé", "maria jose"]
    keywords_cdg = ["cdg", "control de gestión", "control de gestion", "planilla",
                    "vr bursatil", "vr contable", "valor razonable", "dividendo",
                    "aporte", "precio cuota", "bursátil", "bursatil",
                    "input ap", "input pt", "input ren", "datos fs", "tir"]
    keywords_rentroll = ["rent roll", "rentroll", "vacancia", "absorción",
                         "absorcion", "jll", "nicole", "tres a", "tres asociados",
                         "sebastian", "arrendatario", "escalonada"]

    grupos = set()
    if any(k in u for k in keywords_noi):
        grupos.add("noi")
    if any(k in u for k in keywords_caja):
        grupos.add("caja")
    if any(k in u for k in keywords_cdg):
        grupos.add("cdg")
    if any(k in u for k in keywords_rentroll):
        grupos.add("rentroll")

    # Si no hay match, devolver todas (fallback)
    if not grupos:
        return TOOL_DEFINITIONS

    nombres = set(_TOOLS_GENERAL)
    if "cdg"      in grupos: nombres |= _TOOLS_CDG
    if "noi"      in grupos: nombres |= _TOOLS_NOI
    if "caja"     in grupos: nombres |= _TOOLS_CAJA
    if "rentroll" in grupos: nombres |= _TOOLS_RENTROLL

    selected = [_TOOL_INDEX[n] for n in nombres if n in _TOOL_INDEX]
    return selected


# ─── Runner principal ─────────────────────────────────────────────────────────

def run_agent(user_input: str) -> None:
    print("\n" + "=" * 60)
    print(f"Instrucción: {user_input}")
    print("=" * 60)

    # Inyectar memoria en el system prompt
    memory_block = load_memory()
    system_content = SYSTEM_PROMPT
    if memory_block:
        system_content = SYSTEM_PROMPT + "\n\n---\n\n" + memory_block

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_input},
    ]

    tools_used = []
    final_response = ""

    selected_tools = _select_tools(user_input)
    n_selected = len(selected_tools)
    n_total = len(TOOL_DEFINITIONS)
    if n_selected < n_total:
        print(f"  [tools] {n_selected}/{n_total} herramientas activas")

    while True:
        response = client.chat.completions.create(
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
