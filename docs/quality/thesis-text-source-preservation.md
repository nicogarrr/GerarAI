# Thesis text: preserve source content

Base main ac7490c7. Red regression first (c7db106), then implementation.
The old cleanThesisText rewrites snake_case query keys and long decimals
inside URLs. It also changes None in English quoted headlines. Zone-free
ISO timestamps at23:30 were interpreted as UTC and rendered tomorrow in Madrid.

URLs and fenced code now pass through unchanged in both cleaners. None is
localized only as a missing-value token (end/punctuation or field delimiter),
not in prose such as None of the above, or inside straight/curly quotations.
A zone-free date is formatted as a calendar date in UTC, preserving its day;
explicit Z/offset timestamps retain Europe/Madrid conversion. No persisted
thesis content, source URL destination or numeric model is modified.

Run: npx vitest run --config scripts/vitest-thesis-text.config.mts --coverage
and node --experimental-strip-types scripts/thesis-text-guard.test.ts.
47unit tests and7node guards pass; complete source file100%lines,97.5%branches.
Focused strict TypeScript passed on changed sources/tests and their imports.
Local Vitest3.2.7/Node22.23.4 were available; repository CI uses its lockfile
and still needs to run. No full frontend build/typecheck/production claim.

Auditor follow-up: contextual None rules now cover parenthesized field values,
closing delimiters and isolated inline-code None. English prose beginning
None followed by comma/semicolon remains unchanged, as do quoted field values.
The old fixture "... y None" was made an explicit "... y ROE: None" field;
end-of-sentence prose alone is no longer taken as missing data.49unit tests
and7node guards pass. Local branch measurement97.5%; Auditor measured96.66%
on the prior SHA in its environment, both above85; no cross-environment claim.
