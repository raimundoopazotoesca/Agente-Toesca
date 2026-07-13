import sys
sys.path.insert(0, r'C:\Users\raimundo.opazo\.claude\skills\real-estate-finance-expert\scripts')
from _common import get_conn

conn = get_conn()

with open(r'C:\Users\raimundo.opazo\automation_agent\scripts\tri_flows_out.txt', 'w', encoding='utf-8') as f:
    # All event types for TRI
    f.write("=== Todos los detalle types en raw_ar_event_line para TRI ===\n")
    rows = conn.execute(
        "SELECT nemotecnico, detalle, COUNT(*) as n, SUM(monto_uf) as total_uf "
        "FROM raw_ar_event_line WHERE nemotecnico LIKE 'CFITOERI%' "
        "GROUP BY nemotecnico, detalle ORDER BY nemotecnico, detalle"
    ).fetchall()
    for r in rows:
        f.write(f"  {r[0]} | {r[1]} | n={r[2]} | total_uf={r[3]}\n")

    # Disminuciones
    f.write("\n=== Disminuciones CFITOERI1A ===\n")
    rows = conn.execute(
        "SELECT fecha, detalle, monto_uf, cuotas, monto_uf_cuota FROM raw_ar_event_line "
        "WHERE nemotecnico='CFITOERI1A' AND detalle='Disminucion' ORDER BY fecha"
    ).fetchall()
    for r in rows:
        f.write(f"  {r[0]} monto_uf={r[2]} cuotas={r[3]} uf_cuota={r[4]}\n")
    if not rows:
        f.write("  (ninguna)\n")

    # All aportes CFITOERI1A (complete list)
    f.write("\n=== ALL aportes CFITOERI1A ===\n")
    rows = conn.execute(
        "SELECT fecha, cuotas, monto_uf, monto_uf_cuota FROM raw_ar_event_line "
        "WHERE nemotecnico='CFITOERI1A' AND detalle='Aporte' ORDER BY fecha"
    ).fetchall()
    total_cuotas = 0
    total_monto = 0
    for r in rows:
        f.write(f"  {r[0]} cuotas={r[1]} monto_uf={r[2]:.2f} vna={r[3]:.6f}\n")
        total_cuotas += r[1] or 0
        total_monto += r[2] or 0
    f.write(f"  TOTAL cuotas={total_cuotas} monto_uf={total_monto:.2f}\n")

    # Simulate TIR manually to understand what VNA would be needed for 3.276%
    from datetime import date
    from _common import ultimo_dia_mes

    nemo = 'CFITOERI1A'
    fecha_corte = '2025-12-31'
    cuotas_totales = total_cuotas

    # Build cashflows like _calcular_tir_por_cuota does
    ar_rows = conn.execute(
        "SELECT fecha, detalle, monto_uf, cuotas FROM raw_ar_event_line "
        "WHERE nemotecnico=? AND detalle IN ('Aporte', 'Disminucion') ORDER BY fecha, id", (nemo,)
    ).fetchall()
    cashflows, dates = [], []
    for r in ar_rows:
        fecha, detalle, monto_uf, cuotas = r[0], r[1], r[2], r[3]
        if not monto_uf or not cuotas: continue
        if detalle == 'Aporte':
            cashflows.append(-(monto_uf / cuotas_totales))
        else:
            if fecha > fecha_corte: continue
            cashflows.append(monto_uf / cuotas)
        dates.append(date.fromisoformat(fecha))

    div_rows = conn.execute(
        "SELECT fecha_pago, monto_uf_cuota FROM raw_dividendo_line "
        "WHERE nemotecnico=? AND fecha_pago<=? AND superseded_at IS NULL "
        "AND tipo='dividendo' AND monto_uf_cuota IS NOT NULL AND monto_uf_cuota > 0 ORDER BY fecha_pago",
        (nemo, fecha_corte)
    ).fetchall()
    for fp, muf in div_rows:
        cashflows.append(float(muf))
        dates.append(date.fromisoformat(fp))

    combined = sorted(zip(dates, cashflows))
    dates_sorted = [c[0] for c in combined]
    cashflows_sorted = [c[1] for c in combined]

    f.write(f"\n=== Flujos acumulados (sin terminal) ===\n")
    f.write(f"  Num flujos: {len(cashflows_sorted)}\n")
    f.write(f"  Suma aportes (neg): {sum(c for c in cashflows_sorted if c < 0):.6f}\n")
    f.write(f"  Suma dividendos (pos): {sum(c for c in cashflows_sorted if c > 0):.6f}\n")
    f.write(f"  VNA terminal actual: 0.900923\n")

    # What VNA would give TIR = 3.276%?
    # NPV at r=3.276% without terminal, then find terminal needed to make NPV=0
    r_target = 0.03276
    d0 = dates_sorted[0]
    npv_without_terminal = sum(
        cf / ((1 + r_target) ** ((d - d0).days / 365))
        for cf, d in zip(cashflows_sorted, dates_sorted)
    )
    d_terminal = date.fromisoformat(fecha_corte)
    discount_terminal = (1 + r_target) ** ((d_terminal - d0).days / 365)
    # npv_without_terminal + terminal_needed / discount = 0
    terminal_needed = -npv_without_terminal * discount_terminal
    f.write(f"\n  Para TIR=3.276%, VNA terminal necesario: {terminal_needed:.6f}\n")
    f.write(f"  Para TIR=1.743%, VNA terminal actual: 0.900923\n")
    f.write(f"  Diferencia: {terminal_needed - 0.900923:.6f}\n")

print("Done")
