# Semántica de los campos de renta en `raw_rent_roll_line` — v1

Fecha: 2026-08-28
Alcance: `raw_rent_roll_line` (era legacy) y hoja `RentRoll` de la planilla JLL v2.
Estado: **demostrado**. Habilita el backfill previsto en la migración `085`.
Script reproducible: `eval/analysis/audit_renta_uf_semantics.py`.

## Por qué existe este documento

El plan JLL v2 fija como target `renta_uf` = renta total UF y `renta_uf_m2` = tasa
UF/m². Cambiar la semántica de una columna con histórico exige demostrar primero
qué contiene hoy, no inferirlo. Una lectura preliminar comparó campos de **dos
filas distintas** y concluyó erróneamente que ninguna interpretación cerraba.

## Resultado — era legacy

Evaluado sobre las 1.198 filas vivas con `extra_json`, `m2 > 0` y `renta_uf ≠ 0`:

| Activo | `renta_uf × m2 == renta_esperada_total` | `renta_uf × m2 == renta_real` |
|---|---|---|
| Apo4501 | **592/592 — 100%** | 0/592 |
| Torre A | **329/329 — 100%** | 0/329 |
| Apo4700 | **230/230 — 100%** | 0/230 |
| Boulevard | **31/31 — 100%** | 0/31 |
| Apo3001 | 13/16 — 81,2% | 12/16 |

**Conclusión: `raw_rent_roll_line.renta_uf` es una tasa UF/m²/mes.** Coincide con
la fuente declarada en el código: `tools/db/ingest_rent_roll_validated.py:819` la
lee de la columna `"Renta Fija (UF/m2 /mes)"`, y el docstring de `:138` ya lo
afirmaba.

Los tres campos de renta del histórico son distintos y complementarios:

| Campo | Dónde vive | Qué es |
|---|---|---|
| `renta_uf` | columna | tasa contractual UF/m²/mes |
| `extra_json.renta_esperada_total` | JSON | total contractual UF/mes = `renta_uf × m2` |
| `extra_json.renta_real` | JSON | total **efectivo** del mes, con gracia y prorrateo aplicados |

Ejemplo (Apo4501, 2026-06, unidad `5`): `m2=238,2`, `renta_uf=0,300`,
`renta_esperada_total=71,449` (= 0,300 × 238,2 ✓), `renta_real=21,435`
(= 30% del contractual, por prorrateo del mes).

**Apo3001 queda al 81,2%**: 3 de 16 filas no cierran bajo ninguna hipótesis. Es
una muestra chica y el activo ya venía señalado por otra anomalía (su regla de
contribuciones se desvía −8,4% mientras las otras cuatro quedan bajo 2,1%).
Revisar antes de backfillear ese activo.

## Resultado — era JLL v2

Sobre las 1.724 filas de la hoja `RentRoll` con `gla > 0` y `renta_m2 ≠ 0`
(las 15.124 restantes son mayoritariamente estacionamientos con tasa 0):

```
renta_m2 × información_locatario_gla == renta_renta_real   →   1.718/1.724 = 99,7%
```

Las 6 excepciones son todas la unidad `703` de Apoquindo 4700, donde
`renta_m2 = 79,51` es un monto total mal colocado en la columna de tasa.

**Hallazgo importante: pese a su nombre, `renta_renta_real` de v2 es el total
_contractual_, no el efectivo.** Al computarse exactamente como tasa × área, su
equivalente legacy es `renta_esperada_total`, **no** `renta_real`.

### Consecuencia: v2 no trae renta efectiva en el rent roll

`Renta_real_Pesos` está 100% vacía en las 16.849 filas, y no hay otra columna con
gracia o prorrateo aplicados. La renta efectivamente facturada ya no vive en el
rent roll de v2: migró a la hoja `AuxiliarContable`, como movimientos de
`Ingreso por arriendo` por tercero.

Esto no es una pérdida de información a nivel de activo — el auxiliar la tiene
con más detalle — pero sí **a nivel de unidad**: el auxiliar sólo llega a
`(activo, tercero)`, porque `inmueble` y `centro_de_costo` vienen 100% vacías. Es
decir, en v2 no se puede reconstruir la renta efectiva por local.

## Mapeo para la migración

| Campo destino | Era legacy | Era JLL v2 |
|---|---|---|
| `renta_uf_m2` (tasa UF/m²) | valor actual de `renta_uf` | `renta_m2` |
| `renta_uf` (total UF contractual) | `extra_json.renta_esperada_total` | `renta_renta_real` |
| `renta_semantica` | `total_uf` tras el backfill | `total_uf` |

