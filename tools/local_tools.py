"""
Herramientas para archivos en servidor local o unidad de red.
Accede directamente a rutas locales o de red (\\servidor\carpeta o Z:\carpeta).
"""
import os
import shutil
from datetime import datetime
from config import LOCAL_FILES_DIR, WORK_DIR


def _check_dir() -> str | None:
    if not LOCAL_FILES_DIR:
        return (
            "LOCAL_FILES_DIR no está configurado en el .env.\n"
            "Configura la ruta al servidor local.\n"
            "Ejemplo: \\\\servidor\\archivos  o  Z:\\Planillas"
        )
    if not os.path.exists(LOCAL_FILES_DIR):
        return (
            f"La ruta '{LOCAL_FILES_DIR}' no está accesible.\n"
            "Verifica que estés conectado a la red o que la unidad esté mapeada."
        )
    return None


def list_local_excel_files(subfolder: str = "") -> str:
    """Lista archivos Excel en el servidor local o unidad de red."""
    err = _check_dir()
    if err:
        return err

    try:
        base = os.path.join(LOCAL_FILES_DIR, subfolder) if subfolder else LOCAL_FILES_DIR

        if not os.path.exists(base):
            return f"La subcarpeta '{subfolder}' no existe en el servidor."

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
            return f"No hay archivos Excel en el servidor ({subfolder or 'raíz'})."

        result = f"Servidor local — {subfolder or 'raíz'} ({base}):\n\n"
        for kind, name, size, mod in entries:
            if kind == "dir":
                result += f"  📁 {name}/\n"
            else:
                result += f"  📊 {name}  ({size:,} bytes  |  {mod})\n"

        n_files = sum(1 for k, *_ in entries if k == "file")
        result += f"\nTotal planillas: {n_files}"
        return result

    except PermissionError:
        return f"Sin permisos para acceder a '{LOCAL_FILES_DIR}'."
    except Exception as e:
        return f"Error al listar archivos del servidor: {e}"


def copy_from_local(filename: str, subfolder: str = "") -> str:
    """Copia un archivo del servidor local al directorio de trabajo."""
    err = _check_dir()
    if err:
        return err

    try:
        os.makedirs(WORK_DIR, exist_ok=True)
        base = os.path.join(LOCAL_FILES_DIR, subfolder) if subfolder else LOCAL_FILES_DIR
        source = os.path.join(base, filename)

        if not os.path.exists(source):
            return f"Archivo '{filename}' no encontrado en el servidor ({base})."

        dest = os.path.join(WORK_DIR, filename)
        shutil.copy2(source, dest)
        return f"'{filename}' copiado del servidor al directorio de trabajo: {dest}"

    except Exception as e:
        return f"Error al copiar del servidor: {e}"


def save_to_local(filename: str, dest_subfolder: str = "") -> str:
    """Guarda un archivo del directorio de trabajo en el servidor local."""
    err = _check_dir()
    if err:
        return err

    try:
        source = os.path.join(WORK_DIR, filename)
        if not os.path.exists(source):
            return f"'{filename}' no encontrado en el directorio de trabajo."

        dest_dir = os.path.join(LOCAL_FILES_DIR, dest_subfolder) if dest_subfolder else LOCAL_FILES_DIR
        os.makedirs(dest_dir, exist_ok=True)

        dest = os.path.join(dest_dir, filename)
        shutil.copy2(source, dest)
        return f"'{filename}' guardado en el servidor: {dest}"

    except Exception as e:
        return f"Error al guardar en servidor: {e}"
