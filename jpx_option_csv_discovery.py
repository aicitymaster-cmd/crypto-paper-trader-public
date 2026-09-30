"""Discover JPX option-price JSON and CSV links.

Read-only GETs to JPX. No authentication, account access, or trading.
"""
from __future__ import annotations
import json, ssl, urllib.parse, urllib.request

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-readonly/1.0"
TIMEOUT=20
MAX_BYTES=4_000_000

def get(url):
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"application/json,text/plain,*/*"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=TIMEOUT) as resp:
        body=resp.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES:
        raise RuntimeError("BODY_TOO_LARGE")
    return body

def main():
    data=json.loads(get(JSON_URL).decode("utf-8","replace"))
    rows=data.get("TableDatas") or []
    normalized=[]
    for r in rows:
        # Preserve raw keys because the page controls their exact names.
        item={"raw":r}
        for k,v in r.items():
            lk=str(k).lower()
            if any(x in lk for x in ("file","path","url")) and isinstance(v,str) and v:
                item["resolved_file"]=urllib.parse.urljoin(BASE,v)
            if "date" in lk or "day" in lk:
                item["date_value"]=v
        normalized.append(item)
    print(json.dumps({
        "json_url":JSON_URL,
        "count":len(rows),
        "rows":normalized,
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
