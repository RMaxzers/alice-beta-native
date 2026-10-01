# API_CONTRACT · alice-next-20260928-01 · v1

Estado: v1 aceptado por Claude el 2026-09-28. Codex implementó R-01–R-06; commits y validación final quedan registrados en `CODEX_STATUS.md`. Base: `bc37fd445f44b3f4ac9b5a68e6c7692351cd2eb4`. Este documento y su copia en `alice-coordination/API_CONTRACT.md` tienen un único escritor: Codex.

## Autenticación existente y extensiones aditivas

`POST /api/login` recibe `{username,password}`; emite cookie HttpOnly `alice_session` y `{user,csrf,expires_at}`. `GET /api/session` recupera esos campos. Sesión de 12 horas, revocable con `POST /api/logout`; todas las mutaciones requieren cookie y `X-CSRF-Token`. HTTP 401 significa sesión ausente/caducada; 403 CSRF/origen inválido. La CLI usa exactamente estas rutas, valida TLS y guarda su sesión protegida localmente. Perfiles son configuración del cliente: `local` apunta al loopback configurado; `casa` requiere una URL HTTPS privada proporcionada por el usuario (no hay dirección supuesta).

`GET /api/identity` (nuevo, autenticado): `{backend_id, executor_name, api_contract:"1", file_action:{enabled,root_label}}`. La identidad persiste en la SQLite del backend y el nombre visible se configura en el servidor. La carpeta autorizada nunca se elige mediante ruta enviada por el cliente.

## Conversaciones nuevas

Todas las consultas filtran por el usuario autenticado. Propiedad, roles y clasificación efectiva se resuelven en el servidor. Un ID ajeno produce 404.

- `GET /api/conversations?limit=50&offset=0` → lista de `{conversation_id,title,privacy,created_at,updated_at}`.
- `POST /api/conversations` con `{title?:"Nueva conversación",privacy?:"PRIVATE"}` → HTTP 201 y el mismo objeto.
- `GET /api/conversations/{id}` → objeto anterior más `messages`: `{message_id,role,content,privacy,created_at,status,client_request_id,sources,operation_ids}`. `role` procede del servidor; `status` distingue `complete`, `interrupted`, `failed`, `awaiting_authorization` y `running`; `sources` y `operation_ids` permiten rehidratar los elementos asociados a cada respuesta.
- `POST /api/chat` conserva `message`, `privacy`, `document_ids`, `force_route`, `authorization_ticket`; añade `conversation_id` y `client_request_id` (UUID o token opaco de 8–100 caracteres). Sin ID de conversación crea una nueva. El cliente envía solamente el turno actual: el servidor carga el historial. `history` legado deja de conceder roles o etiquetas: el contenido legado se trata como datos importados privados, nunca como respuestas auténticas del backend.

La privacidad de una conversación solo puede subir: PUBLIC < INTERNAL < PRIVATE. Incluye fuentes y memoria recuperadas, incluso si el siguiente cliente intenta enviar PUBLIC. Un reintento con el mismo `client_request_id` y distinto contenido devuelve 409; un turno ya finalizado reproduce sus eventos almacenados sin repetir acciones. Un turno todavía en ejecución devuelve 409; tras caída queda `interrupted` y exige revisar sus operaciones antes de intentar otra solicitud. No se promete exactamente una vez.

## Streaming NDJSON

Se conservan eventos reales `route`, `tool`, `sources`, `token`, `action`, `suggestion`, `authorization_required`, `error`, `done`. El contrato añade `conversation` al inicio: `{type:"conversation",conversation_id,client_request_id,privacy}`. `done` incorpora `conversation_id`, `client_request_id`, `privacy` y `status`. Los clientes ignoran tipos/campos desconocidos. Cada línea es un objeto JSON UTF-8; no es SSE. HTTP puede ser 200 aunque un evento posterior `error` marque un fallo.

Cancelar/Ctrl+C desconecta el cliente y detiene el consumo de la generación; no revierte acciones. El estado persistido se consulta antes de reintentar. La aprobación cloud vuelve a enviar el turno con un `client_request_id` **nuevo**, porque el ticket altera el payload y la clave anterior ya está consumida. Turnos `failed` y `awaiting_authorization` quedan persistidos sin evento `done`; el último evento indica el resultado y el reintento intencional usa clave nueva. Una aprobación cloud sigue vinculada al ticket, usuario, payload, proveedor/modelo, coste y expiración. PUBLIC puede salir con cloud habilitado; INTERNAL/PRIVATE requieren autorización explícita para ese payload. `local_only` bloquea siempre. Un ticket no rebaja la privacidad.

## Acciones de archivo (nuevas)

`POST /api/file-actions` recibe `{conversation_id,client_request_id,filename,content,privacy?}`. Es una petición explícita del usuario autenticado. Herramienta `file.create_text`, extensión `.md`/`.txt`, creación exclusiva en la carpeta configurada. Se comprueba lectura posterior y SHA-256. Sin carpeta autorizada: 403. Rutas inválidas: 422. Archivo existente / clave reutilizada con otra solicitud: 409.

`GET /api/file-actions?conversation_id=&limit=100` lista las operaciones del usuario; el filtro de conversación es opcional y el servidor limita `limit` al rango 1–200. `GET /api/file-actions/{operation_id}` recupera una operación propia. Objeto público: `{operation_id,owner,conversation_id,tool,destination,executor_name,status,privacy,verification,error,created_at,updated_at}`. La evidencia contiene el hash, bytes y resultado de verificación, sin el contenido. Estados: `running`, `done`, `failed`, `needs_review`. Éxito solo con verificación; `needs_review` indica resultado desconocido o evidencia insuficiente y no autoriza repetir a ciegas. El servidor vincula idempotencia a usuario + conversación + petición + contenido. Los eventos del chat devuelven `action` con el objeto también en `file_action`, para la tarjeta UI.

Cada mensaje asistente persistido expone `sources: Source[]` y `operation_ids: string[]` para rehidratar fuentes y operaciones después de reabrir una conversación. No se repite la acción al recargar.

En chat, «Guarda este resumen como prueba-alice.md en mi carpeta de Alice» guarda la última respuesta persistida de esa conversación. Una forma con contenido explícito podrá documentarse junto a la implementación. Solo la petición actual del usuario concede ese alcance: documentos, recuerdos, páginas y texto emitido por el modelo no pueden ejecutarlo. La respuesta incluye operación, destino y nombre del equipo.

## Compatibilidad y fixtures

Las rutas de tareas (`GET /api/tasks`, `/api/today`, mutaciones y `/api/actions`) permanecen disponibles. El frontend no debe reconstruir roles desde localStorage como historial confiable: puede conservarlo como archivo local o enviar datos importados marcados privados.

Fixtures sintéticos bajo `tests/fixtures/contracts/` (solo desarrollo/pruebas), sin rutas de simulación habilitadas en producción. Ejemplos y pruebas se completan con la implementación. Cualquier ajuste del objeto de acciones será aditivo o se registrará como revisión antes de integrar. No se ha validado acceso Tailscale ni stack combinado.
