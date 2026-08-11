# Fallback de Mistral para el asistente inmobiliario

## Objetivo

Agregar Mistral como último proveedor de respaldo del chat inmobiliario, sin modificar la prioridad de las tres claves Groq ni del fallback existente de Gemini.

## Diseño

El proveedor se configurará mediante `MISTRAL_API_KEY`, cargada desde el entorno por `config.py`. `tools/db_chat.py` agregará una entrada Mistral a la lista de proveedores con:

- nombre: `mistral`
- endpoint: `https://api.mistral.ai/v1`
- modelo: `mistral-large-latest`

La cadena resultante será `Groq 1 → Groq 2 → Groq 3 → Gemini → Mistral` cuando `DB_CHAT_PROVIDER=groq`. La lógica existente seguirá intentando el siguiente proveedor únicamente para errores de cuota o rate limit.

## Configuración y seguridad

Se documentará `MISTRAL_API_KEY` en `.env.example` y en los mensajes de configuración faltante. La clave real no se agregará al repositorio ni se imprimirá durante las pruebas.

## Pruebas

Se agregará una prueba determinística que valide que Mistral aparece después de Gemini en la cadena de proveedores configurados. También se ejecutarán las pruebas focales de `tests/test_db_chat.py` y una compilación de los módulos modificados.

## Fuera de alcance

No se cambiará el agente Gemini de `agent.py`, el orden de los proveedores existentes, el modelo de Gemini, ni el manejo general de errores del chat.
