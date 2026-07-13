"""
Herramientas para archivos de SharePoint.
Accede a la carpeta de SharePoint sincronizada en tu PC vía OneDrive.
No requiere ninguna configuración de Azure — solo tener la carpeta sincronizada.
"""
import os
import shutil
from datetime import datetime
from config import SHAREPOINT_DIR, WORK_DIR
from tools.path_security import UnsafePathError, resolve_within

_WIKI_INDEX = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "wiki", "sharepoint", "index.md"
)


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
        base = resolve_within(SHAREPOINT_DIR, subfolder)

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


def search_sharepoint_files(keyword: str, subfolder: str = "") -> str:
    """Busca archivos recursivamente en SharePoint que contengan el keyword en su nombre."""
    err = _check_dir()
    if err:
        return err

    try:
        base = resolve_within(SHAREPOINT_DIR, subfolder)
        if not os.path.exists(base):
            return f"La subcarpeta '{subfolder}' no existe en SharePoint."

        keyword_lower = keyword.lower()
        matches = []
        for root, dirs, files in os.walk(base):
            dirs.sort()
            for name in sorted(files):
                if keyword_lower in name.lower():
                    rel = os.path.relpath(os.path.join(root, name), SHAREPOINT_DIR)
                    size = os.path.getsize(os.path.join(root, name))
                    mod = datetime.fromtimestamp(os.path.getmtime(os.path.join(root, name))).strftime("%Y-%m-%d %H:%M")
                    matches.append((rel, name, size, mod))

        if not matches:
            return f"No se encontraron archivos con '{keyword}' en SharePoint."

        result = f"Archivos encontrados con '{keyword}' en SharePoint:\n\n"
        for rel, name, size, mod in matches:
            subfolder_found = os.path.dirname(rel)
            result += f"  {name}\n    subcarpeta: {subfolder_found}\n    {size:,} bytes  |  {mod}\n\n"
        result += f"Total: {len(matches)} archivo(s)"
        return result

    except Exception as e:
        return f"Error al buscar en SharePoint: {e}"


def copy_from_sharepoint(filename: str, subfolder: str = "") -> str:
    """Copia un archivo de SharePoint al directorio de trabajo para procesarlo."""
    err = _check_dir()
    if err:
        return err

    try:
        os.makedirs(WORK_DIR, exist_ok=True)
        base = resolve_within(SHAREPOINT_DIR, subfolder)
        source = resolve_within(SHAREPOINT_DIR, subfolder, filename)

        if not os.path.exists(source):
            return f"Archivo '{filename}' no encontrado en SharePoint ({base})."

        dest = resolve_within(WORK_DIR, os.path.basename(filename))
        shutil.copy2(source, dest)
        return f"'{filename}' copiado de SharePoint al directorio de trabajo: {dest}"

    except UnsafePathError as e:
        return f"Error: ruta no permitida: {e}"
    except Exception as e:
        return f"Error al copiar de SharePoint: {e}"


