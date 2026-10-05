# Alice en Ubuntu Server / VirtualBox

Perfil independiente de Windows, basado en `integration/alice-next` (`951e7a9`).
Ubuntu ejecuta API, web, SQLite, archivos y Qdrant. LM Studio ejecuta los modelos
en la GPU de Windows. Un túnel SSH inverso hace que el endpoint sea
`127.0.0.1:1234` dentro de Ubuntu; no se expone LM Studio en la LAN.

## Estado operativo (2026-10-05)

- VM ALICE: Ubuntu 26.04.1, 4 GB RAM, 4 CPU y disco de 50 GB. Se redujo la RAM
  de 8 a 4 GB para dejar memoria disponible en Windows y LM Studio.
- NAT de VirtualBox: Windows `127.0.0.1:2222` → Ubuntu `22`, usuario `eva2`.
- La llave SSH de Windows está autorizada. Docker Engine y Compose están instalados;
  Alice, Qdrant y Homepage se recuperaron al reiniciar completamente la VM.
- El adaptador puente recibió `192.168.1.14` del router; Alice, Homepage y Pi-hole
  responden en esa dirección. Pi-hole resolvió `example.com` y bloqueó
  `doubleclick.net` con `0.0.0.0` en la prueba desde Windows.
- Los modelos descargados ocupan unos 36 GB en Windows; no se migran todos a un disco de 50 GB.
- El perfil usa Gemma 4 E4B y Nomic v1.5 (768 dimensiones), colección nueva
  `alice_home_nomic_768`. No reutilizar índices BGE-M3 de 1024 dimensiones.
- Voz y Hindsight están desactivados en este perfil inicial.

## Instalación

En **Termius / Ubuntu**, como `eva2`:

```bash
sudo bash ~/alice-setup/install-docker.sh eva2
```

El script usa el repositorio apt firmado de Docker, instala Engine y Compose,
habilita Docker al arrancar y agrega `eva2` al grupo docker. Ese grupo permite
administrar el host. No crea reglas de sudo sin contraseña. Abrir una nueva
conexión SSH después de instalar para aplicar la pertenencia al grupo.

Luego, en Ubuntu:

```bash
cd ~/alice-home
python3 scripts/linux/prepare-home.py
bash scripts/linux/start-home.sh
cat ~/alice-home-state/access.txt
```

La preparación conserva archivos y claves existentes; las contraseñas nuevas
se generan dentro de Ubuntu y quedan en archivos de permiso 600. No compartir
el contenido de `.env` ni `access.txt`.

En **PowerShell / Windows**, mientras la VM esté encendida:

```powershell
& .\scripts\windows\Start-Alice-Vm-Link.ps1
```

Ese proceso mantiene el túnel. El servidor LM Studio arranca en loopback, sin
cargar automáticamente los modelos. Antes del chat, cargar un solo modelo con
contexto 2048 y una predicción simultánea. Primero completar la instalación de
Docker; el PC tiene poca RAM libre y no conviene solapar el build con la carga.

En este PC está instalada la tarea de Windows `Alice-Ubuntu-Link`. Al iniciar
sesión, ejecuta `C:\Users\cuent\.config\alice-vm\Start-Alice-Vm-Link.ps1`
con `-KeepAlive -StartVm`: enciende ALICE si estaba apagada y reconecta el túnel
tras un reinicio de Ubuntu. No vuelve a encender una VM apagada intencionalmente
durante esa ejecución. Para detener la conexión, detener la tarea desde el
Programador de tareas de Windows.

## Acceso desde este PC

Configurar reglas NAT TCP de VirtualBox ligadas a `127.0.0.1`:

| Servicio | Puerto Windows | Puerto Ubuntu |
| --- | --- | --- |
| Alice | 8330 | 8000 |
| Panel Homepage | 8331 | 3000 |
| Pi-hole, si se activa | 8332 | 8080 |

Alice: <http://127.0.0.1:8330>. Panel: <http://127.0.0.1:8331>.
El puerto 8000 de Windows queda disponible para la instalación anterior.
La CLI está incluida y conserva su sesión en `~/alice-home-state/storage/cli`:

```bash
cd ~/alice-home
bash scripts/linux/alice-cli.sh status
bash scripts/linux/alice-cli.sh chat
```

La prueba real de chat respondió «Alice lista en Ubuntu» usando Gemma en Windows.

## Acceso privado desde la laptop

Tailscale Serve está configurado en Windows y conserva los servicios anteriores:
<https://eva01.tail3f8e85.ts.net:8444/> apunta a Alice en `127.0.0.1:8330`.
La laptop debe estar conectada a la misma red Tailscale. Este acceso no configura
DNS ni acceso directo desde cualquier dispositivo de la red de casa.

## Red de casa y Pi-hole

NAT no da a la VM una dirección directamente accesible por otros dispositivos.
El segundo adaptador **puente** se conecta a la Ethernet Realtek del PC;
NAT/SSH se conserva en el primero. Ubuntu obtuvo una IP automáticamente; se
configuró el perfil y se activó Pi-hole sin otro paso sudo.

| Servicio | Enlace en la red de casa |
| --- | --- |
| Alice | <http://192.168.1.14:8000> |
| Panel | <http://192.168.1.14:3000> |
| Pi-hole | <http://192.168.1.14:8080/admin/> |

