# Fixtures sintéticos del contrato

Estos ejemplos son solo para pruebas, demo y desarrollo UI. No hay endpoints de fixtures en la API de producción y nunca deben contener datos personales reales.

- `chat-success.ndjson`: flujo exitoso local con una fuente privada persistida.
- `file-action.ndjson`: respuesta pública de una acción ya verificada.
- `conversation.json`: forma de `/api/conversations/{id}`, con referencias para rehidratar UI.

La suite real de API usa `tests/conftest.py` y almacenes SQLite/Qdrant temporales. Los ejemplos aquí no sustituyen esas pruebas.
