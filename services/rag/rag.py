import os,sqlite3,re
DB=os.path.expanduser("~/NEXO/data/memory.db")

def _tokens(text):
    return set(re.findall(r"[a-zA-Z0-9_]{3,}",text.lower()))

def retrieve(query,limit=8):
    q=_tokens(query)
    if not q or not os.path.exists(DB): return []
    con=sqlite3.connect(DB)
    try:
        rows=con.execute("SELECT * FROM memories ORDER BY id DESC LIMIT 500").fetchall()
    except Exception:
        return []
    finally:
        con.close()
    scored=[]
    for row in rows:
        text=" ".join(str(x) for x in row if x is not None)
        score=len(q & _tokens(text))
        if score: scored.append((score,text))
    scored.sort(key=lambda x:x[0],reverse=True)
    return [x[1] for x in scored[:limit]]

def build_context(query):
    items=retrieve(query)
    return "\n\n".join(f"[MEMORY {i+1}] {x}" for i,x in enumerate(items))
