"""Extract legacy JPX Daily Report OSE archive links for 2025 months.

Read-only. No authentication or trading.
"""
from __future__ import annotations
import json,re,ssl,urllib.parse,urllib.request

BASE="https://www.jpx.co.jp"
ROOT=BASE+"/automation/markets/statistics-derivatives/daily/json/"
UA="crypto-paper-trader-public-jpx-legacy-daily-links/1.0"
MONTHS=("202511","202510","202509","202508")

def get(url):
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"text/html,*/*"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20) as resp:
        return resp.read(6_000_000).decode("utf-8","replace")

def main():
    out={}
    for month in MONTHS:
        url=f"{ROOT}daily_report_{month}.html"
        html=get(url)
        hrefs=re.findall(r'''href=["']([^"'<>]+)["']''',html,re.I)
        links=[]
        for h in hrefs:
            full=urllib.parse.urljoin(url,h)
            low=full.lower()
            if ("ose" in low or "daily" in low) and (low.endswith(".zip") or low.endswith(".pdf")):
                links.append(full)
        # Also capture raw path-looking tokens in case links are data attrs.
        tokens=re.findall(r'''[^"'<>\s]+(?:\.zip|\.pdf)''',html,re.I)
        for t in tokens:
            full=urllib.parse.urljoin(url,t)
            if "ose" in full.lower() or "daily" in full.lower():
                links.append(full)
        out[month]={
          "url":url,
          "html_bytes":len(html.encode("utf-8")),
          "links":sorted(set(links))[:500]
        }
    print(json.dumps({"paper_only":True,"months":out},ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
