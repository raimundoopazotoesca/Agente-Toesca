"""Persiste gastos PT desde JSON (extracción manual o vía LLM).
Uso: python scripts/ingest_pt_gastos_from_json.py <archivo.json>

Regla dura: sum(componentes) == total_gastos_operacion EXACTO (tolerancia 0).
"""
import json, sqlite3, sys
from datetime import datetime
from pathlib import Path

DB = Path(__file__).parent.parent / "memory" / "agente_toesca_v2.db"

COMP = ['ER.depreciaciones', 'ER.remun_comite', 'ER.comision_admin',
        'ER.honorarios_custodia', 'ER.costos_transaccion', 'ER.otros_gastos']
TOTAL_KEY = 'ER.total_gastos_operacion'
ALL_KEYS = COMP + [TOTAL_KEY]


def main(json_path):
    data = json.loads(Path(json_path).read_text(encoding='utf-8'))
    assert data['fondo'] == 'PT', f"fondo esperado PT, viene {data['fondo']}"
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ok, skip = 0, 0
    for p in data['periodos']:
        periodo = p['periodo']
        g_in = p['gastos']
        # Convertir miles → pesos si aplica
        mult = 1000 if p.get('en_miles_pesos', True) else 1
        gastos = {k: int((g_in.get(k) or 0) * mult) for k in ALL_KEYS}
        total = gastos[TOTAL_KEY]
        s = sum(gastos[k] for k in COMP)
        if s != total:
            print(f"  X PT {periodo}: NO cuadra exacto (sum={s:,}, total={total:,}, diff={s-total:,}) -- skip")
            skip += 1
            continue
        # Supersede activos existentes
        for cta in ALL_KEYS:
            cur.execute(
                "UPDATE raw_eeff_line SET superseded_at=? "
                "WHERE fondo_key='PT' AND periodo=? AND cuenta_codigo_canonical=? "
                "AND superseded_at IS NULL",
                (now, periodo, cta))
        src = f"EEFF PT {periodo} (manual)"
        for cta, monto in gastos.items():
            cur.execute(
                """INSERT INTO raw_eeff_line
                     (fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
                      source_file, source_sheet, source_row, file_hash, ingest_run_id,
                      loaded_at, cuenta_codigo_canonical)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ('PT', periodo, None, cta, monto, None,
                 src, 'ER (manual)', None, 'manual_v1', None, now, cta))
        print(f"  OK PT {periodo}: total={total:,}")
        ok += 1
    con.commit()
    con.close()
    print(f"\nResumen: {ok} OK, {skip} skip")


if __name__ == "__main__":
    main(sys.argv[1])
