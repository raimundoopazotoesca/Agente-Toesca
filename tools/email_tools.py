"""
Herramientas de correo Outlook.
Usa el Outlook Desktop instalado en la PC — sin contraseñas ni configuración extra.
Requiere que Outlook esté abierto. Solo disponible en Windows.
"""
import os
import shutil
from config import WORK_DIR

try:
    import win32com.client
    _OUTLOOK_OK = True
except ImportError:
    _OUTLOOK_OK = False


def _not_available() -> str:
    return (
        "Herramientas de email no disponibles en este sistema.\n"
        "Requiere Windows + Outlook Desktop instalado (pywin32)."
    )


def _get_outlook():
    """Conecta al Outlook que ya está abierto (evita abrir Outlook 2016)."""
    try:
        return win32com.client.GetActiveObject("Outlook.Application")
    except Exception:
        return win32com.client.Dispatch("Outlook.Application")


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
        messages.Sort("[ReceivedTime]", True)  # Más recientes primero

        found = []
        checked = 0

        for msg in messages:
            if checked >= limit * 5:  # Revisar hasta 5x el límite buscando con Excel
                break
            checked += 1

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

                if len(found) >= limit:
                    break
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

        found = []
        for msg in messages:
            if len(found) >= limit:
                break
            try:
                if keyword.lower() in (msg.Subject or "").lower():
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
