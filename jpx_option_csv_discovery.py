"""Discover JPX option-price CSV links from the official page.

Read-only GET to JPX. No authentication, account access, or trading.
"""
from __future__ import annotations
import json, re, ssl, urllib.parse, urllib.request

URL="https://www.jpx.co.jp/markets/derivatives/option-price/index.html"
UA="crypto-paper-trader-public-jpx-readonly/1.0"
TIMEOUT=20
MAX_BYTES=4_000_000

def main():
    req=urllib.request.Request(URL,method="GET",headers={"User-Agent":UA,"Accept":"text/html,*/*"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=TIMEOUT) as resp:
        body=resp.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES:
        raise RuntimeError("BODY_TOO_LARGE")
    text=body.decode("utf-8","replace")
    hrefs=re.findall(r'''(?:href|src)=["']([^"'<>]+)["']''',text,re.I)
    csv=[]
    js=[]
    for h in hrefs:
        full=urllib.parse.urljoin(URL,h)
        low=full.lower()
        if ".csv" in low:
            csv.append(full)
        if low.endswith(".js") or ".js?" in low:
            js.append(full)
    print(json.dumps({
        "page":URL,
        "csv_links":sorted(set(csv)),
        "js_links":sorted(set(js)),
        "html_bytes":len(body),
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
