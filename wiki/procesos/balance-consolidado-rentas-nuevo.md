# Balance Consolidado Rentas Nuevo

## Estado

La herramienta automatica para esta planilla aun no esta implementada. Esta pagina deja aprendido el criterio de fuente por quarter, hoja y seccion, derivado del historico visible en `12.2025- Balance Consolidado Rentas Nuevo vF.xlsx`.

## Fuente fija por quarter

| Hoja | Seccion | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|
| `Inmosa` | Balance | Analisis | Analisis | Analisis | EEFF |
| `Inmosa` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Chañarcillo` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Chañarcillo` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Curicó` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Curicó` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Inmob VC` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Inmob VC` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Viña Centro` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Viña Centro` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Fondo Rentas` | Balance | EEFF | Analisis | Analisis | EEFF |
| `Fondo Rentas` | EERR | EEFF | EEFF | Analisis | EEFF |
| `Machalí` | Balance | Pendiente | Analisis | Pendiente | EEFF |
| `Machalí` | EERR | Pendiente | Analisis | Pendiente | Analisis |

## Notas

- Las hojas `Resumen`, `Consolidado ...` y equivalentes son salidas/resumen; no se deben usar como input aunque tengan fechas en D:K.
- `Machalí` solo tiene evidencia historica suficiente para Q2 y Q4 en el vF revisado. Para Q1/Q3 hay que confirmar con planillas futuras o con el usuario antes de automatizar.
- La regla general sigue siendo la misma: si aparece un caso no definido, mirar el mismo periodo del año anterior y clasificar por terminacion en `000`.

