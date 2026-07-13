import json
import os
import re
import unicodedata
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
    guardar_ubicacion,
    buscar_ubicacion,
    leer_wiki,
)

from tools.email_tools import (
    list_emails_with_attachments,
    download_email_attachment,
    send_email,
    search_emails_by_subject,
    check_replies_from_contact,
    find_sent_email,
    reply_to_email,
)
from tools.sharepoint_tools import (
    list_sharepoint_files,
    search_sharepoint_files,
    copy_from_sharepoint,
    save_to_sharepoint,
    refresh_sharepoint_index,
    mover_en_sharepoint,
    crear_carpeta_sharepoint,
    eliminar_carpeta_sharepoint,
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
    guardar_cdg,
    buscar_tir,
    verificar_archivos_cdg,
    previsualizar_correos_solicitud_cdg,
    enviar_correos_solicitud_cdg,
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
    leer_cdg_historico,
)
from tools.eeff_tools import (
    listar_eeff_disponibles,
    leer_eeff,
)
from tools.web_bursatil_tools import (
    obtener_precio_cuota,
    obtener_precios_mes,
)
from tools.uf_web_tools import actualizar_uf_desde_web
from tools.rentroll_tools import (
    revisar_rent_rolls,
    revisar_rent_roll_jll,
    enviar_emails_rent_roll,
    consolidar_rent_rolls,
    consolidar_absorcion,
    buscar_en_rent_roll,
)
from tools.factsheet_tools import (
    fecha_contable_fs,
    obtener_valor_libro_fs,
    obtener_historico_valor_libro_fs,
    obtener_precios_bursatiles_fs,
    leer_repartos_fs,
    listar_shapes_fs,
    leer_tabla_fs,
    preparar_fs,
    actualizar_fs_pt,
    actualizar_fs_apoquindo,
    actualizar_fs_tri,
    guardar_fs,
)
from tools.ask_tools import preguntar_usuario
from tools.raw_tools import ordenar_archivos_raw, reemplazar_en_tool, reemplazar_en_wiki
from tools.query_tools import (
    consultar_db_kpi,
    consultar_db_precio,
    consultar_db_rent_roll,
    consultar_db_er,
    consultar_db_flujo,
    consultar_db_dividendos,
    consultar_db_cobertura,
    consultar_db_capital_suscrito,
    consultar_db_patrimonio_bursatil,
    consultar_db_valor_libro,
    consultar_db_valor_bursatil,
    consultar_dividend_yield,
    consultar_db_tasaciones,
    consultar_db_adquisiciones,
    consultar_ltv,
)
from tools.db.dashboard import generar_dashboard
from tools.db.ingest_router import ingestar_archivo
from tools.noi_query import consultar_noi
from tools.finance_tools import (
    calcular_indicador_financiero,
    calcular_dy_fondo,
    calcular_tir_fondo,
    listar_indicadores_disponibles,
    invalidar_cache_indicador,
    verificar_skill,
)
from tools.financiamiento_tools import consultar_financiamiento

