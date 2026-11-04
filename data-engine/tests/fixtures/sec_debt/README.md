# Original SEC companyfacts corpus

Unmodified downloaded JSON, reproducibly gzipped. Each adjacent source manifest
records the observed URL, byte length and decompressed SHA256. Retrieval:
2026-11-04. Tests do not contact the network.

UNH Q3-2026 accession 0000731766-26-000266 reports DebtCurrent 5,617M and
LongTermDebtNoncurrent 68,714M. DebtCurrent, not LongTermDebtCurrent, is the
current concept at this closing date. Disjoint total is 74,331M. Cash is25,845M
and short-term investments2,704M. Cash-only net debt48,486M; including explicitly
reported current securities45,782M. These are distinct chosen policies, not a
single interchangeable net-debt figure.

PLTR Q3-2026 current securities6,942.117M, unrestricted cash3,619.414M,
restricted cash9.731M. No current-period complete borrowing concept in these
bytes: total/net debt remains N/D. Neither old zero nor narrative 'no significant
debt' supplies a current official zero. Restricted cash is not subtracted.

CHTR latest available duration here ends June30,2026. 6M CFO8,229M and PPE
capex5,726M. Q3 requested returns N/D with latest available end, never Q2/YTD.
Exact Q2 flows are available in the separate EX99 fixture parser; this selector
deliberately does not derive quarterly CFO by subtracting two YTD documents.
