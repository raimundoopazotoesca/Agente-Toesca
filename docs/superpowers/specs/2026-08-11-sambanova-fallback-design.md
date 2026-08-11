# Fallback de SambaNova para el asistente inmobiliario

## Objetivo

Agregar SambaNova como último proveedor de respaldo del chat inmobiliario, después de Groq, Gemini y Mistral.

## Diseño

El proveedor se configurará mediante `SAMBANOVA_API_KEY`, cargada desde el entorno por `config.py`. `tools/db_chat.py` agregará una entrada SambaNova al final de `_PROVIDER_LIST` con:

- nombre: `sambanova`
- endpoint: `https://api.sambanova.ai/v1`
- modelo: `gpt-oss-120b`

La cadena resultante será `Groq 1 → Groq 2 → Groq 3 → Gemini → Mistral → SambaNova` cuando `DB_CHAT_PROVIDER=groq` y no exista DeepSeek configurado. Se reutilizará el manejo existente: SambaNova solo se intenta ante errores de cuota o rate limit.

## Configuración y seguridad

Se documentará `SAMBANOVA_API_KEY` en `.env.example` y en los mensajes de configuración faltante. La clave real no se agregará al repositorio ni se imprimirá durante las pruebas.

## Pruebas

Se ampliará la prueba de cadena de proveedores para exigir que SambaNova sea el último elemento. Se ejecutarán las pruebas focales de `tests/test_db_chat.py` y la compilación de los módulos modificados.

## Fuera de alcance

No se cambiará el orden de los proveedores actuales, el agente Gemini independiente de `agent.py`, ni el manejo general de errores del chat.
