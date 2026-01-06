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
    if not tenant:
        return

    print(f"🔔 Iniciando notificaciones para agente: {tenant['name']}")

    # 1. Datos base
    token = os.getenv("WHATSAPP_TOKEN", GLOBAL_WA_TOKEN)
    phone_id = os.getenv("WHATSAPP_PHONE_ID", GLOBAL_WA_PHONE_ID)    

    cliente_email = data.get("cliente_email")
    
    # --- CORRECCIÓN DEFINITIVA ---
    # Solo usamos asesor_email. No intentamos usar el calendar_id porque no es un correo.
    asesor_email = data.get("asesor_email")
    
    print(f"📧 Email detectado para Asesor: {asesor_email}")

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
        # Al Cliente
        if data.get("cliente_telefono"):
            await send_whatsapp(
                to=data["cliente_telefono"],
                template="cita_confirmada_cliente",
                params=[cliente_nombre, fecha_humana], 
                token=token,
                phone_id=phone_id,
            )
        # Al Dueño (Owner) - Copia de seguridad
        if tenant.get("owner_phone"):
            await send_whatsapp(
                to=tenant["owner_phone"],
                template="alerta_nuevo_lead_owner",
                params=[
                    tenant["name"],
                    cliente_nombre,
                    data.get("cliente_telefono"),
                    f"{fecha_humana} - {propiedad}",
                ],
                token=token,
                phone_id=phone_id,
            )

    # --- 3. ENVIAR CORREOS ELECTRÓNICOS ---
    asunto = f"Confirmación Cita: {propiedad} - {fecha_humana}"

    # Cuerpo del mensaje (HTML simple)
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

    # Enviar al Cliente
    if cliente_email and "@" in cliente_email:
        send_email_smtp(to_email=cliente_email, subject=asunto, body_html=mensaje_html)

    # Enviar al Asesor (Copia)
    if asesor_email and "@" in asesor_email:
        asunto_asesor = f"🔔 NUEVA CITA: {cliente_nombre}"
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
    else:
        print(f"⚠️ NO SE ENVIÓ CORREO AL ASESOR. Faltó el campo 'asesor_email' o no es válido: '{asesor_email}'")

    # Enviar al Dueño (Opcional - Copia de respaldo si es diferente al asesor)
    owner_email = tenant.get("owner_email")
    if owner_email and "@" in owner_email and owner_email != asesor_email:
        send_email_smtp(
            to_email=owner_email, 
            subject=f"Respaldo Cita: {cliente_nombre}", 
            body_html=mensaje_asesor
        )

async def send_whatsapp(to: str, template: str, params: list, token: str, phone_id: str):
    url = f"https://graph.facebook.com/v24.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    to = to.replace("+", "").replace(" ", "")
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "es"}, 
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
        msg.attach(MIMEText(body_html, "html"))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print(f"📧 Correo enviado exitosamente a {to_email}")
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")