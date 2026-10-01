"""Discover JPX Daily Report archive data endpoints.

Read-only HTML/JS inspection only. No auth, no trading.
"""
from __future__ import annotations
import json,re,ssl,urllib.parse,urllib.request

URL="https://www.jpx.co.jp/markets/statistics-derivatives/daily/index.html"
UA="crypto-paper-trader-public-jpx-daily-archive-discovery/1.0"

def get(url):
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"text/html,*/*"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20) as resp:
        return resp.read(6_000_000).decode("utf-8","replace")

def main():
    html=get(URL)
    hrefs=re.findall(r'''(?:href|src)=["']([^"'<>]+)["']''',html,re.I)
    refs=[]
    for h in hrefs:
        full=urllib.parse.urljoin(URL,h)
        low=full.lower()
        if any(k in low for k in ("daily","archive","json","xml","csv",".js")):
            refs.append(full)
    snippets=[]
    low=html.lower()
    for needle in ("archive","daily_report","json","ajax","select","2025"):
        pos=0
        while True:
            pos=low.find(needle,pos)
            if pos<0:break
            snippets.append(html[max(0,pos-240):min(len(html),pos+520)])
            pos+=len(needle)
    print(json.dumps({
      "page":URL,
      "html_bytes":len(html.encode("utf-8")),
      "refs":sorted(set(refs)),
      "snippets":snippets[:120]
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
