import httpx
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import locale
from app.config import GLOBAL_WA_TOKEN, GLOBAL_WA_PHONE_ID, TENANTS
from dotenv import load_dotenv

load_dotenv()

try:
    locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
except:
    pass


async def notify_all_parties(agent_id: str, data: dict):
    """
    Orquesta el envío de WhatsApps y Correos para NUEVAS CITAS.
    """
    tenant = TENANTS.get(agent_id)
    if not tenant:
        return

    print(f"🔔 Notificando partes para {tenant.get('name')}...")

    token = os.getenv("WHATSAPP_TOKEN", GLOBAL_WA_TOKEN)
    phone_id = os.getenv("WHATSAPP_PHONE_ID", GLOBAL_WA_PHONE_ID)

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

    propiedad = data.get("propiedad_interes", "Propiedad")
    cliente_nombre = data.get("cliente_nombre", "Cliente")
    cliente_telefono = data.get("cliente_telefono", "")
    asesor_nombre = data.get("asesor_nombre", "Asesor")

    # --- 2. ENVIAR WHATSAPP ---
    if token and phone_id:
        if data.get("cliente_telefono"):
            await send_whatsapp(
                to=data["cliente_telefono"],
                template="cita_confirmada_cliente",
                params=[cliente_nombre, fecha_humana, asesor_nombre, propiedad],
                token=token,
                phone_id=phone_id,
            )
        if tenant.get("owner_phone"):
            await send_whatsapp(
                to=tenant["owner_phone"],
                template="alerta_nuevo_lead_owner",
                params=[
                    tenant["name"],
                    cliente_nombre,
                    cliente_telefono,
                    fecha_humana,
                    propiedad,
                ],
                token=token,
                phone_id=phone_id,
            )

    # --- 3. ENVIAR CORREOS ---
    asunto = f"Confirmación Cita: {propiedad} - {fecha_humana}"

    mensaje_html = f"""
    <h2>Hola {cliente_nombre},</h2>
    <p>Tu cita ha sido confirmada exitosamente.</p>
    <ul>
        <li><strong>Propiedad:</strong> {propiedad}</li>
        <li><strong>Fecha:</strong> {fecha_humana}</li>
        <li><strong>Asesor:</strong> {data.get('asesor_nombre', 'Asignado')}</li>
    </ul>
    <p>Nos vemos pronto.<br>Equipo {tenant['name']}</p>
    """

    if cliente_email and "@" in cliente_email:
        send_email_smtp(to_email=cliente_email, subject=asunto, body_html=mensaje_html)

    if asesor_email and "@" in asesor_email:
        asunto_asesor = f"🔔 NUEVA CITA: {cliente_nombre} - {fecha_humana}"
        mensaje_asesor = f"""
        <h3>Nueva Cita Agendada</h3>
        <ul>
            <li><strong>Cliente:</strong> {cliente_nombre}</li>
            <li><strong>Teléfono:</strong> {data.get('cliente_telefono')}</li>
            <li><strong>Email:</strong> {cliente_email}</li>
            <li><strong>Propiedad:</strong> {propiedad}</li>
            <li><strong>Fecha:</strong> {fecha_humana}</li>
        </ul>
        """
        send_email_smtp(
            to_email=asesor_email, subject=asunto_asesor, body_html=mensaje_asesor
        )

    owner_email = tenant.get("owner_email")
    if owner_email and "@" in owner_email and owner_email != asesor_email:
        asunto_owner = f"🔔 NUEVA CITA Agendada - {cliente_nombre}"
        mensaje_owner = f"""
        <h3>Nueva Cita Agendada en {tenant['name']}</h3>
        <ul>
            <li><strong>Cliente:</strong> {cliente_nombre}</li>
            <li><strong>Teléfono:</strong> {data.get('cliente_telefono')}</li>
            <li><strong>Email:</strong> {cliente_email}</li>
            <li><strong>Propiedad:</strong> {propiedad}</li>
            <li><strong>Fecha:</strong> {fecha_humana}</li>
        </ul>
        """
        send_email_smtp(
            to_email=owner_email, subject=asunto_owner, body_html=mensaje_owner
        )


async def send_whatsapp(
    to: str, template: str, params: list, token: str, phone_id: str
):
    url = f"https://graph.facebook.com/v24.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    to = to.replace("+", "").replace(" ", "")
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "es_CO"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in params],
                }
            ],
        },
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, headers=headers)
        except Exception as e:
            print(f"❌ Error WhatsApp: {e}")


