"""Clave canónica de fondo — fuente única.

`dim_fondo` usa `TRI`, `PT`, `Apo`. Pero el prompt de EEFF, la UI y los CLI
históricos hablan de `APO` en mayúsculas, y `raw_eeff_line.fondo_key` referencia
`dim_fondo(fondo_key)`: persistir `APO` viola esa FK.

Las 18.009 filas históricas con `APO` entraron por `scripts/ingest_eeff.py`, que
abre la conexión con `sqlite3.connect()` sin `PRAGMA foreign_keys = ON`, así que
nadie las rechazó. La migración 058 las consolidó a `Apo`.

Regla: los alias se aceptan en la **entrada** (CLI, formularios, payloads); a la
DB se escribe siempre la clave canónica.

Ojo con las cuatro entidades distintas de Apoquindo — este módulo resuelve solo
la del fondo:
  - fondo  `Apo`      → Fondo Toesca Rentas Inmob Apoquindo
  - activo `Apo4501`  → Apoquindo 4501 (del fondo Apo)
  - activo `Apo4700`  → Apoquindo 4700 (del fondo Apo)
  - activo `Apo3001`  → Apoquindo 3001 (del fondo **TRI**)
"""
from __future__ import annotations

# alias en mayúsculas -> clave canónica de dim_fondo
_CANONICO: dict[str, str] = {
    "TRI": "TRI",
    "PT": "PT",
    "APO": "Apo",
    "APOQUINDO": "Apo",
}


def fondo_canonico(fondo: str) -> str:
    """Devuelve la clave canónica de un fondo. Si no se reconoce, lo deja igual
    (para no enmascarar una clave nueva con un silencioso fallback)."""
    if not fondo:
        return fondo
    return _CANONICO.get(fondo.strip().upper(), fondo)
