# # Etapa 2 · contrato backend v2 · 2026-10-05

Base confirmada limpia: `180c0cb`. Rama Codex `feat/alice-agenda-backend`, checkout `C:/Users/cuent/alice-agenda-codex`. Contrato publicado antes del código. No cambia autenticación: cookie + `X-CSRF-Token` en TODAS las mutaciones, 401 sin sesión, 403 CSRF/origen, 404 ID ajeno. Errores de dominio `{ "detail": "explicación" }`; validación Pydantic 422 con `detail` array. 409 versión obsoleta/conflicto de estado; 503 Push sin configurar.

## Tareas y series (R-13, R-14)

`POST /api/tasks` conserva su respuesta `{task,action,event_id,duplicate}` y admite:
```json
{"title":"Revisar agenda","due_date":"2026-10-05","due_time":"09:00","recurrence":{"freq":"weekly","interval":1,"weekdays":[1,3,5],"until":"2026-12-31"}}
```
`recurrence` admite `daily`, `weekly`, `monthly`; `interval` solo 1 en esta etapa. ISO weekdays 1=lunes…7=domingo, sin duplicados, obligatorio en weekly y prohibido para otras frecuencias. `until` fecha local inclusiva, opcional/null, nunca anterior al inicio. Requiere due_date válida y status open; weekly requiere que el inicio corresponda a un día seleccionado. Mensual conserva el día ancla: 31 enero → 28/29 febrero → 31 marzo. Hora local estable America/Santiago; sin due_time hay agenda pero no aviso. En hora repetida se usa la primera (fold=0); en hora inexistente se desplaza por el salto DST (00:30 → 01:30).

Task añade `series_id: string|null`, `recurrence: object|null`, `next_due:{due_date,due_time}|null`. Cada Task es una ocurrencia con ID propio. Serie en tabla separada; UNIQUE(series_id, occurrence_date). Worker materializa vencidas y próximas 7 jornadas, por lotes limitados recuperables. No exige completar ayer para crear hoy. Puede tardar varios ticks en recuperar años de inactividad.

`PATCH /api/tasks/{id}` requiere `version` como antes. `{version:1,status:"done"}` completa SOLO esa ocurrencia y devuelve `{task,action,event_id,next:Task|null}`. La siguiente queda disponible en la misma transacción. `cancelled` omite esa ocurrencia, no cancela la serie. Ediciones de título/fecha/hora afectan solo esa ocurrencia. Se puede añadir recurrence mediante PATCH a una tarea no recurrente abierta. Reglas existentes son inmutables: cambiar/quitar recurrence devuelve 409; para finalizar usar la ruta siguiente y crear una serie nueva. Esto evita reinterpretar el historial.

`GET /api/tasks/{id}` recupera una ocurrencia, incluso completada. `GET /api/series/{id}` → `{series_id,recurrence,active,timezone,start_date}`. `POST /api/series/{id}/stop` → `{ok:true}` detiene materialización y cancela ocurrencias abiertas futuras (conserva vencidas e historial). Idempotente. `GET /api/tasks?status=done,cancelled` y `/api/tasks/{id}/events` conservan historial.

**R-14 / undo:** deshacer completar restaura esa ocurrencia; NO borra la siguiente porque pertenece al calendario de la serie, que avanza independientemente. No mostrar «deshacer programación siguiente». Undo de alta recurrente se rechaza 409: usar detener serie. Undo no revierte efectos externos ya entregados.

## Avisos y posponer (R-15)

`GET /api/reminders` conserva `{enabled,unread,items}`; cada aviso añade `snoozed_until`, `generation`, `task_id`, `title`. `GET /api/reminders/{id}` recupera aviso propio con `history` de aplazamientos/disparos/lectura, aun si la tarea terminó. `POST /api/reminders/{id}/ack` conserva `{ok:true}`.

`POST /api/reminders/42/snooze`:
```json
{"minutes":10}
```
o `{"minutes":60}` o `{"until":"2026-10-06T11:00:00-03:00"}` (exactamente una opción, zona obligatoria y futuro). Respuesta 200: aviso con el mismo reminder_id, `snoozed_until` UTC, `generation` incrementada. Ejemplo parcial: `{"reminder_id":42,"task_id":"abc","snoozed_until":"2026-10-06T14:00:00+00:00","generation":1,"history":[...]}`. Mientras está pospuesto no cuenta como unread. 404 ajeno/inexistente; 409 completado, cancelado o reprogramado; 422 combinación inválida/fecha pasada. Repetir la misma fecha absoluta antes de disparar es idempotente. Los presets relativos representan una nueva intención al repetir.

