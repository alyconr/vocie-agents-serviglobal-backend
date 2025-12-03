from datetime import datetime
import pytz
from app.core.google_auth import get_service
from app.config import TENANTS

# Definimos la zona horaria de Colombia
BOGOTA_TZ = pytz.timezone('America/Bogota')

async def log_lead_bg(agent_id: str, data: dict):
    """
    Registra el lead en Google Sheets en segundo plano.
    Convierte la hora del servidor a Hora Bogotá.
    """
    print(f"📝 Iniciando registro de Lead para {agent_id}...")
    
    tenant = TENANTS.get(agent_id)
    if not tenant:
        print(f"❌ Error CRM: Tenant {agent_id} no encontrado en la configuración.")
        return

    try:
        # 1. Conectar con Google Sheets
        service = get_service('sheets', 'v4', tenant['creds_file'])
        
        # 2. Obtener fecha y hora exacta en Bogotá
        now_bogota = datetime.now(BOGOTA_TZ)
        fecha = now_bogota.strftime("%Y-%m-%d")
        hora = now_bogota.strftime("%I:%M %p") # Formato amigable: 02:30 PM
        
        # 3. Determinar Clasificación y Estado
        # Si existe 'fecha_hora_inicio', significa que se logró agendar.
        if data.get('fecha_hora_inicio'):
            clasificacion = "Caliente"
            estado = "Agendado"
        else:
            clasificacion = "Tibio"
            estado = "Interesado / Pendiente"

        # 4. Preparar la fila de datos
        # Orden de columnas en tu Sheet: [Fecha, Hora, Nombre, Telefono, Interes, Clasificacion, Estado]
        row_values = [
            fecha,
            hora,
            data.get('cliente_nombre', 'Desconocido'),
            data.get('cliente_telefono', 'No provisto'),
            data.get('propiedad_interes', 'General'),
            clasificacion,
            estado
        ]

        body = {'values': [row_values]}
        
        # 5. Insertar la fila al final (Append)
        service.spreadsheets().values().append(
            spreadsheetId=tenant['sheet_crm_id'],
            range="Leads!A:G", # IMPORTANTE: La pestaña debe llamarse 'Leads'
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        
        print(f"✅ Lead guardado exitosamente en CRM: {data.get('cliente_nombre')}")

    except Exception as e:
        print(f"❌ CRITICAL ERROR CRM: No se pudo guardar el lead.")
        print(f"Detalle del error: {e}")