"""Inspect JPX option-price CSV with official header."""
from __future__ import annotations
import csv, io, json, ssl, urllib.request

DATA_URL="https://www.jpx.co.jp/automation/markets/derivatives/option-price/files/ose20260930tp.csv"
HEADER_URL="https://www.jpx.co.jp/markets/derivatives/option-price/tvdivq00000014eu-att/head.csv"
UA="crypto-paper-trader-public-jpx-readonly/1.0"

def get(url):
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"text/csv,*/*"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20) as resp:
        return resp.read(8_000_000)

def dec(body):
    for enc in ("utf-8-sig","shift_jis","cp932"):
        try:return body.decode(enc)
        except UnicodeDecodeError:pass
    return body.decode("utf-8","replace")

def main():
    hrows=list(csv.reader(io.StringIO(dec(get(HEADER_URL)))))
    drows=list(csv.reader(io.StringIO(dec(get(DATA_URL)))))
    header=hrows[0] if hrows else []
    mapped=[dict(zip(header,r)) for r in drows[:30000]]
    samples=[]
    for row in mapped:
        vals=" | ".join(str(v) for v in row.values())
        keys=" | ".join(row.keys())
        if "NK225" in vals or "日経225" in vals or "Mini" in vals or "ミニ" in vals:
            samples.append(row)
            if len(samples)>=80:break
    print(json.dumps({
      "header_url":HEADER_URL,
      "data_url":DATA_URL,
      "header_rows":hrows[:4],
      "header":header,
      "row_count":len(drows),
      "samples":samples,
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
