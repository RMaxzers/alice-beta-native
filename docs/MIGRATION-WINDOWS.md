# Migración a Windows nativo

Beta 0.1 nació directamente como perfil `windows-native` (D1). No había una instalación previa de Alice en WSL ni en Docker que migrar: WSL y Docker no están instalados en `eva01`.

## Reutilizado

| Elemento | Cómo |
|---|---|
| Ollama 0.34.x (app de bandeja) y el modelo `qwen3:4b-instruct-2507-q4_K_M` | Se reutiliza la instancia en marcha; Start-Alice solo arranca un `ollama serve` propio (en 127.0.0.1) si no responde. Se añadió `bge-m3` |
| Claves de OpenRouter y Tavily de Hermes | Copiadas a `alice\.env` (D6); Hermes no es dependencia de ejecución |
| Tailscale 1.102.2 y su regla Serve `/ -> 127.0.0.1:8080` | Se conserva sin cambios; Alice usará el puerto 8443 (D8, pendiente) |
| Open WebUI (datos en `%LOCALAPPDATA%\IA-Lab\OpenWebUI\data`) | No se toca |
| uv incluido con Hermes | Gestiona el venv de Python 3.12 de Alice (D11) |

## Adaptado

| Componente | Adaptación |
|---|---|
| Qdrant | Binario nativo 1.19.1 en modo servidor, loopback, datos en `storage\qdrant` (la especificación prefería modo embebido; el servidor nativo no depende de Docker y pasa las mismas pruebas de disponibilidad) |
| Prometheus, Grafana, windows_exporter | Binarios nativos fijados con SHA256 en `infra\bin` (Setup-Alice) |
| Métricas de GPU | Muestreo de `nvidia-smi` dentro de Alice (D12) en lugar de un exporter |
| Procesos | Scripts PowerShell con manifiesto de PID en lugar de Compose |
| Docker | Adapter preparado, host pendiente (DOCKER-INTEGRATION) |

## Datos preservados

No había datos previos de Alice. Los datos de Open WebUI, Hermes y los modelos de Ollama no se movieron ni modificaron.

## Pendiente

Modo Qdrant embebido, arranque automático tras reinicio, acceso remoto real y corrección del binding de Ollama. Ver STATUS.
