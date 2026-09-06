import sqlite3,os
DB=os.path.expanduser("~/NEXO/data/memory.db")
def recent(limit=20):
    con=sqlite3.connect(DB)
    try:
        return con.execute("SELECT * FROM memories ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    except Exception:
        return []
    finally:
        con.close()
