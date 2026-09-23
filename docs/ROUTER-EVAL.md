# Router evaluation

Date: 2026-09-23 00:13 · cases: 52 · embeddings: bge-m3 · classifier: qwen3:4b-instruct-2507-q4_K_M

**Accuracy: 52/52 = 100.0%** · malformed classifier outputs: 0
Latency: p50 0 ms · p95 2018 ms · max 7793 ms (includes embedding/classifier calls)
Decided by: {'classifier': 8, 'rules': 44}
By set: eval-1 40/40, holdout2 12/12 (holdout2 was written after eval-1 rule changes and never used for tuning)

| Route | Correct |
|---|---|
| AUTOMATION | 1/1 |
| CLOUD_POWERFUL | 2/2 |
| FINANCIAL_RESEARCH | 4/4 |
| LOCAL_CODE | 7/7 |
| LOCAL_RAG | 4/4 |
| LOCAL_SIMPLE | 8/8 |
| LOG_ANALYSIS | 3/3 |
| OBSERVABILITY | 14/14 |
| STRUCTURED_QUERY | 4/4 |
| WEB_RESEARCH | 5/5 |

| Query | Expected | Got | By | Conf. | ms | OK |
|---|---|---|---|---|---|---|
| Explícame qué es una VLAN. | LOCAL_SIMPLE | LOCAL_SIMPLE | classifier | 0.99 | 7793 | ✅ |
| Explícame DHCP en pocas palabras | LOCAL_SIMPLE | LOCAL_SIMPLE | classifier | 0.99 | 1758 | ✅ |
| ¿Qué diferencia hay entre RAID 1 y RAID 5? | LOCAL_SIMPLE | LOCAL_SIMPLE | classifier | 0.99 | 2018 | ✅ |
| Dame tres consejos para dormir mejor | LOCAL_SIMPLE | LOCAL_SIMPLE | classifier | 0.95 | 2007 | ✅ |
| What is a subnet mask? | LOCAL_SIMPLE | LOCAL_SIMPLE | classifier | 0.99 | 2095 | ✅ |
| Escribe un PowerShell que muestre los cinco procesos que más | LOCAL_CODE | LOCAL_CODE | rules |  | 0 | ✅ |
| Genera una función que valide estas direcciones IP | LOCAL_CODE | LOCAL_CODE | rules |  | 0 | ✅ |
| Corrige este código Python: for i in range(10) print(i) | LOCAL_CODE | LOCAL_CODE | rules |  | 0 | ✅ |
| Escribe una regex para validar correos | LOCAL_CODE | LOCAL_CODE | rules |  | 0 | ✅ |
| ¿Cómo hago un bucle en bash que recorra archivos .log? | LOCAL_CODE | LOCAL_CODE | rules |  | 0 | ✅ |
| ¿Cuáles son los hallazgos principales? | LOCAL_RAG | LOCAL_RAG | rules |  | 0 | ✅ |
| Según el documento, ¿qué recomienda para las contraseñas? | LOCAL_RAG | LOCAL_RAG | rules |  | 0 | ✅ |
| Resume la sección de riesgos | LOCAL_RAG | LOCAL_RAG | rules |  | 0 | ✅ |
| ¿Cuántos elementos cumplen X? | STRUCTURED_QUERY | STRUCTURED_QUERY | rules |  | 0 | ✅ |
| ¿Cuántos activos del inventario están fuera de soporte? | STRUCTURED_QUERY | STRUCTURED_QUERY | rules |  | 0 | ✅ |
| Suma el total de licencias por área en la planilla | STRUCTURED_QUERY | STRUCTURED_QUERY | rules |  | 0 | ✅ |
| ¿Cuál es el error más frecuente? | LOG_ANALYSIS | LOG_ANALYSIS | rules |  | 0 | ✅ |
| ¿Qué patrones de error aparecen en el log? | LOG_ANALYSIS | LOG_ANALYSIS | rules |  | 0 | ✅ |
| Investiga las novedades recientes de Ollama. | WEB_RESEARCH | WEB_RESEARCH | rules |  | 0 | ✅ |
| ¿Cuáles son las últimas noticias sobre Tailscale? | WEB_RESEARCH | WEB_RESEARCH | rules |  | 0 | ✅ |
| Busca en internet la última versión de Grafana | WEB_RESEARCH | WEB_RESEARCH | rules |  | 0 | ✅ |
| ¿Cuál es la cotización actual del cobre en Londres? | FINANCIAL_RESEARCH | FINANCIAL_RESEARCH | rules |  | 0 | ✅ |
| ¿A cuánto está el dólar observado hoy en Chile? | FINANCIAL_RESEARCH | FINANCIAL_RESEARCH | rules |  | 0 | ✅ |
| Compara la capitalización bursátil de Nvidia y AMD | FINANCIAL_RESEARCH | FINANCIAL_RESEARCH | rules |  | 0 | ✅ |
| ¿Cómo está Alice? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Cuánta CPU y RAM está usando el sistema? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Cuánta VRAM estoy utilizando? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Qué contenedor consume más memoria? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Están todos los servicios de Alice funcionando? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Qué modelo está cargado en Ollama? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Cuántas consultas fueron locales hoy? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Cuál fue la consulta más lenta? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Cómo cambió la GPU durante los últimos 30 minutos? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Por qué Alice estuvo lenta durante la última hora? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| Dame los últimos errores del contenedor de Qdrant. | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Qué ocurrió con CPU, RAM y GPU durante mi última consulta? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| Automatiza un resumen diario de mis logs | AUTOMATION | AUTOMATION | rules |  | 0 | ✅ |
| Usa el modelo más potente para diseñar una estrategia de mig | CLOUD_POWERFUL | CLOUD_POWERFUL | rules |  | 0 | ✅ |
| Hazme un análisis profundo de pros y contras de microservici | CLOUD_POWERFUL | CLOUD_POWERFUL | rules |  | 0 | ✅ |
| ¿Por qué el cielo es azul? | LOCAL_SIMPLE | LOCAL_SIMPLE | classifier | 0.99 | 2050 | ✅ |
| Crea un script de Python que mida el uso de RAM de un proces | LOCAL_CODE | LOCAL_CODE | rules |  | 0 | ✅ |
| Investiga qué cambió en Prometheus 3 | WEB_RESEARCH | WEB_RESEARCH | rules |  | 0 | ✅ |
| ¿Cuánta memoria está usando el contenedor de Grafana? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| ¿Qué es un hipervisor? | LOCAL_SIMPLE | LOCAL_SIMPLE | classifier | 0.95 | 1936 | ✅ |
| ¿Cuántos equipos del inventario tienen Windows 10? | STRUCTURED_QUERY | STRUCTURED_QUERY | rules |  | 0 | ✅ |
| ¿A qué hora ocurrió el primer error en el log? | LOG_ANALYSIS | LOG_ANALYSIS | rules |  | 0 | ✅ |
| ¿Cuál es el precio de la acción de Apple? | FINANCIAL_RESEARCH | FINANCIAL_RESEARCH | rules |  | 0 | ✅ |
| Según mis documentos, ¿quién aprobó el cambio? | LOCAL_RAG | LOCAL_RAG | rules |  | 0 | ✅ |
| Explica la diferencia entre proceso e hilo | LOCAL_SIMPLE | LOCAL_SIMPLE | classifier | 0.99 | 1259 | ✅ |
| ¿Está funcionando Prometheus? | OBSERVABILITY | OBSERVABILITY | rules |  | 0 | ✅ |
| Últimas noticias sobre la regulación de IA en Chile | WEB_RESEARCH | WEB_RESEARCH | rules |  | 0 | ✅ |
| Escribe una consulta SQL que agrupe ventas por mes | LOCAL_CODE | LOCAL_CODE | rules |  | 0 | ✅ |
