# Know your ballot

A plain, non-partisan guide to the parties and people asking for your vote in South Africa.

**Local**4 November 2026 **National**Due by 2029

Showing your municipal council election

## The parties

Search parties

The IEC certified 547 parties for 2026. This guide covers every party with seats in the National Assembly plus the most significant newcomers. Tick up to three boxes to compare.

## Side by side

Tick the box next to any party on the Parties tab to add it here. You can compare up to three at a time.

## Weighing parties by biblical principles of leadership

Scripture sets a high bar for those who govern: they should be honest, just to the poor, protective of life, and servants rather than masters. Christians agree on these principles but weigh them differently, so this lens lets you set the weights yourself. The ranking changes as you do.

**How to read this.** Each score is our summary of the public record and each party's stated positions as of 29 September 2026, and every score shows its reasons. Where there isn't enough evidence, we leave the principle blank rather than guess. Disagree with a score? Open the party and change it; your changes stay on this device. This is an aid to prayerful judgement, not a voting instruction.

### What matters most to you?

### Questions to ask anyone who wants your vote

In the ward ballot you choose a person, not only a party. Proverbs 18:17 says the first to speak seems right until someone asks questions. Ask these at a candidate meeting or on their social pages.

**Independence.** This guide is not affiliated with any party, church or the Electoral Commission. Party details come from manifestos, launch speeches and reporting by the IEC, Africa Check, Daily Maverick, TimesLIVE, News24, SABC, EWN and others, as of 7 October 2026. Positions change during a campaign; check the linked sources and the [IEC](https://www.elections.org.za/pw/) before you vote.

Official help: IEC contact centre 0800 11 8000. Voting stations open 07:00 to 21:00 on 4 November 2026.
## Live results

The **Live results** tab shows the 2026 count by province, metro, district, council and ward.

The IEC's results feed (`results.elections.org.za/dashboards/lge/MapsJason/…`) can't be read by browsers on other sites (it sends no CORS headers). So the `Live results relay` GitHub Action runs `scripts/fetch_results.py` about once a minute. It condenses the national and nine provincial feeds into `live.json` (about 150 KB when complete) and force-pushes it as a single commit to the `live-data` branch, so no Pages builds are triggered. The page reads it from `raw.githubusercontent.com` once a minute and falls back to `results/live.json` on `master`.

- GitHub's cron is best effort, so each run loops for 25 minutes and then starts the next run itself. The 5-minute schedule is only a backstop. Chaining stops when counting is complete, or after 12 November 2026. After that, disable the workflow in the Actions tab.

- Run the relay by hand from the Actions tab (**Run workflow**), or locally with `python3 scripts/fetch_results.py`.
- Test with full 2021 results: `python3 scripts/fetch_results.py --event 1091 --year 2021`. The page shows a "Test data" banner. Run it again without arguments afterwards so you don't commit 2021 data.
- District figures add up each district's local councils, because the feed doesn't publish district councils' own results.
- The province feed lists only each council's top three parties. For councils whose count moved, the relay also fetches the IEC's per-council file (`EEID…Munic{id}.js`, every party) and stores it as `all`: metros every minute, others at most every 5 minutes, up to 40 files a run. The coalition builder and the full party-vote lists use it.
- `results/base2021.json` holds the 2021 result per council, province and nationally, for the ▲▼ swing figures. Rebuild it with `python3 scripts/build_baseline.py`.
- Turnout: the IEC's "votes cast" counts ballots, and each voter casts two for their council (ward and party list), so the page shows voters as ballots ÷ 2. That matches the official 2021 turnout to within half a point. While counting, turnout is estimated against the share of voting districts counted, but only once at least half are in: districts that report early tend to be smaller, so earlier estimates run low. (The IEC's own turnout report covers only audited districts, which early on can be a single district.) The feed has no registered voters per ward, so wards show only the valid ward ballots counted (the relay stores these as `wt` from the per-council files).
- Ward votes per party go to `wards/<council>.json` on the `live-data` branch, written from the same per-council files. The Candidates tab loads the one it needs to show 2026 votes next to 2021. The feed has no candidate names (candidates are matched by party) and gives a ward's independents as one total.
- **Track live**: people can pin the country, a province, district, council or ward as live tiles at the top of Live results. Websites can't create iOS Live Activities or Android live notifications, so the site offers what the web allows: a floating pop-out window (Document Picture-in-Picture, Chrome and Edge on computers), alerts when a tracked area is declared, a ward is won or the lead changes (while the site is open), and the % counted as a badge on the installed app's icon.
- Installable: `manifest.webmanifest`, `sw.js` (no caching; it's there for install and alerts) and icons in `icons/` (`icon.svg` is the source; PNGs and `favicon.ico` were rendered from it with ImageMagick). `?tab=results` or `?tab=cands` opens a tab directly.
- Link straight to a council with `?council=JHB` (any IEC council code). The WhatsApp share buttons use this.
