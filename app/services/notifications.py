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

# Intentar configurar locale a español
try:
    locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
except:
    pass


async def notify_all_parties(agent_id: str, data: dict):
    """
    Orquesta el envío de WhatsApps y Correos Electrónicos.
    """
    tenant = TENANTS.get(agent_id)
    print(f"🔔 Notificando partes para agente {tenant}...")

    if not tenant:
        return

    # 1. Datos base
    token = os.getenv("WHATSAPP_TOKEN", GLOBAL_WA_TOKEN)
    phone_id = os.getenv("WHATSAPP_PHONE_ID", GLOBAL_WA_PHONE_ID)

    cliente_email = data.get("cliente_email")
    asesor_email = data.get(
        "asesor_email"
    )  # Asumimos que el ID del calendario es el email

    # Formateo de fecha
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
    asesor_nombre = data.get("asesor_nombre", "Asesor")
    # --- 2. ENVIAR WHATSAPP ---
    if token and phone_id:
        print(f"📲 Enviando WhatsApps a {data.get('cliente_telefono')} y asesor...")
        # Al Cliente
        if data.get("cliente_telefono"):
            await send_whatsapp(
                to=data["cliente_telefono"],
                template="cita_confirmada_cliente",
                params=[
                    cliente_nombre,
                    fecha_humana,
                    asesor_nombre,
                    propiedad,
                ],
                token=token,
                phone_id=phone_id,
            )
        # Al Asesor
        if tenant.get("owner_phone"):
            await send_whatsapp(
                to=tenant["owner_phone"],
                template="alerta_nuevo_lead_owner",
                params=[
                    tenant["name"],
                    cliente_nombre,
                    data.get("cliente_telefono"),
                    fecha_humana,
                    propiedad,
                ],
                token=token,
                phone_id=phone_id,
            )
    else:
        print("⚠️ Token o Phone ID de WhatsApp no configurado; no se envió WhatsApp.")

    # --- 3. ENVIAR CORREOS ELECTRÓNICOS ---
    asunto = f"Confirmación Cita: {propiedad} - {fecha_humana}"

    # Cuerpo del mensaje (HTML simple)
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

    # Enviar al Cliente
    if cliente_email and "@" in cliente_email:
        send_email_smtp(to_email=cliente_email, subject=asunto, body_html=mensaje_html)

    # Enviar al Asesor (Copia)
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

    # enviar el dueño de la inmobiliaria si tiene email
    owner_email = tenant.get("owner_email")
    if owner_email and "@" in owner_email:
        asunto_owner = f"🔔 NUEVA CITA: {cliente_nombre} - {fecha_humana}"
        mensaje_owner = f"""
        <h3>Nueva Cita Agendada en {tenant['name']}</h3>
        <ul>
            <li><strong>Cliente:</strong> {cliente_nombre}</li>
            <li><strong>Teléfono:</strong> {data.get('cliente_telefono')}</li>
            <li><strong>Email:</strong> {cliente_email}</li>
            <li><strong>Propiedad:</strong> {propiedad}</li>
            <li><strong>Fecha:</strong> {fecha_humana}</li>
            <li><strong>Asesor:</strong> {data.get('asesor_nombre')}</li>
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
    Envía correo usando servidor SMTP (Gmail, Outlook, AWS SES).
    Maneja puertos vacíos de forma segura.
    """
    smtp_server = os.getenv("SMTP_HOST", "smtp.gmail.com")

    # --- CORRECCIÓN CRÍTICA: Manejo seguro del puerto ---
    port_env = os.getenv("SMTP_PORT")
    try:
        # Si existe y tiene texto, convertir. Si es cadena vacía o None, usar 587.
        smtp_port = int(port_env) if port_env and port_env.strip() else 587
    except ValueError:
        print(f"⚠️ Puerto SMTP inválido ('{port_env}'). Usando 587.")
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
        msg.attach(MIMEText(body_html, "html"))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print(f"📧 Correo enviado exitosamente a {to_email}")
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")


