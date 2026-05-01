---
tipo: concepto
nombre: "Números chilenos — formato CLP en Excel"
actualizado: 2026-05-01
---

# Números chilenos — Formato CLP en Excel

## Regla de parseo

| Cadena en Excel | Interpretación | Valor |
|-----------------|----------------|-------|
| `"1.234.567"` | Puntos = miles, sin decimales | `1234567.0` |
| `"1.234,56"` | Punto = miles, coma = decimal | `1234.56` |

## Regla general

- **Punto** → separador de miles
- **Coma** → separador decimal (si aparece al final)

## Vínculos

- [[procesos/noi-rcsd]]
- [[conceptos/ooxml]]