_MAX_TOOL_RESULT    = 6_000   # chars máximos por resultado de tool antes de truncar
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "preguntar_usuario",
            "description": (
                "Hace una pregunta directa al usuario y espera su respuesta. "
                "Usar cuando: (1) no encuentras un archivo después de buscar en ubicaciones conocidas y derivadas, "
                "(2) hay ambigüedad real que no puedes resolver con el contexto disponible, "
                "(3) una operación falla repetidamente y no tienes más alternativas, "
                "(4) necesitas un dato específico que no puedes derivar (ruta exacta, nombre, credencial). "
                "IMPORTANTE: llámala sola o como última herramienta del turno. Una sola pregunta por llamada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pregunta": {
                        "type": "string",
                        "description": "La pregunta específica para el usuario. Concisa y clara.",
                    }
                },
                "required": ["pregunta"],
            },
        },
    },
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
            "description": (
                "Busca correos cuyo asunto contenga una palabra o frase. "
                "No usar para preguntas tipo 'X respondio el mail?' si hay un contacto/persona; "
                "en ese caso usar revisar_respuestas_contacto."
            ),
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
            "name": "revisar_respuestas_contacto",
            "description": (
                "Revisa Outlook por contacto/remitente/destinatario si una persona respondio "
                "despues del ultimo correo enviado a esa persona. Usar para preguntas como "
                "'Cantillana respondio el mail que le mandaste?' o seguimientos personales. "
                "No requiere saber el asunto; evita buscar por temas CDG salvo que el usuario lo pida."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contacto": {
                        "type": "string",
                        "description": "Nombre, apellido o alias del contacto. Ej: 'Cantillana'.",
                    },
                    "email": {
                        "type": "string",
                        "description": "Email opcional si se conoce. Ej: lcantillana@grupoaraucana.cl.",
                    },
                    "limite": {
                        "type": "integer",
                        "description": "Maximo de respuestas a mostrar (por defecto 5).",
                    },
                    "scan_limit": {
                        "type": "integer",
                        "description": "Cantidad de correos recientes a revisar en enviados/entrada (por defecto 500).",
                    },
                },
                "required": ["contacto"],
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
            "description": "Envía un correo desde Outlook con o sin archivo adjunto. NUNCA inventes un destinatario: usa un email completo (con @) o uno de los alias conocidos: nicole, cantillana/leonardo, valentina, sebastian. Si el usuario menciona un contacto que no está en esa lista, pregúntale el email antes de llamar a esta tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destinatario":    {"type": "string", "description": "Email completo (ej. nicole.carvajal@jll.com) o alias conocido (ej. 'nicole'). NO usar el email del propio usuario."},
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
            "name": "buscar_en_sharepoint",
            "description": "Busca archivos recursivamente en SharePoint cuyo nombre contenga el keyword dado. Usar cuando no se sabe la subcarpeta exacta de un archivo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword":    {"type": "string", "description": "Texto a buscar en el nombre del archivo (ej: '2602', 'CDG', 'EEFF')"},
                    "subcarpeta": {"type": "string", "description": "Subcarpeta raíz donde buscar (opcional, por defecto busca en todo SharePoint)"},
                },
                "required": ["keyword"],
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
            "name": "actualizar_indice_sharepoint",
            "description": "Escanea el SharePoint sincronizado y actualiza wiki/sharepoint/index.md con el árbol actual de archivos. Usar después de mover o reorganizar archivos.",
            "parameters": {"type": "object", "properties": {}},
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
            "description": "Crea la planilla mensual de Control de Gestión Renta Comercial copiando la del mes anterior en SharePoint. El archivo nuevo tendrá sufijo vAgente.",
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
            "name": "guardar_cdg",
            "description": (
                "Guarda el CDG editado de vuelta en SharePoint (Control de Gestión/CDG Mensual/{año}/). "
                "SOLO puede guardar archivos vAgente — rechaza vF y vActualizar. "
                "Llamar al terminar de actualizar el CDG."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del archivo vAgente en WORK_DIR o ruta absoluta"},
                },
                "required": ["nombre_archivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verificar_archivos_cdg",
            "description": (
                "Verifica qué archivos necesarios para actualizar el CDG de un mes están disponibles "
                "y cuáles faltan. Usar cuando el usuario pregunta: '¿tienes todo para el CDG?', "
                "'¿qué archivos tienes?', '¿qué archivos te faltan?', '¿qué te falta?', '¿puedes actualizar el CDG?'. "
                "Retorna el resultado COMPLETO con dos secciones claramente separadas: "
                "'Archivos encontrados (X/N)' con la ruta exacta de cada uno, "
                "y 'Archivos faltantes (Y/N)' con los que no se encontraron. "
                "SIEMPRE copiar el resultado ÍNTEGRO al usuario — nunca resumir ni omitir la sección de encontrados. "
                "Incluye archivos de fin de trimestre si corresponde (mar/jun/sep/dic). "
                "No existe un requisito RR/NOI Cushman para el CDG; INMOSA corresponde a ER-FC INMOSA."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año": {"type": "integer", "description": "Año del CDG (ej: 2026)"},
                    "mes": {"type": "integer", "description": "Mes del CDG (1-12)"},
                },
                "required": ["año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "previsualizar_correos_solicitud_cdg",
            "description": (
                "Redacta, sin enviar, los correos para pedir los archivos faltantes del CDG "
                "a los contactos configurados. Usar cuando el usuario pide ver/redactar/preparar "
                "el mail de solicitud o de seguimiento. Si seguimiento no se informa, se decide "
                "automáticamente según si ya existen solicitudes registradas para ese período."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año": {"type": "integer", "description": "Año del período (ej: 2026)"},
                    "mes": {"type": "integer", "description": "Mes del período (1-12)"},
                    "seguimiento": {
                        "type": "boolean",
                        "description": "True para redactar seguimiento; False para primera solicitud. Omitir para automático.",
                    },
                    "excluir": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Contactos o archivos a omitir. Ej: ['jll'], ['rr_jll'], ['nicole'], ['er_fc_inmosa'].",
                    },
                    "solo": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Si se especifica, SOLO se incluye a estos contactos. Ej: ['nicole'] para enviar únicamente a Nicole. Toma precedencia sobre excluir.",
                    },
                },
                "required": ["año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_correos_solicitud_cdg",
            "description": (
                "Envía desde Outlook los correos para solicitar los archivos faltantes del CDG "
                "y registra la fecha de envío para futuros seguimientos. Usar solo cuando el usuario "
                "confirma explícitamente que quiere enviarlos. Si seguimiento no se informa, se decide "
                "automáticamente según si ya existen solicitudes registradas para ese período."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año": {"type": "integer", "description": "Año del período (ej: 2026)"},
                    "mes": {"type": "integer", "description": "Mes del período (1-12)"},
                    "seguimiento": {
                        "type": "boolean",
                        "description": "True para enviar seguimiento; False para primera solicitud. Omitir para automático.",
                    },
                    "excluir": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Contactos o archivos a omitir. Ej: ['jll'], ['rr_jll'], ['nicole'], ['er_fc_inmosa'].",
                    },
                    "solo": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Si se especifica, SOLO se envía a estos contactos. Ej: ['nicole']. Toma precedencia sobre excluir.",
                    },
                },
                "required": ["año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_tir",
            "description": (
                "Busca el archivo Cálculo TIR Fondo Rentas más reciente en SharePoint "
                "(Control de Gestión/Cálculo TIR/). Necesario solo en fin de trimestre."
            ),
            "parameters": {"type": "object", "properties": {}},
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
            "name": "actualizar_uf_desde_web",
            "description": (
                "Descarga los valores de UF diaria desde mindicador.cl y actualiza fact_uf en la DB "
                "con todos los días que falten desde la última fecha registrada hasta hoy. "
                "Úsala antes de calcular cualquier indicador en UF si puede haber datos desactualizados."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agregar_vr_bursatil_pt",
            "description": "Agrega la fila mensual de VR Bursátil en la hoja PT de la planilla.",
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
            "description": "Agrega las 3 filas mensuales de VR Bursátil en la hoja TRI (series A, C, I).",
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
            "description": "Agrega la fila trimestral de VR Contable en la hoja PT.",
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
            "description": "Agrega las 3 filas trimestrales de VR Contable en la hoja TRI.",
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
                    "fondo_key": {"type": "string", "description": "Nombre del fondo: 'Apo', 'PT' o 'TRI'"},
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
                "IMPORTANTE: para VR Contable del CDG, usar el trimestre ANTERIOR al mes del CDG "
                "(CDG marzo → mes=12, año=año-1; CDG junio → mes=3; etc.). "
                "Si la extracción automática falla, retorna el texto relevante del PDF "
                "para que puedas identificar los valores manualmente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {"type": "string", "description": "'Apo', 'PT' o 'TRI'"},
                    "año":       {"type": "integer", "description": "Año del trimestre (OJO: puede diferir del año del CDG)"},
                    "mes":       {"type": "integer", "description": "Mes de cierre del trimestre ANTERIOR al CDG (3, 6, 9 o 12)"},
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
            "description": "Agrega una fila de Dividendo en la hoja PT.",
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
            "description": "Agrega filas de Dividendo en TRI (series A, C, I).",
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
            "description": "Agrega una fila de Dividendo en la hoja Apo.",
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
            "description": "Agrega una fila de Aporte en la hoja PT.",
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
            "description": "Agrega filas de Aporte en TRI (series A, C, I).",
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
            "description": "Agrega una fila de Aporte en la hoja Apo.",
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
            "description": "Agrega la fila trimestral de VR Contable en la hoja Apo.",
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
            "name": "revisar_rent_roll_jll",
            "description": (
                "Revisa solo el Rent Roll JLL del mes indicado con las validaciones de rent roll. "
                "Es SOLO LECTURA: no copia datos al CDG, no actualiza NOI y no modifica archivos. "
                "Usar cuando el usuario pida revisar, validar o chequear el RR/Rent Roll de JLL."
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
    {
        "type": "function",
        "function": {
            "name": "enviar_emails_rent_roll",
            "description": (
                "Envía los correos con los errores de Rent Roll a Nicole (JLL) y Sebastián (Tres A), "
                "basándose en el resultado de la última revisión con 'revisar_rent_rolls'. "
                "Usar SIEMPRE esta herramienta para enviar correos de Rent Roll — nunca usar 'enviar_correo' directamente. "
                "El correo a Sebastián (Tres A) solo incluye errores de Viña Centro y Curicó, NUNCA datos de JLL. "
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
                    "fondo":   {"type": "string", "description": "Nombre del fondo o activo (ej: 'PT', 'Viña Centro', 'Mall Curicó', 'Parque Titanium')"},
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
    {
        "type": "function",
        "function": {
            "name": "consultar_db_cobertura",
            "description": "PRIMERO al responder preguntas sobre datos: muestra qué hay en la base de datos del agente (filas y rango de períodos por dominio: rent_roll, er_activo, flujo, kpi, precios, uf, dividendos). Úsala para saber si la DB ya tiene el dato antes de abrir un Excel.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_kpi",
            "description": "Consulta la serie temporal de un KPI desde la base de datos (no abre Excel). KPIs disponibles dependen de lo registrado, ej. 'valor_cuota_libro'. Para preguntas sobre evolución/tendencias de un fondo, activo o serie.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entidad_tipo": {"type": "string", "enum": ["fondo", "activo", "serie"], "description": "Tipo de entidad"},
                    "entidad_key":  {"type": "string", "description": "Clave: ej 'PT', 'TRI', nemotécnico 'CFITOERI1A'"},
                    "kpi":          {"type": "string", "description": "Nombre del KPI, ej 'valor_cuota_libro'"},
                    "desde":        {"type": "string", "description": "Período inicial YYYY-MM (opcional)"},
                    "hasta":        {"type": "string", "description": "Período final YYYY-MM (opcional)"},
                },
                "required": ["entidad_tipo", "entidad_key", "kpi"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_precio",
            "description": "Consulta precios de cuota desde la base de datos (no abre Excel ni web). Sin fecha devuelve los más recientes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {"type": "string", "description": "Ej CFITRIPT-E, CFITOERI1A/C/I"},
                    "fecha":       {"type": "string", "description": "Fecha YYYY-MM-DD (opcional)"},
                },
                "required": ["nemotecnico"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_rent_roll",
            "description": "Consulta el rent roll (arrendatarios, m², renta, vencimiento) de un activo y período desde la base de datos, sin abrir el Excel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activo_key": {"type": "string", "description": "PT, Apoquindo, Apo3001, Viña Centro, Mall Curicó"},
                    "periodo":    {"type": "string", "description": "Período YYYY-MM"},
                },
                "required": ["activo_key", "periodo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_er",
            "description": "Consulta las líneas del estado de resultado (cuenta y monto CLP) de un activo y período desde la base de datos. Para Viña Centro y Mall Curicó.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activo_key": {"type": "string", "description": "Viña Centro, Mall Curicó"},
                    "periodo":    {"type": "string", "description": "Período YYYY-MM"},
                },
                "required": ["activo_key", "periodo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_flujo",
            "description": "Consulta las líneas de flujo (cuenta y monto CLP) de un activo y período desde la base de datos. Ej. INMOSA.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activo_key": {"type": "string", "description": "Ej INMOSA"},
                    "periodo":    {"type": "string", "description": "Período YYYY-MM"},
                },
                "required": ["activo_key", "periodo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_valor_bursatil",
            "description": (
                "Consulta el VR Bursátil por cuota por serie TRI en UF. "
                "= SUM(Monto UF/cuota col M) donde Detalle='VR Bursátil' y Fecha=exacta. "
                "Dato mensual desde 2017-12 hasta 2026-03. "
                "Distinto de Patrimonio Bursátil total (que usa col L). Aquí se usa col M."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {
                        "type": "string",
                        "description": "Ej: 'CFITOERI1A' (Serie A), 'CFITOERI1C' (Serie C), 'CFITOERI1I' (Serie I). Omitir para todas."
                    },
                    "fecha": {
                        "type": "string",
                        "description": "Fecha exacta: 'YYYY-MM-DD' o 'YYYY-MM'. Omitir para la última disponible."
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_valor_libro",
            "description": (
                "Consulta el VR Contable (valor libro) por cuota por serie TRI en UF. "
                "Fuente: raw_valor_cuota_contable tipo='contable' (EEFF PDFs prioritario, fallback A&R Rentas). "
                "Dato trimestral. Devuelve precio_uf = UF por cuota a la fecha exacta solicitada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {
                        "type": "string",
                        "description": "Ej: 'CFITOERI1A' (Serie A), 'CFITOERI1C' (Serie C), 'CFITOERI1I' (Serie I). Omitir para todas."
                    },
                    "fecha": {
                        "type": "string",
                        "description": "Fecha de corte trimestral: 'YYYY-MM-DD' o 'YYYY-MM'. Omitir para la última disponible."
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_patrimonio_bursatil",
            "description": (
                "Consulta el Patrimonio Bursátil por serie del fondo TRI desde la base de datos. "
                "Patrimonio Bursátil = SUM(Monto UF) de filas con Detalle='VR Bursátil' para la fecha exacta. "
                "Cubre 114 fechas mensuales desde 2017 hasta 2026-03. "
                "A diferencia del capital suscrito, NO es acumulado — es un snapshot mensual."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {
                        "type": "string",
                        "description": "Ej: 'CFITOERI1A' (Serie A), 'CFITOERI1C' (Serie C), 'CFITOERI1I' (Serie I). Omitir para todas."
                    },
                    "fecha": {
                        "type": "string",
                        "description": "Fecha exacta de corte: 'YYYY-MM-DD' o 'YYYY-MM' (se expande al último día del mes). Omitir para la última disponible."
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_capital_suscrito",
            "description": (
                "Consulta el capital suscrito acumulado por serie del fondo TRI desde la base de datos. "
                "Calcula desde movimientos históricos A&R (Aportes + Canjes - Disminuciones en UF). "
                "Para un período dado devuelve el último valor acumulado en o antes de esa fecha. "
                "Si no se especifica fecha_corte, devuelve el último disponible (sep-2021)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {
                        "type": "string",
                        "description": "Ej: 'CFITOERI1A' (Serie A), 'CFITOERI1C' (Serie C), 'CFITOERI1I' (Serie I). Omitir para todas."
                    },
                    "fecha_corte": {
                        "type": "string",
                        "description": "Fecha de corte: 'YYYY-MM-DD' o 'YYYY-MM'. Devuelve el acumulado en o antes de esta fecha."
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_financiamiento",
            "description": (
                "Consulta información de deuda, amortización y financiamiento del portfolio Toesca desde la DB. "
                "Usar para cualquier pregunta sobre: créditos bancarios, saldo de deuda, amortización de capital, "
                "perfil de vencimientos, pagarés intercompañía, o DY+amortización (dividend yield + amort) por serie TRI.\n"
                "Tipos disponibles:\n"
                "  creditos_vigentes: lista créditos bancarios con saldo, tasa, vencimiento.\n"
                "  amortizacion: capital amortizado en un período (desde/hasta YYYY-MM).\n"
                "  saldo_deuda: saldo de deuda actual por fondo o crédito.\n"
                "  perfil_vencimientos: amortizaciones anuales proyectadas (histograma).\n"
                "  pagares: pagarés intercompañía fondo↔sociedad.\n"
                "  dy_amort: dividend yield + amortización por cuota para series TRI (A/C/I), "
                "rolling 12 meses. Fórmula: (dividendos_U12M + amort_UF×UF/cuotas) / valor_cuota."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "enum": ["creditos_vigentes", "amortizacion", "saldo_deuda",
                                 "perfil_vencimientos", "pagares", "dy_amort"],
                        "description": "Tipo de consulta.",
                    },
                    "fondo": {
                        "type": "string",
                        "description": "Filtrar por fondo: 'TRI', 'PT' o 'Apo'. Opcional.",
                    },
                    "desde": {
                        "type": "string",
                        "description": "Período inicio YYYY-MM (para tipo=amortizacion).",
                    },
                    "hasta": {
                        "type": "string",
                        "description": "Período fin YYYY-MM (para tipo=amortizacion).",
                    },
                    "credito_key": {
                        "type": "string",
                        "description": "Clave de crédito específico, ej: TRI_SUCDEN_BICE. Opcional.",
                    },
                    "fecha_corte": {
                        "type": "string",
                        "description": "Fecha de corte YYYY-MM para dy_amort (rolling 12 meses hasta esa fecha). Por defecto: mes anterior al día de hoy.",
                    },
                    "tipo_valor": {
                        "type": "string",
                        "enum": ["bursatil", "contable"],
                        "description": "Tipo de valor cuota para dy_amort: 'bursatil' o 'contable'. Por defecto: bursatil.",
                    },
                },
                "required": ["tipo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_dividendos",
            "description": "Consulta el historial de dividendos por cuota de una serie desde la base de datos. Nemotécnicos: CFITRIPT-E, CFITOERI1A/C/I.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {"type": "string", "description": "Ej CFITRIPT-E"},
                },
                "required": ["nemotecnico"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_dividend_yield",
            "description": (
                "Calcula el dividend yield o total de dividendos repartidos de una serie TRI. "
                "tipo='contable' (default): DY = dividendos U12M UF/cuota / valor libro UF/cuota. "
                "tipo='bursatil': DY = dividendos U12M UF/cuota / precio bursátil UF/cuota. "
                "tipo='total': suma total de dividendos UF/cuota repartidos en el año. "
                "Usar cuando el usuario pregunta por: dividend yield, DY, rentabilidad por dividendos, "
                "cuánto rinde el fondo en dividendos, total dividendos repartidos, distribuciones. "
                "Nemotécnicos TRI: CFITOERI1A (Serie A), CFITOERI1C (Serie C), CFITOERI1I (Serie I)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {
                        "type": "string",
                        "description": "Ej. CFITOERI1A, CFITOERI1C, CFITOERI1I",
                    },
                    "periodo": {
                        "type": "string",
                        "description": "Período de referencia YYYY-MM. Si se omite, usa el año más reciente con datos.",
                    },
                    "anio": {
                        "type": "integer",
                        "description": "Año calendario (ej. 2025). Alternativo a periodo; usa diciembre de ese año.",
                    },
                    "tipo": {
                        "type": "string",
                        "enum": ["contable", "bursatil", "total"],
                        "description": "Tipo de cálculo: 'contable' (DY sobre libro), 'bursatil' (DY sobre precio bolsa), 'total' (suma dividendos del año).",
                    },
                },
                "required": ["nemotecnico"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_tasaciones",
            "description": (
                "Consulta las tasaciones de activos inmobiliarios (fact_tasacion). "
                "Muestra los valores de cada tasadora por año y el promedio. "
                "Usar cuando el usuario pregunta por: tasación, valor tasado, cap rate, "
                "tasa de descuento, LTV, LTC, leverage financiero, UF/m² tasado, "
                "o comparación entre tasadoras."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activo_key": {
                        "type": "string",
                        "description": "Ej. 'PT', 'Viña Centro', 'INMOSA'. Omitir para todos.",
                    },
                    "periodo": {
                        "type": "string",
                        "description": "Año (YYYY). Omitir para todos los años.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_db_adquisiciones",
            "description": (
                "Consulta los valores de compra/adquisición de activos inmobiliarios (fact_adquisicion). "
                "Muestra el precio pagado, valor del activo al 100%, UF/m², fecha y porcentaje adquirido. "
                "Usar cuando el usuario pregunta por: precio de compra, valor de adquisición, "
                "cuánto se pagó por el activo, fecha de entrada al portfolio."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activo_key": {
                        "type": "string",
                        "description": "Ej. 'PT', 'Viña Centro'. Omitir para todos.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_ltv",
            "description": (
                "Calcula el LTV (Loan-to-Value) dinámico por activo inmobiliario y por fondo. "
                "LTV = deuda total al 100% del activo / tasación promedio vigente. "
                "El saldo de deuda se actualiza mensualmente (baja a medida que se paga). "
                "La tasación usa el promedio del año más reciente disponible. "
                "Muestra también el LTV agregado por fondo (deuda económica / valor económico). "
                "Usar cuando el usuario pregunta por: LTV, apalancamiento, deuda sobre valor, "
                "loan to value, deuda relativa al activo, cuánto debe el fondo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activo_key": {
                        "type": "string",
                        "description": "Ej. 'Torre A', 'INMOSA'. Omitir para todos.",
                    },
                    "periodo": {
                        "type": "string",
                        "description": "Período YYYY-MM. Omitir para usar el último mes disponible.",
                    },
                    "fondo_key": {
                        "type": "string",
                        "enum": ["PT", "TRI", "Apo"],
                        "description": "Filtrar por fondo. Omitir para todos.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_noi",
            "description": "Consulta el NOI (Net Operating Income) en UF desde la base de datos: mensual, anual, anualizado (real YTD + promedio histórico de meses faltantes), U12M, y variaciones MoM e YoY. Puede agregar por activo, fondo, categoría (Oficinas, Centros Comerciales, Residencias, Industrial) o total, al 100% del activo o ponderado por % de participación del fondo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nivel": {"type": "string", "enum": ["activo", "fondo", "categoria", "total"], "description": "Nivel de agregación"},
                    "clave": {"type": "string", "description": "activo_key (PT, Apoquindo, Apo3001, Viña Centro, Mall Curicó, INMOSA, Sucden), fondo_key (PT, Apo, TRI) o categoría. Omitir para 'total'."},
                    "año": {"type": "integer", "description": "Año de referencia (default: el del último dato)"},
                    "ponderado": {"type": "boolean", "description": "Si true, pondera por % de participación del fondo en cada activo. Default false (100%)."},
                },
                "required": ["nivel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generar_dashboard",
            "description": "Regenera el dashboard HTML (dashboard.html) con todo lo que tiene la base de datos: cobertura por activo/período, gaps a poblar, series de mercado y explorador. Devuelve la ruta del archivo para abrir en el navegador.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ingestar_archivo",
            "description": (
                "Ingesta un archivo de proveedor a la DB del agente. Detecta el tipo "
                "automáticamente por nombre del archivo (INFORME EEFF Viña/Curicó → "
                "raw_er_activo_line; ER-FC INMOSA → raw_flujo_line). Es idempotente: "
                "re-ingestar no duplica. Usar cuando el usuario provee un archivo "
                "nuevo que debe entrar a la DB."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta al archivo a ingestar."},
                    "periodo": {"type": "string", "description": "YYYY-MM. Opcional; se infiere del archivo si no se entrega."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_ubicacion",
            "description": (
                "Busca si ya se conoce la ubicación de un archivo o recurso. "
                "LLAMAR SIEMPRE ANTES de buscar cualquier archivo en disco, SharePoint o servidor. "
                "Si retorna una ruta conocida, ir directamente ahí sin explorar. "
                "Ejemplos de concepto: 'eeff viña', 'rent roll jll', 'er inmosa', 'cdg febrero 2026', 'saldo caja'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "concepto": {"type": "string", "description": "Término de búsqueda (ej: 'eeff viña 2026', 'rr jll febrero')"},
                },
                "required": ["concepto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "guardar_ubicacion",
            "description": (
                "Guarda la ubicación de un archivo encontrado para recordarlo en futuras sesiones. "
                "LLAMAR SIEMPRE después de encontrar un archivo que fue buscado (ya sea por el agente o indicado por el usuario). "
                "Así la próxima vez el agente va directo al archivo sin buscar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "concepto": {"type": "string", "description": "Identificador semántico (ej: 'eeff_vina_2026', 'rr_jll_febrero_2026')"},
                    "ruta":     {"type": "string", "description": "Ruta absoluta o nombre del archivo encontrado"},
                    "notas":    {"type": "string", "description": "Info adicional: hoja relevante, convención de nombre, columnas clave, etc."},
                },
                "required": ["concepto", "ruta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_wiki",
            "description": (
                "Lee una página de la wiki del agente. "
                "USAR para consultar rutas SharePoint, convenciones de nombres, procesos o cualquier "
                "información documentada en la wiki antes de responder preguntas de ubicación de archivos. "
                "Páginas útiles: 'sharepoint/index' (árbol completo con rutas y patrones de nombre), "
                "'index' (índice general), 'log' (historial de cambios). "
                "Si el usuario pregunta dónde subir un archivo, leer 'sharepoint/index' primero."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pagina": {"type": "string", "description": "Nombre de la página, ej: 'sharepoint/index', 'index', 'log'"},
                },
                "required": ["pagina"],
            },
        },
    },
    # ── Consultas históricas ───────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "leer_cdg_historico",
            "description": (
                "Lee una hoja de cualquier CDG histórico directamente desde el servidor, "
                "sin copiar al WORK_DIR. Responde preguntas históricas sobre vacancia, NOI, "
                "precios cuota, dividendos, balances, etc. de cualquier mes pasado. "
                "Hojas útiles: 'Vacancia', 'NOI-RCSD', 'Input AP', 'Input PT', 'Input Ren', "
                "'ER Viña', 'ER Curico', 'Rent Roll'. "
                "Usa 'filtro' para buscar un activo o concepto específico dentro de la hoja."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mes":    {"type": "integer", "description": "Mes del CDG (1-12)"},
                    "año":    {"type": "integer", "description": "Año del CDG (ej: 2026)"},
                    "hoja":   {"type": "string",  "description": "Nombre de la hoja a leer"},
                    "filtro": {"type": "string",  "description": "Keyword para filtrar filas (opcional). Ej: 'Apoquindo', 'Viña', 'PT'"},
                },
                "required": ["mes", "año", "hoja"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_rent_roll",
            "description": (
                "Busca arrendatarios y condiciones de contrato en el Rent Roll JLL de un mes histórico. "
                "Lee directamente desde SharePoint sin copiar el archivo. "
                "Responde preguntas como: '¿quién ocupaba el local X en Apoquindo en febrero?', "
                "'¿cuál era la renta de Y?', '¿cuándo vence el contrato de Z?'. "
                "Filtra por activo (ej: 'Apoquindo', 'Parque Titanium') y/o por local/detalle."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mes":    {"type": "integer", "description": "Mes del Rent Roll (1-12)"},
                    "año":    {"type": "integer", "description": "Año del Rent Roll (ej: 2026)"},
                    "activo": {"type": "string",  "description": "Filtrar por activo (ej: 'Apoquindo', 'PT', 'Titanium'). Opcional."},
                    "local":  {"type": "string",  "description": "Filtrar por nombre/número de local o detalle. Opcional."},
                },
                "required": ["mes", "año"],
            },
        },
    },
    # ── Fact Sheets ──────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "listar_shapes_fs",
            "description": "Lista todos los shapes del Slide 1 de un Fact Sheet. Útil para descubrir nombres de tablas antes de actualizar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {"type": "string", "description": "'PT', 'Apoquindo' o 'TRI'"},
                    "año":       {"type": "integer", "description": "Año del FS (ej: 2026)"},
                    "mes":       {"type": "integer", "description": "Mes del FS (1-12)"},
                },
                "required": ["fondo_key", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_tabla_fs",
            "description": "Lee el contenido de una tabla específica del Fact Sheet (Slide 1) por nombre de shape (ej: 'Tabla 52'). Útil para inspeccionar datos antes de actualizar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key":  {"type": "string", "description": "'PT', 'Apoquindo' o 'TRI'"},
                    "año":        {"type": "integer"},
                    "mes":        {"type": "integer"},
                    "shape_name": {"type": "string", "description": "Nombre del shape, ej: 'Tabla 52'"},
                },
                "required": ["fondo_key", "año", "mes", "shape_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preparar_fs",
            "description": "Copia el archivo vActualizar/vRevisar del Fact Sheet desde SharePoint a WORK_DIR para edición. Llamar siempre antes de actualizar_fs_pt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {"type": "string", "description": "'PT', 'Apoquindo' o 'TRI'"},
                    "año":       {"type": "integer"},
                    "mes":       {"type": "integer"},
                },
                "required": ["fondo_key", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_fs_pt",
            "description": (
                "Actualiza todas las tablas numéricas del Slide 1 del Fact Sheet PT. "
                "Requiere haber llamado preparar_fs('PT', año, mes) antes. "
                "datos_json acepta los campos: precios_bursatiles, valor_libro, rentabilidad, dividendos, "
                "otros_indicadores, balance, gastos, endeudamiento, perfil_vencimiento, info_fondo. "
                "Solo actualiza los campos incluidos; el resto queda sin cambios."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año":       {"type": "integer"},
                    "mes":       {"type": "integer"},
                    "datos_json": {
                        "type": "string",
                        "description": "JSON con los datos a actualizar. Ver docstring de actualizar_fs_pt para estructura completa.",
                    },
                },
                "required": ["año", "mes", "datos_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_historico_valor_libro_fs",
            "description": (
                "Retorna los últimos n trimestres de valor cuota libro para la Tabla 7 del FS. "
                "El trimestre más reciente es el cierre contable del mes del FS. "
                "Llama a leer_eeff para cada trimestre automáticamente. "
                "Retorna JSON listo para datos_json['valor_libro']."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {"type": "string", "description": "'PT', 'Apo' o 'TRI'"},
                    "año_fs":    {"type": "integer"},
                    "mes_fs":    {"type": "integer", "description": "Mes del FS: 1, 4, 7 ó 10"},
                    "n":         {"type": "integer", "description": "Número de trimestres (default 3)"},
                },
                "required": ["fondo_key", "año_fs", "mes_fs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_valor_libro_fs",
            "description": (
                "Extrae el valor cuota libro del EEFF PDF para la tabla 'EL FONDO' del Fact Sheet. "
                "Usa automáticamente la fecha contable correcta según el mes del FS. "
                "Retorna JSON listo para datos_json['info_fondo']. "
                "Para TRI retorna las 3 series (A, C, I)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {"type": "string", "description": "'PT', 'Apo' o 'TRI'"},
                    "año_fs":    {"type": "integer", "description": "Año del FS"},
                    "mes_fs":    {"type": "integer", "description": "Mes del FS: 1, 4, 7 ó 10"},
                },
                "required": ["fondo_key", "año_fs", "mes_fs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fecha_contable_fs",
            "description": (
                "Retorna la fecha de cierre contable para el mes del FS. "
                "FS enero→31-dic año anterior, abril→31-mar, julio→30-jun, octubre→30-sep. "
                "Usar para saber qué EEFF y balance corresponde leer para cada FS."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año":    {"type": "integer"},
                    "mes_fs": {"type": "integer", "description": "Mes del FS: 1, 4, 7 ó 10"},
                },
                "required": ["año", "mes_fs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_precios_bursatiles_fs",
            "description": (
                "Obtiene los últimos n meses de precios de cuota formateados para el Fact Sheet. "
                "Usa obtener_precio_cuota internamente y parsea el resultado. "
                "Retorna JSON listo para usar en datos_json['precios_bursatiles'] de actualizar_fs_pt o actualizar_fs_tri."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nemotecnico": {"type": "string", "description": "Ej: 'CFITRIPT-E', 'CFITOERI1A'"},
                    "año":         {"type": "integer"},
                    "mes":         {"type": "integer"},
                    "n":           {"type": "integer", "description": "Número de meses hacia atrás (default 3)"},
                },
                "required": ["nemotecnico", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_repartos_fs",
            "description": (
                "Lee los dividendos pagados en las últimas 12 meses desde la hoja Input del CDG. "
                "Retorna JSON lista de {fecha, concepto, monto_serie_unica} listo para "
                "datos_json['dividendos'] de actualizar_fs_pt. "
                "Usar CDG con fecha contable del FS (ej: FS Enero 2026 → CDG 2601)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del CDG en WORK_DIR, ej: '2601 Control De Gestión Renta Comercial vF.xlsx'"},
                    "fondo_key":      {"type": "string", "description": "'PT', 'Apoquindo' o 'TRI'"},
                    "año_fs":         {"type": "integer", "description": "Año del Fact Sheet"},
                    "mes_fs":         {"type": "integer", "description": "Mes del Fact Sheet (1, 4, 7 o 10)"},
                },
                "required": ["nombre_archivo", "fondo_key", "año_fs", "mes_fs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_fs_apoquindo",
            "description": (
                "Actualiza las tablas numéricas del Slide 1 del Fact Sheet Apoquindo: "
                "valor cuota libro, rentabilidad (solo libro, sin bursátil), otros indicadores, "
                "gastos, balance consolidado, endeudamiento, perfil de vencimiento. "
                "No tiene tabla de precios bursátiles ni de repartos. "
                "Requiere haber llamado preparar_fs('Apoquindo', año, mes) antes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año":        {"type": "integer"},
                    "mes":        {"type": "integer"},
                    "datos_json": {"type": "string", "description": "JSON con los datos a actualizar. Ver docstring de actualizar_fs_apoquindo para estructura completa."},
                },
                "required": ["año", "mes", "datos_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_fs_tri",
            "description": (
                "Actualiza las tablas numéricas del Slide 1 del Fact Sheet TRI (Rentas Inmobiliarias). "
                "Maneja 3 series (A, C, I) en rentabilidad, precios bursátiles, valor libro y repartos. "
                "Tablas: Tabla 15 (bursátil), Tabla 3 (libro), Tabla 11 (rentabilidad), "
                "Tabla 52 (repartos), Tabla 44 (otros indicadores), Tabla 5 (balance), "
                "Tabla 8 (gastos), Tabla 38 (endeudamiento), Tabla 2 (perfil vencimiento). "
                "Requiere haber llamado preparar_fs('TRI', año, mes) antes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "año":        {"type": "integer"},
                    "mes":        {"type": "integer"},
                    "datos_json": {"type": "string", "description": "JSON con los datos a actualizar. Ver docstring de actualizar_fs_tri para estructura completa."},
                },
                "required": ["año", "mes", "datos_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "guardar_fs",
            "description": "Guarda el Fact Sheet actualizado desde WORK_DIR a la carpeta Facts Sheet del fondo en SharePoint. Nombra el archivo como YYMM Fact Sheet - <fondo>.pptx.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {"type": "string", "description": "'PT', 'Apoquindo' o 'TRI'"},
                    "año":       {"type": "integer"},
                    "mes":       {"type": "integer"},
                },
                "required": ["fondo_key", "año", "mes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ordenar_archivos_raw",
            "description": (
                "Revisa la carpeta RAW de SharePoint y mueve cada archivo al lugar correcto según su nombre. "
                "Llamar cuando el usuario avise que subió archivos a la carpeta RAW. "
                "Retorna un resumen con los archivos movidos y los no reconocidos (que quedan en RAW para revisión manual)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mover_en_sharepoint",
            "description": (
                "Mueve un archivo o carpeta de una ubicación a otra dentro de SharePoint. "
                "Usar cuando el usuario pida reorganizar la estructura de carpetas. "
                "origen y destino son rutas relativas a SHAREPOINT_DIR (ej: 'Fondos/Rentas Apoquindo/EEFF'). "
                "Si el origen es carpeta, mueve todo su contenido recursivamente. "
                "Después de reorganizar, llamar a reemplazar_en_tool para actualizar las rutas en el código "
                "y a actualizar_indice_sharepoint para refrescar el wiki."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origen":  {"type": "string", "description": "Ruta relativa a SHAREPOINT_DIR del archivo o carpeta a mover"},
                    "destino": {"type": "string", "description": "Ruta relativa a SHAREPOINT_DIR del directorio destino"},
                },
                "required": ["origen", "destino"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crear_carpeta_sharepoint",
            "description": "Crea una carpeta en SharePoint. ruta es relativa a SHAREPOINT_DIR.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "Ruta relativa a SHAREPOINT_DIR (ej: 'Fondos/NuevaCarpeta')"},
                },
                "required": ["ruta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eliminar_carpeta_sharepoint",
            "description": "Elimina una carpeta VACÍA en SharePoint. Falla si tiene archivos — mueve el contenido primero.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "Ruta relativa a SHAREPOINT_DIR de la carpeta vacía a eliminar"},
                },
                "required": ["ruta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reemplazar_en_tool",
            "description": (
                "Busca y reemplaza texto en un archivo de código del agente (tools/*.py o cualquier .py del proyecto). "
                "Usar para actualizar rutas de SharePoint en el código después de reorganizar carpetas. "
                "Ejemplo: reemplazar una ruta SharePoint antigua por la ruta canonica en noi_tools.py."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del archivo (ej: 'noi_tools.py') o ruta relativa al proyecto"},
                    "texto_viejo":    {"type": "string", "description": "Cadena exacta a buscar (sensible a mayúsculas)"},
                    "texto_nuevo":    {"type": "string", "description": "Cadena de reemplazo"},
                },
                "required": ["nombre_archivo", "texto_viejo", "texto_nuevo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reemplazar_en_wiki",
            "description": (
                "Busca y reemplaza texto en un archivo del wiki del agente (wiki/**/*.md). "
                "Usar para actualizar rutas o descripciones en el wiki después de reorganizar SharePoint."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_archivo": {"type": "string", "description": "Nombre del archivo .md (ej: 'index.md') o ruta relativa al directorio wiki/"},
                    "texto_viejo":    {"type": "string", "description": "Cadena exacta a buscar"},
                    "texto_nuevo":    {"type": "string", "description": "Cadena de reemplazo"},
                },
                "required": ["nombre_archivo", "texto_viejo", "texto_nuevo"],
            },
        },
    },
    # Real Estate Finance Indicators (skill: real-estate-finance-expert)
    {
        "type": "function",
        "function": {
            "name": "calcular_indicador",
            "description": (
                "Calcula un indicador financiero derivado a partir de agente_toesca.db. "
                "Invoca la skill real-estate-finance-expert. Usa cache si ya fue computado; persiste si compensa. "
                "KPIs OPERATIVOS: "
                "'rent_anualizada' (CAGR), 'rent_u12m', "
                "'dividend_yield', 'dividend_yield_contable', 'dividend_yield_capital', 'dividend_yield_con_amort', "
                "'cap_rate_real', 'cap_rate_implicito', 'tasa_arriendo_uf_m2', "
                "'tir_bursatil_ytd' (XIRR bursátil YTD, T0=31-dic año anterior), "
                "'tir_contable_ytd' (XIRR contable YTD), "
                "'tir_bursatil_u12m' (XIRR bursátil U12M), "
                "'tir_contable_u12m' (XIRR contable U12M), "
                "'tir_bursatil_desde_inicio' (XIRR bursátil desde primer aporte, método por cuota: aportes/disminuciones de raw_ar_event + dividendos de raw_dividendo). "
                "Para TIR de todas las series de un fondo usar calcular_tir_fondo. "
                "PENDIENTE: 'tir_contable_desde_inicio' (metodología por definir)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kpi": {
                        "type": "string",
                        "description": (
                            "KPI a calcular. Operativos: rent_anualizada, rent_u12m, dividend_yield, "
                            "dividend_yield_contable, dividend_yield_capital, dividend_yield_con_amort, "
                            "cap_rate_real, cap_rate_implicito, tasa_arriendo_uf_m2, "
                            "tir_bursatil_ytd, tir_contable_ytd, tir_bursatil_u12m, tir_contable_u12m."
                        )
                    },
                    "entidad_tipo": {
                        "type": "string",
                        "description": "Tipo de entidad ('serie', 'activo', 'fondo', etc)"
                    },
                    "entidad_key": {
                        "type": "string",
                        "description": "Identificador único (ej: 'CFITOERI1A' para TRI Serie A, 'Parque Titanium' para PT)"
                    },
                    "periodo": {
                        "type": "string",
                        "description": "Período en formato YYYY-MM (ej: '2026-03', '2026-04')"
                    },
                    "force_recompute": {
                        "type": "boolean",
                        "description": "Si true, recalcula aunque esté en cache (default: false)"
                    },
                },
                "required": ["kpi", "entidad_tipo", "entidad_key", "periodo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_indicadores",
            "description": (
                "Lista todos los indicadores financieros disponibles en la skill real-estate-finance-expert. "
                "Muestra cuáles están operativos y cuáles tienen dependencias pendientes (placeholders)."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "invalidar_cache_indicador",
            "description": (
                "Invalida el cache de un indicador específico. "
                "La próxima consulta recalculará desde datos crudos. "
                "Útil después de actualizar la DB o cambiar fórmulas en config/formulas.yaml."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kpi": {
                        "type": "string",
                        "description": "Nombre del indicador a invalidar (ej: 'rent_anualizada')"
                    },
                },
                "required": ["kpi"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verificar_skill_finanzas",
            "description": (
                "Verifica que la skill real-estate-finance-expert esté instalada y accesible. "
                "Útil para diagnosticar si hay problemas de importación."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_dy_fondo",
            "description": (
                "Calcula DY bursátil, DY contable y DY+Amortización para TODAS las series de un fondo en una sola llamada. "
                "Usar en lugar de múltiples llamadas a calcular_indicador cuando se necesita la tabla completa de dividend yield. "
                "Devuelve una fila por serie con: dy_bursatil, dy_contable, dy_amort_bursatil, amort_uf_cuota, dividendos_uf_cuota."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {
                        "type": "string",
                        "description": "Clave del fondo: 'TRI', 'PT', 'APO'"
                    },
                    "periodo": {
                        "type": "string",
                        "description": "Período YYYY-MM (ej: '2026-02'). Calcula U12M hasta el último día de ese mes."
                    },
                    "force_recompute": {
                        "type": "boolean",
                        "description": "Si true, ignora cache y recalcula. Default false."
                    },
                },
                "required": ["fondo_key", "periodo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_tir_fondo",
            "description": (
                "Calcula TIR (XIRR) YTD y U12M para TODAS las series de un fondo en una sola llamada. "
                "Devuelve una fila por serie con: tir_bursatil_desde_inicio, tir_contable_desde_inicio, "
                "tir_bursatil_ytd, tir_contable_ytd, tir_bursatil_u12m, tir_contable_u12m. "
                "T0 para YTD = 31-dic año anterior; T0 para U12M = mismo mes año anterior. "
                "tir_*_desde_inicio: XIRR por cuota desde primer aporte. Aportes/disminuciones desde raw_ar_event, "
                "dividendos desde raw_dividendo (canónica). Terminal = VR Bursátil o VR Contable en FECHA_CORTE."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fondo_key": {
                        "type": "string",
                        "description": "Clave del fondo: 'TRI', 'PT', 'APO'"
                    },
                    "periodo": {
                        "type": "string",
                        "description": "Período YYYY-MM (ej: '2025-12'). Calcula hasta el último día de ese mes."
                    },
                    "force_recompute": {
                        "type": "boolean",
                        "description": "Si true, ignora cache y recalcula. Default false."
                    },
                },
                "required": ["fondo_key", "periodo"],
            },
        },
    },
]

_WRITE_TOOL_FILE_ARGS = {
    "actualizar_celda": ("nombre_archivo",),
    "guardar_en_sharepoint": ("nombre_archivo",),
    "guardar_cdg": ("nombre_archivo",),
    "actualizar_fecha_pendientes": ("nombre_archivo",),
    "agregar_vr_bursatil_pt": ("nombre_archivo",),
    "agregar_vr_bursatil_rentas": ("nombre_archivo",),
    "agregar_vr_contable_pt": ("nombre_archivo",),
    "agregar_vr_contable_rentas": ("nombre_archivo",),
    "agregar_vr_contable_apoquindo": ("nombre_archivo",),
    "agregar_dividendo_pt": ("nombre_archivo",),
    "agregar_dividendo_rentas": ("nombre_archivo",),
    "agregar_dividendo_apoquindo": ("nombre_archivo",),
    "agregar_aporte_pt": ("nombre_archivo",),
    "agregar_aporte_rentas": ("nombre_archivo",),
    "agregar_aporte_apoquindo": ("nombre_archivo",),
    "consolidar_rent_rolls": ("nombre_cdg",),
    "consolidar_absorcion": ("nombre_cdg",),
}


def _enforce_vagente_write_permission(name: str, args: dict) -> str | None:
    """Reject writes to operational Excel files unless they are agent-created vAgente files."""
    for key in _WRITE_TOOL_FILE_ARGS.get(name, ()):
        value = args.get(key)
        if not value:
            continue
        filename = os.path.basename(str(value))
        if filename.lower().endswith((".xlsx", ".xlsm", ".xls")) and "vagente" not in filename.casefold():
            return (
                f"Error: sin permiso para modificar '{filename}'. "
                "El agente solo puede editar archivos creados por el con sufijo vAgente. "
                "Primero crea o usa una copia vAgente."
            )
    return None


_DISABLED_MODEL_TOOLS = {"reemplazar_en_tool", "reemplazar_en_wiki"}


def _dispatch(name: str, args: dict, allowed_tool_names: set[str] | None = None) -> str:
    if name in _DISABLED_MODEL_TOOLS:
        return f"Error: herramienta '{name}' deshabilitada por seguridad."
    if allowed_tool_names is not None and name not in allowed_tool_names:
        return f"Error: herramienta '{name}' no autorizada para esta instrucción."

    permission_error = _enforce_vagente_write_permission(name, args)
    if permission_error:
        return permission_error

    dispatch = {
        "preguntar_usuario":            lambda a: preguntar_usuario(a["pregunta"]),
        "buscar_correos_con_planillas": lambda a: list_emails_with_attachments(a.get("limite", 20)),
        "buscar_correos_por_asunto":    lambda a: search_emails_by_subject(a["palabra_clave"], a.get("limite", 10)),
        "revisar_respuestas_contacto":  lambda a: check_replies_from_contact(
            a["contacto"], a.get("email"), a.get("limite", 5), a.get("scan_limit", 500),
        ),
        "descargar_adjunto_correo":     lambda a: download_email_attachment(a["entry_id"], a["attachment_index"], a["nombre_archivo"]),
        "enviar_correo":                lambda a: send_email(a["destinatario"], a["asunto"], a["cuerpo"], a.get("archivo_adjunto")),
        "listar_sharepoint":            lambda a: list_sharepoint_files(a.get("subcarpeta", "")),
        "buscar_en_sharepoint":         lambda a: search_sharepoint_files(a["keyword"], a.get("subcarpeta", "")),
        "copiar_de_sharepoint":         lambda a: copy_from_sharepoint(a["nombre_archivo"], a.get("subcarpeta", "")),
        "guardar_en_sharepoint":        lambda a: save_to_sharepoint(a["nombre_archivo"], a.get("subcarpeta_destino", "")),
        "actualizar_indice_sharepoint": lambda a: refresh_sharepoint_index(),
        "listar_servidor_local":        lambda a: list_local_excel_files(a.get("subcarpeta", "")),
        "copiar_del_servidor":          lambda a: copy_from_local(a["nombre_archivo"], a.get("subcarpeta", "")),
        "guardar_en_servidor":          lambda a: save_to_local(a["nombre_archivo"], a.get("subcarpeta_destino", "")),
        "leer_planilla":                lambda a: read_excel_file(a["nombre_archivo"], a.get("hoja")),
        "validar_planilla":             lambda a: validate_excel_file(a["nombre_archivo"], a.get("columnas_requeridas")),
        "actualizar_celda":             lambda a: update_excel_cell(a["nombre_archivo"], a["hoja"], a["celda"], a["valor"]),
        "listar_planillas_en_trabajo":  lambda a: list_work_files(),
        # Gestión Renta Comercial
        "crear_planilla_mes":           lambda a: crear_planilla_mes(a["mes_code_nuevo"]),
        "guardar_cdg":                  lambda a: guardar_cdg(a["nombre_archivo"]),
        "buscar_tir":                   lambda a: buscar_tir(),
        "verificar_archivos_cdg":       lambda a: verificar_archivos_cdg(a["año"], a["mes"]),
        "previsualizar_correos_solicitud_cdg": lambda a: previsualizar_correos_solicitud_cdg(
            a["año"], a["mes"], a.get("seguimiento"), a.get("excluir"), a.get("solo"),
        ),
        "enviar_correos_solicitud_cdg": lambda a: enviar_correos_solicitud_cdg(
            a["año"], a["mes"], a.get("seguimiento"), a.get("excluir"), a.get("solo"),
        ),
        "actualizar_fecha_pendientes":  lambda a: actualizar_fecha_pendientes(a["nombre_archivo"], a["año"], a["mes"]),
        "info_siguiente_accion":        lambda a: info_siguiente_accion(a["nombre_archivo"]),
        "obtener_precio_cuota":         lambda a: obtener_precio_cuota(a["nemotecnico"], a["año"], a["mes"]),
        "obtener_precios_mes":          lambda a: obtener_precios_mes(a["año"], a["mes"]),
        "actualizar_uf_desde_web":      lambda _: str(actualizar_uf_desde_web()),
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
        # Rent Roll
        "revisar_rent_rolls":            lambda a: revisar_rent_rolls(a["año"], a["mes"]),
        "revisar_rent_roll_jll":         lambda a: revisar_rent_roll_jll(a["año"], a["mes"]),
        "enviar_emails_rent_roll":       lambda a: enviar_emails_rent_roll(),
        "consolidar_rent_rolls":         lambda a: consolidar_rent_rolls(a["año"], a["mes"], a["nombre_cdg"]),
        "consolidar_absorcion":          lambda a: consolidar_absorcion(a["año"], a["mes"], a["nombre_cdg"]),
        # Memoria
        "leer_contexto":                 lambda a: leer_contexto(),
        "actualizar_contexto":           lambda a: actualizar_contexto(a["contenido"]),
        "leer_historial":                lambda a: leer_historial(a.get("n", 20)),
        # KPIs
        "registrar_kpi":                 lambda a: registrar_kpi(a["fondo"], a["periodo"], a["kpi"], a["valor"], a.get("unidad", ""), a.get("fuente", "")),
        "consultar_kpi":                 lambda a: consultar_kpi(a["fondo"], a["kpi"], a.get("n_periodos", 12)),
        "resumen_kpis":                  lambda a: resumen_kpis(a["fondo"], a["periodo"]),
        "comparar_periodos":             lambda a: comparar_periodos(a["fondo"], a["periodo_base"], a["periodo_actual"]),
        "buscar_ubicacion":              lambda a: buscar_ubicacion(a["concepto"]),
        "guardar_ubicacion":             lambda a: guardar_ubicacion(a["concepto"], a["ruta"], a.get("notas", "")),
        "leer_wiki":                     lambda a: leer_wiki(a["pagina"]),
        # Consultas a la DB (Fase 1/4) — lectura, no abren Excel
        "consultar_db_cobertura":        lambda a: consultar_db_cobertura(),
        "consultar_db_kpi":              lambda a: consultar_db_kpi(a["entidad_tipo"], a["entidad_key"], a["kpi"], a.get("desde"), a.get("hasta")),
        "consultar_db_precio":           lambda a: consultar_db_precio(a["nemotecnico"], a.get("fecha")),
        "consultar_db_rent_roll":        lambda a: consultar_db_rent_roll(a["activo_key"], a["periodo"]),
        "consultar_db_er":               lambda a: consultar_db_er(a["activo_key"], a["periodo"]),
        "consultar_db_flujo":            lambda a: consultar_db_flujo(a["activo_key"], a["periodo"]),
        "consultar_db_valor_bursatil":        lambda a: consultar_db_valor_bursatil(a.get("nemotecnico"), a.get("fecha")),
        "consultar_db_valor_libro":          lambda a: consultar_db_valor_libro(a.get("nemotecnico"), a.get("fecha")),
        "consultar_db_patrimonio_bursatil": lambda a: consultar_db_patrimonio_bursatil(a.get("nemotecnico"), a.get("fecha")),
        "consultar_db_capital_suscrito":  lambda a: consultar_db_capital_suscrito(a.get("nemotecnico"), a.get("fecha_corte")),
        "consultar_financiamiento":      lambda a: consultar_financiamiento(
            a["tipo"], a.get("fondo"), a.get("desde"), a.get("hasta"), a.get("credito_key"),
            a.get("fecha_corte"), a.get("tipo_valor", "bursatil")
        ),
        "consultar_db_dividendos":       lambda a: consultar_db_dividendos(a["nemotecnico"]),
        "consultar_dividend_yield":      lambda a: consultar_dividend_yield(a["nemotecnico"], a.get("periodo"), a.get("anio"), a.get("tipo", "contable")),
        "consultar_db_tasaciones":       lambda a: consultar_db_tasaciones(a.get("activo_key"), a.get("periodo")),
        "consultar_db_adquisiciones":    lambda a: consultar_db_adquisiciones(a.get("activo_key")),
        "consultar_ltv":                 lambda a: consultar_ltv(a.get("activo_key"), a.get("periodo"), a.get("fondo_key")),
        "consultar_noi":                 lambda a: consultar_noi(a["nivel"], a.get("clave"), a.get("año"), a.get("ponderado", False)),
        "generar_dashboard":             lambda a: f"Dashboard generado: {generar_dashboard()}",
        "ingestar_archivo":              lambda a: ingestar_archivo(a["path"], a.get("periodo")),
        # Consultas históricas
        "leer_cdg_historico":            lambda a: leer_cdg_historico(a["mes"], a["año"], a["hoja"], a.get("filtro")),
        "buscar_en_rent_roll":           lambda a: buscar_en_rent_roll(a["mes"], a["año"], a.get("activo"), a.get("local")),
        # Fact Sheets
        "listar_shapes_fs":              lambda a: listar_shapes_fs(a["fondo_key"], a["año"], a["mes"]),
        "leer_tabla_fs":                 lambda a: leer_tabla_fs(a["fondo_key"], a["año"], a["mes"], a["shape_name"]),
        "preparar_fs":                   lambda a: preparar_fs(a["fondo_key"], a["año"], a["mes"]),
        "actualizar_fs_pt":              lambda a: actualizar_fs_pt(a["año"], a["mes"], a["datos_json"]),
        "obtener_historico_valor_libro_fs": lambda a: obtener_historico_valor_libro_fs(a["fondo_key"], a["año_fs"], a["mes_fs"], a.get("n", 3)),
        "obtener_valor_libro_fs":          lambda a: obtener_valor_libro_fs(a["fondo_key"], a["año_fs"], a["mes_fs"]),
        "fecha_contable_fs":              lambda a: str(fecha_contable_fs(a["año"], a["mes_fs"])),
        "obtener_precios_bursatiles_fs":  lambda a: obtener_precios_bursatiles_fs(a["nemotecnico"], a["año"], a["mes"], a.get("n", 3)),
        "leer_repartos_fs":               lambda a: leer_repartos_fs(a["nombre_archivo"], a["fondo_key"], a["año_fs"], a["mes_fs"]),
        "actualizar_fs_apoquindo":       lambda a: actualizar_fs_apoquindo(a["año"], a["mes"], a["datos_json"]),
        "actualizar_fs_tri":             lambda a: actualizar_fs_tri(a["año"], a["mes"], a["datos_json"]),
        "guardar_fs":                    lambda a: guardar_fs(a["fondo_key"], a["año"], a["mes"]),
        "ordenar_archivos_raw":        lambda _: ordenar_archivos_raw(),
        "mover_en_sharepoint":         lambda a: mover_en_sharepoint(a["origen"], a["destino"]),
        "crear_carpeta_sharepoint":    lambda a: crear_carpeta_sharepoint(a["ruta"]),
        "eliminar_carpeta_sharepoint": lambda a: eliminar_carpeta_sharepoint(a["ruta"]),
        "reemplazar_en_tool":          lambda a: reemplazar_en_tool(a["nombre_archivo"], a["texto_viejo"], a["texto_nuevo"]),
        "reemplazar_en_wiki":          lambda a: reemplazar_en_wiki(a["nombre_archivo"], a["texto_viejo"], a["texto_nuevo"]),
        # Real Estate Finance Indicators (skill: real-estate-finance-expert)
        "calcular_indicador":          lambda a: calcular_indicador_financiero(
            a["kpi"], a["entidad_tipo"], a["entidad_key"], a["periodo"], a.get("force_recompute", False)
        ),
        "calcular_dy_fondo":           lambda a: calcular_dy_fondo(
            a["fondo_key"], a["periodo"], a.get("force_recompute", False)
        ),
        "calcular_tir_fondo":          lambda a: calcular_tir_fondo(
            a["fondo_key"], a["periodo"], a.get("force_recompute", False)
        ),
        "listar_indicadores":          lambda a: listar_indicadores_disponibles(),
        "invalidar_cache_indicador":   lambda a: invalidar_cache_indicador(a["kpi"]),
        "verificar_skill_finanzas":    lambda a: verificar_skill(),
    }
    fn = dispatch.get(name)
    if fn is None:
        return f"Error: herramienta '{name}' no reconocida."
    result = fn(args)
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False, default=str)
    if len(result) > _MAX_TOOL_RESULT:
        result = result[:_MAX_TOOL_RESULT] + f"\n\n[...resultado truncado — {len(result):,} chars totales. Llama con parámetros más específicos para obtener datos concretos.]"
    return result


# ─── Selección dinámica de herramientas ───────────────────────────────────────
_TOOLS_GENERAL = {
    "preguntar_usuario",
    "buscar_correos_con_planillas", "buscar_correos_por_asunto",
    "revisar_respuestas_contacto",
    "descargar_adjunto_correo", "enviar_correo",
    "listar_sharepoint", "buscar_en_sharepoint", "copiar_de_sharepoint", "guardar_en_sharepoint", "actualizar_indice_sharepoint",
    "listar_servidor_local", "copiar_del_servidor", "guardar_en_servidor",
    "leer_planilla", "validar_planilla", "actualizar_celda",
    "listar_planillas_en_trabajo",
    "leer_contexto", "actualizar_contexto", "leer_historial",
    "registrar_kpi", "consultar_kpi", "resumen_kpis", "comparar_periodos",
    "consultar_db_cobertura", "consultar_db_kpi", "consultar_db_precio",
    "consultar_db_rent_roll", "consultar_db_er", "consultar_db_flujo",
    "consultar_db_valor_bursatil", "consultar_db_valor_libro", "consultar_db_patrimonio_bursatil", "consultar_db_capital_suscrito", "consultar_db_dividendos", "consultar_dividend_yield", "consultar_noi", "consultar_financiamiento", "generar_dashboard",
    "consultar_db_tasaciones", "consultar_db_adquisiciones", "consultar_ltv",
    "calcular_indicador", "calcular_dy_fondo", "calcular_tir_fondo",
    "listar_indicadores", "invalidar_cache_indicador", "verificar_skill_finanzas",
    "buscar_ubicacion", "guardar_ubicacion", "leer_wiki",
    "ordenar_archivos_raw",
    "leer_cdg_historico", "buscar_en_rent_roll",
    "enviar_emails_rent_roll",  # siempre disponible para confirmaciones de seguimiento
    "previsualizar_correos_solicitud_cdg", "enviar_correos_solicitud_cdg",
}

_TOOLS_CDG = {
    "crear_planilla_mes", "guardar_cdg", "verificar_archivos_cdg", "buscar_tir",
    "previsualizar_correos_solicitud_cdg", "enviar_correos_solicitud_cdg",
    "actualizar_fecha_pendientes", "info_siguiente_accion",
    "agregar_vr_bursatil_pt", "agregar_vr_bursatil_rentas",
    "agregar_vr_contable_pt", "agregar_vr_contable_rentas", "agregar_vr_contable_apoquindo",
    "agregar_dividendo_pt", "agregar_dividendo_rentas", "agregar_dividendo_apoquindo",
    "agregar_aporte_pt", "agregar_aporte_rentas", "agregar_aporte_apoquindo",
    "obtener_precio_cuota", "obtener_precios_mes",
    "listar_eeff_disponibles", "leer_eeff",
}

_TOOLS_RENTROLL = {
    "revisar_rent_rolls", "revisar_rent_roll_jll", "consolidar_absorcion", "consolidar_rent_rolls",
    "enviar_emails_rent_roll",
}

_TOOLS_FACTSHEET = {
    "listar_shapes_fs", "leer_tabla_fs", "preparar_fs",
    "fecha_contable_fs", "obtener_valor_libro_fs", "obtener_historico_valor_libro_fs", "obtener_precios_bursatiles_fs",
    "leer_repartos_fs",
    "actualizar_fs_pt", "actualizar_fs_apoquindo", "actualizar_fs_tri", "guardar_fs",
    # Herramientas de datos que el agente necesita para alimentar el FS
    "obtener_precio_cuota", "leer_eeff",
}

_TOOL_INDEX = {t["function"]["name"]: t for t in TOOL_DEFINITIONS}


_MUTATING_TOOL_PREFIXES = (
    "actualizar_", "agregar_", "consolidar_", "crear_", "descargar_",
    "eliminar_", "enviar_", "guardar_", "ingestar_", "invalidar_",
    "mover_", "ordenar_", "preparar_", "registrar_", "reemplazar_",
)
_SEND_TOOLS = {"enviar_correo", "enviar_correos_solicitud_cdg", "enviar_emails_rent_roll"}
_MUTATION_INTENT_RE = re.compile(
    r"\b(actualiz\w*|agreg\w*|cambi\w*|consolid\w*|copi\w*|cre\w*|"
    r"descarg\w*|elimin\w*|envi\w*|guard\w*|ingest\w*|invalid\w*|"
    r"mand\w*|modific\w*|mov\w*|orden\w*|prepar\w*|registr\w*|"
    r"reemplaz\w*|respond\w*)\b",
    re.IGNORECASE,
)
_SEND_INTENT_RE = re.compile(
    r"\b(avis\w*|envi\w*|mand\w*|respond\w*)\b.*\b(correo\w*|email\w*|mail\w*)\b|"
    r"\b(correo\w*|email\w*|mail\w*)\b.*\b(avis\w*|envi\w*|mand\w*|respond\w*)\b",
    re.IGNORECASE,
)


def _is_mutating_tool(name: str) -> bool:
    return name.startswith(_MUTATING_TOOL_PREFIXES)


def _normalized_intent(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", str(text or ""))
        if not unicodedata.combining(char)
    )


def _select_tools(grupos: set, user_input: str = "") -> list:
    if not grupos:
        nombres = set(_TOOLS_GENERAL)
    else:
        nombres = set(_TOOLS_GENERAL)
        if "cdg"        in grupos: nombres |= _TOOLS_CDG
        if "rentroll"   in grupos: nombres |= _TOOLS_RENTROLL
        if "factsheet"  in grupos: nombres |= _TOOLS_FACTSHEET

    nombres -= _DISABLED_MODEL_TOOLS
    normalized_input = _normalized_intent(user_input)
    if not _MUTATION_INTENT_RE.search(normalized_input):
        nombres = {name for name in nombres if not _is_mutating_tool(name)}
    if not _SEND_INTENT_RE.search(normalized_input):
        nombres -= _SEND_TOOLS

    return [_TOOL_INDEX[n] for n in nombres if n in _TOOL_INDEX]


# ─── Runner principal ─────────────────────────────────────────────────────────
