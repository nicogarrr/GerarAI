# Ownership and home day rails

Existing scroll-affordance-x replaces hidden scrollbar rules only. No labels,
links, event selection or day calculations changed. Each component has a direct
rendered DOM assertion. 82 focused tests pass. EarningsDayStrip100/100 lines/
branches; ownership page97.76/96.11. ownership-en.test.tsx is excluded from this
focused config because it imports auth/nodemailer absent in local test deps;
no claim that the full ownership suite ran. Repository CI remains required.

390x844 screenshot uses actual rendered components, fixture values, Tailwind
and existing affordance CSS. Inspected labels/cards stay single line and clip
inside rails. Chrome headless overlay scrollbars are not conspicuous in pixels;
computed scroll cue does not prove discoverability on Safari. Pilot should
check horizontal interaction and cues on the whole production page.
