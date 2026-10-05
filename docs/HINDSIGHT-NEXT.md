# Propuesta de etapa independiente: activar Hindsight local

**No forma parte de CORE-10.** El perfil Ubuntu sigue teniendo `MEMORY_ENABLED=false`; esta nota deja los pasos y decisiones para un cambio posterior y medido.

## Compatibilidad con el adaptador

El cliente existente [services/memory/hindsight.py](../services/memory/hindsight.py) ya llama el contrato HTTP de Hindsight en `HINDSIGHT_URL`, en la familia `/v1/default/banks/{bank_id}/…` (health, recall, retain, list y forget). Conserva `bank_id(username) -> alice-{username}`; cada usuario de Alice tiene un banco Hindsight. Las operaciones que recuerdan se ejecutan en segundo plano, recall tiene un límite de 1,5 s y el chat sigue respondiendo si Hindsight está apagado. La tabla SQLite `memory_prefs` ya permite opt-in por usuario.

Antes de activar, fijar una versión inmutable de la imagen Hindsight y comprobar en staging el OpenAPI de esa versión contra esas rutas/JSON. `HINDSIGHT_URL=http://127.0.0.1:8888` coincide con el adaptador actual si API y Hindsight comparten el host de red de Compose; `MEMORY_ENABLED=true` permite la integración, mientras los usuarios la mantienen apagada hasta habilitarla individualmente. No cambiar esos dos valores ni arrancar el servicio como parte de esta entrega. La configuración del contenedor de Hindsight debe elegir PostgreSQL 14+ con pgvector, endpoint LLM, volumen persistente, healthcheck y límite de recursos después de la prueba.

El túnel de LM Studio de la VM ya termina en `127.0.0.1:1234` y es OpenAI-compatible. El adaptador de Alice no usa directamente el modelo. Hindsight actual admite proveedor OpenAI-compatible/LM Studio; hay que probar extracción/recall con un modelo en contexto corto, medir RAM/latencia y verificar que llamadas a embeddings también usan el endpoint local o elegir explícitamente un proveedor local soportado. No exponer el puerto 8888 fuera del loopback/Compose. Hindsight self-hosted requiere conexión al proveedor LLM que se configure; con LM Studio local, el contenido se queda en VM+túnel Windows.

## Recursos para el host actual

La documentación actual de Hindsight informa 4 GB como mínimo para la API y 8 GB recomendados en producción. La VM existente tiene 4 GB en total y fija límites de hasta 1,5 GB Alice, 768 MB Qdrant, 384 MB Homepage y 384 MB Pi-hole, antes de PostgreSQL, Hindsight y Ubuntu. La documentación no da un límite máximo útil para una prueba local; la demanda depende de PostgreSQL, modelo/endpoint y carga. Con estas cifras no recomiendo arrancarlo en paralelo en el perfil actual: el mínimo publicado de Hindsight por sí solo equivale a toda la RAM de la VM.

La opción concreta es hacer primero una prueba desechable (sin recuerdos personales) con al menos 8 GB asignados a Ubuntu, manteniendo el modelo en Windows; con la VM actual de 4 GB, no activar Hindsight. En 8 GB, poner un límite explícito tras medir, revisar OOM/RSS y latencias bajo Alice+Qdrant+PostgreSQL y dejar memoria al kernel/caché. Si Windows se queda sin memoria libre al asignar 8 GB, posponer la etapa: los 4 GB fueron elegidos expresamente para conservar recursos de Windows/LM Studio. No descargar modelos dentro del disco Ubuntu de 50 GB.

## Preferencias confirmadas que conviene guardar

Guardar solo datos que ayuden a Alice a personalizar respuestas: idioma español; zona `America/Santiago`; preferencias explícitas de redacción y formato; proyectos activos que el usuario identifique; objetivos y decisiones estables que autorice recordar. Etiquetar cada hecho por usuario y procedencia; mostrarlo, editarlo y olvidarlo desde la interfaz. Usar privacidad PRIVATE como mínimo para recuerdos de conversación; no guardar contraseñas, secretos de acceso, tokens, contenido de archivos/adjuntos ni inferencias sensibles. No convertir cada chat en memoria de largo plazo: permitir opt-in por usuario y recordar lo necesario según la política explícita de retención.

Estas son reglas propuestas, no afirmaciones de consentimiento para guardar memorias personales. En la etapa Hindsight pediría la confirmación explícita del usuario antes de pasar sus conversaciones nuevas al banco. No importar memorias de Windows automáticamente.

## Procedimiento futuro

1. Hacer backup SQLite + PostgreSQL vacío y verificar que rollback no afecta la agenda.
2. Añadir Hindsight pinned, PostgreSQL+pgvector y límites/healthcheck en un compose específico; binding a loopback y puerto 8888.
3. Verificar adaptador contractualmente, sandbox de usuarios (`alice-eva2`, segundo usuario sintético), timeout/down, retain async, recall privado, lista/forget, restart y restore.
4. Medir pico RSS/CPU/latencia con la VM asignada; solo entonces integrar el servicio al compose Ubuntu y permitir el opt-in en UI.

Fuentes del proveedor consultadas el 2026-10-05: [requisitos self-hosted: 4 GB mínimo, 8 GB recomendado](https://hindsight.vectorize.io/faq), [instalación, PostgreSQL y proveedores locales](https://hindsight.vectorize.io/developer/installation), [configuración actual](https://hindsight.vectorize.io/developer/configuration).
