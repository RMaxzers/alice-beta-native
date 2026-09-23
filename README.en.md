# Alice Beta 0.1

A local assistant for a Windows 11 PC with an NVIDIA GPU: chat with local models (Ollama), knowledge over your own documents (RAG with Qdrant and SQLite), SQL over imported tables, observability of Windows, the GPU and Alice itself (Prometheus + Grafana), and authorized, budgeted cloud access (OpenRouter). Everything runs as native Windows processes on loopback, without WSL2 or Docker.

Spanish is the primary documentation language; the files under `docs/` are in Spanish. Versión en español: [README.md](README.md).

## Requirements

Windows 11, PowerShell 7, an NVIDIA GPU with `nvidia-smi`, Ollama, Node.js (to build the UI) and `uv`. See `docs/ENVIRONMENT.md` for the reference machine.

## Getting started

```powershell
.\scripts\windows\Setup-Alice.ps1     # pinned binaries (SHA256), .env with random secrets, venv, models, migrations, UI build
.\scripts\windows\Start-Alice.ps1     # starts whatever is missing and prints the real status
.\scripts\windows\Demo-Alice.ps1 -Load   # optional: loads the synthetic demo dataset
```

- UI and API: http://127.0.0.1:8000 (user and password in `.env`).
- Dashboard: http://127.0.0.1:3000/d/alice-overview (ALICE / OVERVIEW).
- Status: `.\scripts\windows\Status-Alice.ps1`; stop: `.\scripts\windows\Stop-Alice.ps1`.
- Tests: `.\scripts\windows\Test-Alice.ps1` (report in `work\test-<date>\REPORT.md`).
- Backup: `.\scripts\windows\Backup-Alice.ps1`; restore: `.\scripts\windows\Restore-Alice.ps1`.

## Components

Alice API + UI (127.0.0.1:8000, metrics on 9101), Ollama (reused tray instance), Qdrant 1.19.1 in server mode (6333), windows_exporter 0.31.8 (9182), Prometheus 3.14.0 (9090, 7 days / 2 GB), Grafana 13.2.2 (3000). Docker integration: adapter ready, host pending. Remote access through Tailscale Serve: pending. Details in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.

## Data and privacy

Documents, databases, vectors, logs and backups live in `data\`, `storage\`, `logs\` and `backups\`, all excluded from Git. `data\samples` only holds the synthetic demo dataset. `.env` is never committed.

## License

No distribution license has been chosen yet; that is the owner's decision. Model licenses are listed in `docs/MODELS.md`.
