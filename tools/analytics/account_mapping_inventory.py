"""Reproducible, read-only inventory for Account Concept mappings."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from tools.analytics.account_concepts import AccountConceptCatalog


def render(db_path: Path, catalog: AccountConceptCatalog | None = None) -> str:
    catalog = catalog or AccountConceptCatalog.load()
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    try:
        lines = ["# Account concept mapping inventory v1", "", "| Concepto | Código | Nombre | Scope | Signo | Asignación | Unidad | Vigencia | Estado | Rationale |", "|---|---|---|---|---|---:|---|---|---|---|"]
        for concept in sorted(catalog._concepts.values(), key=lambda item: item.concept_id):
            for mapping in concept.mappings:
                where, params = ("cuenta_codigo=?", (mapping.code,)) if mapping.code else ("cuenta_nombre=?", (mapping.name,))
                if mapping.asset:
                    where += " AND activo_key=?"; params += (mapping.asset,)
                stats = conn.execute(f"SELECT COUNT(*), MIN(periodo), MAX(periodo) FROM raw_er_activo_line WHERE superseded_at IS NULL AND {where}", params).fetchone()
                validity = f"{mapping.valid_from or stats[1] or '—'}..{mapping.valid_to or stats[2] or '—'} ({stats[0]} filas)"
                lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in (
                    concept.concept_id, mapping.code or "—", mapping.name or "—", mapping.asset or "all assets",
                    mapping.sign_rule or "—", mapping.allocation, f"{mapping.unit}/{mapping.amount_field}", validity,
                    mapping.status.upper(), mapping.note or "—")) + " |")
        return "\n".join(lines) + "\n"
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("memory/agente_toesca_v2.db"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(render(args.db), encoding="utf-8")
