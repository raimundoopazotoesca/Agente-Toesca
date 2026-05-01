---
tipo: concepto
nombre: "Fechas Excel — seriales"
actualizado: 2026-05-01
---

# Fechas Excel — Seriales

## Fórmula de conversión

```python
serial = (date - date(1899, 12, 30)).days
```

## Ejemplos

| Serial | Fecha |
|--------|-------|
| 46022 | 31-dic-2025 |
| 46112 | 31-mar-2026 |

## Dónde aplica

- CDG XLSX: columna D (Fecha/SF) en las hojas de fondos
- ER Curicó: fila 4 = fila de fechas (seriales)
- ER Viña: fila 6 = fila de fechas (seriales)
- NOI-RCSD: fila 7 = row de fechas; col CY = Ene 2026

## Vínculos

- [[conceptos/ooxml]]
- [[procesos/cdg-mensual]]
- [[procesos/noi-rcsd]]
