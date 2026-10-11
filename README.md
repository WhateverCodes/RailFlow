# RailFlow

A local railway timetable and disruption simulator with separate city authority, station master and passenger views. Maintenance planning is a supporting workflow.

See **START_HERE.md** for simple launch and demonstration instructions. Python 3.10+; standard library only. Start with `py -3 server.py`, then visit http://localhost:3010.

## Problem statement coverage

| Requirement | Implementation |
|---|---|
| Small fictional station with configurable platforms and gaps | Rivergate scenario: 8 trains, 3 platforms; platform count/gap settings in Train schedules. |
| Arrival/departure inputs and required platforms | Advertised timetable plus editable reported times; required-platform constraints retained. |
| No double occupancy; minimum gaps | Deterministic earliest-feasible scheduling, followed by independent validation. |
| Conflict reporting | Previous timetable audited under new conditions; train/platform conflicts listed. Every conflicting pair is reported, including nested overlaps. |
| Delays and timed closures | Explicit events, downstream delay propagation, revised platforms/times, reasons for changes. |
| Infeasibility | Calls that exceed the delay allowance or horizon are explicitly unscheduled. Partial schedules are labelled incomplete, even if their assigned calls pass checks. |
| Independent validator | `railflow/validator.py` imports no scheduler code. Checks identities, coverage, overlaps, gaps, required platforms, closures, dwell, reported timing, advertised departure and journey times. Failed revisions are rejected before saving. |
| Optional AI assistance | Small locally trained Naive Bayes intent classifier plus explicit slot extraction. User reviews structured disruptions. No AI platform assignment. |
| No live railway data | Train names, times, capacities, incidents and crews are synthetic. No live railway API is called. |

## Role differences

- Authority: district map, delay/early-arrival lists, full editable Simulation, train creation/import, settings and maintenance proposals.
- Station master: prominently marked own station, station timetable cards and hover details, own-station Simulation, assigned maintenance decisions and crews.
- Customer: origin/destination and upcoming direct trains only. No operations map, counters, simulation controls or mutations. Operational notes and crew details are excluded from customer API responses.

The homepage uses a locally included AI-generated realistic train image (see IMAGE_NOTES.md). Simulation clock controls have been removed. The fictional scenario has a fixed reference point of 08:10 for “upcoming” lists; it is not the wall clock or a real-time service. Maintenance progress is reported by the station master, with accepted work intervals still reserved in the timetable.

Customer colours: red if departure or destination arrival is delayed; yellow if a platform turnaround anywhere on the journey has at most three minutes of slack beyond the required gap; green otherwise. Yellow is a transparent rule-based risk indicator, not a probability prediction.

## Scheduling scope and limits

The algorithm chooses earliest feasible train times and platforms under the constraints. It is greedy, not globally optimal. The maximum extra arrival delay is 120 minutes and the planning horizon is two days. Early-arrival disruption reports retain advertised departure times. Explicit Simulation edits may advance departure when minimum dwell, journey time and platform constraints allow it; unmet requests are shown with explanations. Explicit min_run and min_dwell values separate mandatory travel/stop times from timetable recovery allowances. A delay incident applies at its reporting station; actual departures propagate downstream using minimum travel times. Without supplied minimums, full scheduled travel/dwell remains mandatory. Incidents report a minimum arrival offset against the advertised timetable; further constraints can cause more delay.

“Approach A/B → Platform → Exit A/B” describes a fictional access path derived from the assigned platform. These labels do not implement alternative geographic railway routes or shared approach-track conflicts. Inter-station signals, track occupancy, junction capacity, rolling-stock diagrams and crew driving hours are not modelled. Do not present this as a railway signalling or live dispatch system.

The maintenance module supports a free-window search, proposals, master acceptance/refusal, department/shift/overlap checks for assigned crews, and progress reports. It is an adapted workflow, not a complete port of every feature in the original maintenance prototype.

## Geography and attribution

The offline district reference map contains 48 conventional railway stations across Pune–Lonavala, Pune–Daund, Pune–Nira, Daund–Baramati and Daund–Bhigwan corridors. It excludes metro/proposed stations. It is a reference snapshot, not a certified exhaustive list of all stations in Pune district. Connections are schematic.

- District boundary and station geography: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL; [Pune district boundary](https://www.openstreetmap.org/relation/1986140).
- Khadki coordinate cross-reference: [Khadki railway station](https://en.wikipedia.org/wiki/Khadki_railway_station).
- Provenance is also included in `data/geography.json`. Real geography is used only as context; all operational data is fictional. The Rivergate scenario is entirely fictional.

## Storage and verification

SQLite stores the active state and revision snapshots in `local-data/railflow.sqlite3`. The folder is created automatically. Preview does not write. Saving rejects stale revisions so concurrent users cannot silently overwrite each other. Server-side role and station checks protect mutations. Drafts do not change this official state. Publishing rejects incomplete timetables as well as validation failures.

Run tests: `py -3 -m unittest discover -s tests -v`.

39 tests cover scheduling, independent validation, nested overlaps, closures, early arrivals, downstream propagation, overnight calls, infeasibility, editable reported times, maintenance, permissions, preview isolation, stale writes and customer data filtering. Browser checks cover all three role layouts, authority/master edit-and-apply flows, passenger results and a 390-pixel phone viewport.

Demo credentials are publicly displayed by design. This local server is not production authentication or deployment infrastructure. The full app works offline after extraction; AI interpretation also runs locally.


## Version 3 additions

- Full arrival AND departure before/after comparisons, downstream effects, requested-versus-feasible timing explanations, and the complete draft timetable.
- Generate a draft in Simulation; choose Push to official schedule to publish. Drafts are temporary and are discarded when navigating away or reloading. Other accounts see only the saved official timetable.
- Operating dates displayed as dd/mm/yy in all roles, including rollover to the next day. The authority can change the operating date for the entire scenario. All trains share that operating date; minute offsets can reach the following day.
- Excel-style vertical-time occupancy sheets: station platforms, all district stations (six columns per page), or all railway corridors. Select a date and scroll through the complete 00:00–24:00 day. These are interactive web sheets, not Excel files. Line views show movements, not railway-line capacity validation.
- Maintenance refusal form requires a reason and optionally accepts an alternative start/end datetime. Suggestions do not reserve capacity; the authority must propose a replacement job. Acceptance opens crew selection; approval is checked for crew count, department, station, shifts and overlap, then reviewed before publishing.
- Backlogs lists arrival/departure delays, turnaround risks, unscheduled calls and actual resolved occupancy/gap/closure conflicts. The conflict log starts with version 3 and does not invent records for old revisions.
- Compact editing tables fit desktop width; phone layout changes editable rows to cards.

The RailFlow4 folder was based on RailFlow3, including its saved state. The distribution ZIP omits local-data so it starts clean; to preserve your previous data after extracting the ZIP, stop both servers and copy your existing local-data folder into the new RailFlow4 folder before launching. Startup upgrades the copied database automatically and keeps earlier revisions.

Version 4 replaces built-in district train times with a varied fictional dataset and recovery allowances. Prior manual timing edits to replaced services remain in revision history. Custom services, maintenance jobs and incidents are retained. REC01 demonstrates staged recovery after changing its first departure from 09:25 to 10:25; platform constraints can limit recovery.
