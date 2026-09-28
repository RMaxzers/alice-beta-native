# Tareas y autonomía graduada

Alice distingue entre **pensar** (responder), **organizar** (leer y ordenar tus tareas), **preparar** (sugerir o dejar un borrador) y **hacer** (cambiar algo). Quién decide lo que se hace es el servidor, con reglas fijas. El modelo solo puede proponer.

Código: `services/policies/autonomy.py` (política), `services/tasks/store.py` (tareas, acciones, deshacer), `services/workers/orchestrator.py` (`_automation`, `_log_followup`). Pruebas: `tests/unit/test_tasks.py`, `tests/security/test_tasks_api.py`.

## Niveles

| Nivel | Qué hay hoy | Conducta implementada |
|---|---|---|
| C0 lectura | Organizar el día, listar tareas, RAG, SQL, logs, observabilidad | Se ejecuta sin esperar y no cambia nada |
| C1 cambio local reversible | Crear, editar, completar, mover, reordenar y deshacer tareas dentro de Alice | Se ejecuta solo si la orden viene de ti: el mensaje que escribes o un clic en la UI. Queda registrado quién lo pidió, desde dónde, y el estado antes y después. Se puede deshacer y se evitan duplicados |
| C2 efecto externo | *Ninguna herramienta C2 implementada todavía* (enviar, programar, archivos fuera de Alice) | La política lo marca `awaiting_authorization`. No existe ejecutor, así que nunca corre. La salida a la nube sigue controlada por `EgressGate` (ticket ligado a usuario, destino, hash del contenido, coste y vencimiento) |
| C3 alto impacto | Cualquier herramienta desconocida o de alto impacto | `needs_review`: no se automatiza |

Reglas duras:

- El nivel de cada herramienta está fijado en `TOOL_LEVEL`. Una herramienta que no esté en la lista es C3.
- El modelo puede proponer un nivel más alto, nunca uno más bajo.
- La intención de una tarea se extrae **solo del mensaje actual del usuario**. Nunca del historial, de los documentos, de los logs ni de la salida del modelo. Una frase como «crea una tarea…» dentro de un log es un dato y no ejecuta nada (lo comprueba `test_instructions_inside_sources_never_execute`).
- Las fechas habituales se resuelven con reglas: «hoy», «mañana», «pasado mañana», un día de la semana, «en N días», una fecha ISO y «a las H[:MM] [am/pm]». Para otras formas, como «3 de octubre», el modelo local propone una fecha y el servidor la valida. Solo se acepta si está entre hoy y hoy + 10 años. Aun así, una fecha propuesta por el modelo deja la tarea como **borrador** hasta que la confirmes, y lo mismo pasa si la fecha no se entiende.
- Una orden ambigua no cambia nada: por ejemplo, «marca como hecha la tarea llamar» cuando hay dos tareas que coinciden. Alice pregunta cuál.
- Las tareas recurrentes y los avisos no están implementados, y Alice lo dice en lugar de fingir que lo hace.

## Estados de una acción (`actions`)

`proposed` · `awaiting_authorization` · `running` · `done` · `failed` · `needs_review` · `cancelled`

- Ejecución: primero se confirma la fila `running`. Después el cambio, sus eventos y el paso a `done` se escriben en **una sola transacción**. Si falla a mitad, el cambio se revierte y la acción queda `failed` con su error.
- Tras una caída, `reconcile()` se ejecuta al arrancar. Una acción `running` que tiene eventos aplicados pasa a `done`. Si no tiene ninguno, pasa a `failed` con el motivo «verificado: sin cambios». Nunca se reintenta sola.
- Idempotencia: `POST /api/tasks` acepta la cabecera `Idempotency-Key`. Si llega una clave ya conocida, se devuelve el resultado anterior. Si ese intento había fallado, se responde 409 y no se reintenta en silencio.
- Duplicados: una tarea abierta con el mismo título normalizado y la misma fecha no se crea dos veces. La comprobación se hace bajo el mismo bloqueo de escritura que la inserción, así que ocho creaciones simultáneas producen una sola tarea. Si el duplicado se detecta cuando la acción ya estaba registrada, esa acción queda `cancelled` con su motivo.
- Verificación: el chat vuelve a leer la tarea de la base de datos y comprueba los campos esperados antes de decir «hecho».

## Deshacer (`task_events`)

Cada cambio guarda el estado antes y después. `POST /api/events/{id}/undo` revierte todos los eventos de esa acción; en un reordenamiento, todas las tareas a la vez. Se niega con 409 si la tarea cambió después, para no pisar ese cambio. Deshacer una creación **cancela** la tarea en vez de borrarla, así se conserva la auditoría.

## De evidencia a seguimiento

En el análisis de logs, el error más frecuente genera una tarea de seguimiento con fuente `{kind: "log", document_id, line}`:

- Si tu mensaje lo pide («…y crea un seguimiento para mañana»), se crea con nivel C1 y origen `evidence`.
- Si no, llega al chat como **sugerencia**: no se crea nada hasta que pulsas «Crear seguimiento».

El servidor resuelve cada fuente contra tus propios datos. El título del documento y el extracto de la línea se leen de la base de datos, nunca del cliente. Una línea inexistente, un documento ajeno o un campo extra dan 422. La privacidad de la tarea es la más estricta entre la que se pide y la de sus fuentes. La descripción aclara que el hallazgo **no está corregido**.

## API

Todas las rutas exigen sesión. Las que modifican datos exigen además CSRF. Todas están aisladas por usuario: una tarea ajena responde 404.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/today` | Vencidas, hoy, próximos 7 días, sin fecha, borradores, recomendaciones con su razón y acciones recientes |
| GET | `/api/tasks?status=&limit=&offset=` | Lista paginada (límite máximo de 200) |
| POST | `/api/tasks` | Crear. Cabecera opcional `Idempotency-Key` |
| PATCH | `/api/tasks/{id}` | Editar o completar, con `version` obligatoria (409 si hay conflicto) |
| POST | `/api/tasks/reorder` | Nuevo orden de un subconjunto; el resto de las tareas conserva su lugar |
| GET | `/api/tasks/{id}/events` | Historial de la tarea |
| POST | `/api/events/{id}/undo` | Deshacer |
| GET | `/api/actions` | Registro de acciones con su estado real |

Eventos nuevos del chat: `action` (qué se hizo, verificado) y `suggestion` (qué se propone, sin ejecutar).

## Recomendaciones de «Hoy»

Son deterministas y cada una lleva su razón, en este orden: vencidas (por antigüedad), las de hoy (con hora), las que son requisito de otra tarea abierta, las de prioridad urgente o alta, y las que vencen en ≤3 días. Son sugerencias: no cambian nada.

## Migración

La migración 3 de `apps/api/db.py` solo **añade** tres tablas nuevas (`tasks`, `actions`, `task_events`), con restricciones `CHECK` sobre estados y niveles, y no toca ninguna tabla existente. Se aplica sola al arrancar la API (o con `uv run python -m apps.api.migrate`). Para volver atrás, restaura el backup previo con `Restore-Alice.ps1`. Una versión anterior de Alice ignora estas tablas, aunque vería `user_version=3`.
