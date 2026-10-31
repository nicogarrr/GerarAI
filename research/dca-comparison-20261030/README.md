# Research only, not production

No formula change. Read report.md limitations before using the numbers.
The CSV and compact evidence were delivered to the owner conversation.
Raw downloaded histories and daily curves are not committed. They are retained
in the research evidence archive; audit.json contains hashes. Downloading again
may yield revised adjustments and does not reproduce identical historical bytes.

`download.py` resumes using manifest.json. For a new download use a fresh folder
or remove the manifest explicitly. Never silently replace the recorded run.
`compare.py` expects data/<symbol>.csv and writes results.json/results.csv.
The actual-data invariant test is explicitly gated: without the immutable
results.json artifact it reports a declared skip, so the suite is
«4 pass, 1 skip» (verified 2026-10-31). Re-running download.py + compare.py
regenerates the artifact from a fresh download, but revised adjustments mean
it is a NEW run, not the recorded one (measured: 55/64 CSV hashes differ,
up to +1 4X signal in two strategies). The synthetic tests cover
no-lookahead, equal budget, costs and constant-price invariants.

Source data retrieval is sequential with one second between symbols; no paid
services, broker connections, portfolio writes, alerts or production mutations.
