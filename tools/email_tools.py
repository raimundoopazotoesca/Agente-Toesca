"""
Herramientas de correo Outlook.
Usa el Outlook Desktop instalado en la PC — sin contraseñas ni configuración extra.
Si Outlook no está abierto, lo lanza automáticamente (Office16). Solo disponible en Windows.
"""
import os
import shutil
import subprocess
import time
import unicodedata
from config import WORK_DIR

DEFAULT_CC = "Inmobiliario Toesca"
CANTILLANA_CC = "mlagos@grupoaraucana.cl"

KNOWN_EMAIL_CONTACTS = {
    "cantillana": "lcantillana@grupoaraucana.cl",
    "leonardo": "lcantillana@grupoaraucana.cl",
    "leonardo cantillana": "lcantillana@grupoaraucana.cl",
    "nicole": "Nicole.Carvajal@jll.com",
    "carvajal": "Nicole.Carvajal@jll.com",
    "nicole carvajal": "Nicole.Carvajal@jll.com",
    "valentina": "valentina.bravo@tresasociados.cl",
    "valentina bravo": "valentina.bravo@tresasociados.cl",
    "sebastian": "sebastian.bravo@tresasociados.cl",
    "sebastian bravo": "sebastian.bravo@tresasociados.cl",
}

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


def with_default_cc(cc: str = None) -> str:
    """Agrega la copia obligatoria a Inmobiliario Toesca sin duplicar destinatarios."""
    recipients = []
    seen = set()
    for raw in (cc or "", DEFAULT_CC):
        for part in str(raw or "").split(";"):
            recipient = part.strip()
            key = recipient.lower()
            if recipient and key not in seen:
                recipients.append(recipient)
                seen.add(key)
    return "; ".join(recipients)


def _recipient_is_cantillana(to: str | None) -> bool:
    normalized = _norm(to)
    return "cantillana" in normalized or "lcantillana@grupoaraucana.cl" in str(to or "").casefold()


def cc_for_recipient(to: str | None, cc: str = None) -> str:
    """Devuelve el CC base y agrega copia extra cuando el destinatario es Cantillana."""
    recipients = []
    seen = set()

    for raw in (cc or "", DEFAULT_CC):
        for part in str(raw or "").split(";"):
            recipient = part.strip()
            key = recipient.lower()
            if recipient and key not in seen:
                recipients.append(recipient)
                seen.add(key)

    if _recipient_is_cantillana(to):
        key = CANTILLANA_CC.lower()
        if key not in seen:
            recipients.append(CANTILLANA_CC)
            seen.add(key)

    return "; ".join(recipients)


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


def _norm(text: str | None) -> str:
    text = str(text or "").casefold()
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    return " ".join(text.replace("_", " ").replace("-", " ").split())


def _contact_matchers(contacto: str, email: str | None = None) -> tuple[set[str], set[str]]:
    emails = {str(email).strip().casefold()} if email else set()
    emails = {e for e in emails if e}
    terms = {_norm(contacto)}
    terms = {t for t in terms if t}

    normalized_contact = _norm(contacto)
    for alias, alias_email in KNOWN_EMAIL_CONTACTS.items():
        alias_norm = _norm(alias)
        if alias_norm and alias_norm in normalized_contact:
            emails.add(alias_email.casefold())
            terms.add(alias_norm)

    for email_value in list(emails):
        local_part = email_value.split("@", 1)[0]
        terms.add(_norm(local_part.replace(".", " ")))

    return emails, terms


def _smtp_from_address_entry(address_entry):
    try:
        exchange_user = address_entry.GetExchangeUser()
        smtp = getattr(exchange_user, "PrimarySmtpAddress", None)
        if smtp:
            return smtp
    except Exception:
        pass
    try:
        exchange_dl = address_entry.GetExchangeDistributionList()
        smtp = getattr(exchange_dl, "PrimarySmtpAddress", None)
        if smtp:
            return smtp
    except Exception:
        pass
    return None


def _sender_values(msg) -> list[str]:
    values = []
    for attr in ("SenderName", "SenderEmailAddress"):
        try:
            value = getattr(msg, attr, None)
            if value:
                values.append(str(value))
        except Exception:
            pass
    try:
        smtp = _smtp_from_address_entry(msg.Sender)
        if smtp:
            values.append(str(smtp))
    except Exception:
        pass
    return values


def _recipient_values(recipient) -> list[str]:
    values = []
    for attr in ("Name", "Address"):
        try:
            value = getattr(recipient, attr, None)
            if value:
                values.append(str(value))
        except Exception:
            pass
    try:
        smtp = _smtp_from_address_entry(recipient.AddressEntry)
        if smtp:
            values.append(str(smtp))
    except Exception:
        pass
    return values


