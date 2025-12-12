from fastapi import FastAPI, BackgroundTasks, Request
from app.services import inventory, calendar, notifications, crm
from app.config import TENANTS

app = FastAPI()

@app.post("/webhook")
async def retell_webhook(request: Request, bg_tasks: BackgroundTasks):
    """
    Webhook Inteligente: Maneja payloads planos y estándar.
    Prioriza la detección de Agendamiento para evitar bucles en la conversación.
    """
    try:
        # 1. Leer el JSON
        payload = await request.json()
        print(f"📥 PAYLOAD: {payload}")

        # 2. Intentar extraer estructura estándar
        agent_id = payload.get('agent_id')
        func_name = payload.get('name') or payload.get('tool_name')
        args = payload.get('args')

        # --- MODO INFERENCIA (Si llega JSON plano) ---
        if not agent_id or not args:
            print("⚠️ Payload plano detectado. Iniciando inferencia...")
            
            # A. Los argumentos son todo el payload
            args = payload
            
            # B. Fallback de Agente
            try:
                agent_id = list(TENANTS.keys())[0]
            except:
                return {"result": "Error crítico: Sin agentes configurados."}

            # C. LÓGICA DE INFERENCIA MEJORADA (PRIORIDAD ESTRICTA)
            keys = args.keys()
            
            # CASO 1: AGENDAR (Prioridad Máxima)
            # Si hay teléfono O (nombre Y fecha_hora), es un cierre.
            if 'cliente_telefono' in keys or ('cliente_nombre' in keys and 'fecha_hora_inicio' in keys):
                func_name = "book_appointment_and_notify"
            
            # CASO 2: BUSCAR INVENTARIO
            elif 'ciudad' in keys or 'tipo_operacion' in keys or 'presupuesto_max' in keys:
                func_name = "search_inventory"
            
            # CASO 3: CONSULTAR DISPONIBILIDAD (Solo si no es lo anterior)
            elif 'fecha' in keys or 'asesor_calendar_id' in keys:
                func_name = "check_calendar_availability"
            
            else:
                print("⚠️ No pude inferir la función. Usando default seguro.")
                func_name = "check_calendar_availability" # Default seguro
            
            print(f"🕵️ Función inferida: {func_name}")

        # --- EJECUCIÓN ---
        print(f"🔔 Ejecutando: {func_name} | Agent: {agent_id}")

        if func_name == "search_inventory":
            return {"result": await inventory.search_inventory(agent_id, args)}

        if func_name == "check_calendar_availability":
            fecha = args.get('fecha')
            cal_id = args.get('asesor_calendar_id') or args.get('asesor_email')
            if not fecha: 
                # Si falta la fecha, devolvemos un mensaje natural
                return {"result": "¿Para qué fecha te gustaría revisar la disponibilidad?"}
            return {"result": await calendar.check_availability(agent_id, fecha, cal_id)}

        if func_name == "book_appointment_and_notify":
            # Validación suave: Si falta el teléfono, pedirlo
            if not args.get('cliente_telefono'):
                return {"result": "Necesito confirmar tu número de WhatsApp para finalizar el agendamiento."}
            
            # Intentar Agendar
            success = await calendar.create_event_and_lock(agent_id, args)
            
            if success:
                bg_tasks.add_task(notifications.notify_all_parties, agent_id, args)
                bg_tasks.add_task(crm.log_lead_bg, agent_id, args)
                return {"result": "¡Listo! Cita confirmada y agendada en el sistema."}
            else:
                # Manejo de conflicto
                try:
                    full_date = args.get('fecha_hora_inicio', '')
                    date_only = full_date.split('T')[0] if 'T' in full_date else full_date
                    cal_id = args.get('asesor_calendar_id')
                    alternativas = await calendar.check_availability(agent_id, date_only, cal_id)
                    return {"result": f"Justo ese horario ya se ocupó. {alternativas} ¿Te sirve alguna?"}
                except:
                    return {"result": "Ese horario ya está ocupado. ¿Te sirve otra hora?"}

        return {"result": f"Función {func_name} no encontrada."}

    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return {"result": "Tuve un error técnico, ¿podemos intentar de nuevo?"}