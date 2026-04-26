import httpx
import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import locale
from app.config import GLOBAL_WA_TOKEN, GLOBAL_WA_PHONE_ID, TENANTS

logger = logging.getLogger(__name__)
from dotenv import load_dotenv

# Importar inventory para buscar emails de asesores si es necesario
from app.services import inventory

load_dotenv()

try:
    locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
except:
    pass

async def notify_all_parties(agent_id: str, data: dict):
    tenant = TENANTS.get(agent_id)
    if not tenant: return

    print(f"🔔 Nueva Cita: Notificando a todas las partes ({tenant.get('name')})...")

    token = os.getenv("WHATSAPP_TOKEN", GLOBAL_WA_TOKEN)
    phone_id = os.getenv("WHATSAPP_PHONE_ID", GLOBAL_WA_PHONE_ID)

    # Extracción Segura
    cliente_nombre = data.get("cliente_nombre", "Cliente")
    cliente_telefono = data.get("cliente_telefono", "")
    propiedad = data.get("propiedad_interes", "Propiedad")
    asesor_nombre = data.get("asesor_nombre", "Asesor")
    cliente_email = data.get("cliente_email")
    asesor_email = data.get("asesor_email")

    fecha_raw = data.get("fecha_hora_inicio", "")
    fecha_humana = fecha_raw
    try:
        if "T" in fecha_raw:
            dt = datetime.fromisoformat(fecha_raw)
            fecha_humana = dt.strftime("%d/%m/%Y a las %I:%M %p")
    except:
        pass

    # Registro de resultados para resumen final
    resultados = []

    # --- 1. WHATSAPP (CONFIRMACIÓN) ---
    if token and phone_id:
        if cliente_telefono:
            ok = await send_whatsapp(
                to=cliente_telefono,
                template="cita_confirmada_cliente",
                params=[cliente_nombre, fecha_humana, asesor_nombre, propiedad],
                token=token,
                phone_id=phone_id
            )
            resultados.append(("WA→Cliente", cliente_telefono, ok))
        else:
            resultados.append(("WA→Cliente", "SIN NÚMERO", False))

        if tenant.get("owner_phone"):
            ok = await send_whatsapp(
                to=tenant["owner_phone"],
                template="alerta_nuevo_lead_owner",
                params=[tenant["name"], cliente_nombre, cliente_telefono, fecha_humana, propiedad],
                token=token,
                phone_id=phone_id
            )
            resultados.append(("WA→Owner", tenant["owner_phone"], ok))
    else:
        logger.warning("⚠️ WHATSAPP NO CONFIGURADO: Falta WHATSAPP_TOKEN o WHATSAPP_PHONE_ID")
        resultados.append(("WA→Cliente", "NO CONFIG", False))
        resultados.append(("WA→Owner", "NO CONFIG", False))

    # --- 2. EMAILS ---
    asunto = f"Confirmación Cita: {propiedad} - {fecha_humana}"
    mensaje_html = f"""
    <h2>Hola {cliente_nombre},</h2>
    <p>Tu cita ha sido confirmada exitosamente.</p>
    <ul>
        <li><strong>Propiedad:</strong> {propiedad}</li>
        <li><strong>Fecha:</strong> {fecha_humana}</li>
        <li><strong>Asesor:</strong> {asesor_nombre}</li>
    </ul>
    <p>Nos vemos pronto.<br>Equipo {tenant['name']}</p>
    """

    if cliente_email and "@" in cliente_email:
        ok = send_email_smtp(cliente_email, asunto, mensaje_html)
        resultados.append(("Email→Cliente", cliente_email, ok))

    if asesor_email and "@" in asesor_email:
        ok = send_email_smtp(asesor_email, f"🔔 NUEVA CITA: {cliente_nombre}", mensaje_html)
        resultados.append(("Email→Asesor", asesor_email, ok))

    owner_email = tenant.get("owner_email")
    if owner_email and owner_email != asesor_email:
        ok = send_email_smtp(owner_email, f"🔔 NUEVA CITA: {cliente_nombre}", mensaje_html)
        resultados.append(("Email→Owner", owner_email, ok))

    # --- RESUMEN FINAL ---
    print("\n" + "=" * 55)
    print("📊 RESUMEN NOTIFICACIONES - NUEVA CITA")
    print(f"   Cliente: {cliente_nombre} | Tel: {cliente_telefono}")
    print("-" * 55)
    for canal, destino, exito in resultados:
        estado = "✅ OK" if exito else "❌ FALLÓ"
        print(f"   {estado} | {canal} → {destino}")
    print("=" * 55 + "\n")


async def send_whatsapp(to: str, template: str, params: list, token: str, phone_id: str) -> bool:
    """
    Envía mensaje de plantilla WhatsApp. Retorna True si fue exitoso, False si falló.
    """
    if not to:
        logger.warning("⚠️ WA: Número destino vacío, no se envía.")
        return False

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    to_clean = to.replace("+", "").replace(" ", "").strip()

    payload = {
        "messaging_product": "whatsapp",
        "to": to_clean,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "es_CO"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in params]
                }
            ]
        }
    }

    print(f"📤 WA Enviando a {to_clean} | Template: {template} | Params: {params}")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code in [200, 201]:
                msg_id = response.json().get('messages', [{}])[0].get('id', 'N/A')
                print(f"✅ WA OK → {to_clean} | Template: {template} | MsgID: {msg_id}")
                return True
            else:
                error_body = response.text
                print(f"❌ WA FALLÓ → {to_clean} | Template: {template} | HTTP {response.status_code} | Error: {error_body}")
                return False

        except Exception as e:
            print(f"❌ WA EXCEPCIÓN → {to_clean} | Template: {template} | {type(e).__name__}: {e}")
            return False


