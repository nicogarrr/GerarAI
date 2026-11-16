# Visible scroll pattern on mobile rails

Base main ac7490c7. Red commit6feff7a:3component tests fail on the missing
scroll-affordance-x class. Identical change on five rails in three components:
CompanyNavigation, CalendarTabs and the3PoliticiansListSection filtergroups.
Replaces scrollbar-hide with the existing scroll-affordance-x pattern only.
No link, label, active-state, filter, data fetching or tab scroll behavior
changes. Existing CalendarTabs fades stay intact. Help and ChangesFeed are
not changed. Their old expectations stay intact; the Calendar/Politicians
expectations in the shared guard were updated to match the new requirement.

Run npx vitest run --config scripts/vitest-scroll-affordance.config.mts --coverage.
63tests pass; source coverage100%lines/branches for CompanyNavigation and
PoliticiansListSection,100%lines96%branches for CalendarTabs. Existing active
tab scrolling and filter lifecycle tests remain included.

Visual check: actual rendered component fixture at390x844 with Tailwind CSS
and the exact existing scroll-affordance CSS. All5rails compute thin scrollbar,
remain horizontally scrollable and do not wrap their controls. Desktop Chrome
headless may overlay/hide a scrollbar in a still screenshot, so computed
scrollbar-width and class tests are the evidence for the thin scrollbar;
this is not a production mobile Safari screenshot or a claim that every
browser displays the cue equally. Calendar's pre-existing negative margins
expect its page container; the isolated fixture is not the full page layout.

No production call, merge, deployment or spending. Local Vitest3.2.7 with
isolated dependencies; lockfile CI/full frontend typecheck still required.
