# Toesca Analyst Mini-Dev v1 freeze

- **Mini-Dev ID:** `toesca-analyst-mini-dev-v1`
- **Fecha de freeze:** 2026-08-17
- **Commit base Ronda B:** `d423a2ead08db56296bf229f0a95cffef8b03050`
- **Origen:** Dev Set v1, `eval/benchmark/DEV_SET_V1_FREEZE.md`
- **Snapshot:** `592399a8e34c7111e4a9aaa84dd0002532d7a24ffb26f27c90e186647294125c`
- **Rubric:** v1.3; **Judge Impl:** 1.2.0

## Composición y cobertura

El manifiesto contiene exactamente 15 casos y 25 turnos: 10 TAE y 5 TCE.
Los TAE cubren L1, L2, L3, L4, L5, L6 y L8. La muestra cubre recuperación
factual, comparación, resumen, diagnóstico, investigación, decision support,
información insuficiente, incertidumbre y uso de herramientas. Los TCE cubren
ambigüedad, corrección, challenge de evidencia, investigación multi-dominio y
conversación analítica sostenida.

`mini_dev_v1.yaml` es una lista de IDs existentes más metadata de cobertura.
No duplica contenido de casos: el Dev Set congelado sigue siendo la única fuente
de prompts, comportamiento esperado, ground truth y restricciones.

## Política anti-bias

La selección, el orden y el hash del manifiesto se congelan antes de cualquier
output de los cinco candidatos. Todos reciben el mismo manifiesto y el mismo
orden. No se agregan, eliminan, reordenan o sustituyen casos por resultados de
un proveedor, ni se crean subsets por proveedor.

## Protocolo de ejecución B1_STANDARD

Cada candidato usa el mismo snapshot, catálogo semántico, esquema, herramienta
SQL de solo lectura y límite de cinco iteraciones de herramienta de Track B.
El modelo queda sticky dentro de una sesión; cada caso inicia una sesión nueva.
Habrá una ronda por candidato y no se repetirá un caso por calidad.

El perfil de inferencia es `B1_STANDARD`: se omiten `temperature`, `top_p` y
`seed` cuando no son comparables entre proveedores; no se prueba reasoning
`high` ni `max`. El mapping precomprometido es:

| Provider/model | Sampling efectivo | Reasoning efectivo |
| --- | --- | --- |
| Groq / `openai/gpt-oss-120b` | provider default (parámetros omitidos) | `medium`, default documentado del modelo |
| NVIDIA / `z-ai/glm-5.2` | provider default (parámetros omitidos) | provider default, sin escalamiento experimental |
| DashScope / `qwen3.8-max` | provider default (parámetros omitidos) | provider default, sin escalamiento experimental |
| Mistral / `mistral-large-2512` | provider default (parámetros omitidos) | provider default; sin override de reasoning |
| SambaNova / `MiniMax-M2.7` | provider default (parámetros omitidos) | modo estándar del proveedor; sin `high`/`max` |

El adapter Track B congelado actualmente envía `temperature=0.0`; este freeze
no lo modifica. Antes de ejecutar B1, el executor debe aplicar el mapping
anterior sin alterar prompts, contexto ni herramientas. Esa compatibilidad es
una precondición de ejecución, no una modificación realizada por este freeze.

Un único retry se permite sólo para `429`, `5xx`, red o timeout, respetando
`Retry-After` cuando exista. No se reintentan errores de protocolo, SQL inválido
generado por el modelo, agotamiento del loop ni no-respuestas.

## Failure taxonomy y telemetría

Clasificar por turno: `quota_rate_limit`, `provider_infra`, `timeout`,
`adapter_protocol`, `model_output_invalid`, `tool_sql_invalid`,
`tool_loop_exhausted`, `model_non_answer`, `snapshot_gate` y
`judge_unavailable`.

Persistir output crudo, estado, llamadas API/herramienta, SQL capturado, gates,
latencia, input/output/reasoning/cached tokens y costo observado. Los precios
preliminares viven en `eval/round_b/pricing.yaml`; no pertenecen al benchmark.

## Judge y política de selección

Gemini provisional continúa bloqueado por quota. Esto no bloquea el freeze.
Se pueden conservar outputs, deterministic graders, señales de infraestructura,
costo y SQL. Ninguna decisión final basada en analytical quality,
investigation quality, grounding cualitativo o usefulness se toma sin judge
válido/calibrado o revisión humana explícita. No se sustituye Gemini
automáticamente.

No se elimina un candidato sólo por scoring deterministic si el resultado
depende de dimensiones judge-only. La excepción son fallas fatales, factuales o
de protocolo cuya conclusión sea independiente del judge. Un candidato puede
sobrevivir por calidad superior, calidad/costo superior, capacidad analítica o
conversacional distintiva, o valor como baseline. Completion, éxito de
infraestructura/protocolo, grounding, hallucination, corrección de herramienta,
latencia, tokens y costo se reportan separadamente; no se reducen a un score.

## Costos preliminares

Los montos no son observados. Hasta instrumentar tokens, el presupuesto de
planificación por candidato es 0,40 M input y 0,04 M output; el techo operativo
provisional es 1,00 M input y 0,25 M output. `pricing.yaml` registra tarifas
públicas consultadas el 2026-08-17 y `unknown` cuando no existe una tarifa fiable.