def send_email_smtp(to_email, subject, body_html) -> bool:
    """Envía email por SMTP. Retorna True si fue exitoso, False si falló."""
    smtp_server = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port_env = os.getenv("SMTP_PORT")
    try:
        smtp_port = int(port_env) if port_env and port_env.strip() else 587
    except:
        smtp_port = 587

    smtp_user = os.getenv("SMTP_EMAIL")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    if not smtp_user or not smtp_pass:
        print(f"❌ EMAIL NO CONFIGURADO: Faltan SMTP_EMAIL o SMTP_PASSWORD → No se envió a {to_email}")
        return False

    print(f"📧 EMAIL Enviando a {to_email} | Asunto: {subject} | Via: {smtp_server}:{smtp_port}")

    try:
        msg = MIMEMultipart()
        msg["From"] = f"Inmobiliaria Bot <{smtp_user}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print(f"✅ EMAIL OK → {to_email}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ EMAIL AUTH FALLÓ → {to_email} | Error: {e}")
        return False
    except Exception as e:
        print(f"❌ EMAIL FALLÓ → {to_email} | {type(e).__name__}: {e}")
        return False


async def notify_cancellation(agent_id: str, cancel_data: dict, origin_data: dict = None):
    tenant = TENANTS.get(agent_id)
    if not tenant: return

    print(f"🔕 Procesando Cancelación...")

    token = os.getenv("WHATSAPP_TOKEN", GLOBAL_WA_TOKEN)
    phone_id = os.getenv("WHATSAPP_PHONE_ID", GLOBAL_WA_PHONE_ID)

    # 1. Recuperar datos
    fecha_humana = cancel_data.get("fecha_humana", "Fecha desconocida")
    cliente_telefono = cancel_data.get("cliente_telefono", "")
    summary = cancel_data.get("evento_summary", "")

    # 2. Extraer Nombre y Propiedad del Título del Evento
    # Formato esperado: "CITA: Nombre Cliente - Nombre Propiedad"
    cliente_nombre = "Cliente"
    propiedad = "Propiedad General" # Valor por defecto para evitar NameError

    if summary and "CITA:" in summary:
        try:
            clean = summary.replace("CITA:", "").strip()
            if "-" in clean:
                parts = clean.split("-", 1)
                cliente_nombre = parts[0].strip()
                if len(parts) > 1:
                    propiedad = parts[1].strip()
            else:
                cliente_nombre = clean
        except:
            pass
            
    resultados = []

    # --- 1. WHATSAPP ---
    if token and phone_id:
        if cliente_telefono:
            ok = await send_whatsapp(
                to=cliente_telefono,
                template="cita_cancelada_cliente",
                params=[cliente_nombre, fecha_humana],
                token=token,
                phone_id=phone_id
            )
            resultados.append(("WA→Cliente", cliente_telefono, ok))

        if tenant.get("owner_phone"):
            ok = await send_whatsapp(
                to=tenant["owner_phone"],
                template="alerta_cancelacion_owner",
                params=[cliente_nombre, fecha_humana, propiedad],
                token=token,
                phone_id=phone_id
            )
            resultados.append(("WA→Owner", tenant["owner_phone"], ok))

    # --- 2. EMAILS ---
    asesor_email = None
    cal_id = cancel_data.get("asesor_calendario_origen")

    if cal_id:
        asesor_email = await inventory.get_advisor_email_by_calendar(agent_id, cal_id)
        if not asesor_email and "@" in cal_id and "group.calendar.google.com" not in cal_id:
            asesor_email = cal_id

    destinatarios = set()
    if tenant.get("owner_email"): destinatarios.add(tenant["owner_email"])
    if asesor_email: destinatarios.add(asesor_email)

    body_interno = f"""
    <h3>Cita Cancelada</h3>
    <ul>
        <li><strong>Cliente:</strong> {cliente_nombre}</li>
        <li><strong>Tel:</strong> {cliente_telefono}</li>
        <li><strong>Propiedad:</strong> {propiedad}</li>
        <li><strong>Fecha original:</strong> {fecha_humana}</li>
    </ul>
    """

    for email in destinatarios:
        ok = send_email_smtp(email, f"🚫 CANCELACIÓN: {cliente_nombre}", body_interno)
        resultados.append(("Email→Equipo", email, ok))

    if origin_data and origin_data.get("cliente_email"):
        ok = send_email_smtp(origin_data["cliente_email"], "Cita Cancelada", f"Hola {cliente_nombre}, tu cita del {fecha_humana} ha sido cancelada.")
        resultados.append(("Email→Cliente", origin_data["cliente_email"], ok))

    # --- RESUMEN FINAL ---
    print("\n" + "=" * 55)
    print("📊 RESUMEN NOTIFICACIONES - CANCELACIÓN")
    print(f"   Cliente: {cliente_nombre} | Tel: {cliente_telefono}")
    print("-" * 55)
    for canal, destino, exito in resultados:
        estado = "✅ OK" if exito else "❌ FALLÓ"
        print(f"   {estado} | {canal} → {destino}")
    print("=" * 55 + "\n")