Un aviso lógico por ocurrencia (se conservan los avisos legados); posponer crea generaciones del mismo aviso y registra historial. Un reinicio no crea otra generación. Reprogramar una tarea ya avisada no crea otro aviso automáticamente: usar posponer para pedirlo explícitamente.

## Resumen determinista (R-16)

`GET /api/summary/daily?date=2026-10-05` (fecha opcional, default hoy en Santiago):
```json
{"date":"2026-10-05","timezone":"America/Santiago","counts":{"pending":3,"overdue":1,"upcoming":2},"next":null,"overdue":[],"today":[],"upcoming":[],"generated_at":"2026-10-05T12:00:00+00:00"}
```
Ejemplo de estructura, los números reales coinciden con datos. Listas limitadas a 5; counts completos. `pending` = activas para esa fecha o sin fecha, excluye vencidas y próximas; overdue incluye hora ya pasada cuando date=hoy, para otras fechas compara fechas. Próximas = 7 días posteriores. `next` primera vencida, luego hoy/sin fecha, luego próxima; orden fecha/hora/prioridad. Sin modelo ni dependencia de LM Studio. Esta etapa entrega resumen consultable, no envío programado del resumen.

## Push (R-17, R-18)

Opt-in por dispositivo desde gesto del usuario. `GET /api/push/config` → `{enabled,vapid_public_key,reason}`. Disabled por defecto, 503 al intentar suscribirse sin claves. `POST /api/push/subscriptions` (201):
```json
{"endpoint":"https://fcm.googleapis.com/fcm/send/opaque","expirationTime":null,"keys":{"p256dh":"BASE64URL_P256_PUBLIC_KEY","auth":"BASE64URL_16_BYTES"},"device_label":"Laptop"}
```
Respuesta `{subscription_id}`. Alta idempotente por endpoint propio; 409 si pertenece a otro usuario (no reasigna). `GET /api/push/subscriptions` → `{items:[{subscription_id,endpoint,device_label,created_at,expirationTime}]}` sin claves. `DELETE /api/push/subscriptions` body `{endpoint}` → `{ok:true}`, 404 ajeno. expirationTime se limpia como Unix ms solo si el valor es posterior a 2000-01-01; valores de reloj DOMHighRes relativos o ambiguos se guardan como null y dependen de 404/410. También se limpian respuestas 404/410 del proveedor. Máximo 20 dispositivos por usuario. No hay `/api/push/test` en v2; probar creando un aviso cercano.

Payload: `{title:"Alice",body:"Tienes un recordatorio pendiente",tag:"alice-reminder-42",url:"/#today?task=abc&reminder=42",task_id:"abc",reminder_id:42,generation:0}`. Texto genérico para privacidad en pantalla bloqueada. El SW muestra notificación y abre url; NO modifica datos ni guarda CSRF. Al abrir, la web autentica/recupera sesión y carga GET reminder; acciones usan CSRF normal. Tag estable permite reemplazo; transporte reintenta fallos transitorios y entrega incierta tras caída, por lo que el navegador podría mostrar de nuevo el mismo tag. No se promete exactly-once externo.

Backend habilita `/sw.js`, `/manifest.webmanifest` por Tailscale, MIME correcto y no-cache. Claude es único escritor de esos archivos y `apps/web/**`. HTTPS existente `https://eva01.tail3f8e85.ts.net:8444/`; LAN HTTP no sirve Push. Proveedores permitidos FCM/Google, Mozilla y Apple; Internet saliente requerido aunque el origen sea privado. Backend puede notificar con navegador/página cerrados; entrega con navegador completamente terminado depende de SO/navegador. iOS/iPadOS requiere app en pantalla de inicio y permiso mediante gesto. Documentación detallada en handoff.

R-19: `GET /api/settings` añadirá `voice:{enabled,stt,tts}` (stt/tts booleanos de disponibilidad reportada por backend).

## Reserva de archivos / coordinación

Codex reserva `apps/api/**`, `packages/schemas/models.py`, `services/tasks/**`, nuevos tests Python, `pyproject.toml`, `uv.lock`, documentación nueva `docs/AGENDA-*`, script nuevo de claves. Claude conserva exclusivamente `apps/web/**`. No se edita UBUNTU-HOME ni compose compartidos: los pasos de configuración se entregan en documento nuevo. Sin desplegar ni modificar datos de VM.


