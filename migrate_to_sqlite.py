import sqlite3
import json
import os

MEMORY_DIR = os.path.join(os.path.dirname(__file__), "memory")
DB_PATH = os.path.join(MEMORY_DIR, "agente_toesca.db")
HISTORIAL_FILE = os.path.join(MEMORY_DIR, "historial.jsonl")
KPIS_FILE = os.path.join(MEMORY_DIR, "kpis.jsonl")
CONTEXT_FILE = os.path.join(MEMORY_DIR, "context.md")
UBICACIONES_FILE = os.path.join(MEMORY_DIR, "ubicaciones.json")

def _init_db():
    os.makedirs(MEMORY_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS historial_chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        fecha TEXT,
        instruccion TEXT,
        herramientas TEXT,
        resumen TEXT
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS kpis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        fecha_registro TEXT,
        fondo TEXT,
        periodo TEXT,
        kpi TEXT,
        valor REAL,
        unidad TEXT,
        fuente TEXT
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS contexto (
        username TEXT PRIMARY KEY,
        contenido TEXT
    )
    """)
    
    conn.commit()
    return conn

def migrate():
    conn = _init_db()
    cur = conn.cursor()
    default_user = "raimundo"

    # Migrate Historial
    if os.path.isfile(HISTORIAL_FILE):
        for line in open(HISTORIAL_FILE, encoding="utf-8"):
            line = line.strip()
            if not line: continue
            try:
                e = json.loads(line)
                fecha = e.get("fecha", "")
                instruccion = e.get("instruccion", "")
                herramientas = json.dumps(e.get("herramientas", []), ensure_ascii=False)
                resumen = e.get("resumen", "")
                cur.execute(
                    "INSERT INTO historial_chat (username, fecha, instruccion, herramientas, resumen) VALUES (?, ?, ?, ?, ?)",
                    (default_user, fecha, instruccion, herramientas, resumen)
                )
            except Exception as ex:
                print("Error history line:", ex)
        
        # Rename file to backup
        os.rename(HISTORIAL_FILE, HISTORIAL_FILE + ".bak")
        print("Historial migrado.")

    # Migrate KPIs
    if os.path.isfile(KPIS_FILE):
        for line in open(KPIS_FILE, encoding="utf-8"):
            line = line.strip()
            if not line: continue
            try:
                e = json.loads(line)
                cur.execute(
                    "INSERT INTO kpis (username, fecha_registro, fondo, periodo, kpi, valor, unidad, fuente) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (default_user, e.get("fecha_registro",""), e.get("fondo",""), e.get("periodo",""), 
                     e.get("kpi",""), e.get("valor",0), e.get("unidad",""), e.get("fuente",""))
                )
            except Exception as ex:
                print("Error kpi line:", ex)
                
        os.rename(KPIS_FILE, KPIS_FILE + ".bak")
        print("KPIs migrados.")

    # Migrate Context
    if os.path.isfile(CONTEXT_FILE):
        content = open(CONTEXT_FILE, encoding="utf-8").read().strip()
        cur.execute("INSERT OR REPLACE INTO contexto (username, contenido) VALUES (?, ?)", (default_user, content))
        os.rename(CONTEXT_FILE, CONTEXT_FILE + ".bak")
        print("Contexto migrado.")

    # Ubicaciones is usually global, we can leave it as JSON or move to DB.
    # Leaving it as JSON is fine since it's shared knowledge of where files live on the network.
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
