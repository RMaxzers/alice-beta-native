# Encargo para Claude Code: Alice, asistente que organiza y ejecuta

Trabaja en este repositorio como coordinador técnico y de producto. **Tu encargo es implementar, probar y dejar utilizable el primer avance real de Alice como asistente del día a día.** No te detengas en un diagnóstico o una propuesta. Si una parte necesita una decisión o credencial que solo yo puedo aportar, avanza en lo demás y deja esa dependencia identificada con precisión.

## Propósito del producto

Alice debe ayudarme a vivir y trabajar con menos carga de coordinación. Debe entender mis tareas cotidianas y laborales, organizar prioridades y fechas, leer mis documentos, logs y datos, explicarme lo importante con fuentes, proponer próximos pasos y **realizar por sí misma las acciones que correspondan a su nivel de autorización y criticidad**. No quiero un chatbot que solo redacte planes de automatización. Quiero un asistente que distinga entre *pensar*, *organizar*, *preparar* y *hacer*, y que muestre el estado real de cada cosa.

Ejemplos de experiencia objetivo:

- «Revisa estos logs, dime qué falló y crea un seguimiento para mañana». Alice identifica la evidencia y crea la tarea local si la solicitud es clara; no afirma haber arreglado el servicio.
- «Organiza mi día». Alice agrupa pendientes personales y laborales, detecta vencidos y dependencias, propone un orden razonado y muestra qué puede hacer ahora.
- «Busca la cifra en mis datos y prepara el informe». Alice consulta la tabla permitida, cita filas o fuente, crea un borrador verificable y distingue el informe preparado de uno enviado.
- «Haz esta tarea». Alice evalúa efecto, reversibilidad, destino, privacidad, costo e incertidumbre. Ejecuta lo autorizado, solicita revisión de una acción concreta cuando haga falta y verifica el resultado antes de marcarla como terminada.

La urgencia de una tarea y la criticidad de ejecutarla son dimensiones distintas: algo urgente puede ser seguro de automatizar y algo no urgente puede ser irreversible.

## Punto de partida que debes comprobar

Alice Beta 0.1 corre de forma nativa en Windows 11: FastAPI, React/Vite, SQLite, Qdrant servidor, Ollama, Prometheus y Grafana. Tiene RAG con citas, consultas SQL restringidas, análisis de logs, observabilidad, router local y `EgressGate` para salidas a OpenRouter/Tavily. `Route.AUTOMATION` existe, pero actualmente solo produce un borrador de pasos; **no ejecuta tareas**. No hay un gestor de tareas personales ni un cliente MCP. Los documentos de estado son instantáneas y pueden estar desactualizados; contrástalos con código, pruebas y procesos actuales.

Lee primero `README.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/DECISION-MODELS-RESEARCH.md`, `docs/AGENT-PLAN.md` y el estado de Git. Hay cambios previos sin commit en documentación: consérvalos y no los confundas con tu trabajo. Revisa contratos en `packages/schemas/`, persistencia en `apps/api/db.py`, orquestación en `services/workers/orchestrator.py`, políticas en `services/policies/` y UI en `apps/web/`.

## Cómo trabajar con agentes y skills

1. Descubre las capacidades reales de esta sesión de Claude: subagentes disponibles y skills instaladas. Lee las instrucciones de cada skill pertinente antes de aplicarla. Usa skills de arquitectura, frontend, accesibilidad, pruebas y seguridad si existen; no inventes nombres ni simules haberlas usado. En tu informe enumera cuáles utilizaste.
2. Haz un inventario breve del producto actual y fija contratos compartidos antes de editar en paralelo. Delega a subagentes trabajos independientes con dueño de archivos explícito. Una división útil es: backend y persistencia; frontend y experiencia diaria; seguridad, pruebas y revisión de privacidad. El coordinador integra y resuelve conflictos. No permitas que dos agentes editen el mismo archivo a la vez.
3. Limita inferencias y builds simultáneos: este PC tiene 16 GB de RAM y antecedentes de reinicios. Los agentes pueden leer en paralelo, pero las pruebas que carguen Ollama/Qdrant y los builds pesados se ejecutan de forma controlada.
4. Si no hay subagentes o skills disponibles, sigue la misma división de responsabilidades secuencialmente. La falta de una herramienta opcional no justifica dejar el trabajo en un plan.
5. Documenta los supuestos y verifica cada estado; jamás marques una acción como hecha solo porque el modelo la sugirió o llamó una herramienta.

