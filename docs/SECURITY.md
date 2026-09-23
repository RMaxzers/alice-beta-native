# Seguridad

## Exposición de red

| Puerto | Binding | Estado |
|---|---|---|
| 8000 API + UI, 9101 métricas, 6333/6334 Qdrant, 9182 windows_exporter, 9090 Prometheus, 3000 Grafana | 127.0.0.1 | Verificado con `Get-NetTCPConnection` |
| 11434 Ollama | `[::]` (todas las interfaces, IPv4 e IPv6) | **Hallazgo abierto** |
| 443 tailscaled | IP de la tailnet | Preexistente |
| 3389 RDP | 0.0.0.0 | Preexistente, fuera del alcance de Alice |

### Hallazgo: Ollama escucha en todas las interfaces

El proceso `ollama.exe` (PID 12876 el 2026-09-22) lo lanza la app de bandeja de Ollama, no los scripts de Alice, y escucha en `:::11434`. Cualquier equipo que alcance el PC por la LAN o la tailnet puede usar la API de Ollama (generar, listar, borrar o descargar modelos) si el firewall de Windows lo permite. Cuando `Start-Alice.ps1` tiene que arrancar Ollama él mismo, lo hace con `OLLAMA_HOST=127.0.0.1:11434`, pero hoy reutiliza la instancia de la bandeja.

Corrección propuesta (no aplicada; requiere consentimiento porque cambia una variable de entorno de usuario):

```powershell
[Environment]::SetEnvironmentVariable('OLLAMA_HOST', '127.0.0.1:11434', 'User')
# Salir de Ollama desde el icono de la bandeja y volver a abrir "Ollama" desde el menú Inicio.
Get-NetTCPConnection -LocalPort 11434 -State Listen | Select-Object LocalAddress   # esperado: 127.0.0.1
```

Para deshacerlo: `[Environment]::SetEnvironmentVariable('OLLAMA_HOST', $null, 'User')` y reiniciar la app. Open WebUI (si vuelve a usarse desde 127.0.0.1:8080) sigue funcionando porque también es local.

## Secretos

- `.env` lo genera `Setup-Alice.ps1` con valores aleatorios (`ALICE_PASSWORD`, `ALICE_SESSION_SECRET`, `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_VIEWER_PASSWORD`) y copia `OPENROUTER_API_KEY`/`TAVILY_API_KEY` del `.env` de Hermes (D6). La ACL queda en el usuario actual (lectura/escritura) y SYSTEM. Nunca se imprimen.
- `.env` está en `.gitignore`; `.env.example` solo tiene nombres y valores ficticios.
- Los scripts leen `.env` en memoria (`Read-DotEnv`). La contraseña de admin de Grafana se pasa a Grafana por variable de entorno del proceso y a la API de Grafana en una cabecera Basic; no aparece en argumentos de línea de comandos ni en logs.
- `Test-Alice.ps1` sustituye por `<REDACTED>` el valor de cualquier variable de `.env` cuyo nombre contenga PASSWORD, SECRET, KEY o TOKEN antes de guardar el informe.
- Los backups no incluyen `.env`, pero sí documentos y la base de datos: `backups\` está fuera de Git y con ACL solo para el usuario y SYSTEM.

## Aplicación

Según el código de `apps/api/` (probado por `tests/security/`): sesión por cookie firmada `HttpOnly`, `SameSite=Strict`, `Secure` cuando llega por HTTPS, 12 h; token CSRF en la cabecera `x-csrf-token` para peticiones que cambian estado; limitación de intentos de login; cabeceras CSP, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`; `/healthz` y cualquier ruta fuera de `/`, `/assets/` y `/api/` responden 404 cuando la petición llega a través de un proxy (cabecera `X-Forwarded-For` o `Tailscale-User-Login`); `/metrics` solo existe en 9101 (D9).

## Grafana

Acceso anónimo desactivado, registro de usuarios desactivado, analítica e informes de actualización desactivados. El admin solo se usa en local para provisioning y verificación. Existe un usuario `viewer` (rol Viewer) creado por `Start-Alice.ps1` para la demo remota. Alice no recibe la credencial de admin.

## Telemetría

Qdrant con `QDRANT__TELEMETRY_DISABLED=true`; Grafana con `GF_ANALYTICS_*` desactivados y sin feed de noticias. Ollama, Tailscale y Windows mantienen su propio comportamiento (no modificado).

## Pendiente

- Aplicar la corrección de `OLLAMA_HOST` (arriba).
- ACL/grants de Tailscale para limitar el acceso a la entrada de Alice a los dispositivos autorizados (ver REMOTE-DEMO). La tailnet incluye un dispositivo de otro usuario.
- Escaneo de secretos antes del primer push (lo hace el coordinador).