def _values_match(values: list[str], emails: set[str], terms: set[str]) -> bool:
    normalized_values = [_norm(v) for v in values]
    lowered_values = [str(v or "").casefold() for v in values]

    for email in emails:
        if any(email in value for value in lowered_values):
            return True

    for term in terms:
        if term and any(term in value for value in normalized_values):
            return True

    return False


def _sender_matches(msg, emails: set[str], terms: set[str]) -> bool:
    return _values_match(_sender_values(msg), emails, terms)


def _recipients_match(msg, emails: set[str], terms: set[str]) -> bool:
    try:
        recipients = msg.Recipients
        for i in range(1, recipients.Count + 1):
            if _values_match(_recipient_values(recipients.Item(i)), emails, terms):
                return True
    except Exception:
        pass
    return False


def _mail_summary(msg, date_attr: str) -> dict:
    try:
        date_value = getattr(msg, date_attr)
    except Exception:
        date_value = ""
    excel_atts = []
    try:
        for att in msg.Attachments:
            if att.FileName.lower().endswith((".xlsx", ".xls")):
                excel_atts.append(att.FileName)
    except Exception:
        pass
    return {
        "entry_id": getattr(msg, "EntryID", ""),
        "asunto": getattr(msg, "Subject", "") or "Sin asunto",
        "fecha": str(date_value)[:19],
        "conversation_id": getattr(msg, "ConversationID", "") or "",
        "adjuntos_excel": excel_atts,
    }


def _subject_key(subject: str) -> str:
    subject = _norm(subject)
    while subject.startswith(("re ", "fw ", "fwd ")):
        subject = subject.split(" ", 1)[1]
    return subject


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


def send_email(to: str, subject: str, body: str, attachment_path: str = None, cc: str = None) -> str:
    """Envía un correo desde Outlook con o sin adjunto y opcionalmente con CC."""
    if not _OUTLOOK_OK:
        return _not_available()
    try:
        outlook = _get_outlook()
        mail = outlook.CreateItem(0)  # 0 = MailItem
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        cc = cc_for_recipient(to, cc)
        mail.CC = cc

        if attachment_path:
            if not os.path.isabs(attachment_path):
                attachment_path = os.path.join(WORK_DIR, attachment_path)
            if os.path.exists(attachment_path):
                mail.Attachments.Add(attachment_path)
            else:
                return f"Error: No se encontró el archivo adjunto '{attachment_path}'."

        mail.Send()

        if attachment_path and os.path.exists(attachment_path):
            return f"Correo enviado a {to} con adjunto '{os.path.basename(attachment_path)}'."
        suffix = f" (CC: {cc})" if cc else ""
        return f"Correo enviado exitosamente a {to}{suffix}."

    except Exception as e:
        return f"Error al enviar correo: {e}"


def find_sent_email(to_email: str, subject_keyword: str) -> str | None:
    """
    Busca en Elementos enviados el EntryID del correo más reciente enviado a `to_email`
    cuyo asunto contenga `subject_keyword`. Retorna el EntryID o None si no encuentra.
    """
    if not _OUTLOOK_OK:
        return None
    try:
        outlook = _get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        sent = namespace.GetDefaultFolder(5)  # 5 = Sent Items
        messages = sent.Items
        messages.Sort("[SentOn]", True)
        safe_kw = subject_keyword.replace("'", "''")
        filtered = messages.Restrict(
            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{safe_kw}%'"
        )
        to_lower = to_email.lower()
        for msg in filtered:
            try:
                recipients = msg.Recipients
                for i in range(1, recipients.Count + 1):
                    r = recipients.Item(i)
                    if r.Address.lower() == to_lower:
                        return msg.EntryID
            except Exception:
                continue
    except Exception:
        pass
    return None


def reply_to_email(entry_id: str, body: str, cc: str = None) -> str:
    """Responde un correo existente (mismo hilo) con el cuerpo indicado."""
    if not _OUTLOOK_OK:
        return _not_available()
    try:
        outlook = _get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        original = namespace.GetItemFromID(entry_id)
        reply = original.Reply()
        reply.Body = body
        cc = cc_for_recipient(getattr(original, "To", None), cc)
        reply.CC = cc
        reply.Send()
        suffix = f" (CC: {cc})" if cc else ""
        return f"Respuesta enviada en el mismo hilo a {original.To}{suffix}."
    except Exception as e:
        return f"Error al responder correo: {e}"


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