async def notify_cancellation(
    agent_id: str, cancel_data: dict, origin_data: dict = None
):
    """
    Notifica la cancelación vía WhatsApp y Email.
    cancel_data: viene de calendar.cancel_appointment (datos del evento borrado)
    origin_data: datos adicionales que podamos tener (ej. email cliente si vino en el payload del webhook)
    """
    tenant = TENANTS.get(agent_id)
    if not tenant:
        return

    print(f"🔕 Iniciando notificaciones de cancelación para {tenant['name']}...")

    token = os.getenv("WHATSAPP_TOKEN", GLOBAL_WA_TOKEN)
    phone_id = os.getenv("WHATSAPP_PHONE_ID", GLOBAL_WA_PHONE_ID)

    # 1. Recuperar datos clave
    fecha_humana = cancel_data.get("fecha_humana", "Fecha desconocida")
    cliente_telefono = cancel_data.get("cliente_telefono", "")
    asesor_nombre = cancel_data.get("asesor_nombre", "")

    # Intentar sacar nombre cliente y asesor del summary/description del evento
    # Format summary: "CITA: {cliente_nombre} - {propiedad}"
    # Format description: "Cliente: ... \nTel: ... \nAsesor: ..."

    summary = cancel_data.get("evento_summary", "")
    description = cancel_data.get("evento_description", "")

    cliente_nombre = "Cliente"
    if "CITA:" in summary:
        try:
            parts = summary.replace("CITA:", "").split("-")
            cliente_nombre = parts[0].strip()
        except:
            pass

    # Intentar sacar email cliente de origin_data si existe
    cliente_email = None
    if origin_data:
        cliente_email = origin_data.get("cliente_email")

    # Asesor email?
    asesor_email = (
        None  # Se podría intentar parsear del description si se guardara el email allá
    )

    # --- 2. ENVIAR WHATSAPP CANCELACIÓN ---
    if token and phone_id:

        # A. Al Cliente (cita_cancelada_cliente)
        # Params plantilla: {{1}} nombre cliente, {{2}} fecha cita, {{3}} nombre inmobiliaria
        if cliente_telefono:
            print(f"📲 Enviando WhatsApp Cancelación a Cliente {cliente_telefono}")
            await send_whatsapp(
                to=cliente_telefono,
                template="cita_cancelada_cliente",  # Asegurarse que este nombre coincida con Meta
                params=[cliente_nombre, fecha_humana],
                token=token,
                phone_id=phone_id,
            )

        # B. Al Dueño / Asesor (alerta_cancelacion_owner)
        # Params plantilla: {{1}} nombre cliente, {{2}} fecha cita, {{3}} motivo/info extra
        if tenant.get("owner_phone"):
            print(f"📲 Enviando WhatsApp Cancelación a Owner {tenant['owner_phone']}")
            await send_whatsapp(
                to=tenant["owner_phone"],
                template="alerta_cancelacion_owner",
                params=[
                    cliente_nombre,
                    fecha_humana,
                    asesor_nombre,
                    "Cancelado por el cliente vía WhatsApp (Quick Reply)",
                ],
                token=token,
                phone_id=phone_id,
            )

    # --- 3. ENVIAR EMAILS DE CANCELACIÓN ---

    # A. Cliente
    if cliente_email:
        asunto_cli = f"Cita Cancelada: {fecha_humana}"
        body_cli = f"""
        <h2>Hola {cliente_nombre},</h2>
        <p>Confirmamos que tu cita programada para el <strong>{fecha_humana}</strong> ha sido cancelada exitosamente.</p>
        <p>Si deseas reagendar, no dudes en escribirnos nuevamente.</p>
        <p>Saludos,<br>{tenant['name']}</p>
        """
        send_email_smtp(cliente_email, asunto_cli, body_cli)

    # B. Asesor / Inmobiliaria
    owner_email = tenant.get("owner_email")
    if owner_email:
        asunto_owner = f"🚫 CITA CANCELADA: {cliente_nombre}"
        body_owner = f"""
        <h3>Aviso de Cancelación</h3>
        <ul>
            <li><strong>Cliente:</strong> {cliente_nombre}</li>
            <li><strong>Teléfono:</strong> {cliente_telefono}</li>
            <li><strong>Fecha cancelada:</strong> {fecha_humana}</li>
            <li><strong>Origen:</strong> WhatsApp Automático</li>
        </ul>
        """
        send_email_smtp(owner_email, asunto_owner, body_owner)
