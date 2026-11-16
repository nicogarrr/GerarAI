# Unified ProPicks components

OpportunitiesView and TrackingView are not wired into the ProPicks page yet. The state notice keeps asOf only inside stale/retained data warnings. Unknown external reason codes use a neutral translated fallback. The data action checks all fields consumed by the view-model before exposing the response. Other contract fields pass through untouched; no scores are recalculated.

Independent test, coverage and visual verification for this revision are recorded in the pull request. Fixture values are illustrative, not live data.
