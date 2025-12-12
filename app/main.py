from fastapi import FastAPI, BackgroundTasks, Request
from app.services import inventory, calendar, notifications, crm
from app.config import TENANTS

app = FastAPI()

@app.post("/webhook")
async def retell_webhook(request: Request, bg_tasks: BackgroundTasks):
    """
    Webhook Inteligente: Acepta payload estándar de Retell Y payload crudo (solo args).
    Autodetecta la función y el agente si faltan.
    """
    try:
        payload = await request.json()
        print(f"📥 PAYLOAD RECIBIDO: {payload}")

        # --- LÓGICA DE NORMALIZACIÓN (EL SECRETO) ---
        agent_id = payload.get('agent_id')
        func_name = payload.get('name') or payload.get('tool_name')
        args = payload.get('args')

        # CASO DE FALLO: Si llega el JSON "desnudo" (sin agent_id ni args)
        if not agent_id or not args:
            print("⚠️ Payload sin estructura estándar. Intentando inferir datos...")
            
            # 1. Asumimos que todo el payload son los argumentos
            args = payload
            
            # 2. Asignamos el primer agente configurado por defecto (Fallback)
            # Esto evita que falle, usando las credenciales del primer cliente que tengas
            try:
                agent_id = list(TENANTS.keys())[0]
                print(f"🔧 Usando agente por defecto: {agent_id}")
            except:
                return {"result": "Error crítico: No hay agentes configurados en el sistema."}

            # 3. Adivinamos la función según los campos
            if 'ciudad' in args and 'tipo_operacion' in args:
                func_name = "search_inventory"
            elif 'asesor_calendar_id' in args and 'cliente_nombre' in args:
                func_name = "book_appointment_and_notify"
            elif 'fecha' in args and 'asesor_calendar_id' in args:
                func_name = "check_calendar_availability"
            else:
                # Último intento de adivinanza
                if 'presupuesto_max' in args: func_name = "search_inventory"
                elif 'cliente_telefono' in args: func_name = "book_appointment_and_notify"
                elif 'fecha' in args: func_name = "check_calendar_availability"
            
            print(f"🕵️ Función inferida: {func_name}")

        # Validación final
        if not func_name:
            return {"result": "No pude entender qué función ejecutar con estos datos."}

        print(f"🔔 Ejecutando: {func_name} | Agent: {agent_id}")

        # --- DISPATCHER DE FUNCIONES ---

        if func_name == "search_inventory":
            return {"result": await inventory.search_inventory(agent_id, args)}

        if func_name == "check_calendar_availability":
            fecha = args.get('fecha')
            cal_id = args.get('asesor_calendar_id') or args.get('asesor_email')
            if not fecha: return {"result": "¿Para qué fecha?"}
            return {"result": await calendar.check_availability(agent_id, fecha, cal_id)}

        if func_name == "book_appointment_and_notify":
            if not args.get('cliente_telefono'):
                return {"result": "Necesito confirmar tu número de WhatsApp."}
            
            # Intento de Agendamiento
            success = await calendar.create_event_and_lock(agent_id, args)
            
            if success:
                bg_tasks.add_task(notifications.notify_all_parties, agent_id, args)
                bg_tasks.add_task(crm.log_lead_bg, agent_id, args)
                return {"result": "Listo, cita agendada y confirmación enviada."}
            else:
                try:
                    full_date = args.get('fecha_hora_inicio', '')
                    date_only = full_date.split('T')[0] if 'T' in full_date else full_date
                    cal_id = args.get('asesor_calendar_id')
                    alternativas = await calendar.check_availability(agent_id, date_only, cal_id)
                    return {"result": f"Ese horario ya está ocupado. {alternativas} ¿Alguna te sirve?"}
                except:
                    return {"result": "Ese horario ya está ocupado. ¿Te sirve otra hora?"}

        return {"result": f"Función {func_name} no encontrada."}

    except Exception as e:
        print(f"❌ ERROR FATAL: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"result": "Tuve un error técnico interno."}