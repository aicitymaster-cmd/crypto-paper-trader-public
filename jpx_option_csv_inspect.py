"""Inspect JPX option-price CSV structure and mini-option identifiers."""
from __future__ import annotations
import csv, io, json, ssl, urllib.request

URL="https://www.jpx.co.jp/automation/markets/derivatives/option-price/files/ose20260930tp.csv"
UA="crypto-paper-trader-public-jpx-readonly/1.0"

def main():
    req=urllib.request.Request(URL,method="GET",headers={"User-Agent":UA,"Accept":"text/csv,*/*"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20) as resp:
        body=resp.read(8_000_000)
    text=body.decode("shift_jis","replace")
    rows=list(csv.reader(io.StringIO(text)))
    hits=[]
    for r in rows:
        joined=" | ".join(r)
        if "ミニ" in joined or "Nikkei 225 Mini" in joined or "日経225" in joined:
            hits.append(r)
    print(json.dumps({
      "url":URL,
      "row_count":len(rows),
      "first_rows":rows[:12],
      "matching_rows":hits[:80],
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
