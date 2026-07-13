#!/usr/bin/env python
"""Punto de entrada retirado para una ingesta CDG antigua e incorrecta.

El script anterior infería columnas y nemotécnicos, y escribía en tablas/vistas
que ya no forman parte del esquema canónico. Se conserva este archivo solo para
fallar de forma explícita si algún proceso histórico todavía intenta invocarlo.
"""

raise SystemExit(
    "scripts/extract_cdg_vc.py está obsoleto y fue deshabilitado para evitar "
    "datos incorrectos. Use: python -X utf8 -m tools.db.backfill "
    "ar_pt ar_apo dividendos"
)