El backfill es una reasignación entre campos ya presentes: no reconstruye ni
estima nada. Debe correr por período completo para no violar el invariante de
semántica no mixta.

## Pendientes

- Resolver las 3 filas de Apo3001 antes de backfillear ese activo.
- Pedir a JLL que corrija la unidad `703` de Apoquindo 4700 (total en la columna
  de tasa).
- Decidir si se expone la renta efectiva por unidad como concepto discontinuado a
  partir del corte v2, o si se le pide a JLL reincorporarla al rent roll.

---

## Acoplamiento catálogo ↔ schema (aprendido durante la implementación)

`tools/datasets/catalog_v1.yaml` declara hoy:

```yaml
rent_rate_uf_m2: {field: renta_uf, unit: UF/m2, allowed_aggregations: [avg]}
```

Es coherente con la era clásica (donde `renta_uf` sí es la tasa) e incorrecto
para la era v2. La corrección natural es repuntar la medida a `renta_uf_m2` y
publicar `renta_total_uf` y `renta_semantica`, que es lo que expone la migración
091 en `v_rent_roll_semantic`.

**Pero el catálogo no puede adelantarse a la migración.** El catálogo es código
desplegado y el Analyst lo lee contra la DB productiva en vivo; la migración 091
está detrás del gate. Repuntar la medida antes de aplicar la migración deja al
Analyst consultando una columna inexistente — verificado: rompe
`tests/datasets/test_governed_dataset_executor.py`, que corre contra
`memory/agente_toesca_v2.db` directamente.

**Por eso el cambio de catálogo es un paso del gate, no del desarrollo.** Debe
aplicarse en el mismo commit que aplica las migraciones a producción:

| Elemento | Valor actual | Valor objetivo |
|---|---|---|
| medida `rent_rate_uf_m2` | `field: renta_uf` | `field: renta_uf_m2` |
| medida `rent_total_uf` | no existe | `field: renta_total_uf, unit: UF` |
| `fields` | sin renta desglosada | + `renta_semantica`, `renta_total_uf`, `renta_uf_m2`, `fuente_proveedor`, `fuente_formato` |
| `semantic_fields` | sin procedencia | + los mismos tres campos semánticos |
| dominio `unit_category` | sin `storage_unit_pending` | + `storage_unit_pending` (para `UG`) |
| dominio `renta_semantica` | no existe | enum `[total_uf, tasa_uf_m2, indeterminada]` |

Al hacerlo hay que actualizar en el mismo commit
`tests/datasets/test_rent_roll_semantics.py`, que fija el conjunto exacto de
`semantic_fields` — es un test de contrato, y el contrato cambia.

## Contribuciones: JLL vs interno (corrida de sandbox, 2026-08-28)

La ingesta completa del archivo en sandbox produjo 22 alertas de control
cruzado. La brecha **no es un desfase constante**, y es idéntica mes a mes entre
Apo4501 y Apo4700:

| Período | JLL Apo4501 | Interno | Δ | JLL Apo4700 | Interno | Δ |
|---|---|---|---|---|---|---|
| 2025-01 | −2.514,5 | −1.484,0 | +69,4% | −838,2 | −494,7 | +69,4% |
| 2025-04 | −2.166,7 | −1.465,3 | +47,9% | −722,2 | −488,4 | +47,9% |
| 2025-06 | −2.149,7 | −1.454,7 | +47,8% | −716,6 | −484,9 | +47,8% |
| 2025-11 | −2.401,4 | −1.439,2 | +66,8% | −800,5 | −479,7 | +66,8% |

Que el porcentaje sea **exactamente el mismo** en ambos activos cada mes indica
que el desacuerdo no es del split 75/25 ni del avalúo de un activo: es un factor
escalar sobre la misma base compartida. El piso de la serie ronda +47,9%, cerca
de +50% (= dividir por 2 en vez de por 3). Vale la pena plantearle esa hipótesis
a JLL en la consulta que ya está abierta.

Como control aparte, la regla interna reproduce el ER histórico ya cargado
dentro de ±1,5% en todo 2025–2026 (Apo4501: +1,3% en 2025-01, +0,2% en 2025-12,
−0,9% en 2026-05), así que la parametrización es sólida y la discrepancia está
del lado de JLL.
