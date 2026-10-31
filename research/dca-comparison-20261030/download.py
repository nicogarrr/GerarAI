import yfinance as yf,time,json,datetime,pathlib
root=pathlib.Path(__file__).resolve().parent
(root/'data').mkdir(exist_ok=True)
etfs='SPY QQQ DIA IWM EFA EEM XLF XLK XLE XLV XLI XLP XLU XLB XLY'.split()
stocks='AMZN NOW META GOOGL GOOG AAPL MSFT NVDA INTC IBM ORCL CSCO ADBE CRM PYPL NFLX TSLA BABA BIDU SNAP ROKU ZM PTON WBD PARA WBA GE F C BA DIS XOM CVX JPM BAC WFC JNJ PFE MRK KO PEP WMT TGT HD LOW MCD NKE MMM AIG T VZ'.split()
manifest=json.load(open(root/'manifest.json')) if (root/'manifest.json').exists() else []
done={x['symbol'] for x in manifest}
for panel,symbols in [('etf',etfs),('stock_biased',stocks)]:
 for s in symbols:
  if s in done:continue
  path=root/'data'/f'{s}.csv';row={'symbol':s,'panel':panel,'source_url':f'https://finance.yahoo.com/quote/{s}/history/','retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
  try:
   h=yf.Ticker(s).history(period='max',auto_adjust=False,timeout=12)
   if h.empty:raise ValueError('empty history')
   currency=yf.Ticker(s).fast_info['currency'];assert currency=='USD',currency
   h=h[h.index.strftime('%Y-%m-%d')<='2026-09-30']
   h.to_csv(path);row.update(rows=len(h),first=str(h.index[0]),last=str(h.index[-1]),currency=currency,status='downloaded')
   print(s,len(h),flush=True)
  except Exception as e:row.update(status='unavailable',error=repr(e));print(s,repr(e),flush=True)
  manifest.append(row);json.dump(manifest,open(root/'manifest.json','w'),indent=2)
  time.sleep(1)
