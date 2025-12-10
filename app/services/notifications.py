import httpx
from app.config import GLOBAL_WA_TOKEN, GLOBAL_WA_PHONE_ID, TENANTS

async def notify_all_parties(agent_id: str, data: dict):
    """
    Orquesta el envío de mensajes de WhatsApp.
    Maneja la lógica de tokens (Global vs Específico del Tenant) y evita crashes si faltan credenciales.
    """
    tenant = TENANTS.get(agent_id)
    if not tenant:
        print(f"⚠️ WhatsApp Error: Tenant {agent_id} no encontrado.")
        return

    # 1. Resolver Credenciales (Prioridad: Tenant > Global)
    token = tenant.get('whatsapp_token') or GLOBAL_WA_TOKEN
    phone_id = tenant.get('whatsapp_phone_id') or GLOBAL_WA_PHONE_ID

    # 2. Validación de Seguridad (ESTO FALTABA)
    if not token or not phone_id:
        print(f"⚠️ WhatsApp Alerta: No hay token/ID configurado para {agent_id}. Saltando notificación (El sistema no se detendrá).")
        return

    print(f"📨 Enviando WhatsApps para {agent_id}...")

    # 3. Notificar al Cliente
    if data.get('cliente_telefono'):
        await send_whatsapp(
            to=data['cliente_telefono'],
            template="cita_confirmada_cliente",
            params=[data.get('cliente_nombre', 'Cliente'), data.get('fecha_hora_inicio', '')],
            token=token,
            phone_id=phone_id
        )

    # 4. Notificar al Dueño/Asesor
    destinatario_interno = tenant.get('owner_phone')
    
    if destinatario_interno:
        await send_whatsapp(
            to=destinatario_interno,
            template="alerta_nuevo_lead_owner",
            params=[
                tenant['name'],
                data.get('cliente_nombre', 'Cliente'),
                data.get('cliente_telefono', 'Sin numero'),
                data.get('fecha_hora_inicio', '')
            ],
            token=token,
            phone_id=phone_id
        )

async def send_whatsapp(to: str, template: str, params: list, token: str, phone_id: str):
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Validación básica del número
    to = to.replace('+', '').replace(' ', '')
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "es"},
            "components": [{
                "type": "body", 
                "parameters": [{"type": "text", "text": str(p)} for p in params]
            }]
        }
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                print(f"✅ WhatsApp enviado a {to}")
            else:
                print(f"⚠️ Error Meta API ({response.status_code}): {response.text}")
        except Exception as e:
            print(f"❌ Error conexión WhatsApp: {e}")