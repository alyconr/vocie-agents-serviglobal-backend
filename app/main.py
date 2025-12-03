from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from app.services import inventory, calendar, notifications, crm

app = FastAPI()

class RetellPayload(BaseModel):
    agent_id: str
    name: str
    args: dict

@app.post("/webhook")
async def retell_webhook(payload: RetellPayload, bg_tasks: BackgroundTasks):
    print(f"🔔 Call: {payload.name} | Agent: {payload.agent_id}")
    
    # 1. BUSCAR INVENTARIO
    if payload.name == "search_inventory":
        return {"result": await inventory.search_inventory(payload.agent_id, payload.args)}

    # 2. VERIFICAR DISPONIBILIDAD (Solo consulta)
    if payload.name == "check_calendar_availability":
        # Si no mandan fecha, asumimos 'hoy' o devolvemos error, 
        # pero Retell suele mandar la fecha.
        fecha = payload.args.get('fecha')
        if not fecha:
            return {"result": "¿Para qué fecha te gustaría revisar la disponibilidad?"}
            
        return {"result": await calendar.check_availability(payload.agent_id, fecha)}

    # 3. AGENDAR CITA (Transaccional)
    if payload.name == "book_appointment_and_notify":
        # Validación de seguridad
        if not payload.args.get('cliente_telefono'):
            return {"result": "Necesito confirmar tu número de WhatsApp para poder agendar."}
            
        # INTENTO DE AGENDAMIENTO
        booking_success = await calendar.create_event_and_lock(payload.agent_id, payload.args)
        
        if booking_success:
            # --- ÉXITO ---
            # Disparamos tareas en segundo plano
            bg_tasks.add_task(notifications.notify_all_parties, payload.agent_id, payload.args)
            bg_tasks.add_task(crm.log_lead_bg, payload.agent_id, payload.args)
            
            return {"result": "Listo, cita agendada correctamente. Ya te envié la confirmación por WhatsApp."}
        
        else:
            # --- FALLO POR CONFLICTO ---
            # 1. Extraemos la fecha del intento (viene como '2024-12-05T10:00:00')
            full_date = payload.args.get('fecha_hora_inicio', '')
            try:
                # Tomamos solo la parte YYYY-MM-DD
                date_only = full_date.split('T')[0]
                
                # 2. Consultamos huecos reales disponibles para ese día
                alternativas = await calendar.check_availability(payload.agent_id, date_only)
                
                # 3. Construimos la respuesta natural
                # Ej: "Ese horario ya está ocupado. Tengo disponibilidad a las 09:00 AM..."
                return {"result": f"Justo ese horario ya está ocupado. {alternativas} ¿Te sirve alguna de estas?"}
                
            except Exception as e:
                print(f"Error generando alternativas: {e}")
                return {"result": "Ese horario ya está ocupado. ¿Te queda bien otra hora?"}

    return {"result": "Función no reconocida por el sistema."}