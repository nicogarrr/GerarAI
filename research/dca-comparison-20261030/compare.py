import sys,json,math,pathlib,csv,statistics,hashlib
from dataclasses import replace
from datetime import date
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'data-engine'))
import pandas as pd
from app.services.dca_signal_engine import DailyBar,evaluate_series,DEFAULT_PARAMS
from app.services.dca_backtest import irr_monthly
ROOT=pathlib.Path(__file__).resolve().parent
PERIODS={'full':('2003-01','2026-09'),'2003-2009':('2003-01','2009-12'),'2010-2019':('2010-01','2019-12'),'2020-2026':('2020-01','2026-09'),'2005-2009':('2005-01','2009-12'),'2010-2014':('2010-01','2014-12'),'2015-2019':('2015-01','2019-12'),'2020-2024':('2020-01','2024-12'),'2025-2026':('2025-01','2026-09')}
STRATEGIES=['plain','nico_v1','drawdown36','combination_max']

def next_month(p):
 y,m=map(int,p.split('-'));return f'{y+(m==12):04}-{m%12+1:02}'

def simulate(bars,levels,start,end,strategy,cost_bps=10):
 first={}
 for b in bars:first.setdefault(b.day.strftime('%Y-%m'),b)
 orders={}
 for period,level in levels.items():
  p=next_month(period)
  if start<=p<=end and p in first:orders[first[p].day]=max(level,1)
 if len(orders)<12:return None
 first_order=min(orders)
 rows=[b for b in bars if first_order<=b.day and b.day.strftime('%Y-%m')<=end]
 cash=shares=units=0.;peak=nav=1.;maxdd=0.;contributed=deployed=0.;flows=[];counts={};trades=[];cash_final=0.;curve=[]
 for b in rows:
  value=shares*b.close+cash
  if units:nav=value/units
  if b.day in orders:
   amount=100.;units+=amount/nav;cash+=amount;contributed+=amount
   level=orders[b.day];counts[level]=counts.get(level,0)+1
   spend=min(cash,100. if strategy=='plain' else 50.*level)
   fee=spend*cost_bps/10000
   shares+=(spend-fee)/b.close;cash-=spend;deployed+=spend
   flows.append(-100.);trades.append({'day':str(b.day),'level':level,'spend':spend,'price':b.close,'fee':fee})
  value=shares*b.close+cash;nav=value/units
  peak=max(peak,nav);maxdd=min(maxdd,nav/peak-1.)
  curve.append((str(b.day),value,nav))
 terminal=shares*rows[-1].close*(1-cost_bps/10000)+cash
 flows.append(terminal)
 return dict(contributed=contributed,terminal=terminal,gain_on_contributed=terminal/contributed-1,irr=irr_monthly(flows),max_drawdown=maxdd,cash=cash,deployed=deployed,n_months=len(orders),counts=counts,first=str(min(orders)),last=str(rows[-1].day),trades=trades,curve=curve)

def levels_for(bars):
 nico=evaluate_series(bars,today=date(2026,10,1))
 dd=evaluate_series(bars,params=replace(DEFAULT_PARAMS,signal='drawdown',version='comparison-dd36'),today=date(2026,10,1))
 n={v.period:v.level for v in nico if v.status=='confirmed'};d={v.period:v.level for v in dd if v.status=='confirmed'}
 common=n.keys() & d.keys()
 return {'plain':{p:1 for p in common},'nico_v1':{p:n[p] for p in common},'drawdown36':{p:d[p] for p in common},'combination_max':{p:max(n[p],d[p]) for p in common}}

def main():
 manifest=json.load(open(ROOT/'manifest.json'));results=[];audit=[]
 for item in manifest:
  s=item['symbol']
  if item['status']!='downloaded':continue
  df=pd.read_csv(ROOT/'data'/f'{s}.csv');bars=[]
  for _,r in df.iterrows():
   c=float(r['Adj Close']);day=date.fromisoformat(str(r['Date'])[:10])
   if math.isfinite(c) and c>0:bars.append(DailyBar(day,c))
  if bars[-1].day<date(2026,9,29):audit.append({'symbol':s,'status':'incomplete_or_delisted_not_stitched','last':str(bars[-1].day)});continue
  levels=levels_for(bars)
  for period,(start,end) in PERIODS.items():
   for cost in ([0,10,25] if period=='full' else [10]):
    for strategy in STRATEGIES:
     result=simulate(bars,levels[strategy],start,end,strategy,cost)
     if result:
      result.update(symbol=s,panel=item['panel'],period=period,strategy=strategy,cost_bps=cost)
      if period=='full' and cost==10:
       (ROOT/'trades').mkdir(exist_ok=True);json.dump({'trades':result['trades'],'curve':result['curve']},open(ROOT/'trades'/f'{s}-{strategy}.json','w'))
      del result['trades'];del result['curve'];results.append(result)
  audit.append({'symbol':s,'status':'included','rows':len(bars),'sha256':hashlib.sha256((ROOT/'data'/f'{s}.csv').read_bytes()).hexdigest()})
 json.dump(results,open(ROOT/'results.json','w'),indent=2)
 json.dump(audit,open(ROOT/'audit.json','w'),indent=2)
 fields=[k for k in results[0] if k!='counts']
 with open(ROOT/'results.csv','w') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(results)
 summary=[]
 for panel in ['etf','stock_biased']:
  for period in PERIODS:
   for cost in ([0,10,25] if period=='full' else [10]):
    plain={r['symbol']:r for r in results if r['panel']==panel and r['period']==period and r['strategy']=='plain' and r['cost_bps']==cost}
    for strategy in STRATEGIES:
     rows=[r for r in results if r['panel']==panel and r['period']==period and r['strategy']==strategy and r['cost_bps']==cost and r['symbol'] in plain]
     if not rows:continue
     diff=[r['terminal']/plain[r['symbol']]['terminal']-1 for r in rows]
     irr=[r['irr'] for r in rows if r['irr'] is not None]
     summary.append(dict(panel=panel,period=period,cost_bps=cost,strategy=strategy,n=len(rows),median_terminal_vs_plain=statistics.median(diff),wins_vs_plain=sum(x>1e-8 for x in diff),median_irr=statistics.median(irr) if irr else None,median_drawdown=statistics.median(r['max_drawdown'] for r in rows),worst_drawdown=min(r['max_drawdown'] for r in rows),signals_2plus=sum(sum(v for k,v in r['counts'].items() if int(k)>=2) for r in rows),signals4=sum(r['counts'].get(4,0) for r in rows)))
 json.dump(summary,open(ROOT/'summary.json','w'),indent=2)
 for r in summary:
  if r['cost_bps']==10 and r['period'] in ['full','2003-2009','2010-2019','2020-2026']:print(r)
if __name__=='__main__':main()
