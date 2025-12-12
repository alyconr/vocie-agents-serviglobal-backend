from fastapi import FastAPI, BackgroundTasks, Request
from app.services import inventory, calendar, notifications, crm

app = FastAPI()

@app.post("/webhook")
async def retell_webhook(request: Request, bg_tasks: BackgroundTasks):
    """
    Webhook flexible que acepta el payload crudo de Retell para evitar errores 422 de validación.
    """
    try:
        # 1. Leer el JSON crudo (Raw Body)
        payload = await request.json()
        print(f"📥 RAW PAYLOAD DE RETELL: {payload}") # ESTO TE SALVARÁ LA VIDA EN LOS LOGS

        # 2. Extracción segura de datos (Safe Parsing)
        # Usamos .get() para que no explote si falta un campo
        agent_id = payload.get('agent_id')
        func_name = payload.get('name') or payload.get('tool_name') # A veces cambia el nombre
        args = payload.get('args', {})
        
        # Fallback: Si agent_id no viene en la raíz, a veces viene dentro de 'call'
        if not agent_id and 'call' in payload:
            agent_id = payload['call'].get('agent_id')
        
        # Validación mínima
        if not agent_id or not func_name:
            print("⚠️ Alerta: Payload incompleto recibido.")
            # No devolvemos error 500 para no cortar la llamada, devolvemos algo genérico
            return {"result": "Error leyendo datos de la llamada."}

        print(f"🔔 Call: {func_name} | Agent: {agent_id}")

        # --- LÓGICA DE NEGOCIO ---

        # 1. BUSCAR INVENTARIO
        if func_name == "search_inventory":
            return {"result": await inventory.search_inventory(agent_id, args)}

        # 2. VERIFICAR DISPONIBILIDAD
        if func_name == "check_calendar_availability":
            fecha = args.get('fecha')
            # Extraemos el calendario específico si viene
            cal_id = args.get('asesor_calendar_id') or args.get('asesor_email')
            
            if not fecha:
                return {"result": "¿Para qué fecha te gustaría revisar?"}
                
            return {"result": await calendar.check_availability(agent_id, fecha, cal_id)}

        # 3. AGENDAR CITA
        if func_name == "book_appointment_and_notify":
            if not args.get('cliente_telefono'):
                return {"result": "Necesito confirmar tu número de WhatsApp."}
                
            # INTENTO DE AGENDAMIENTO
            success = await calendar.create_event_and_lock(agent_id, args)
            
            if success:
                bg_tasks.add_task(notifications.notify_all_parties, agent_id, args)
                bg_tasks.add_task(crm.log_lead_bg, agent_id, args)
                return {"result": "Listo, cita agendada y confirmación enviada."}
            else:
                # FALLO: Sugerir alternativas
                try:
                    full_date = args.get('fecha_hora_inicio', '')
                    # Manejo seguro del split por si viene vacío
                    date_only = full_date.split('T')[0] if 'T' in full_date else full_date
                    cal_id = args.get('asesor_calendar_id')
                    
                    alternativas = await calendar.check_availability(agent_id, date_only, cal_id)
                    return {"result": f"Ese horario ya está ocupado. {alternativas} ¿Alguna te sirve?"}
                except Exception as e:
                    print(f"Error generando alternativas: {e}")
                    return {"result": "Ese horario ya está ocupado. ¿Te sirve otra hora?"}

        # Si llegamos aquí, la función no se reconoció
        print(f"⚠️ Función desconocida: {func_name}")
        return {"result": f"Función {func_name} no implementada."}

    except Exception as e:
        print(f"❌ CRITICAL ERROR EN WEBHOOK: {str(e)}")
        # Devolver un mensaje amable al bot para que lo lea al usuario en vez de colgar
        return {"result": "Tuve un pequeño error técnico, ¿me puedes repetir?"}