# Securities FX criterion change

New computed reports use `summary.securities_fx_criterion = dgt_native_gain_sale_date_v1`.
The securities gain is calculated in the security currency and converted once at
the available ECB sale-date rate. A later disposal of the currency is separate;
this patch does not implement a currency-disposal ledger.

Existing stored TaxReport JSON is NOT rewritten or silently deleted. After the
new backend is deployed, the owner must use the existing Regenerate action for
each affected fiscal year (POST /api/taxes/report/{year}/regenerate). That action
recomputes and updates that tenant's report. Keep an export of the previous report
for comparison. Reading a stored report before regeneration still returns the old
figures. The criterion marker distinguishes new calculations from legacy reports.
Do not treat any old stored report as recalculated until that marker is present.
No production regeneration was performed by this PR.

Review by a qualified Spanish tax adviser remains recommended. The zero-gain test
uses synthetic amounts to reproduce the 0.00 versus -123.08 EUR discrepancy; it
is not a verbatim transcription of the entire consultation.