def send_email_smtp(to_email, subject, body_html):
    """
    Envía correo usando servidor SMTP.
    """
    smtp_server = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port_env = os.getenv("SMTP_PORT")

    try:
        smtp_port = int(port_env) if port_env and port_env.strip() else 587
    except ValueError:
        smtp_port = 587

    smtp_user = os.getenv("SMTP_EMAIL")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    if not smtp_user or not smtp_pass:
        print(f"⚠️ SMTP no configurado. No se envió correo a {to_email}")
        return

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
        print(f"📧 Correo enviado exitosamente a {to_email}")
    except Exception as e:
        print(f"❌ Error enviando correo a {to_email}: {e}")


async def notify_cancellation(
    agent_id: str, cancel_data: dict, origin_data: dict = None
):
    """
    Notifica la cancelación.
    USA EL EMAIL DETECTADO POR CALENDAR.PY
    """
    tenant = TENANTS.get(agent_id)
    if not tenant:
        return

    print(f"🔕 Iniciando notificaciones de cancelación para {tenant['name']}...")

    token = os.getenv("WHATSAPP_TOKEN", GLOBAL_WA_TOKEN)
    phone_id = os.getenv("WHATSAPP_PHONE_ID", GLOBAL_WA_PHONE_ID)

    fecha_humana = cancel_data.get("fecha_humana", "Fecha desconocida")
    cliente_telefono = cancel_data.get("cliente_telefono", "")
    asesor_nombre = cancel_data.get("asesor_nombre", "")
    summary = cancel_data.get("evento_summary", "")

    # Intentar sacar nombre
    cliente_nombre = "Cliente"
    if "CITA:" in summary:
        try:
            parts = summary.replace("CITA:", "").split("-")
            cliente_nombre = parts[0].strip()
        except:
            pass

    cliente_email = None
    if origin_data:
        cliente_email = origin_data.get("cliente_email")

    # --- ENVIAR WHATSAPP ---
    if token and phone_id:
        if cliente_telefono:
            print(f"📲 Enviando WhatsApp Cancelación a Cliente {cliente_telefono}")
            await send_whatsapp(
                to=cliente_telefono,
                template="cita_cancelada_cliente",
                params=[cliente_nombre, fecha_humana],
                token=token,
                phone_id=phone_id,
            )

        if tenant.get("owner_phone"):
            print(f"📲 Enviando WhatsApp Cancelación a Owner {tenant['owner_phone']}")
            await send_whatsapp(
                to=tenant["owner_phone"],
                template="alerta_cancelacion_owner",
                params=[
                    cliente_nombre,
                    fecha_humana,
                    propiedad,
                ],
                token=token,
                phone_id=phone_id,
            )

    # --- EMAILS ---
    # 1. Al Cliente
    if cliente_email:
        asunto_cli = f"Cita Cancelada: {fecha_humana}"
        body_cli = f"<h2>Hola {cliente_nombre},</h2><p>Tu cita del <strong>{fecha_humana}</strong> ha sido cancelada.</p>"
        send_email_smtp(cliente_email, asunto_cli, body_cli)

    # 2. Obtener Emails Internos (Dueño + Asesor)
    owner_email = tenant.get("owner_email")
    destinatarios = set()
    if owner_email:
        destinatarios.add(owner_email)

    # --- CORRECCIÓN AQUÍ: BUSCAR EMAIL REAL DEL ASESOR ---
    asesor_email = None

    # Intento 1: Buscar en el inventario usando el ID del calendario origen
    cal_origen_id = cancel_data.get("asesor_calendario_origen")
    if cal_origen_id:
        print(f"🔎 Buscando email para calendario ID: {cal_origen_id}")
        asesor_email = await inventory.get_advisor_email_by_calendar(
            agent_id, cal_origen_id
        )

        if asesor_email:
            print(f"✅ Email encontrado: {asesor_email}")
        else:
            print(f"⚠️ No se encontró email para ese ID en inventario.")
            # Fallback: Si el ID NO es un grupo raro, podría ser el email mismo
            if (
                "@" in cal_origen_id
                and "group.calendar.google.com" not in cal_origen_id
            ):
                asesor_email = cal_origen_id

    if asesor_email:
        destinatarios.add(asesor_email)

    # Enviar a todos los destinatarios internos encontrados
    for email_destino in destinatarios:
        asunto_interno = f"🚫 CITA CANCELADA: {cliente_nombre}"
        body_interno = f"""
        <h3>Aviso de Cancelación</h3>
        <ul>
            <li><strong>Cliente:</strong> {cliente_nombre}</li>
            <li><strong>Teléfono:</strong> {cliente_telefono}</li>
            <li><strong>Fecha:</strong> {fecha_humana}</li>
            <li><strong>Origen:</strong> WhatsApp Automático</li>
        </ul>
        """
        send_email_smtp(email_destino, asunto_interno, body_interno)
