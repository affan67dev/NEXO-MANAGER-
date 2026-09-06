import requests
URL="http://127.0.0.1:8080/v1/chat/completions"
def chat(messages):
    r=requests.post(URL,json={"messages":messages,"temperature":0.4,"max_tokens":500},timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
