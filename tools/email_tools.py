"""
Herramientas de correo Outlook.
Usa el Outlook Desktop instalado en la PC — sin contraseñas ni configuración extra.
Si Outlook no está abierto, lo lanza automáticamente (Office16). Solo disponible en Windows.
"""
import os
import shutil
import subprocess
import time
from config import WORK_DIR

try:
    import win32com.client
    import winreg
    import platform
    _OUTLOOK_OK = True
except ImportError:
    _OUTLOOK_OK = False

def _not_available() -> str:
    return (
        "Herramientas de email no disponibles en este sistema.\n"
        "Requiere Windows + Outlook Desktop instalado (pywin32)."
    )


def _try_launch_outlook():
    """Intenta abrir Outlook, priorizando el Clásico para soporte COM."""
    if platform.system() != "Windows":
        print("Outlook only available on Windows.")
        return False

    # 1. Intentar Outlook Clásico por rutas conocidas (Prioridad máxima para COM)
    print("Trying Classic Outlook via absolute paths...")
    classic_paths = [
        r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
    ]
    for path in classic_paths:
        if os.path.exists(path):
            try:
                os.startfile(path)
                print(f"Success: Launched Classic Outlook via {path}")
                return True
            except Exception:
                continue

    # 2. Intentar protocolo outlook: (Suele abrir el clásico, pero puede ser el nuevo)
    print("Trying outlook: protocol...")
    try:
        os.startfile("outlook:")
        print("Success: Launched via outlook: protocol")
        return True
    except Exception:
        pass

    # 3. Intentar olk.exe (Nuevo Outlook - Como fallback si el clásico no existe)
    print("Trying New Outlook via olk.exe as fallback...")
    try:
        subprocess.run(["powershell", "-Command", "Start-Process 'olk.exe'"], check=True, capture_output=True)
        print("Success: Launched via olk.exe")
        return True
    except subprocess.CalledProcessError:
        pass

    # 4. Intentar vía Registro (Nuevo Outlook)
    print("Trying New Outlook via registry App Paths as fallback...")
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths\olk.exe"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            folder_path, _ = winreg.QueryValueEx(key, "Path")
            if folder_path:
                exe_path = os.path.join(folder_path, "olk.exe")
                if os.path.exists(exe_path):
                    os.startfile(exe_path)
                    print("Success: Launched via registry path")
                    return True
    except Exception:
        pass

    print("ERROR: No se pudo abrir ninguna versión de Outlook.")
    return False


def _get_outlook():
    """Conecta al Outlook activo; si no está abierto, lo lanza y espera."""
    try:
        return win32com.client.GetActiveObject("Outlook.Application")
    except Exception:
        pass

    # Intentar lanzar Outlook automáticamente
    if not _try_launch_outlook():
        raise RuntimeError("No se pudo iniciar Outlook automáticamente.")

    # Esperar hasta 30 s a que esté disponible por COM (Solo funciona con Outlook Clásico)
    print("Waiting for Outlook to respond via COM (this may time out if using New Outlook)...")
    for _ in range(15):
        time.sleep(2)
        try:
            return win32com.client.GetActiveObject("Outlook.Application")
        except Exception:
            pass

    # Nota: El Nuevo Outlook NO soporta COM, así que es normal que falle aquí si solo está instalado el nuevo.
    # Sin embargo, el usuario pidió que abriera automáticamente y siguiera el flujo.
    # Si las herramientas de COM fallan después, el usuario verá el error de COM.
    raise RuntimeError("Outlook se lanzó pero no respondió por COM tras 30 s. "
                       "Nota: El 'Nuevo Outlook' (versión Store) no soporta automatización COM.")


def _get_inbox():
    outlook = _get_outlook()
    namespace = outlook.GetNamespace("MAPI")
    return namespace.GetDefaultFolder(6)  # 6 = Bandeja de entrada