DNS de Pi-hole: `192.168.1.14`. Reservar esa dirección en el router para la MAC
`08:00:27:0c:46:f1` antes de usarla como DNS de toda la casa. La prueba utilizó
consultas explícitas a Pi-hole; no se cambió el DNS de Windows ni el del router.

Si Ubuntu deja de obtener la dirección automáticamente, el script de respaldo
configura solamente el segundo adaptador:

```bash
sudo bash ~/alice-home/scripts/linux/enable-home-lan.sh eva2
```

Ubuntu exige la contraseña sudo de `eva2` para escribir su configuración de red.
El script crea solamente `90-alice-home-lan.yaml`, obtiene una IP por DHCP y
ajusta `ALICE_PUBLIC_ORIGIN`, `ALICE_BROWSER_URL`, `HOMEPAGE_ALLOWED_HOSTS` y
`DNS_BIND_ADDR` a esa IP. Imprime los enlaces y la MAC para reservar la IP en el
router. No cambia el DNS ni el DHCP del router.
El panel no tiene autenticación propia; el acceso remoto requiere una red
privada o un proxy con autenticación. Alice sí exige iniciar sesión.

Pi-hole está activo en este PC y sigue siendo un perfil opcional para nuevas
instalaciones. `DNS_BIND_ADDR` debe ser la IP LAN concreta de
la VM; evitar `0.0.0.0` para no ocupar el resolver de Ubuntu en `127.0.0.53`.

```bash
docker compose --env-file infra/home/.env -f infra/home/compose.yaml --profile dns up -d pihole
```

Comprobar DNS desde un dispositivo antes de cambiar el DNS de toda la casa.
No activar DHCP de Pi-hole: el router sigue entregando direcciones.

## Persistencia y autonomía

`restart: unless-stopped` hace que los contenedores vuelvan al encender Ubuntu.
El túnel y los modelos dependen de Windows; apagar o suspender el PC detiene este
servidor. El arranque automático está ligado al inicio de sesión de Windows.

El perfil habilita `ALICE_REMINDERS_ENABLED=true`. Cada 15 segundos, un proceso
de Alice revisa tareas activas con fecha y hora en `America/Santiago`, y guarda
un aviso en SQLite cuando vencen. Funciona con el navegador cerrado y sin un
modelo cargado. Una clave única evita repetir el mismo aviso tras reinicios.
Reprogramar, completar o cancelar la tarea oculta el aviso anterior.

En **Hoy**, crear o editar una tarea y elegir **Fecha** y **Hora del aviso**.
Sin hora, la tarea aparece en la agenda pero no genera un aviso automático.
El menú **Recordatorios** muestra avisos pendientes y permite marcarlos leídos;
se abre al llegar uno nuevo mientras Alice está abierta. El orbe refleja tareas
vencidas y las que vencen durante la próxima hora.

Los avisos se conservan para verlos al volver a Alice; todavía no hay push al
teléfono ni sincronización con Google Calendar u Outlook. La prueba automática
«Prueba automática de recordatorios» venció a las 01:23 de Santiago y generó un
solo aviso sin navegador abierto.
Se comprobó que continuaba existiendo exactamente una fila después de reiniciar
Ubuntu y recrear el contenedor. Al completar la tarea desde la web, desapareció
del menú de avisos y el orbe volvió al estado despejado.

También se creó **Prueba del aviso en vivo** desde la web, con fecha y hora a las
01:37. El aviso se abrió automáticamente y el orbe cambió de cian a cobre.
**Marcar leído** quitó el contador; completar la tarea dejó la agenda despejada.
Las dos pruebas quedaron completadas, con una sola fila de aviso por tarea.

La CLI responde a **Qué tareas tengo para hoy** consultando SQLite, sin necesitar
generación del modelo. Se corrigió su selección de ruta durante la prueba.
Los avisos requieren sesión válida (401 sin sesión) y sus cambios requieren
CSRF (403 sin token). No se ejecutó una suite de tests; estas comprobaciones
se hicieron con el servicio y el navegador reales.

Los datos nuevos van a `~/alice-home-state`; Qdrant y Pi-hole usan volúmenes del
proyecto `alice-home`. No se han copiado conversaciones, sesiones ni memoria de
Windows. Hacer un backup consistente antes de migrar esos datos.

## Operación

```bash
cd ~/alice-home
docker compose --env-file infra/home/.env -f infra/home/compose.yaml ps
docker compose --env-file infra/home/.env -f infra/home/compose.yaml logs --tail 100 alice
docker compose --env-file infra/home/.env -f infra/home/compose.yaml stop
```

No usar `down -v` al detener: borra los volúmenes. Los logs rotan y los servicios
tienen límites de memoria (Alice 1,5 GB, Qdrant 768 MB, Homepage 384 MB y Pi-hole
384 MB). No se monta el socket Docker en Alice o Homepage.

Fuentes: [Docker en Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[API de LM Studio](https://lmstudio.ai/docs/developer/openai-compat/chat-completions),
[Pi-hole Docker](https://docs.pi-hole.net/docker/),
[Homepage Docker](https://gethomepage.dev/installation/docker/).
La configuración opcional del segundo adaptador sigue los
[ejemplos de Netplan](https://github.com/canonical/netplan/blob/main/doc/examples.md).
