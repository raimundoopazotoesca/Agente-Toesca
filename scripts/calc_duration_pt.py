"""
Macaulay Duration para PT - créditos bullet con cuotas mensuales de interés.
Referencia: hoy = 2026-06-11
"""
from datetime import date
from dateutil.relativedelta import relativedelta

today = date(2026, 6, 11)

creditos = [
    {
        "key": "PT_TORREA_SECURITY",
        "saldo_uf": 1_705_313.76,
        "tasa_anual": 0.0415,
        "cuota_mensual_uf": 5_663.30,
        "fecha_venc": date(2029, 1, 11),
        # amortizaciones parciales
        "amorts": [
            (date(2026, 11, 1), 14_200),
            (date(2027, 11, 1), 14_200),
            (date(2028, 11, 1), 14_200),
        ],
        "cuton": 1_662_682,
    },
    {
        "key": "PT_BOULEVARD_SECURITY",
        "saldo_uf": 662_583.48,
        "tasa_anual": 0.0411,
        "cuota_mensual_uf": 2_200.28,
        "fecha_venc": date(2029, 1, 11),
        "amorts": [
            (date(2026, 11, 1), 5_800),
            (date(2027, 11, 1), 5_800),
            (date(2028, 11, 1), 5_800),
        ],
        "cuton": 645_170,
    },
]

def macaulay(c, today):
    r_monthly = (1 + c["tasa_anual"]) ** (1/12) - 1
    amort_dates = {a[0]: a[1] for a in c["amorts"]}

    # generar flujos mensuales desde el próximo mes hasta vencimiento
    flujos = []  # (years_from_today, cf_uf)

    cur_date = today.replace(day=11) + relativedelta(months=1)  # primer pago
    saldo_actual = c["saldo_uf"]

    while cur_date <= c["fecha_venc"]:
        t = (cur_date - today).days / 365.25
        interes = saldo_actual * r_monthly
        principal = amort_dates.get(cur_date.replace(day=1), 0)

        # en fecha vencimiento: devuelve saldo restante (cutón)
        if cur_date >= c["fecha_venc"]:
            principal = saldo_actual

        cf = interes + principal
        flujos.append((t, cf))
        saldo_actual -= principal

        if saldo_actual <= 0:
            break
        cur_date += relativedelta(months=1)

    # Macaulay duration
    pv_total = sum(cf / (1 + c["tasa_anual"]) ** t for t, cf in flujos)
    mac_dur = sum(t * cf / (1 + c["tasa_anual"]) ** t for t, cf in flujos) / pv_total

    print(f"\n{c['key']}")
    print(f"  Saldo: UF {c['saldo_uf']:,.0f} | Tasa: {c['tasa_anual']*100:.2f}%")
    print(f"  Flujos generados: {len(flujos)} | Primer CF: {flujos[0]} | Último: {flujos[-1]}")
    print(f"  PV total: UF {pv_total:,.0f}")
    print(f"  Macaulay Duration: {mac_dur:.4f} años")
    print(f"  Tiempo a vencimiento: {(c['fecha_venc'] - today).days/365.25:.4f} años")
    return mac_dur, c["saldo_uf"]

results = [macaulay(c, today) for c in creditos]

# Duration consolidado (ponderado por saldo)
total_saldo = sum(r[1] for r in results)
dur_consolidado = sum(r[0] * r[1] for r in results) / total_saldo
print(f"\n=== Duration consolidado PT (ponderado por saldo) ===")
print(f"  Macaulay Duration: {dur_consolidado:.4f} años")
print(f"  (tiempo a vencimiento puro: 2.5896 años)")
