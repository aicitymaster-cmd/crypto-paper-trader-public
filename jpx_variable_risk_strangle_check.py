"""Cleanly inspect legacy JPX Daily Report quote-PDF links.

Read-only discovery for selected months. Extract only the official
Quotations_Index_Futures_and_Options_and_Equity_Options PDF hrefs.
"""
from __future__ import annotations
import json,re,ssl,urllib.parse,urllib.request

BASE="https://www.jpx.co.jp"
ROOT=BASE+"/automation/markets/statistics-derivatives/daily/json/"
UA="crypto-paper-trader-public-jpx-clean-legacy-links/1.0"
MONTHS=("202511","202501","202401")

def get(url):
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"text/html,*/*"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20) as resp:
        return resp.read(8_000_000).decode("utf-8","replace")

def main():
    out={}
    pat=re.compile(r'''href=["']([^"']*Quotations_Index_Futures_and_Options_and_Equity_Options\.pdf)["']''',re.I)
    for month in MONTHS:
        url=f"{ROOT}daily_report_{month}.html"
        try:
            html=get(url)
        except Exception as e:
            out[month]={"error":f"{type(e).__name__}:{e}","url":url}
            continue
        links=[urllib.parse.urljoin(BASE,h) for h in pat.findall(html)]
        links=sorted(set(links))
        out[month]={
          "url":url,
          "count":len(links),
          "first":links[:3],
          "last":links[-3:],
        }
    print(json.dumps({"paper_only":True,"months":out},ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
