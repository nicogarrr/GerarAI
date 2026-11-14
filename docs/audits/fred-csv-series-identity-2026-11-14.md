# FRED CSV must identify the requested series

`series_csv("DGS10")` previously accepted any CSV whose first column was a
date label. A controlled `observation_date,CPIAUCSL` response passed as DGS10,
was marked healthy and reached the WACC writer as a Treasury observation.
This is a reproduced validation gap, not a claim that FRED or production
actually returned a wrong series.

The fix requires exactly two columns, a supported date label and the
requested series name. Name matching ignores case and surrounding spaces.
The standard CSV reader handles quoted headers and a BOM; the legacy DATE
label remains supported. An incorrect or ambiguous header records a source
failure and raises before WACC can save a financial fact or FRED document.

Source check on 2026-11-14, HTTP 200 without a key:
https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10

Observed prefix:

```csv
observation_date,DGS10
1962-01-02,4.06
1962-01-03,4.03
```

Red first: six wrong/ambiguous headers and the real CSV-to-WACC integration
failed to reject them. The quoted/BOM valid-header control also failed on
the old parser. With the fix, 57 connector/WACC/free-source tests pass and
connector coverage is 86.00% including branches (gate 85%). No database
migration, UI, model calls, paid service or deployment is part of this fix.
