# Balance Consolidado Rentas Apoquindo

## Resumen

Planilla trimestral que consolida:

- `Fondo Apoquindo`
- `Inmobilaria Apoquindo` (nombre de hoja tal como viene en Excel)

## Ubicacion de archivos

Planillas vF:

```text
SharePoint/Control de Gestion/Balances Consolidados/{YYYY}/{TQ}/
  {MM}.{YYYY}- Balance Consolidado Rentas Apoquindo vF.xlsx
```

EEFF Fondo Apoquindo:

```text
SharePoint/Fondos/Rentas Apoquindo/EEFF/{YYYY}/{TT}/
  Toesca Rentas Inmobiliarias Apoquindo {YYYY} {MM}*.pdf
```

EEFF Inmobiliaria Apoquindo:

```text
SharePoint/Fondos/Rentas TRI/Sociedades/Inmobiliaria Apoquindo/EEFF/{YYYY}/
  EEFF Inmobiliaria Apoquindo {MM}-{YYYY}*.pdf
```

## Regla general

Usa la misma regla de Balance Consolidado PT:

1. Para cada hoja y seccion (`balance` / `eerr`), mirar el mismo periodo del ano anterior.
2. Si todos los inputs terminan en `000`, la fuente es EEFF PDF en M$ y se multiplica por 1.000.
3. Si algun input no termina en `000`, la fuente es Analisis/Matriz en pesos directos.
4. Si la herramienta no sabe leer la fuente inferida, debe detener esa seccion y reportarlo.

## Fuente fija por quarter

Derivado del historico 2025 de la planilla `12.2025- Balance Consolidado Rentas Apoquindo vF.xlsx`. La herramienta usa esta tabla primero y deja la inferencia historica como respaldo.

| Hoja | Seccion | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|
| `Fondo Apoquindo` | Balance | EEFF | EEFF | EEFF | EEFF |
| `Fondo Apoquindo` | EERR | EEFF | EEFF | EEFF | EEFF |
| `Inmobilaria Apoquindo` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Inmobilaria Apoquindo` | EERR | Analisis | Analisis | Analisis | Analisis |

## Hojas

| Hoja | Tipo | Estado herramienta |
|---|---|---|
| `Fondo Apoquindo` | Input | EEFF PDF implementado |
| `Inmobilaria Apoquindo` | Input | Analisis/Matriz implementado; EEFF PDF como fallback |
| `Consolidado Apoquindo` | Output | No editar |
| `Resumen Fondo Apoquindo` | Output | No editar |

## Procedimiento

1. Copiar el ultimo `vF` y guardar como `{MM}.{YYYY}- Balance Consolidado Rentas Apoquindo vAgente.xlsx`.
2. Desplazar columnas historicas D:K hacia la derecha, sin insertar columna real.
3. Escribir fecha fin de trimestre en `D2` de las hojas input.
4. Inferir fuente con la regla historica.
5. Rellenar `Fondo Apoquindo` desde EEFF cuando corresponda.
6. Rellenar `Inmobilaria Apoquindo` desde Analisis/Matriz cuando la regla historica indica pesos directos.

## Logica Analisis/Matriz Inmobiliaria Apoquindo

La version asistida de diciembre 2025 trae una columna K en `BT` con formulas de ayuda. Esa columna sirve para documentar la logica, pero la herramienta no depende de ella.

La herramienta reconstruye los valores desde columnas estandar de `BT`:

| Columna BT | Uso |
|---|---|
| G | Activo |
| H | Pasivo |
| I | Perdida |
| J | Ganancia |

Mapeo principal de balance:

| Fila planilla | Cuenta | Logica |
|---|---|---|
| 7 | Efectivo | Activo de bancos `11.02.*` + fondos mutuos `11.03.50` |
| 8 | Deudores comerciales netos | Activo `11.05.10`, `11.06.01`, `11.07.10`, `11.07.35`, `11.07.40`, `11.07.45`, `11.08.01` menos pasivo/provision `11.07.15` |
| 9 | Activos por impuestos corrientes | Activo `11.10.13` |
| 13 | CxC entidades relacionadas NC | Activo `11.08.02` |
| 14 | Otros activos no financieros NC | Activo `11.07.55` |
| 15 | Propiedad de inversiones | Activo `12.01.01` |
| 17 | Activo por impuesto diferido | Activo `11.10.40` |
| 23 | Otros pasivos financieros corrientes | Pasivo `21.01.01` |
| 24 | CxP comerciales y otras | Pasivo `21.07.10`, `21.10.01`, `21.10.18`, `21.10.20`, `21.11.02`, `21.12.15`, `21.13.10`, `21.13.12` |
| 28 | Otros pasivos financieros NC | Pasivo `21.20.30` + `21.21.06` |
| 29 | CxP entidades relacionadas NC | Pasivo `21.21.01` a `21.21.04` |
| 35 | Capital emitido | Pasivo `24.01.10` |
| 36 | Otras reservas | Pasivo `24.01.60` |
| 37 | Resultados acumulados | negativo del activo `24.01.30` |
| 39 | Resultado del ejercicio | total general de `EERR` |

Para EERR, la herramienta usa la hoja `EERR` y copia los valores de `Total general` por codigo contable a las filas equivalentes de la planilla. Si la hoja `EERR` no viene, calcula cada cuenta desde `BT` como `Ganancia - Perdida`.

## Herramienta

- `actualizar_balance_consolidado_apoquindo(mes, año)`
