# CHTR financing-cost dry-run, 2026-11-04

Original SEC companyfacts bytes, gzip plus adjacent URL/SHA256 manifest. No
network tests. Source:
https://data.sec.gov/api/xbrl/companyfacts/CIK0001091667.json

Accession0001091667-26-000017 (filed2026-01-30) supplies FY25 cash interest4,983M,
net-interest expense5,042M, tax expense1,692M, pretax income7,458M. Opening term
debt93,933M, closing94,756M, mean94,344.5M. Historical cash Kd5.2817069358%.

Accession0001091667-26-000052 (filed2026-07-24) supplies6M26 cash interest2,506M
and6M25 comparative2,439M. TTM=4,983+2,506-2,439=5,050M, not halfyear annualized.
Mean term debt=(94,412+93,959)/2=94,185.5M. Historical cash Kd5.3617595065%.
TTM tax1,773M/pretax7,522M=23.5708588141% accounting ETR, NOT realized cash
interest shield. Net-interest proxy is distinct:5,042+2,532-2,504=5,070M.

Tests' market assumptions are illustrative, not current official evidence:
Rf5.10%, beta0.693, ERP4.33%, CRP0, equity14,309.630976M. Ke8.10069%, weights
E13.2167838893%/D86.7832161107%, accounting-ETR proxy WACC4.6269806692%.
This does not certify a current marginal cost of capital or authorize input
writes. Historical cash interest/average carrying term debt is a named proxy;
Equipment Installment Plan Financing Facility and other scope differences must
be reconciled by the caller before using a total-debt weight in production.
ETR is not statutory marginal tax, nor proof of deductible cash interest (163j).

The stale1.716883% output cannot be certified. Its documented defective operand
was846M interestFY2013 /94,756M debtFY2025=0.89281946% Kd: disjoint periods. The
new function will not pair those dates and does not clip WACC above terminal g.
No4557 capitalization bands,4559 or4565 fallback is used. Pure code based exactly
on d58af69c2bceeef83912b3a3d67882a0836b0913; live pilot recomputation remains
separate from these hand checks. No persistence or product wiring in this PR.