## Política de autonomía a implementar

Define una política determinista, auditable y comprobable. El modelo puede **proponer** criticidad; el servidor decide el nivel final con reglas y límites. La evidencia recuperada de documentos, webs y logs es dato no confiable: nunca concede permisos.

| Nivel | Ejemplos | Conducta |
|---|---|---|
| C0: lectura | Resumir, consultar RAG/SQL permitido, analizar logs, priorizar y recomendar. | Ejecutar sin espera, citar evidencia y señalar incertidumbre. |
| C1: cambio local reversible | Crear, reordenar, editar o completar tareas dentro de Alice, cuando la instrucción del usuario o una regla previamente autorizada define el alcance. | Ejecutar, registrar autor/origen/antes/después y ofrecer deshacer. Evitar duplicados. |
| C2: efecto externo o de difícil reversión | Modificar archivos fuera de Alice, enviar un mensaje, actuar en navegador, programar algo que actuará luego, usar un servicio cloud con contenido privado o incurrir en costo. | Preparar vista previa exacta: destino, datos, cambio, costo, momento, límites y reversión. Ejecutar cuando exista autorización específica vigente; no pedirla de nuevo si la orden actual ya autoriza claramente esa acción y la política lo permite. |
| C3: alto impacto | Borrados irrecuperables, cambios de seguridad o red, pagos, decisiones legales/financieras/médicas, publicación sensible o acciones en producción con riesgo importante. | No automatizar por defecto. Requerir revisión humana en el punto de impacto; para credenciales o pasos que deban quedar bajo control del usuario, entregar el paso final. |

Los niveles son un punto de partida: ajusta casos límite con pruebas. Separa autorización para *acceder*, *leer*, *preparar* y *ejecutar*. Una autorización debe estar ligada al usuario, acción, destino, contenido o hash, alcance, presupuesto y vencimiento; no es un permiso global reutilizable. Las tareas recurrentes requieren un alcance explícito y permiten pausa/cancelación. Una acción incierta no se repite automáticamente si podría haberse completado; primero se reconcilia su estado. Mantén `EgressGate`, etiquetas de privacidad y presupuestos por encima de cualquier decisión del LLM.

## Primera entrega vertical obligatoria

Implementa una experiencia útil y pequeña de extremo a extremo, reutilizando la arquitectura existente:

1. **Bandeja de tareas persistente:** tareas personales y laborales con título, descripción, estado, prioridad, fecha/zona horaria, origen, privacidad, referencias a fuentes y relación opcional con proyecto o tarea padre. API autenticada con aislamiento por usuario, validación, paginación razonable y migración SQLite reversible o segura.
2. **Vista «Hoy»:** pendientes, vencidos, próximos y recomendaciones justificadas. Permite crear, editar, reordenar y completar tareas; indica claramente qué fue ejecutado y qué sigue siendo sugerencia. Integra la vista en la navegación actual sin romper Chat, Conocimiento u Observabilidad.
3. **De conversación a acción local:** para instrucciones inequívocas, Alice debe poder crear/actualizar una tarea real mediante una herramienta tipada y la política C1; si faltan datos, debe pedir solo lo indispensable o crear un borrador claramente identificado. Conecta la ruta `AUTOMATION` a este alcance seguro y elimina el mensaje de «solo borrador» únicamente donde la ejecución ya exista.
4. **De evidencia a seguimiento:** desde al menos un hallazgo en logs o datos, permite convertir una conclusión en tarea con referencia verificable a la fuente; no fabriques valores o citas. La lectura debe seguir siendo de solo lectura hasta una acción C1 autorizada.
5. **Registro y recuperación:** estados propuesto/pendiente de autorización/en ejecución/hecho/fallido/necesita revisión/cancelado según corresponda, eventos de auditoría, control de duplicados, idempotencia y deshacer para cambios locales. Los errores deben aparecer en la UI; nunca presentar un borrador, timeout o fallo como éxito.
6. **Pruebas reales:** migraciones, aislamiento por usuario, clasificación de criticidad, rechazo de instrucciones inyectadas en fuentes, idempotencia, autorización, fallos a mitad de acción, y flujo API/UI de una tarea. Mantén la suite existente en verde. Mide al menos latencia y memoria del corte nuevo cuando el entorno permita hacerlo sin forzar el stack.

