import sys
sys.path.insert(0, r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts')
import importlib.util, os

# Reload tir module fresh
spec = importlib.util.spec_from_file_location(
    "tir",
    r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts\tir.py'
)
tir = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tir)

with open(r'C:\Users\raimundo.opazo\automation_agent\scripts\tir_tri_results.txt', 'w', encoding='utf-8') as f:
    for nemo in ['CFITOERI1A', 'CFITOERI1C', 'CFITOERI1I']:
        for kpi in ['tir_desde_inicio_contable', 'tir_desde_inicio_bursatil']:
            result = tir.calcular('serie', nemo, '2025-12', kpi)
            v = result.get('valor')
            pct = f"{v*100:.4f}%" if v is not None else "N/A"
            f.write(f"{nemo} {kpi}: {pct}\n")
            if result.get('advertencias'):
                for w in result['advertencias']:
                    f.write(f"  WARN: {w}\n")
        f.write("\n")

    # Also test PT
    for kpi in ['tir_desde_inicio_contable', 'tir_desde_inicio_bursatil']:
        result = tir.calcular('serie', 'CFITRIPT-E', '2025-12', kpi)
        v = result.get('valor')
        pct = f"{v*100:.4f}%" if v is not None else "N/A"
        f.write(f"CFITRIPT-E {kpi}: {pct}\n")
        if result.get('advertencias'):
            for w in result['advertencias']:
                f.write(f"  WARN: {w}\n")

    f.write("\n=== Debugging CFITOERI1A contable cashflows ===\n")
    # Manual debug
    from _common import get_conn, ultimo_dia_mes
    from datetime import date
    conn = get_conn()
    nemo = 'CFITOERI1A'
    fecha_corte = '2025-12-31'

    # Terminal from raw_ar_event_line
    vr_ar = conn.execute(
        "SELECT fecha, monto_uf_cuota FROM raw_ar_event_line "
        "WHERE nemotecnico=? AND detalle='VR Contable' AND fecha<=? AND monto_uf_cuota IS NOT NULL "
        "ORDER BY fecha DESC LIMIT 1", (nemo, fecha_corte)
    ).fetchone()
    f.write(f"Terminal VR Contable (raw_ar_event): {vr_ar}\n")

    # Cuotas totales aportes
    total = conn.execute("SELECT SUM(cuotas) FROM raw_ar_event_line WHERE nemotecnico=? AND detalle='Aporte'", (nemo,)).fetchone()
    f.write(f"Cuotas totales aportes: {total[0]}\n")

    # Primer VNA
    primer = conn.execute(
        "SELECT MIN(fecha) FROM raw_valor_cuota_contable_line WHERE nemotecnico=? AND tipo='contable' AND precio_uf IS NOT NULL", (nemo,)
    ).fetchone()
    f.write(f"Primer VNA contable: {primer[0]}\n")

    # Aportes post primer VNA
    post = conn.execute(
        "SELECT COUNT(*) FROM raw_ar_event_line WHERE nemotecnico=? AND detalle='Aporte' AND fecha >= ?",
        (nemo, primer[0])
    ).fetchone()
    f.write(f"Aportes post primer VNA: {post[0]}\n")

    # All aportes
    f.write("\nAportes:\n")
    rows = conn.execute(
        "SELECT fecha, detalle, monto_uf, cuotas, monto_uf_cuota FROM raw_ar_event_line "
        "WHERE nemotecnico=? AND detalle='Aporte' ORDER BY fecha LIMIT 10", (nemo,)
    ).fetchall()
    for r in rows:
        f.write(f"  {r[0]} {r[1]} monto_uf={r[2]} cuotas={r[3]} monto_uf_cuota={r[4]}\n")

    # All dividendos
    f.write("\nDividendos:\n")
    rows = conn.execute(
        "SELECT fecha_pago, monto_uf_cuota FROM raw_dividendo_line "
        "WHERE nemotecnico=? AND fecha_pago<=? AND superseded_at IS NULL AND tipo='dividendo' AND monto_uf_cuota IS NOT NULL AND monto_uf_cuota > 0 "
        "ORDER BY fecha_pago", (nemo, fecha_corte)
    ).fetchall()
    for r in rows:
        f.write(f"  {r[0]} div={r[1]}\n")

print("Done")
