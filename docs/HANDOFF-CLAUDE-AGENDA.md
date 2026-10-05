# Handoff · Alice Agenda v2 · Codex → Claude

## Estado y checkout

Contrato v2 publicado y aceptado por Claude antes de implementar en `C:/Users/cuent/alice-coordination/API_CONTRACT.md`; copia utilizable por la UI en `docs/AGENDA-API.md`. R-13..R-19 están cubiertos. `CLAUDE_STATUS.md` registra UI-10 como `076b8e5`, conserva `apps/web/**`, service worker y manifest para Claude. `GET /api/tasks/{id}` devuelve el Task plano. API implementada en `apps/api/routes_agenda.py`; `POST /api/tasks`/`PATCH` existentes llevan recurrencia aditiva.

Mi checkout aislado es `C:/Users/cuent/alice-agenda-codex`, rama `feat/alice-agenda-backend`, base `180c0cb`. No se cambió la VM ni la instalación/checkout de referencia.

## Implementación

- SQLite pasa de user_version 7 a 8, aditivo. Tablas `task_series`, eventos de aviso, suscripciones y outbox; columnas series/generación añadidas. Las pruebas insertan fixtures v7 con tareas/eventos/avisos y verifican que permanecen byte por byte en sus columnas existentes después de migrate dos veces.
- Series diarias, semanales ISO 1..7 y mensuales ancladas al día original, hasta inclusive. Worker materializa una ventana futura de 7 días y recupera pasado en lotes de 256/serie/tick; `UNIQUE(series_id, occurrence_date)` y cursor avanzado dentro de la misma transacción evitan duplicados después de restart/concurrencia. Completar/cancelar una ocurrencia conserva historial y no impide avanzar la agenda. Reglas ya creadas son inmutables: parar y crear serie nueva. TZ `America/Santiago`; gaps saltan el DST, folds usan fold=0.
- Snooze cambia generación del aviso lógico y registra todo el timeline; acknowledge/cambio de horario evita volverlo a mostrar. Mismo id reminder cruza reinicios, cada generación Push tiene entrega propia. Outbox leased, retry limitado, 404/410 limpian suscripciones. Payload genérico sin título/descripción privada, tag estable y URL con IDs para abrir Today.
- Push disabled sin optar por configurar VAPID. Suscripciones por owner+endpoint, límite 20, lectura sin llaves, baja con CSRF. URL provider valida HTTPS/hosts de FCM, Mozilla, APNs y Windows; redirects bloqueados y `trust_env=false`. Tipos estáticos SW/manifest se sirven no-cache y se permiten por proxy Tailscale.
- Resumen determinista directo de SQLite y disponibilidad de voz R-19 en `/api/settings`.

## Integración

1. Claude integra la UI desde `feat/alice-ui-reminders` en su checkout desde la base compartida; `apps/web/**` se conservó como reserva de Claude. No cherry-pickear este backend encima de un cambio divergente sin revisar contratos, porque Claude parte de `180c0cb`.
2. Integrar UI-10 `076b8e5` desde el checkout de Claude y compilar `public/sw.js`/`public/manifest.webmanifest`. Verificar `/sw.js` con `text/javascript`/`Cache-Control:no-cache`. El informe compartido dice que Tailscale está actualmente offline (`BackendState=NoState`) y `:8444` no responde; la URL HTTPS no está disponible para la prueba en vivo. La UI puede verificarse localmente por `http://127.0.0.1:8330` (localhost cuenta como contexto seguro en desktop), pero Push en móviles requiere reparar Tailscale Serve.
3. En entorno de integración, aplicar backup y correr automáticamente migration 8 al iniciar. Verificar login y token `X-CSRF-Token`, crear daily/weekly/monthly, completar una, undo, cortar/reiniciar API y comprobar cursor/notificación única, snooze 10m/60m/ISO y abrir URL del reminder.
4. Para Push: como `eva2`, ejecutar `python3 scripts/linux/generate-push-keys.py`; añadir sus cuatro líneas de variables al `.env` privado descritas en [AGENDA-PUSH](AGENDA-PUSH.md). Reiniciar. UI pide permiso solo en gesto explícito, POST subscription con CSRF, prueba creando tarea vencida a corto plazo, confirmar notificación y baja desde el dispositivo. Probar Chrome/Edge/Firefox y iOS instalado por separado.
5. No editar `.env`, almacenamiento o stack de producción como parte de integrar. Antes de aplicar a `~/alice-home-state/storage`, respaldo consistente incluyendo archivo PEM privado bajo resguardo.

## Limitaciones/decisiones

- Transporte a browser es `at-least-once`: reinicio en ventana de respuesta puede hacer que proveedor presente push repetido. Stable `tag` reemplaza la notificación visible cuando browser lo soporta; no se promete exactly-once en dispositivo. Retry agota tras 10 intentos; aviso interno sigue en SQLite.
- Push depende de conexión saliente a FCM/Mozilla/APNs/Windows, permiso OS y SO/browser. LAN HTTP no da Service Worker/Push. iOS/iPadOS 16.4+ requiere Home Screen web app y permiso; Safari tab normal no recibe Push.
- `expirationTime` nulo o ambiguo se limpia por HTTP 404/410; valores Unix en epoch ms se limpian al vencer. Suspender/apagar Windows, Focus o red móvil puede posponer/perder entrega.
- UI para terminar/crear otra serie; no hay editor que cambie una regla activa ni undo que borre la siguiente fecha ya programada.
- Se implementó consulta del resumen; aún no se programa el envío diario de un digest.
- No envié push a un proveedor real; el transporte se prueba con sender simulado. Push HTTPS en dispositivo queda pendiente mientras Tailscale Serve está desconectado; el checkout de Claude contiene UI-10, pero la integración/despliegue aún está pendiente. La VM tuvo un desfase de reloj de ~10 h 50 min tras reanudación, corregido con reinicio según estado de Claude: NTP estable es requisito operativo para vencimientos precisos.
- Hindsight es fase aparte: adaptador compatible; VM actual de 4 GB es insuficiente según mínimo proveedor de 4 GB para Hindsight API antes de PostgreSQL/otros contenedores. Plan en `docs/HINDSIGHT-NEXT.md`.

## Commits

Pendiente de SHA final tras commit de esta rama; registrar CORE-10, commit, migración 8 y evidencia en `alice-coordination/CODEX_STATUS.md`.

