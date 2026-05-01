---
tipo: concepto
nombre: "OOXML — XML directo en XLSX"
actualizado: 2026-05-01
---

# OOXML — Arquitectura XML directo en XLSX

## Por qué se usa

Para archivos grandes (14MB+, 87 hojas): XML directo es **3x más rápido** que openpyxl. El xlsx es un ZIP; se modifican solo los archivos XML internos necesarios.

## Archivos internos relevantes (CDG)

| Archivo XML | Contenido |
|-------------|-----------|
| `xl/worksheets/sheet15.xml` | Hoja A&R Apoquindo |
| `xl/worksheets/sheet16.xml` | Hoja A&R PT |
| `xl/worksheets/sheet17.xml` | Hoja A&R Rentas |
| `xl/tables/table2.xml` | Tabla133 (Apoquindo) |
| `xl/tables/table3.xml` | Tabla13 (PT) |
| `xl/tables/table4.xml` | Tabla1 (Rentas) |
| `xl/sharedStrings.xml` | Strings compartidos |
| `xl/worksheets/sheet3.xml` | Hoja Pendientes |

`SHEET_CFG` en el código define por hoja: `sheet_file`, `table_file`, `tabla`, `date_col`, `series`, `cuotas`, `has_bursatil`, `nemotecnico/nemotecnicos`.

## Formatos de celda XML

```xml
<c r="D189" s="1622"/>                           <!-- self-closing: sin valor -->
<c r="D189" s="1622"><v>46112</v></c>            <!-- con valor numérico -->
<c r="A189" s="106"><f>+YEAR(...)</f><v>2026</v></c>  <!-- con fórmula -->
<c r="E189" s="133" t="s"><v>821</v></c>         <!-- string compartido -->
```

## Reglas críticas

> **NUNCA usar regex `[^>]*` para parsear celdas** — falla con self-closing (`/>` contiene `/`).

Usar las helpers que escanean char-by-char:

| Helper | Qué hace |
|--------|----------|
| `_cell_has_value(sheet_xml, ref)` | `True / False / None` |
| `_find_cell_bounds(row_xml, ref)` | `(start, end)` |
| `_replace_or_insert_cell(row_xml, ref, new_cell)` | row_xml modificado |

## Filas pre-asignadas

Las 3 tablas tienen filas vacías con estilos y fórmulas N-Y (Libro/Bolsa) ya presentes. Solo rellenar columnas A-M.

## Columnas por hoja

A=YEAR, B=MONTH, C=ID, D=Fecha/SF, E=Detalle, F=Serie, G=Tipo, H=Monto$, I=Precio/cuota, J=Cuotas, K=UF, L=MontoUF, M=MontoUF/cuota, N-Y=Libro/Bolsa

## Fórmulas compartidas (solo A&R Rentas)

Columna C usa `<f t="shared" ref="C590:C621" si="127">`. **No sobreescribir si ya existe.**

## Vínculos

- [[agente/arquitectura]]
- [[conceptos/fechas-excel]]
- [[procesos/cdg-mensual]]
