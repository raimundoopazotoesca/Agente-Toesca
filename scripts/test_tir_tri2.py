import sys
sys.path.insert(0, r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts')
import importlib.util

# Reload tir module fresh
spec = importlib.util.spec_from_file_location(
    "tir",
    r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts\tir.py'
)
tir = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tir)

from _common import get_conn
conn = get_conn()

with open(r'C:\Users\raimundo.opazo\automation_agent\scripts\tir_tri_results2.txt', 'w', encoding='utf-8') as f:
    # Test with correct KPI names
    for nemo in ['CFITOERI1A', 'CFITOERI1C', 'CFITOERI1I', 'CFITRIPT-E']:
        for kpi in ['tir_contable_desde_inicio', 'tir_bursatil_desde_inicio']:
            result = tir.calcular('serie', nemo, '2025-12', kpi)
            v = result.get('valor')
            pct = f"{v*100:.4f}%" if v is not None else "N/A"
            f.write(f"{nemo} {kpi}: {pct}\n")
            if result.get('advertencias'):
                for w in result['advertencias'][:2]:
                    f.write(f"  WARN: {w[:200]}\n")
        f.write("\n")

    # Check dividendos 2024
    f.write("=== raw_dividendo_line ALL CFITOERI1A (all years) ===\n")
    rows = conn.execute(
        "SELECT fecha_pago, monto_uf_cuota, tipo, superseded_at FROM raw_dividendo_line "
        "WHERE nemotecnico='CFITOERI1A' ORDER BY fecha_pago"
    ).fetchall()
    for r in rows:
        f.write(f"  {r[0]} {r[1]} tipo={r[2]} superseded={r[3]}\n")

    f.write("\n=== raw_dividendo_line 2024 all nemotecnicos ===\n")
    rows = conn.execute(
        "SELECT nemotecnico, fecha_pago, monto_uf_cuota, tipo FROM raw_dividendo_line "
        "WHERE fecha_pago LIKE '2024%' ORDER BY fecha_pago"
    ).fetchall()
    for r in rows:
        f.write(f"  {r[0]} {r[1]} {r[2]} tipo={r[3]}\n")
    if not rows:
        f.write("  (sin dividendos 2024)\n")

    # Check total aportes CFITOERI1A
    f.write("\n=== ALL aportes CFITOERI1A ===\n")
    rows = conn.execute(
        "SELECT fecha, detalle, cuotas, monto_uf_cuota FROM raw_ar_event_line "
        "WHERE nemotecnico='CFITOERI1A' AND detalle='Aporte' ORDER BY fecha"
    ).fetchall()
    for r in rows:
        f.write(f"  {r[0]} cuotas={r[2]} VNA={r[3]:.6f}\n")

print("Done")
