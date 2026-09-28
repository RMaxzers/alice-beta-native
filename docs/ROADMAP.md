# Hoja de ruta

## Para cerrar Beta 0.1

1. Acceso remoto real por Tailscale Serve y prueba desde el laptop (REMOTE-DEMO).
2. Prueba real de OpenRouter y Tavily con presupuesto.
3. Corrección del binding de Ollama.
4. Backup offline ejecutado una vez; TEST-REPORT completo; repo privado y tag `v0.1.0-beta.1`.

## Después de la beta

- Evaluar decisiones locales con abstención y evidencia (Jev/Laya y trabajos de Nandakishor): [homologación e hipótesis de prueba](DECISION-MODELS-RESEARCH.md). No reemplazar el router ni la barrera de consentimiento sin evaluación ciega en español y medición de recursos.
- Flag de mantenimiento en la API para pausar mutaciones sin detener el proceso (permitiría backups consistentes sin cortar el chat).
- Variables del contrato §20.1 que faltan: `ALICE_RUNTIME`, `ALICE_DATA_DIR`, `ALICE_VECTORSTORE_MODE`, `QDRANT_LOCAL_PATH`, `ALICE_DOCKER_BROKER_URL`.
- Modo Qdrant embebido (`VectorStoreAdapter` local/server) con migración explícita, si se quiere reducir procesos.
- Arranque automático tras iniciar sesión (tarea programada) una vez probado.
- Broker Docker de solo lectura en un host Linux autorizado.
- Grafana externo (adapter ya preparado, deshabilitado).
- Loki/Alloy para logs, solo tras medir recursos.
- Snapshots de Qdrant más pequeños (hoy ~545 MB por colección con pocos puntos).