def list_emails_with_attachments(limit: int = 20) -> str:
    if not _OUTLOOK_OK:
        return _not_available()
    """Lista los últimos correos que tienen archivos Excel adjuntos."""
    try:
        inbox = _get_inbox()
        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)
        filtered = messages.Restrict("[HasAttachments] = True")

        found = []
        for msg in filtered:
            if len(found) >= limit:
                break
            try:
                excel_atts = []
                for att in msg.Attachments:
                    name = att.FileName
                    if name.lower().endswith((".xlsx", ".xls")):
                        excel_atts.append({"index": att.Index, "name": name})

                if excel_atts:
                    found.append({
                        "entry_id": msg.EntryID,
                        "asunto": msg.Subject or "Sin asunto",
                        "remitente": msg.SenderEmailAddress or "?",
                        "fecha": str(msg.ReceivedTime)[:19],
                        "adjuntos": excel_atts,
                    })
            except Exception:
                continue

        if not found:
            return "No se encontraron correos con archivos Excel adjuntos."

        result = f"Se encontraron {len(found)} correo(s) con planillas Excel:\n\n"
        for i, em in enumerate(found, 1):
            result += f"{i}. Asunto:   {em['asunto']}\n"
            result += f"   De:       {em['remitente']}\n"
            result += f"   Fecha:    {em['fecha']}\n"
            result += f"   entry_id: {em['entry_id']}\n"
            for att in em["adjuntos"]:
                result += f"   📎 {att['name']}  (attachment_index: {att['index']})\n"
            result += "\n"
        return result

    except Exception as e:
        return f"Error al leer Outlook: {e}\n(Asegúrate de que Outlook esté abierto)"


def download_email_attachment(entry_id: str, attachment_index: int, filename: str) -> str:
    """Descarga un adjunto Excel de un correo al directorio de trabajo."""
    if not _OUTLOOK_OK:
        return _not_available()
    try:
        os.makedirs(WORK_DIR, exist_ok=True)

        outlook = _get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        msg = namespace.GetItemFromID(entry_id)

        att = msg.Attachments.Item(attachment_index)
        filepath = os.path.join(WORK_DIR, filename)
        att.SaveAsFile(filepath)

        return f"Archivo '{filename}' descargado en: {filepath}"

    except Exception as e:
        return f"Error al descargar adjunto: {e}"


def send_email(to: str, subject: str, body: str, attachment_path: str = None) -> str:
    """Envía un correo desde Outlook con o sin adjunto."""
    if not _OUTLOOK_OK:
        return _not_available()
    try:
        outlook = _get_outlook()
        mail = outlook.CreateItem(0)  # 0 = MailItem
        mail.To = to
        mail.Subject = subject
        mail.Body = body

        if attachment_path:
            # Resolver ruta relativa al WORK_DIR si no es absoluta
            if not os.path.isabs(attachment_path):
                attachment_path = os.path.join(WORK_DIR, attachment_path)
            if os.path.exists(attachment_path):
                mail.Attachments.Add(attachment_path)
            else:
                return f"Error: No se encontró el archivo adjunto '{attachment_path}'."

        mail.Send()

        if attachment_path and os.path.exists(attachment_path):
            return f"Correo enviado a {to} con adjunto '{os.path.basename(attachment_path)}'."
        return f"Correo enviado exitosamente a {to}."

    except Exception as e:
        return f"Error al enviar correo: {e}"


def search_emails_by_subject(keyword: str, limit: int = 10) -> str:
    """Busca correos cuyo asunto contenga una palabra clave."""
    if not _OUTLOOK_OK:
        return _not_available()
    try:
        inbox = _get_inbox()
        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)
        safe_kw = keyword.replace("'", "''")
        filtered = messages.Restrict(
            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{safe_kw}%'"
        )

        found = []
        for msg in filtered:
            if len(found) >= limit:
                break
            try:
                excel_atts = [
                    att.FileName for att in msg.Attachments
                    if att.FileName.lower().endswith((".xlsx", ".xls"))
                ]
                found.append({
                    "entry_id": msg.EntryID,
                    "asunto": msg.Subject,
                    "remitente": msg.SenderEmailAddress,
                    "fecha": str(msg.ReceivedTime)[:19],
                    "adjuntos_excel": excel_atts,
                })
            except Exception:
                continue

        if not found:
            return f"No se encontraron correos con '{keyword}' en el asunto."

        result = f"Correos con '{keyword}' en el asunto ({len(found)} resultados):\n\n"
        for i, em in enumerate(found, 1):
            result += f"{i}. {em['asunto']}\n"
            result += f"   De: {em['remitente']}  |  {em['fecha']}\n"
            result += f"   entry_id: {em['entry_id']}\n"
            if em["adjuntos_excel"]:
                result += f"   📎 Excel: {', '.join(em['adjuntos_excel'])}\n"
            result += "\n"
        return result

    except Exception as e:
        return f"Error al buscar correos: {e}"
