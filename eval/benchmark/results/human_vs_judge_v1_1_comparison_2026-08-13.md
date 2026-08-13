# Human vs. Rubric Judge v1.1 — segunda calibración

Fecha: 2026-08-13. Judge: `99830c7` + endurecimiento de rúbrica. Provider/modelo:
`mistral / mistral-large-latest`, igual al piloto histórico. Se reutilizaron
exactamente las 10 respuestas, ground truth, SQL y resultados persistidos de la
calibración ciega v1. Respuesta 4 (`model_non_answer`) y Respuesta 7
(`infra_failure`) se excluyen de los denominadores de calidad.

## Métricas por dimensión

`n` cuenta pares donde humano y judge entregaron score numérico. `NA mismatch`
cuenta desacuerdo entre score humano y `not_applicable` del judge, o viceversa.
Las diferencias son `|judge - human|`; `signed` es `judge - human`.

| Dimensión | v1 n / MAD / exact / ±1 / NA | v1.1 n / MAD / exact / ±1 / NA | signed v1.1 |
|---|---:|---:|---:|
| analytical_quality | 5 / 1.000 / 20% / 80% / 3 | 8 / 0.500 / 50% / 100% / 0 | +0.250 |
| grounding | 5 / 1.200 / 0% / 80% / 0 | 5 / 0.800 / 40% / 80% / 0 | +0.800 |
| hallucination | 5 / 1.200 / 20% / 60% / 3 | 8 / 0.500 / 62% / 88% / 0 | +0.250 |
| clarification_judgment | 8 / 0.125 / 88% / 100% / 0 | 8 / 0.625 / 62% / 88% / 0 | -0.375 |
| investigation_quality | 5 / 0.800 / 40% / 80% / 3 | 8 / 0.625 / 38% / 100% / 0 | -0.125 |
| output_usefulness | 8 / 0.500 / 50% / 100% / 0 | 8 / 0.750 / 25% / 100% / 0 | +0.500 |
| tool_correctness | 2 / 1.000 / 0% / 100% / 6 | 6 / 0.333 / 83% / 83% / 2 | +0.333 |

## Gates

| Gate | v1 exact / FP / FN | v1.1 exact / FP / FN |
|---|---:|---:|
| F1_fabrication | 6/8 / 0 / 2 | 6/8 / 1 / 1 |
| C4_unsupported_causality | 7/8 / 0 / 1 | 6/8 / 1 / 1 |

## Divergencias v1.1 mayores que 1

- Respuesta 2: grounding humano 2 vs judge 4; hallucination 2 vs 4; tool correctness 2 vs 4.
- Respuesta 10: clarification judgment humano 3 vs judge 0.

No hay divergencias mayores que 1 en analytical quality, investigation quality ni
output usefulness.

## Lectura de los casos solicitados

- Respuesta 2 / Strip Machalí: no detecta correctamente la transformación
  `vigente_hasta → contrato no renovado`; mantiene F1=false y puntúa 4 en las
  dimensiones principales. Es el principal falso negativo restante.
- Respuesta 8 / Apo: detecta correctamente la atribución externa no consultada
  “10–15% según CBRE/JLL” y activa F1.
- Respuesta 9 / TRI vacancia: limita analytical quality a 1, además de activar
  F1 y C4, por atribuir el driver a Viña Centro/error de reporte.
- Respuesta 10 / TIR: penaliza la investigación y tool correctness por el
  identificador incorrecto; scores 1 en ambas dimensiones y activa F1/C4.
- Respuestas Track A que aclaran innecesariamente: analytical e investigation
  ya no escapan mediante N/A (0 en las respuestas 1, 5 y 6). Grounding queda
  N/A para las aclaraciones puras; tool correctness aún queda N/A en respuestas
  5 y 6, de forma inconsistente con la regla de que una query era necesaria.

## Conclusión

La inflación sistemática se redujo: en los 51 pares numéricos v1.1 el sesgo medio
firmado es `+0.196` (17 positivos, 8 negativos, 26 exactos), frente a un patrón
histórico donde todas las comparaciones no empatadas favorecían al judge. La
mayoría de dimensiones queda dentro de ±1 y grounding queda en MAD 0.800, pero
no se cumple todavía “sin errores materiales claros” para F1/C4 por Respuesta 2,
ni el criterio de sesgo completamente desaparecido.

Recomendación: no congelar todavía v1.1. Hacer una única corrección general y
pequeña para que una inferencia causal específica no quede protegida por un
“sugiere que” cuando el ground truth solo respalda el hecho precedente; después
repetir esta misma muestra. No agregar casos ni tocar Track A/B antes de esa
verificación.
