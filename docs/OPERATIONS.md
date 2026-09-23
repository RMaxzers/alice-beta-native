# Operación

Todos los scripts están en `scripts\windows\`, se ejecutan con PowerShell 7 desde cualquier directorio, son idempotentes y aceptan rutas con espacios. No piden privilegios de administrador.

| Script | Qué hace | Salida |
|---|---|---|
| `Setup-Alice.ps1` | Descarga binarios fijados y verifica SHA256, crea `.env` con secretos aleatorios (sin imprimirlos), `uv sync`, modelos de Ollama, migraciones, build de la UI | 0 / excepción |
| `Start-Alice.ps1` | Arranca en orden lo que falte (Ollama solo si no responde, Qdrant, windows_exporter, API, Prometheus, Grafana), espera la salud y el primer scrape, asegura el usuario Viewer de Grafana y ejecuta `Status-Alice.ps1` | código de Status |
| `Status-Alice.ps1` | Sondas reales de UI, API, router, Ollama, Qdrant, targets de Prometheus, Grafana, integraciones, GPU y Tailscale Serve; refresca la métrica de procesos | 1 si algún componente está en rojo |
| `Stop-Alice.ps1 [-Only nombre]` | Para solo procesos propios verificados (PID + hora de inicio + ejecutable) y su árbol. No borra datos. No toca el Ollama de la bandeja | 0 |
| `Test-Alice.ps1 [-SkipRouterEval]` | pytest, evaluación del router (reescribe `docs\ROUTER-EVAL.md`), Status, Test-Dashboard y checksums de la demo, con timeout por paso. Informe saneado en `work\test-<fecha>\REPORT.md` | 1 si algún paso falla |
| `Test-Dashboard.ps1` | Ejecuta cada consulta del dashboard en Prometheus y en Grafana | 1 si alguna da error |
| `Backup-Alice.ps1 [-Online] [-Keep 3]` | Ver BACKUP-RESTORE | 0/1/2 |
| `Restore-Alice.ps1 -Backup X -Destination Y [-Force]` | Ver BACKUP-RESTORE | 0/1/2 |
| `Demo-Alice.ps1 [-Load] [-Smoke]` | Verifica checksums de `data\samples`; `-Load` los carga en Alice; `-Smoke` lanza una consulta local | 0/1/2 |

## Manifiesto de procesos

Cada proceso arrancado por los scripts tiene `storage\run\<nombre>.json` con `pid`, `exe`, `start_utc_ticks`, `start`, `stdout` y `stderr`. Un PID solo se considera propio si el proceso existe, su ejecutable coincide y su hora de inicio coincide (tolerancia 1 s). Un manifiesto obsoleto se borra. Los antiguos `*.pid` se migran automáticamente si apuntan a un binario dentro del proyecto. Logs de cada proceso: `logs\<nombre>.out.log` y `logs\<nombre>.err.log`; Grafana escribe en `logs\grafana\`.

## Arranque tras reiniciar

No hay servicio ni tarea programada: tras reiniciar e iniciar sesión, ejecutar `scripts\windows\Start-Alice.ps1`. Ollama lo arranca la app de bandeja al iniciar sesión (si está configurada así); si no responde, Start-Alice lanza su propio `ollama serve` en 127.0.0.1. PENDIENTE: no se ha probado un ciclo completo de reinicio del PC.

## Evitar suspensión durante una demo (reversible)

```powershell
powercfg /change standby-timeout-ac 0     # durante la demo
powercfg /change standby-timeout-ac 30    # restaurar (ajusta al valor que tenías: powercfg /q)
```

La pantalla puede apagarse; lo que no debe ocurrir es la suspensión. El PC debe seguir encendido y con sesión iniciada para que Alice y Tailscale respondan.

## Memoria

Con 15,8 GB de RAM el margen es pequeño: se observaron entre 1,4 y 3,1 GB libres con el stack, dos modelos cargados y varias herramientas de desarrollo abiertas. Consumo privado aproximado medido por el dashboard: Grafana ~185 MB, Prometheus ~57 MB, Qdrant ~65 MB, API ~80 MB, windows_exporter ~30 MB. Los modelos viven sobre todo en VRAM (qwen3 ~3,2 GB, bge-m3 ~0,7 GB). Si la RAM libre baja de 2 GB, cerrar navegador/IDE antes que parar componentes.

## Problemas conocidos

- Status marca `Alice UI DOWN` si `apps\web\dist` no existe (build pendiente). Ejecutar el paso de build de `Setup-Alice.ps1`.
- Ollama escucha en todas las interfaces cuando lo arranca la app de bandeja. Ver SECURITY.
- Reinicios Kernel-Power 41 del host (ENVIRONMENT): tras un reinicio inesperado, ejecutar `Start-Alice.ps1` y después `Status-Alice.ps1`. SQLite trabaja en modo WAL y Qdrant tiene su propio WAL, pero la recuperación tras un corte no se ha probado aquí: mantener backups recientes.
