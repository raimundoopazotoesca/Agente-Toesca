import sys
sys.path.insert(0, r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts')
from _common import get_conn
from datetime import date

conn = get_conn()
nemo = 'CFITOERI1A'
fecha_corte = '2025-12-31'

cuotas_totales = conn.execute(
    "SELECT SUM(cuotas) FROM raw_ar_event_line WHERE nemotecnico=? AND detalle='Aporte'", (nemo,)
).fetchone()[0]

# Terminal
vr_ar = conn.execute(
    "SELECT monto_uf_cuota FROM raw_ar_event_line "
    "WHERE nemotecnico=? AND detalle='VR Contable' AND fecha<=? AND monto_uf_cuota IS NOT NULL "
    "ORDER BY fecha DESC LIMIT 1", (nemo, fecha_corte)
).fetchone()
terminal = float(vr_ar[0])

rows = []

# Aportes y Disminuciones
for r in conn.execute(
    "SELECT fecha, detalle, monto_uf, cuotas FROM raw_ar_event_line "
    "WHERE nemotecnico=? AND detalle IN ('Aporte','Disminucion') ORDER BY fecha",
    (nemo,)
).fetchall():
    fecha, detalle, monto_uf, cuotas = r
    if not monto_uf or not cuotas: continue
    if detalle == 'Aporte':
        cf = -(monto_uf / cuotas_totales)
    else:
        cf = monto_uf / cuotas
    rows.append((fecha, detalle, cf, monto_uf, cuotas))

# Dividendos
for r in conn.execute(
    "SELECT fecha_pago, monto_uf_cuota FROM raw_dividendo_line "
    "WHERE nemotecnico=? AND fecha_pago<=? AND superseded_at IS NULL "
    "AND tipo='dividendo' AND monto_uf_cuota IS NOT NULL AND monto_uf_cuota > 0 ORDER BY fecha_pago",
    (nemo, fecha_corte)
).fetchall():
    rows.append((r[0], 'Dividendo', float(r[1]), None, None))

rows.sort(key=lambda x: x[0])
rows.append((fecha_corte, 'VR Contable (terminal)', terminal, None, None))

with open(r'C:\Users\raimundo.opazo\automation_agent\scripts\flujos_tri_1a.txt', 'w', encoding='utf-8') as f:
    f.write(f"Cuotas totales aportes: {cuotas_totales:,.0f}\n")
    f.write(f"Terminal VNA contable al {fecha_corte}: {terminal:.6f} UF/cuota\n\n")
    f.write(f"{'Fecha':<12} {'Tipo':<28} {'Flujo UF/cuota':>16} {'Monto UF total':>16}\n")
    f.write("-" * 80 + "\n")
    sum_neg = sum_pos = 0
    for r in rows:
        fecha, tipo, cf, monto_uf, _ = r
        monto_str = f"{monto_uf:>16,.2f}" if monto_uf else ""
        f.write(f"{fecha:<12} {tipo:<28} {cf:>16.6f} {monto_str}\n")
        if cf < 0: sum_neg += cf
        else: sum_pos += cf
    f.write("-" * 80 + "\n")
    f.write(f"{'TOTAL NEGATIVO':<40} {sum_neg:>16.6f}\n")
    f.write(f"{'TOTAL POSITIVO':<40} {sum_pos:>16.6f}\n")
    f.write(f"{'SUMA NETA':<40} {sum_neg+sum_pos:>16.6f}\n")
    f.write(f"\n{'Num flujos'}: {len(rows)}\n")

    # XIRR
    dates = [date.fromisoformat(r[0]) for r in rows]
    cashflows = [r[2] for r in rows]
    d0 = dates[0]
    years = [(d - d0).days / 365.0 for d in dates]

    def npv(r):
        return sum(cf / (1+r)**t for cf, t in zip(cashflows, years))

    lo, hi = -0.9999, 10.0
    for _ in range(300):
        mid = (lo + hi) / 2
        if hi - lo < 1e-9: break
        if npv(mid) * npv(lo) > 0: lo = mid
        else: hi = mid
    tir = (lo + hi) / 2

    f.write(f"\nXIRR resultado: {tir*100:.4f}%\n")
    f.write(f"VNA necesario para 3.276%: (ver script check_tri_flows.py)\n")

print("Done")
