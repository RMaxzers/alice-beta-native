# Demo remota por Tailscale (PENDIENTE)

Estado al 2026-09-22: **nada de esto está aplicado ni probado desde el laptop.** Los comandos usan la sintaxis de Tailscale 1.102.2 instalada (`tailscale serve --help`). Solo Serve dentro de la tailnet; nunca Funnel ni port forwarding.

## Estado actual (solo lectura)

```text
> tailscale serve status
https://eva01.tail3f8e85.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8080
```

Esa regla (Open WebUI) se conserva siempre. Nunca ejecutar `tailscale serve reset`: borra también reglas ajenas a Alice.

## 1. Requisitos previos

1. PC `eva01` encendido, con sesión de Windows iniciada, sin suspensión (ver OPERATIONS) y `Start-Alice.ps1` en verde.
2. `.env`: `ALICE_PUBLIC_ORIGIN=https://eva01.tail3f8e85.ts.net:8443` (Setup-Alice lo rellena desde `tailscale status`). Comprobar solo su presencia, sin imprimir el archivo.
3. Laptop con Tailscale, con sesión en la misma tailnet y conectado a otra red (por ejemplo, datos móviles).

## 2. Publicar Alice (D8)

```powershell
tailscale serve --bg --https=8443 http://127.0.0.1:8000
tailscale serve status        # debe listar :443 (Open WebUI, intacta) y :8443 -> http://127.0.0.1:8000
.\scripts\windows\Status-Alice.ps1   # la línea "Remote access" pasa a CONFIGURED
```

Solo se publica el puerto 8000. Las métricas (9101), Ollama, Qdrant, Prometheus y exporters no se publican. La API devuelve 404 a `/healthz` y a cualquier ruta fuera de `/`, `/assets/`, `/api/` cuando la petición llega por el proxy.

## 3. Acceso Viewer a Grafana (opcional para el paso 7 de la demo)

```powershell
tailscale serve --bg --https=8444 http://127.0.0.1:3000
```

Después añadir a `.env` la línea `ALICE_GRAFANA_TRUSTED_ORIGINS=eva01.tail3f8e85.ts.net:8444` y reiniciar solo Grafana:

```powershell
.\scripts\windows\Stop-Alice.ps1 -Only grafana; .\scripts\windows\Start-Alice.ps1
```

Entrar como usuario `viewer` (rol Viewer, contraseña `GRAFANA_VIEWER_PASSWORD` de `.env`, que se comunica fuera de banda). No usar la cuenta admin fuera del PC y no poner credenciales en la URL. Dashboard: `https://eva01.tail3f8e85.ts.net:8444/d/alice-overview`. Si el login falla por origen, Grafana queda local y el paso 7 de la demo usa la vista de métricas de Alice.

## 4. Restringir quién accede (ACL/grants)

La tailnet incluye un dispositivo de otro usuario, así que Serve por sí solo no basta. En la consola de administración de Tailscale (Access controls), añadir una regla que permita a los puertos 8443/8444 de `eva01` solo al usuario/dispositivo del laptop, por ejemplo:

```json
{ "grants": [ { "src": ["<usuario-autorizado>"], "dst": ["<tag-o-host-de-eva01>"], "ip": ["tcp:8443", "tcp:8444"] } ] }
```

Esto se edita en la política de la tailnet y lo aplica el propietario; ajustar a la política existente sin borrar reglas de otros. PENDIENTE.

## 5. Prueba desde el laptop (fuera de la LAN)

1. `https://eva01.tail3f8e85.ts.net:8443/` carga la UI con certificado válido.
2. Login con `ALICE_USERNAME`/`ALICE_PASSWORD`.
3. Consulta con streaming («Explícame DHCP en pocas palabras»), subida de un archivo pequeño de `data\samples`, consulta RAG.
4. Cortar la red del laptop unos segundos y comprobar que la UI se reconecta.
5. `https://eva01.tail3f8e85.ts.net:8443/healthz` y `/metrics` deben dar 404.
6. Desde un dispositivo no autorizado y desde la IP pública: sin acceso.
7. Opcional: Grafana Viewer (sección 3).

Registrar el resultado en `docs/TEST-REPORT.md`.

## 6. Retirar solo las reglas de Alice

```powershell
tailscale serve --https=8443 off
tailscale serve --https=8444 off
tailscale serve status        # debe quedar solo "/ proxy http://127.0.0.1:8080"
```

Y quitar `ALICE_GRAFANA_TRUSTED_ORIGINS` de `.env` si se añadió.
