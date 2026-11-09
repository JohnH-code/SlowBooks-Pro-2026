"""Match QuickBooks Desktop attachment folders to transactions (John's build).

QuickBooks keeps each transaction's documents in Attach/<company>/Txn/<TxnID>-<time>,
where <time> is when the document was attached (Unix seconds; the transaction is
saved seconds later) and TxnIDs run in the same order as Trans #. Given:

  1. the Custom Transaction Detail report (Dates All, columns Trans #,
     Entered/Last Modified, Type, Date, Num, Name, Memo, Amount) as CSV,
  2. a JSON {folder: [[file name, size], ...]} of the Txn folders,
  3. optionally a JSON {folder: text of its PDFs} for the uncertain ones,

it aligns folders to transactions in order (folders by TxnID, transactions by
Trans #) scoring: saved within 15 minutes after the attachment time; the
file name's words against the payee; an amount, cheque number or date in
the file name; amounts in the document's text. Writes match.json with a
confidence per folder (high / medium / low / none). Attach high and medium;
send low and none to the person to review.

usage: python3 qb_attachment_match.py txn-detail.csv folders.json [doc-text.json]
"""
import sys
import json, re, datetime, numpy as np, collections
EST=datetime.timezone(datetime.timedelta(hours=-5))
import csv as _csv
def _load_tx(path):
    rows=list(_csv.reader(open(path,encoding="latin-1")))
    hdr=rows[0]; idx={h:i for i,h in enumerate(hdr)}
    tx={}
    for r in rows[1:]:
        if len(r)<len(hdr) or not r[idx["Trans #"]].strip(): continue
        t=r[idx["Trans #"]]
        if t not in tx:
            tx[t]={"trans":int(t),"type":r[idx["Type"]],"mod":r[idx["Entered/Last Modified"]],"date":r[idx["Date"]],"num":r[idx["Num"]],"name":r[idx["Name"]],"memo":r[idx["Memo"]],"amt":0.0}
        try: a=float(r[idx["Amount"]].replace(",",""))
        except ValueError: a=0
        tx[t]["amt"]=max(tx[t]["amt"],abs(a))
    for t in tx.values():
        try:
            d=datetime.datetime.strptime(t["mod"],"%Y/%m/%d %H:%M:%S").replace(tzinfo=EST)
            t["ts"]=int(d.timestamp())
        except ValueError: pass
    return tx
tx=_load_tx(sys.argv[1]); folders=json.load(open(sys.argv[2]))
EST=datetime.timezone(datetime.timedelta(hours=-5))
T=sorted(tx.values(), key=lambda t:t["trans"])
N=len(T)
mod=np.array([t.get("ts",0) for t in T],dtype=np.int64)
dates=np.array([datetime.date.fromisoformat(t["date"]).toordinal() for t in T])
text=[(t["name"]+" "+t["memo"]+" "+t["type"]).lower() for t in T]
amts=np.array([t["amt"] for t in T])
DOC=json.load(open(sys.argv[3])) if len(sys.argv)>3 else {}
F=sorted(folders, key=lambda f:int(f.split('-')[0],16))
STOP=set("pdf jpg jpeg png heic scan img image resized statement statements invoice inv receipt the and from for order doc document copy page oct nov dec jan feb mar apr may jun jul aug sep sept page details payment wire processing were your".split())
def tokens(s):
    return {w for w in re.findall(r"[a-z]{3,}|\d{3,}",s.lower()) if w not in STOP and not re.fullmatch(r"20\d\d|\d{5,}",w)}
def money(s):
    out=set()
    for m in re.findall(r"\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+\.\d\d|\d+k)",s.lower()):
        try: out.add(round(float(m[:-1])*1000 if m.endswith('k') else float(m.replace(',','')),2))
        except: pass
    return out
NEG=-1e9
VOCAB=set()
for t in T:
    VOCAB|={w for w in re.findall(r'[a-z]{3,}',t['name'].lower()) if w not in STOP}
VOCAB|={w for t in T for w in re.findall(r'\b\d{3}\b',t['name'])}
VOCAB-={'inc','ltd','limited','canada','bank','group','services','the','john','herrnstein','alison','hill'}
dp_prev=np.zeros(N+1)
choice=np.zeros((len(F),N+1),dtype=np.int8)  # 0 skip folder(up),1 left,2 diag
scores_used={}; strongs={}
for i,f in enumerate(F):
    ts=int(f.split('-')[1]); fd=datetime.datetime.fromtimestamp(ts,EST).date().toordinal()
    names=" ".join(n for n,_ in folders[f]); tk=tokens(names); mn=money(names)
    gap=mod-ts
    s=np.full(N,NEG)
    timed=(gap>=-5)&(gap<=900)
    s[timed]=10-gap[timed]/120.0
    later=(gap>900)&((fd-dates)<=120)&((fd-dates)>=-45)
    s[later]=2.0
    strong={w for w in tk if w in VOCAB}; strongs[f]=strong
    dm=money(DOC.get(f,''))
    fdates=set()
    for y,mo,d in re.findall(r"(20[012]\d)[-_]?([01]\d)[-_]?([0-3]\d)", names):
        try: fdates.add(datetime.date(int(y),int(mo),int(d)).toordinal())
        except ValueError: pass
    nums=set(re.findall(r"(?<![\d,.$])(\d{1,4})(?![\d,]|\.\d)", names))
    for j in np.where(s>NEG)[0]:
        bonus=0
        if strong:
            bonus += 15 if any(w in text[j] for w in strong) else -8
        if mn and round(amts[j],2) in mn: bonus+=15
        elif dm and round(amts[j],2) in dm and amts[j]>=1: bonus+=12
        if fdates and min(abs(dates[j]-d) for d in fdates)<=3: bonus+=12
        if nums and T[j]["num"] and T[j]["num"] in nums: bonus+=15
        s[j]+=bonus
    # dp
    diag=np.concatenate(([NEG],dp_prev[:-1]+s))  # dp_new[j] from dp_prev[j-1]+s[j-1]
    cand=np.maximum(dp_prev,diag)
    ch=np.where(diag>dp_prev,2,0).astype(np.int8)
    dp_new=np.maximum.accumulate(cand)
    left=dp_new>cand
    ch[left]=1
    choice[i]=ch; dp_prev=dp_new
    scores_used[i]=s
# traceback
i=len(F)-1; j=N; match={}
while i>=0 and j>0:
    c=choice[i][j]
    if c==1: j-=1
    elif c==2: match[F[i]]=(T[j-1]["trans"], float(scores_used[i][j-1])); i-=1; j-=1
    else: i-=1
print("matched",len(match),"of",len(F))
conf=collections.Counter()
out=[]
for f in F:
    if f in match:
        tr,sc=match[f]; t=tx[str(tr)]
        level="high" if sc>=19 or (sc>=8 and not strongs[f]) else ("medium" if sc>=12 else "low")
    else: tr=None; sc=None; level="none"; t=None
    conf[level]+=1
    out.append({"folder":f,"files":[n for n,_ in folders[f]],"trans":tr,"score":sc,"level":level,
                "txn":None if not t else f'{t["type"]} {t["date"]} {t["num"]} {t["name"]} {t["amt"]:,.2f}'})
print(conf)
json.dump(out,open("match.json","w"),indent=0)
