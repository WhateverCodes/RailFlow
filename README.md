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


## Scheduling improvements (October 2026)

The original `schedule(state)` remains the earliest-feasible baseline. Replanning now compares it with a minimum-disruption bounded search in `railflow/strategies.py`. The search uses the same constraints and scheduler, trying chronological order, required-platform priority, and up to six adjacent order swaps. Platform choices prefer lower delay and fewer changes from the previous timetable. Every candidate is independently validated; invalid candidates are excluded. Equivalent results keep the baseline. No external optimiser or AI platform selection is involved.

The objective is `total_call_delay + 5 * platform_changes + changed_calls + 10000 * unscheduled_calls`. One platform change costs the equivalent of five delay minutes; a changed call costs one. Fewer unscheduled calls always take precedence over this score. Hard violations cannot be traded for a better score. Total call delay sums `max(0, arrival lateness, departure lateness)` against advertised times. This is a call-level operational measure, not passenger delay. Maximum delay is the largest individual call lateness. Added delay sums positive increases from previous call lateness; new calls have no previous comparison.

The existing draft impact dashboard displays measured totals, added delay, platform changes, unscheduled calls, scores, validation/completeness and execution milliseconds. Search time includes all candidate scheduling and validation, baseline time includes its scheduling and validation. Comparisons use independent copies without altering input or the previous plan. Publication recomputes against the same revision. The search normally checks eight priority orders; when incomplete, it also checks up to twelve affected-train-first orders plus reversed and deadline orders. It remains bounded to at most 22 orders and earliest feasible choices for each platform; it is not globally optimal and does not enumerate deliberate waiting or every train order.

The local classifier remains in use, with explicit intent cues and checked slots. AM/PM closure times, hour-based durations and Rivergate's short name are supported. Missing, multiple, negated, tentative or conflicting requests require clarification and are not copied into the disruption form. The model score is uncalibrated. Interpretation does not alter state or assign a train platform. Natural language remains a narrow single-incident interface; use manual fields for unsupported descriptions and next-day times such as 24:15.

Platform-change explanations no longer infer congestion solely because the platform changed. Known closure/maintenance checks, actual scheduler blockers, timing propagation and recovered allowances support the displayed explanations. Unknown causes are expressed as verified assignment facts.

All writes of incomplete schedules are rejected, including requests that omit `publish`. Draft previews remain available for infeasible cases. Existing roles, routes, revision checks and independent validation remain in force. The original design is preserved; the final readability stylesheet increases text sizes and adds the requested status colours.

## Final usability and report exports

CSV controls export the full displayed dataset rather than only the current page. Editable timetable downloads include unsaved inputs and are labelled as unapproved. Occupancy-sheet CSV exports include all columns for the selected day. Revision history, backlogs and active disruptions offer CSV and PDF downloads, using authenticated server-side scope checks. History exports include all saved revisions. UTF-8 CSV preserves Hindi/Marathi and escapes spreadsheet formula prefixes.

For PDF downloads install the optional reporting dependencies once: `python -m pip install -r requirements-reports.txt`. The core app remains usable without them. PDF generation uses Windows Nirmala for Hindi/Marathi shaping; on another OS set `RAILFLOW_PDF_FONT` to a suitable licensed TrueType font. Missing source fields are explicitly marked unavailable. PDFs include actual revision data, scope metrics, generated time, repeated table headers and page numbers.

Incomplete drafts trigger additional bounded recovery orders without relaxing constraints. When recovery fails, publication remains disabled and the preview reports the affected stop, arrival bounds, dwell/gap and reservations. Independent validation, station-master approval, revision checks and role restrictions remain mandatory. The plain-language and reproducible-scenario controls were removed from the disruption screen; interpretation APIs and regression infrastructure remain available.

Final verification: `python -m unittest discover -s tests -v` passed 68 tests.
