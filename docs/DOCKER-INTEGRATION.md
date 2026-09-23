# Integración Docker

Estado: **adapter preparado; host pendiente.** No hay daemon Docker en `eva01` (Docker y WSL no instalados, hipervisor ausente, VT-d deshabilitado; ver ENVIRONMENT y D1/D2). Ningún panel ni respuesta muestra contenedores simulados.

## Qué existe

`services/observability/docker.py` (`DockerAdapter`) expone solo cuatro operaciones tipadas de lectura: `list_containers`, `container_stats`, `container_status`, `container_logs`. Cualquier otra operación se rechaza. Reglas del código:

- Ejecuta `docker` con lista de argumentos y `shell=False`, timeout 5 s, salida máxima 256 KB.
- Un contenedor debe estar en `DOCKER_ALLOWED_CONTAINERS` y además aparecer en el inventario en vivo; el identificador se valida con una expresión regular.
- `inspect` se proyecta a un conjunto fijo de campos (sin variables de entorno, cmd, labels ni mounts). Logs acotados (200 líneas por defecto, máximo 1000, últimas 24 h como máximo) y redactados.
- Con `DOCKER_ENABLED=false` (valor actual) el estado es `unavailable`.

Pruebas: `tests/unit/test_docker_adapter.py` (14 casos) contra un runner falso. En el dashboard, la fila «Docker (DESHABILITADO)» lo explica y muestra `alice_dependency_up{dependency="docker"}`.

## Opciones para tener un host (especificación §5.4)

1. **Daemon existente que funcione**: no hay ninguno en este PC.
2. **Docker en otro equipo Linux autorizado** (opción preferida si se quiere Docker): Alice sigue en Windows; en el equipo Linux corre un broker de solo lectura con las cuatro operaciones, expuesto a Alice por la tailnet con autenticación. El socket Docker no sale de ese equipo y no se envían documentos ni embeddings. Cada panel debe etiquetar ese host para no confundirlo con el PC. Requiere que el usuario indique y autorice el equipo. No se ha hecho.
3. **Docker Desktop con VMM en este PC**: requiere versión reciente de Desktop, está en beta y reserva al menos 4 GB para la VM. Con 15,8 GB de RAM (1,4-3,1 GB libres con el stack en marcha) y el historial de reinicios del host, no se recomienda. No evaluado.
4. **Sin daemon** (situación actual): Alice nativa completa, adapter probado con fixtures, host pendiente.

No sirve instalar solo `docker.exe` (no trae motor Linux) ni usar contenedores Windows (las imágenes Linux de Qdrant/Grafana/Prometheus no corren sin cambios). No se recomienda Docker Toolbox.

## Para activarlo cuando exista un host

1. Verificar el daemon con timeout desde el proceso real de Alice (`docker version` o el broker remoto).
2. Ajustar `DOCKER_ALLOWED_CONTAINERS` a los contenedores reales y poner `DOCKER_ENABLED=true`.
3. Añadir en `infra/prometheus/prometheus.yml` un job para el colector de contenedores de ese host (cAdvisor solo si hay Docker Linux) con una etiqueta de host, y paneles etiquetados por host en el dashboard.
4. Registrar la prueba real en TEST-REPORT («integración real validada»).
