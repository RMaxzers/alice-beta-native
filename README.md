# Alice Beta 0.1

Asistente local para un PC Windows 11 con GPU NVIDIA: chat con modelos locales (Ollama), conocimiento sobre documentos propios (RAG con Qdrant y SQLite), consultas SQL sobre tablas importadas, observabilidad de Windows, GPU y de la propia Alice (Prometheus + Grafana), y acceso cloud autorizado y con presupuesto (OpenRouter). Todo corre como procesos nativos de Windows en loopback, sin WSL2 ni Docker.

English version: [README.en.md](README.en.md).

## Requisitos

Windows 11, PowerShell 7, GPU NVIDIA con `nvidia-smi`, Ollama instalado, Node.js (para construir la UI) y `uv`. Ver `docs/ENVIRONMENT.md` para el equipo de referencia.

## Puesta en marcha

```powershell
.\scripts\windows\Setup-Alice.ps1     # binarios fijados (SHA256), .env con secretos aleatorios, venv, modelos, migraciones, build de la UI
.\scripts\windows\Start-Alice.ps1     # arranca lo que falte y muestra el estado real
.\scripts\windows\Demo-Alice.ps1 -Load   # opcional: carga el dataset sintético de demostración
```

- UI y API: http://127.0.0.1:8000 (usuario y contraseña en `.env`).
- Dashboard: http://127.0.0.1:3000/d/alice-overview (ALICE / OVERVIEW).
- Estado: `.\scripts\windows\Status-Alice.ps1`; parada: `.\scripts\windows\Stop-Alice.ps1`.
- Pruebas: `.\scripts\windows\Test-Alice.ps1` (informe en `work\test-<fecha>\REPORT.md`).
- Backup: `.\scripts\windows\Backup-Alice.ps1`; restauración: `.\scripts\windows\Restore-Alice.ps1`.

## Documentación

| Documento | Contenido |
|---|---|
| [STATUS](docs/STATUS.md) | Qué funciona, qué falta, bloqueos y siguiente acción |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Componentes, puertos, almacenamiento y matriz de conexiones |
| [DECISIONS](docs/DECISIONS.md) | Decisiones y alternativas descartadas |
| [ENVIRONMENT](docs/ENVIRONMENT.md) | Inventario saneado del equipo |
| [CONFIGURATION](docs/CONFIGURATION.md) | Variables de entorno |
| [OPERATIONS](docs/OPERATIONS.md) | Scripts, manifiesto de procesos, arranque, memoria |
| [OBSERVABILITY](docs/OBSERVABILITY.md) | Métricas, dashboard y su verificación |
| [BACKUP-RESTORE](docs/BACKUP-RESTORE.md) | Procedimiento probado |
| [SECURITY](docs/SECURITY.md) | Exposición de red, secretos, hallazgos |
| [MODELS](docs/MODELS.md) | Modelos, digests, licencias, VRAM y latencias |
| [REMOTE-DEMO](docs/REMOTE-DEMO.md) | Acceso por Tailscale Serve (pendiente) |
| [DEMO](docs/DEMO.md) | Guion de 12 pasos y plan sin Internet |
| [DOCKER-INTEGRATION](docs/DOCKER-INTEGRATION.md) | Adapter preparado, host pendiente |
| [MIGRATION-WINDOWS](docs/MIGRATION-WINDOWS.md) | Qué se reutilizó y adaptó |
| [AGENT-PLAN](docs/AGENT-PLAN.md) | Reparto de trabajo entre agentes |
| [ROUTER-EVAL](docs/ROUTER-EVAL.md), [TEST-REPORT](docs/TEST-REPORT.md) | Resultados de pruebas |
| [ROADMAP](docs/ROADMAP.md) | Lo que queda |

## Datos y privacidad

Los documentos, bases de datos, vectores, logs y backups viven en `data\`, `storage\`, `logs\` y `backups\`, todos fuera de Git. `data\samples` solo contiene el dataset sintético de demostración. `.env` nunca se versiona.

## Licencia

Sin licencia de distribución elegida todavía; queda a decisión del propietario. Las licencias de los modelos están en `docs/MODELS.md`.
