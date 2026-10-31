import importlib.util,json,sys,math
from datetime import date
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('compare',Path(__file__).with_name('compare.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def toy():
 return [m.DailyBar(date(2020+i//12,i%12+1,d),100.+i) for i in range(48) for d in (1,28)]

def test_future_truncation_does_not_change_past_signals():
 bars=toy();short=bars[:60]
 a=m.levels_for(short);b=m.levels_for(bars)
 for strategy in m.STRATEGIES:
  assert a[strategy]=={p:v for p,v in b[strategy].items() if p<='2022-06'}

def test_orders_are_after_signal_and_equal_external_budget():
 levels={'2020-12':4,**{f'2021-{i:02}':1 for i in range(1,13)}}
 a=m.simulate(toy(),levels,'2021-01','2022-01','plain')
 b=m.simulate(toy(),levels,'2021-01','2022-01','nico_v1')
 assert a['contributed']==b['contributed']==1300
 assert a['first']=='2021-01-01'
 assert b['trades'][0]['level']==4 and b['trades'][1]['level']==1
 assert b['deployed']+b['cash']==pytest.approx(1300)
 assert all(t['spend']>=0 for t in b['trades'])
 assert b['cash']>=0

def test_constant_prices_no_market_dd_and_costs_reduce_value():
 bars=[m.DailyBar(b.day,100.) for b in toy()]
 levels={f'{y}-{i:02}':4 for y in range(2020,2024) for i in range(1,13)}
 a=m.simulate(bars,levels,'2021-01','2022-12','plain',0)
 b=m.simulate(bars,levels,'2021-01','2022-12','plain',25)
 assert a['max_drawdown']==pytest.approx(0)
 assert a['terminal']==pytest.approx(a['contributed'])
 assert b['terminal']<a['terminal']
 assert b['gain_on_contributed']==pytest.approx((1-.0025)**2-1)

def test_insufficient_window_is_not_fabricated():
 assert m.simulate(toy(),{'2020-12':1},'2021-01','2021-12','plain') is None

RESULTS_JSON=Path(__file__).with_name('results.json')

# Artefacto inmutable de la corrida 2026-10-30 (datos reales): NO esta en el
# repo (audit.json guarda los hashes; una descarga nueva trae ajustes
# revisados y no reproduce los mismos bytes — medido 2026-10-31). Sin el
# artefacto este test se salta de forma explicita: bateria declarada
# «4 pass, 1 skip», sin inventar datos.
@pytest.mark.skipif(not RESULTS_JSON.exists(),reason='artefacto results.json ausente (ver README): 4 pass, 1 skip declarado')
def test_actual_results_equal_budget_same_dates_and_no_insolvency():
 rows=json.load(open(RESULTS_JSON))
 grouped={}
 for r in rows:
  key=(r['symbol'],r['period'],r['cost_bps']);grouped.setdefault(key,[]).append(r)
  assert r['cash']>=-1e-8 and r['terminal']>=0
  assert r['deployed']+r['cash']==pytest.approx(r['contributed'])
  assert -1<=r['max_drawdown']<=0
 for rs in grouped.values():
  assert len(rs)==4
  assert len({r['contributed'] for r in rs})==1
  assert len({r['first'] for r in rs})==1
  assert len({r['last'] for r in rs})==1
