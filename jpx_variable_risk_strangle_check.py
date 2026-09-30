"""Probe older JPX option-price CSV archive URLs.

Read-only availability check for historical daily files outside the current
50-business-day JSON listing. No authentication or trading.
"""
from __future__ import annotations
import json, ssl, urllib.error, urllib.request
from datetime import date

BASE="https://www.jpx.co.jp/automation/markets/derivatives/option-price/files/"
UA="crypto-paper-trader-public-jpx-archive-probe/1.0"

DATES=[
 "20260630","20260529","20260430","20260331","20260227","20260130",
 "20251230","20251128","20251031","20250930","20250829","20250731",
]

def check(ds):
    url=f"{BASE}ose{ds}tp.csv"
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Range":"bytes=0-255"})
    try:
        with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=15) as resp:
            body=resp.read(256)
            return {"date":ds,"status":resp.status,"bytes":len(body),
                    "content_type":resp.headers.get("Content-Type"),"url":url}
    except urllib.error.HTTPError as e:
        return {"date":ds,"status":e.code,"url":url}
    except Exception as e:
        return {"date":ds,"error":f"{type(e).__name__}:{e}","url":url}

def main():
    rows=[check(ds) for ds in DATES]
    print(json.dumps({"paper_only":True,"archive_probe":rows},ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
