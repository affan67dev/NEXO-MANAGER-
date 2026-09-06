import os,sqlite3
DB=os.path.expanduser("~/NEXO/data/memory.db")

def index_text(text,category="knowledge",source="local"):
    if not text.strip(): return False
    con=sqlite3.connect(DB)
    try:
        con.execute("INSERT INTO memories (category,content,source) VALUES (?,?,?)",(category,text,source))
        con.commit()
        return True
    except Exception:
        return False
    finally:
        con.close()
