import urllib.parse, urllib.request, re, html

def search_web(query, max_results=5):
    q=urllib.parse.quote(query)
    url="https://html.duckduckgo.com/html/?q="+q
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req,timeout=15) as r:
            page=r.read().decode("utf-8","ignore")
        results=[]
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',page,re.S):
            link=html.unescape(m.group(1))
            title=re.sub("<.*?>","",html.unescape(m.group(2))).strip()
            if title and link:
                results.append({"title":title,"url":link})
            if len(results)>=max_results: break
        return results
    except Exception as e:
        return {"error":str(e)}
