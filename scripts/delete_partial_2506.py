import sqlite3
conn = sqlite3.connect('memory/agente_toesca_v2.db')
fhash = 'cf3cdcf0855ecdd6afc4479eb437ceede08cda51acfff92d5666e7f15ab93e87'
n = conn.execute("DELETE FROM raw_eeff_line WHERE file_hash=?", (fhash,)).rowcount
conn.execute("DELETE FROM ingest_run WHERE file_hash=?", (fhash,))
conn.commit()
print(f'Deleted {n} rows for 2506 partial ingest')
conn.close()
