import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY", "")
SHAREPOINT_DIR        = os.getenv("SHAREPOINT_DIR", "")
LOCAL_FILES_DIR       = os.getenv("LOCAL_FILES_DIR", "")
RENTA_COMERCIAL_DIR   = os.getenv("RENTA_COMERCIAL_DIR", "")  # Ruta directa a carpeta Comercial
FONDOS_DIR            = os.getenv("FONDOS_DIR", "")           # Ruta a R:\Rentas\Fondos (o equiv.)
WORK_DIR              = os.getenv("WORK_DIR", os.path.join(os.path.dirname(__file__), "work"))
