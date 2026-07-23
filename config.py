import os
from dotenv import load_dotenv

load_dotenv(override=True)  # el reloader de Flask hereda os.environ del padre;
                            # sin override, un valor viejo de .env queda "pegado"

GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY", "")
DEEPSEEK_API_KEY      = os.getenv("DEEPSEEK_API_KEY", "")
GROQ_API_KEY          = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEY_2        = os.getenv("GROQ_API_KEY_2", "")  # cuenta Groq extra para duplicar cupo diario gratis
DB_CHAT_PROVIDER      = os.getenv("DB_CHAT_PROVIDER", "groq")  # deepseek | groq | gemini
SHAREPOINT_DIR        = os.getenv("SHAREPOINT_DIR", "")
LOCAL_FILES_DIR       = os.getenv("LOCAL_FILES_DIR", "")
RENTA_COMERCIAL_DIR   = os.getenv("RENTA_COMERCIAL_DIR", "")  # Ruta directa a carpeta Comercial
FONDOS_DIR            = os.getenv("FONDOS_DIR", "")           # Legacy; rutas canonicas en tools/sharepoint_paths.py
SALDO_CAJA_DIR        = os.getenv("SALDO_CAJA_DIR", "")      # Carpeta archivo histórico Saldo Caja
WORK_DIR              = os.getenv("WORK_DIR", os.path.join(os.path.dirname(__file__), "work"))