def refresh_sharepoint_index() -> str:
    """Escanea SharePoint y actualiza wiki/sharepoint/index.md con el árbol actual de archivos."""
    err = _check_dir()
    if err:
        return err

    try:
        # Recolectar todos los archivos con ruta relativa
        files: list[tuple[str, int, str]] = []
        for root, dirs, filenames in os.walk(SHAREPOINT_DIR):
            dirs.sort()
            for name in sorted(filenames):
                if name.startswith("~$"):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, SHAREPOINT_DIR)
                size = os.path.getsize(full)
                mod = datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d")
                files.append((rel, size, mod))

        now = datetime.now().strftime("%Y-%m-%d")
        lines = [
            f"# SharePoint — Índice de Archivos (auto-generado)\n",
            f"\n**Base:** `{SHAREPOINT_DIR}`\n",
            f"**Actualizado:** {now} | **Total:** {len(files)} archivos\n",
            "\n---\n\n",
            "## Árbol completo\n\n",
            "```\n",
        ]

        # Árbol por carpeta raíz
        current_parts: list[str] = []
        for rel, size, mod in files:
            parts = rel.split(os.sep)
            # Imprimir carpetas nuevas
            for i, part in enumerate(parts[:-1]):
                if i >= len(current_parts) or current_parts[i] != part:
                    indent = "  " * i
                    lines.append(f"{indent}{part}/\n")
                    current_parts = parts[:i + 1]
            # Imprimir archivo
            indent = "  " * (len(parts) - 1)
            kb = size // 1024
            lines.append(f"{indent}{parts[-1]}  ({kb:,} KB  {mod})\n")

        lines.append("```\n")

        os.makedirs(os.path.dirname(_WIKI_INDEX), exist_ok=True)
        with open(_WIKI_INDEX, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return f"Índice actualizado: {_WIKI_INDEX}\n{len(files)} archivos escaneados."

    except Exception as e:
        return f"Error al actualizar índice SharePoint: {e}"


def mover_en_sharepoint(origen: str, destino: str) -> str:
    """
    Mueve un archivo o carpeta de una ubicación a otra dentro de SharePoint.
    origen y destino son rutas relativas a SHAREPOINT_DIR (usar / como separador).
    Si el origen es una carpeta, mueve todo su contenido recursivamente.
    Crea la carpeta destino si no existe.
    """
    err = _check_dir()
    if err:
        return err

    try:
        src = resolve_within(SHAREPOINT_DIR, origen)
        dst_dir = resolve_within(SHAREPOINT_DIR, destino)
    except UnsafePathError as e:
        return f"Error: ruta no permitida: {e}"

    if src == os.path.abspath(SHAREPOINT_DIR):
        return "Error: no se puede mover la raíz de SharePoint."

    if not os.path.exists(src):
        return f"No encontrado: {origen}"

    try:
        os.makedirs(dst_dir, exist_ok=True)
        if os.path.isfile(src):
            dst_file = os.path.join(dst_dir, os.path.basename(src))
            if os.path.exists(dst_file):
                return f"Ya existe en destino: {dst_file}"
            shutil.move(src, dst_file)
            return f"Archivo movido: {origen} → {destino}/{os.path.basename(src)}"
        elif os.path.isdir(src):
            try:
                if os.path.commonpath((src, dst_dir)) == src:
                    return "Error: el destino no puede estar dentro de la carpeta de origen."
            except ValueError:
                return "Error: origen y destino no pertenecen al mismo árbol de rutas."

            items = os.listdir(src)
            conflicts = [item for item in items if os.path.exists(os.path.join(dst_dir, item))]
            if conflicts:
                return (
                    "Error: ya existen elementos en el destino: "
                    + ", ".join(conflicts[:10])
                )
            for item in items:
                shutil.move(os.path.join(src, item), os.path.join(dst_dir, item))
            os.rmdir(src)
            return f"Carpeta movida: {origen} → {destino}"
        else:
            return f"Tipo no reconocido: {origen}"
    except Exception as e:
        return f"Error al mover: {e}"


def crear_carpeta_sharepoint(ruta: str) -> str:
    """Crea una carpeta en SharePoint. ruta es relativa a SHAREPOINT_DIR."""
    err = _check_dir()
    if err:
        return err
    try:
        full = resolve_within(SHAREPOINT_DIR, ruta)
    except UnsafePathError as e:
        return f"Error: ruta no permitida: {e}"
    if full == os.path.abspath(SHAREPOINT_DIR):
        return "Error: indica una subcarpeta de SharePoint."
    if os.path.exists(full):
        return f"Ya existe: {ruta}"
    os.makedirs(full, exist_ok=True)
    return f"Carpeta creada: {ruta}"


def eliminar_carpeta_sharepoint(ruta: str) -> str:
    """Elimina una carpeta VACÍA en SharePoint. Falla si tiene archivos."""
    err = _check_dir()
    if err:
        return err
    try:
        full = resolve_within(SHAREPOINT_DIR, ruta)
    except UnsafePathError as e:
        return f"Error: ruta no permitida: {e}"
    if full == os.path.abspath(SHAREPOINT_DIR):
        return "Error: no se puede eliminar la raíz de SharePoint."
    if not os.path.exists(full):
        return f"No existe: {ruta}"
    archivos = [f for f in os.listdir(full) if os.path.isfile(os.path.join(full, f))]
    subcarpetas = [f for f in os.listdir(full) if os.path.isdir(os.path.join(full, f))]
    if archivos or subcarpetas:
        return f"No vacía ({len(archivos)} archivos, {len(subcarpetas)} subcarpetas). Mueve el contenido primero."
    os.rmdir(full)
    return f"Carpeta eliminada: {ruta}"


def save_to_sharepoint(filename: str, dest_subfolder: str = "") -> str:
    """Guarda un archivo del directorio de trabajo de vuelta en SharePoint."""
    err = _check_dir()
    if err:
        return err

    try:
        source = resolve_within(WORK_DIR, filename)
        if not os.path.exists(source):
            return f"'{filename}' no encontrado en el directorio de trabajo."

        dest_dir = resolve_within(SHAREPOINT_DIR, dest_subfolder)
        os.makedirs(dest_dir, exist_ok=True)

        dest = resolve_within(dest_dir, os.path.basename(filename))
        shutil.copy2(source, dest)
        return f"'{filename}' guardado en SharePoint: {dest}"

    except UnsafePathError as e:
        return f"Error: ruta no permitida: {e}"
    except Exception as e:
        return f"Error al guardar en SharePoint: {e}"
