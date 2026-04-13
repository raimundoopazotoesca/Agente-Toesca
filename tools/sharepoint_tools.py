"""
Herramientas para archivos de SharePoint.
Accede a la carpeta de SharePoint sincronizada en tu PC vía OneDrive.
No requiere ninguna configuración de Azure — solo tener la carpeta sincronizada.
"""
import os
import shutil
from datetime import datetime
from config import SHAREPOINT_DIR, WORK_DIR


def _check_dir() -> str | None:
    """Devuelve None si el directorio está disponible, o un mensaje de error."""
    if not SHAREPOINT_DIR:
        return (
            "SHAREPOINT_DIR no está configurado en el .env.\n"
            "Configura la ruta a tu carpeta de SharePoint sincronizada.\n"
            "Ejemplo: C:\\Users\\raimundo.opazo\\OneDrive - Empresa\\Documentos"
        )
    if not os.path.exists(SHAREPOINT_DIR):
        return (
            f"La carpeta '{SHAREPOINT_DIR}' no existe o no está sincronizada.\n"
            "Verifica que OneDrive haya sincronizado los archivos de SharePoint."
        )
    return None


def list_sharepoint_files(subfolder: str = "") -> str:
    """Lista archivos Excel en la carpeta de SharePoint sincronizada."""
    err = _check_dir()
    if err:
        return err

    try:
        base = os.path.join(SHAREPOINT_DIR, subfolder) if subfolder else SHAREPOINT_DIR

        if not os.path.exists(base):
            return f"La subcarpeta '{subfolder}' no existe en SharePoint."

        entries = []
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if os.path.isdir(path):
                entries.append(("dir", name, 0, ""))
            elif name.lower().endswith((".xlsx", ".xls")):
                size = os.path.getsize(path)
                mod = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
                entries.append(("file", name, size, mod))

        if not entries:
            return f"No hay archivos Excel en SharePoint / {subfolder or 'raíz'}."

        result = f"SharePoint — {subfolder or 'raíz'} (sincronizado en: {base}):\n\n"
        for kind, name, size, mod in entries:
            if kind == "dir":
                result += f"  📁 {name}/\n"
            else:
                result += f"  📊 {name}  ({size:,} bytes  |  {mod})\n"

        n_files = sum(1 for k, *_ in entries if k == "file")
        result += f"\nTotal planillas: {n_files}"
        return result

    except Exception as e:
        return f"Error al listar SharePoint: {e}"


def copy_from_sharepoint(filename: str, subfolder: str = "") -> str:
    """Copia un archivo de SharePoint al directorio de trabajo para procesarlo."""
    err = _check_dir()
    if err:
        return err

    try:
        os.makedirs(WORK_DIR, exist_ok=True)
        base = os.path.join(SHAREPOINT_DIR, subfolder) if subfolder else SHAREPOINT_DIR
        source = os.path.join(base, filename)

        if not os.path.exists(source):
            return f"Archivo '{filename}' no encontrado en SharePoint ({base})."

        dest = os.path.join(WORK_DIR, filename)
        shutil.copy2(source, dest)
        return f"'{filename}' copiado de SharePoint al directorio de trabajo: {dest}"

    except Exception as e:
        return f"Error al copiar de SharePoint: {e}"


def save_to_sharepoint(filename: str, dest_subfolder: str = "") -> str:
    """Guarda un archivo del directorio de trabajo de vuelta en SharePoint."""
    err = _check_dir()
    if err:
        return err

    try:
        source = os.path.join(WORK_DIR, filename)
        if not os.path.exists(source):
            return f"'{filename}' no encontrado en el directorio de trabajo."

        dest_dir = os.path.join(SHAREPOINT_DIR, dest_subfolder) if dest_subfolder else SHAREPOINT_DIR
        os.makedirs(dest_dir, exist_ok=True)

        dest = os.path.join(dest_dir, filename)
        shutil.copy2(source, dest)
        return f"'{filename}' guardado en SharePoint: {dest}"

    except Exception as e:
        return f"Error al guardar en SharePoint: {e}"
