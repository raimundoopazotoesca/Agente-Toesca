import sqlite3

DB = 'memory/agente_toesca_v2.db'
con = sqlite3.connect(DB)
cur = con.cursor()

# PT debt with latest saldo
cur.execute("""
    SELECT c.credito_key, c.activo_key, c.acreedor, c.tipo_deuda,
           c.part_fondo, c.tasa_anual, c.fecha_vencimiento, c.estado,
           d.periodo, d.saldo_uf,
           (d.saldo_uf * c.part_fondo) AS saldo_uf_fondo
    FROM raw_deuda_saldo_line d
    JOIN dim_credito c ON c.credito_key = d.credito_key
    WHERE c.fondo_key = 'PT'
      AND d.periodo = (
          SELECT MAX(d2.periodo) FROM raw_deuda_saldo_line d2 WHERE d2.credito_key = d.credito_key
      )
    ORDER BY d.periodo DESC
""")
pt_rows = cur.fetchall()
print("PT deuda (último período por crédito):")
total_fondo = 0
for r in pt_rows:
    print(r)
    total_fondo += r[10] or 0

print(f"\nTotal PT (ponderado part_fondo): UF {total_fondo:,.0f}")

# Check periodos disponibles
cur.execute("""
    SELECT d.credito_key, d.periodo, d.saldo_uf
    FROM raw_deuda_saldo_line d
    JOIN dim_credito c ON c.credito_key = d.credito_key
    WHERE c.fondo_key = 'PT'
    ORDER BY d.credito_key, d.periodo
""")
print("\nTodos los períodos PT:")
for r in cur.fetchall():
    print(r)

con.close()
