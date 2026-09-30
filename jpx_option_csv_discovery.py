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
    refs=[]
    for pat in (
        r'[^"' + "'" + r'<>\\s]{0,180}\\.csv[^"' + "'" + r'<>\\s]{0,180}',
        r'[^"' + "'" + r'<>\\s]{0,180}\\.json[^"' + "'" + r'<>\\s]{0,180}',
        r'[^"' + "'" + r'<>\\s]{0,180}\\.xml[^"' + "'" + r'<>\\s]{0,180}',
        r'[^"' + "'" + r'<>\\s]{0,180}(?:ajax|api|option-price)[^"' + "'" + r'<>\\s]{0,180}',
    ):
        refs.extend(re.findall(pat,text,re.I))
    text_snippets=[]
    low=text.lower()
    for needle in ("csv","json","xml","ajax","option-price","data-"):
        pos=0
        while True:
            pos=low.find(needle,pos)
            if pos<0: break
            text_snippets.append(text[max(0,pos-220):min(len(text),pos+420)])
            pos+=len(needle)
    print(json.dumps({
        "page":URL,
        "csv_links":sorted(set(csv)),
        "js_links":sorted(set(js)),
        "html_bytes":len(body),
        "refs":sorted(set(refs))[:200],
        "snippets":text_snippets[:120],
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
