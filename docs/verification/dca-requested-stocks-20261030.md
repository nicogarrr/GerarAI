# Own DCA audit, 30 October 2026

Read at 16:48 UTC /17:48 CET. Yahoo Finance via yfinance1.7.0, USD.
Settled input through29October. Today30October is explicitly intraday only.
Formula nico-v1: monthly SMA30 gap divided by trailing monthly volatility/30%.
2X gap>=0, 3X>=10%, 4X>=20%; 24months minimum for4X.
These are price zones, not business-quality judgments or buy instructions.

|Ticker|29Oct close|29Oct zone|30Oct intraday|Illustrative zone|2X threshold|4X threshold|Daily adjusted peak drawdown29Oct|
|---|---:|---|---:|---|---:|---:|---:|
|AMZN|243.79|1X|239.24|1X|220.25|178.00|14.16%|
|NOW|109.67|4X|105.05|4X|160.28|111.52|53.15%|
|META|624.52|1X|620.26|1X|616.05|474.89|20.63%|
|GOOGL|283.82|1X|279.74|1X|243.42|193.32|29.42%|
|GOOG|282.32|1X|278.19|1X|243.64|193.92|29.16%|

None changes zone between29October close and the30October intraday snapshot. NOW is4X forming already, last confirmed September3X. Other four are1X both. META is near2X, but still above616.05 at the snapshot. Intraday low is not the settled close: a touch does not confirm a level.

Live production NOW profile says no DCA state evaluated, not1X. Coverage gap is proven; a motor arithmetic bug is not. Do not alter calibrated thresholds merely to match an expectation.

Sources, retrieved independently through public search as well as yfinance:
- https://finance.yahoo.com/quote/AMZN/history/
- https://finance.yahoo.com/quote/NOW/history/
- https://finance.yahoo.com/quote/META/history/
- https://finance.yahoo.com/quote/GOOGL/history/
- https://finance.yahoo.com/quote/GOOG/history/

Regression fixture: monthly adjusted closes captured from the full histories, all five tickers. 64 targeted engine/radar/batch/fixture tests pass. No production data changes or formula changes.
