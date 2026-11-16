# Analyst target label on narrow chart

PriceCanvas observes its own width, not the window. Under480px the target's
line title is distance only (+50,00 %); no-distance target has empty title.
Full desktop title, target price, axis label, line color and upside/downside
color remain unchanged. Other price lines do not use the compact label.

27 focused tests pass, CompanyTechnicalChart98.49%lines89.51%branches. Test
resizes chart container358->900px and asserts compact/full label and price.
Remote range/error and no-distance paths covered too. Local Vitest3.2.7;
repository CI needed for lockfile versions and full build/type checking.

Actual React component and lightweight-charts library rendered in local Vite
fixture, synthetic60-day history/target. Captured390 and1440 Chrome, inspected
pixels: mobile target percentage and price readable without long title;
desktop full title remains. No production data or full Next route claim.

## Auditor coverage follow-up

Reproduced82.55%branches with lockfile Vitest5.1.0 and matching coverage-v8
5.1.0. Added real behavior cases for autoscale provider bounds/null/missing
range, failed remote range retry, since-buy Max history, falling and flat
price/SMA structures and null-volume/currency presentation. No production
implementation changes.31tests pass, full source97.95%lines91.47%branches
(93.02%statements90.16%functions) on5.1.0. Previous3.2.7 measurement is not the
release gate; these5.1.0 numbers supersede it. Captures remain unchanged.
