# Research only, not production

No formula change. Read report.md limitations before using the numbers.
The CSV and compact evidence were delivered to the owner conversation.
Raw downloaded histories and daily curves are not committed. They are retained
in the research evidence archive; audit.json contains hashes. Downloading again
may yield revised adjustments and does not reproduce identical historical bytes.

`download.py` resumes using manifest.json. For a new download use a fresh folder
or remove the manifest explicitly. Never silently replace the recorded run.
`compare.py` expects data/<symbol>.csv and writes results.json/results.csv.
Tests need those results for the actual-data invariant test. They also test
synthetic no-lookahead, equal budget, costs and constant-price invariants.

Source data retrieval is sequential with one second between symbols; no paid
services, broker connections, portfolio writes, alerts or production mutations.
