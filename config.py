import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY", "")
SHAREPOINT_DIR        = os.getenv("SHAREPOINT_DIR", "")
LOCAL_FILES_DIR       = os.getenv("LOCAL_FILES_DIR", "")
RENTA_COMERCIAL_DIR   = os.getenv("RENTA_COMERCIAL_DIR", "")  # Ruta directa a carpeta Comercial
FONDOS_DIR            = os.getenv("FONDOS_DIR", "")           # Legacy; rutas canonicas en tools/sharepoint_paths.py
SALDO_CAJA_DIR        = os.getenv("SALDO_CAJA_DIR", "")      # Carpeta archivo histórico Saldo Caja
WORK_DIR              = os.getenv("WORK_DIR", os.path.join(os.path.dirname(__file__), "work"))
