import csv,io,json,ssl,urllib.request
from datetime import date,datetime,timedelta
D=date(2026,10,2); M=date(2026,10,7); B=10000; MULT=100
u=f"https://www.jpx.co.jp/automation/markets/derivatives/option-price/files/ose{D:%Y%m%d}tp.csv"
req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"})
raw=urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20).read()
for enc in ("utf-8-sig","shift_jis","cp932"):
 try: s=raw.decode(enc); break
 except: pass
rows=list(csv.reader(io.StringIO(s))); und=None; xs=[]
for r in rows:
 if len(r)<17 or r[0].strip()!="NK225MWE": continue
 try:
  if r[15].strip(): und=float(r[15])
 except: pass
 try:
  mat=datetime.strptime(r[2].strip(),"%Y%m%d").date(); strike=float(r[3]); prem=float(r[11])
 except: continue
 code=r[10].strip()
 if mat==M and code and 10<=prem<=30: xs.append({"code":code,"strike":strike,"maturity":r[2].strip(),"premium":prem})
if und is None: raise SystemExit("NO_UNDERLYING")
xs=[x for x in xs if x["strike"]>=und]
xs.sort(key=lambda x:(x["strike"]/und-1,x["premium"]))
chosen=[]; cash=B
for x in xs:
 cost=x["premium"]*MULT
 if cost<=cash and len(chosen)<4:
  y=dict(x); y["qty"]=1; chosen.append(y); cash-=cost
 if len(chosen)>=4: break
progress=True
while progress:
 progress=False
 for y in chosen:
  cost=y["premium"]*MULT
  if cost<=cash: y["qty"]+=1; cash-=cost; progress=True
for y in chosen: y["amount_yen"]=int(y["premium"]*MULT*y["qty"])
print(json.dumps({"date":str(D),"underlying":und,"eligible_count":len(xs),"candidates":chosen,"total_yen":int(B-cash),"cash_left_yen":int(cash)},ensure_ascii=False))