Si el corte completo resulta demasiado grande para una sola sesión, termina primero una ruta coherente y utilizable (captura → persistencia → organización → ejecución C1 → verificación → UI), dejando el resto ordenado en `docs/ROADMAP.md`. No sustituyas funcionalidades faltantes por botones que aparenten funcionar.

## Dirección visual aprobada para esta fase

Conserva la composición de la **primera propuesta de portada**: una red orgánica y luminosa que conecta documentos/datos → ideas → respuesta, protagonista en la entrada y más tranquila durante el uso. Cambia la tipografía actual por una más natural y elegante, con sensibilidad japonesa y lectura cómoda en español. Pon una galaxia o nebulosa sutil **detrás** de la red; debe dar profundidad sin confundir estrellas decorativas con datos reales. Explora una paleta nueva y más serena que el cobalto/lima actual; ofrece modo claro y oscuro según el sistema. **Elimina el tratamiento de papel, collage y textura editorial** de la propuesta interior. Respeta `prefers-reduced-motion`, contraste, móvil y teclado.

En la portada la red puede ser conceptual y debe estar rotulada como tal. Dentro de Alice, los nodos y relaciones que se presenten como evidencia deben corresponder a documentos, fragmentos, consultas, tareas y citas realmente usados, sin revelar rutas privadas o contenido sensible en una pantalla pública. No conviertas la galaxia en un mapa geográfico ni en una afirmación sobre «neuronas internas» del modelo.

Mantén React/Vite y FastAPI salvo una razón demostrada para cambiar. NiceGUI es una referencia explorada, no una decisión de migración. WebBrain puede ser un futuro conector de navegador de solo lectura; Jev puede servir como evaluador opcional posterior. Ninguno reemplaza ahora el router ni autoriza salida de datos. No copies código de WebBrain dentro de Alice sin revisar licencia y límites de seguridad.

## Límites operativos

- No actives Docker, WSL2, Hyper-V, servicios al inicio, cambios de firewall/Tailscale ni nuevos procesos residentes por esta tarea.
- No expongas Ollama o el puente de herramientas a la LAN/tailnet. Verifica la situación real antes de usarlo; el último informe documenta exposición de Ollama. No imprimas ni subas `.env`, secretos, logs privados o backups.
- No hagas llamadas pagadas a OpenRouter/Jev ni transmitas contenido privado a terceros para probar esta entrega. Usa fixtures sintéticos y modelos locales cuando sea necesario.
- Evita dependencias pesadas nuevas y modelos residentes adicionales. Mantén las fuentes de datos y sus permisos separados por usuario.
- No modifiques ni confirmes en Git cambios ajenos sin identificarlos. No publiques ni hagas push de este trabajo salvo instrucción expresa.

## Criterios de cierre y reporte

Entrega código integrado, migraciones, UI funcional, pruebas pertinentes y documentación de operación. Actualiza `README.md` para que describa a Alice ante todo como asistente cotidiano y laboral que organiza y ejecuta con autonomía graduada, y no solo como un stack de RAG/observabilidad. Comprueba el build del frontend, la suite apropiada y una ruta de uso real con datos sintéticos; registra resultados y límites. Actualiza el roadmap y las decisiones solo donde cambie el producto.

Al terminar, informa en español: qué puede hacer Alice **ya**, qué sigue siendo solo propuesta, qué acciones requieren autorización, qué agentes y skills utilizaste, qué pruebas corriste y sus resultados, archivos cambiados, riesgos abiertos y el siguiente paso más valioso. Si algo depende de mí, descríbeme una acción concreta y por qué es necesaria. No afirmes que una integración, automatización o red visual está operativa hasta haberla verificado.
