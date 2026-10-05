# Agenda recurrente, resumen y notificaciones

Entra por la URL HTTPS privada de Tailscale. La ruta LAN `http://192.168.1.14:8000` y el loopback HTTP son útiles para agenda y recordatorios en la página; los navegadores no permiten Web Push en orígenes HTTP que no sean localhost. La URL privada configurada es `https://eva01.tail3f8e85.ts.net:8444/`.

## Activar Web Push

Push está desactivado hasta que el usuario active el opt-in. Alice guarda suscripciones en SQLite, una por dispositivo; cada solicitud se autentica con la cookie existente y las bajas requieren `X-CSRF-Token`. FCM/Google, Mozilla, Apple y Microsoft Edge reciben los avisos con protocolo Web Push cifrado y VAPID. Los proveedores conocen el endpoint de entrega, pero el payload solo incluye `Tienes un recordatorio pendiente` y una URL/IDs opacos: no se envían títulos ni descripciones privadas. Alice funciona como proveedor Web Push directo sin un SaaS ni cuenta de desarrollador Apple. Requiere tráfico saliente HTTPS desde Ubuntu a los servicios Push y que el proveedor de push no esté bloqueado en el dispositivo.

Como `eva2`, después de entrar al checkout actualizado, genera una pareja una sola vez. La opción `--state` indica el directorio de datos del host; `--container-path` indica la ruta que el proceso Alice verá en el contenedor:

```bash
cd ~/alice-home
python3 scripts/linux/generate-push-keys.py --state ~/alice-home-state/storage --container-path /app/storage/secrets/webpush-vapid.pem
```

El script crea `~/alice-home-state/storage/secrets/webpush-vapid.pem` con modo 600, preserva una clave existente y muestra la configuración con la ruta dentro del contenedor, además de una nota con la ubicación host para respaldo. Añade **solo** las líneas de configuración al `.env` privado de `infra/home/.env` (no a Git):

```dotenv
ALICE_PUSH_ENABLED=true
ALICE_PUSH_PRIVATE_KEY=/app/storage/secrets/webpush-vapid.pem
ALICE_PUSH_PUBLIC_KEY=<clave pública impresa por el script>
ALICE_PUSH_SUBJECT=https://eva01.tail3f8e85.ts.net:8444/
```

El `storage` host está montado en `/app/storage`. Reinicia Alice con `bash scripts/linux/start-home.sh`; `GET /api/push/config` debe mostrar `enabled:true`. La rotación reemplaza la clave en el navegador y hay que repetir el consentimiento por dispositivo. No copies ni compartas el PEM privado, ni lo guardes en el `.env`. No actives la suscripción automáticamente: la UI llama `PushManager.subscribe()` dentro de la acción afirmativa del usuario y envía `subscription.toJSON()` con el CSRF de la sesión.

## Compatibilidad real y límites

| Navegador / dispositivo | Condiciones | Fuera de la pestaña/chat |
|---|---|---|
| Chrome y Edge de escritorio/Android | HTTPS, Service Worker, permiso OS/navegador concedido | El servicio Push despierta el worker sin la pestaña. Si se termina por completo el navegador/proceso o se deshabilitan segundo plano, energía, permisos o notificaciones del OS, la recepción depende del sistema. |
| Firefox escritorio/Android | HTTPS y servicio Mozilla disponible | Push funciona con el sitio cerrado si el navegador conserva el Service Worker. Una preferencia de privacidad que borra datos al salir puede quitarlo; no se garantiza una notificación de escritorio con Firefox totalmente cerrado en todas las versiones/OS. |
| Safari macOS | Safari 16.1+ y HTTPS; notificaciones permitidas en macOS | Push Web estándar; Concentración y ajustes de macOS aún pueden ocultarlo o silenciarlo. |
| iPhone/iPad (iOS/iPadOS) | iOS/iPadOS 16.4+; Alice se añade a la pantalla de inicio, se abre como web app y se acepta permiso desde una acción del usuario | El push llega por APNs como el de otras apps. Una pestaña web normal de Safari no es suscripción de push; Concentración/ajustes iOS mandan. Un browser de terceros solo funciona si su versión/iOS ofrece instalar en pantalla de inicio. |
| Navegadores integrados/privados | Depende de soporte e instalación | A menudo no ofrecen Push persistente o dejan el worker/datos efímeros; consulta `GET /api/push/config`, disponibilidad `PushManager` y estado de la suscripción. |

Push es un envío a través de proveedor del navegador. Alice persiste y reintenta errores transitorios, quita suscripciones vencidas (`expirationTime`) y baja endpoints que respondan 404/410. Ningún servidor puede probar exactamente una aparición física en la pantalla: una caída entre aceptar el mensaje y confirmar la respuesta permite una repetición. Un `tag` estable pide al navegador actualizar el aviso existente. La cola agota tras 10 intentos; las tareas siguen en la bandeja/resumen determinista. El horario de Windows, batería, Focus/No molestar, red del teléfono, VPN/filtros y políticas corporativas quedan fuera del control de Alice. Al tocar el aviso, la UI vuelve a autenticarse y consulta la tarea en Alice; el worker no realiza mutaciones.

El resumen `GET /api/summary/daily?date=YYYY-MM-DD` se arma en SQLite (sin LM Studio), agrupa pendientes, vencidas y próximas y se actualiza en cada consulta. No se envía un digest Push diario a una hora fija en esta etapa.

## Migración y recuperación

Primero respalda `~/alice-home-state/storage`; el nuevo user_version SQLite es 8, solo aditivo, y preserva tareas, task_events y avisos existentes. La primera ejecución crea tablas de series, timeline de avisos, suscripciones y outbox. No migres sobrescribiendo ni borres volúmenes. Con el navegador no inscrito, API y recordatorios en SQLite continúan funcionando. Si el proveedor externo falla, los reintentos persisten en SQLite; si vence/expira, el worker limpia la suscripción y la persona vuelve a dar opt-in en su dispositivo. La configuración de VAPID requiere una copia protegida aparte durante la recuperación de la VM; copiar la base sin el PEM mantiene historial y avisos, pero ya no puede cifrar Push con los endpoints guardados.

En la VM de 4 GB no se añadió un servicio de Push: el transporte ejecuta en el proceso Alice. El perfil de producción mantiene Hindsight apagado.

Fuentes primarias: [Web Push en iOS/iPadOS (WebKit)](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/), [Apple: enviar Web Push](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers), [PushSubscription (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/PushSubscription).