def check_replies_from_contact(contacto: str, email: str = None, limit: int = 5, scan_limit: int = 500) -> str:
    """
    Revisa si un contacto respondio despues del ultimo correo enviado a ese contacto.

    La busqueda se hace por destinatario/remitente, no por asunto. Esto evita mezclar
    preguntas personales de seguimiento con flujos especificos como CDG.
    """
    if not _OUTLOOK_OK:
        return _not_available()

    try:
        outlook = _get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)
        sent = namespace.GetDefaultFolder(5)
        emails, terms = _contact_matchers(contacto, email)
        limit = max(1, min(int(limit or 5), 20))
        scan_limit = max(50, min(int(scan_limit or 500), 2000))

        if not emails and not terms:
            return "Error: indica un contacto o email para revisar respuestas."

        sent_items = sent.Items
        sent_items.Sort("[SentOn]", True)
        last_sent = None
        scanned = 0
        for msg in sent_items:
            scanned += 1
            if scanned > scan_limit:
                break
            try:
                if _recipients_match(msg, emails, terms):
                    last_sent = msg
                    break
            except Exception:
                continue

        inbox_items = inbox.Items
        inbox_items.Sort("[ReceivedTime]", True)
        replies = []
        recent_from_contact = []
        scanned = 0
        sent_time = getattr(last_sent, "SentOn", None) if last_sent else None
        sent_conversation = getattr(last_sent, "ConversationID", "") if last_sent else ""
        sent_subject_key = _subject_key(getattr(last_sent, "Subject", "") if last_sent else "")

        for msg in inbox_items:
            scanned += 1
            if scanned > scan_limit:
                break
            try:
                if not _sender_matches(msg, emails, terms):
                    continue

                summary = _mail_summary(msg, "ReceivedTime")
                recent_from_contact.append(summary)

                received_time = getattr(msg, "ReceivedTime", None)
                is_after_sent = True
                if sent_time and received_time:
                    try:
                        is_after_sent = received_time > sent_time
                    except Exception:
                        is_after_sent = str(received_time) > str(sent_time)

                if last_sent and not is_after_sent:
                    continue

                same_thread = False
                if sent_conversation and summary["conversation_id"] == sent_conversation:
                    same_thread = True
                elif sent_subject_key and sent_subject_key in _subject_key(summary["asunto"]):
                    same_thread = True
                summary["mismo_hilo"] = same_thread
                replies.append(summary)

                if len(replies) >= limit and len(recent_from_contact) >= limit:
                    break
            except Exception:
                continue

        lines = [f"## 📬 Revisión de respuestas: **{contacto}**"]
        if emails:
            lines.append(f"**Emails considerados:** `{', '.join(sorted(emails))}`")

        if last_sent:
            sent_summary = _mail_summary(last_sent, "SentOn")
            lines.extend([
                "",
                "### ✉️ Último correo enviado encontrado",
                f"- **Fecha:** {sent_summary['fecha']}",
                f"- **Asunto:** {sent_summary['asunto']}",
                f"- **Entry ID:** `{sent_summary['entry_id']}`",
            ])
        else:
            lines.extend([
                "",
                "### ⚠️ Sin correo enviado encontrado",
                f"No encontré correos enviados a **{contacto}** en los últimos `{scan_limit}` enviados revisados.",
            ])

        if replies:
            lines.extend(["", f"### ✅ Respuestas posteriores encontradas `{len(replies)}`"])
            for i, reply in enumerate(replies[:limit], 1):
                hilo = "sí" if reply.get("mismo_hilo") else "no / no confirmado"
                lines.append(f"{i}. **{reply['fecha']}**")
                lines.append(f"   - **Asunto:** {reply['asunto']}")
                lines.append(f"   - **Mismo hilo del enviado:** {hilo}")
                lines.append(f"   - **Entry ID:** `{reply['entry_id']}`")
                if reply["adjuntos_excel"]:
                    lines.append(f"   - 📎 **Excel:** {', '.join(reply['adjuntos_excel'])}")
        elif last_sent:
            lines.append("")
            lines.append("🚫 **No encontré respuestas posteriores** a ese correo en la bandeja de entrada revisada.")

        if not replies and recent_from_contact:
            lines.extend(["", f"### 📥 Últimos correos recibidos de **{contacto}**"])
            for i, msg in enumerate(recent_from_contact[:limit], 1):
                lines.append(f"{i}. **{msg['fecha']}** · {msg['asunto']} · `{msg['entry_id']}`")
        elif not replies and not recent_from_contact:
            lines.append("")
            lines.append(f"🚫 Tampoco encontré correos recibidos de **{contacto}** en los últimos `{scan_limit}` correos revisados.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error al revisar respuestas de {contacto}: {e}"
