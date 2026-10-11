# RailBlock AI — local railway maintenance planning

Local railway maintenance planning, crew coordination, progress tracking, saved reports, and observed-data model training. Both supplied CSV datasets are preserved. The operational planner uses supplied requests and a versioned planning register; the earlier generated scenario is available separately. Nothing is published.

## Operational block planning

Control Centre → **Block planner** now connects the supplied maintenance requests to saved planning inputs and department jobs.

1. **Sources & settings:** add the researched timetable for the chosen dates, or edit/import movements in **Train timetable**. The current catalogue contains 42 service/direction records for Pune–Lonavala, Pune–Daund and Pune–Miraj. It is explicitly incomplete public reference coverage. `npm run data:timetable` appends the next seven days locally without overwriting corrected records.
2. **Sections:** record the work section and source. Different section IDs on the same corridor still conflict conservatively; exact track topology is not assumed.
3. **Prepared requests:** choose a source request and record its exact work location/reference, reporting station, crew requirement, earliest start, deadline, power and machine needs. A shared compatibility group requires a recorded review reference. Original source duration, severity, department and corridor remain unchanged.
4. **Work windows:** enter the candidate work periods. Mark traffic coverage checked only after recording/reviewing passenger movements, freight and restrictions. Incomplete windows may support provisional draft planning, but cannot release work.
5. **Plans & release:** select prepared requests and generate a daily, weekly or monthly plan. CP-SAT checks full duration, setup allowance, train headway, deadlines, corridor exclusivity, machines and individual nearby worker shifts/bookings. Singles remain alternatives to compatible joint bundles. The comparison uses only identical requests served by both joint and separate-block schedules.
6. Accept the saved plan with a reason, then release it. Each scheduled request becomes a pending job in its owning department. Heads tick the named workers manually. Controller-approved times are locked in both the application and database. Crew eligibility is checked again at assignment.
7. Workers see their saved jobs, acknowledge them and report progress. Jobs released from blocks cannot be started outside their approved interval. Updated train conflicts appear as controller alerts and prevent new assignment/start. Unreleased plans can be regenerated against changed timings; released work remains fixed for explicit operational review.

Every register write and plan review uses revision checks. Release is transactional and rejects concurrent duplicate release. Roster/assignment changes invalidate earlier planning snapshots. The database additions preserve existing jobs, imported rows, passwords and sessions.

The operational department overview excludes simulated jobs from completion percentages. Existing demo history is retained separately in the database.

## Freight model training

Block planner → **Sources & settings** includes observed freight-history CSV import, training, chronological evaluation, saved candidate results and controller activation. At least 42 consecutive complete days per section are required, with the last 14 days held out. A Random Forest candidate is compared with a section/weekday/hour historical mean; activation requires the saved holdout gate to pass. Active forecasts are a bounded scheduling preference, never a substitute for protected train movements or checked work windows.

No observed railway freight model is active yet. No suitable public historical movement series for these three corridors has been obtained. The passenger timetable is not used as freight training history. See [data provenance, model contract and remaining dependencies](docs/observed-data-and-model-status.md).

## Saved PDF reports

Finalized schedule/crew sheets, full daily maintenance reports, workers' own daily assignments, saved operational block plans and daily block plans download directly as PDFs. Reports read saved server-side data, enforce role/department/worker scope and check plan revisions. Daily exports include overlapping overnight work and all matching records, regardless of UI pagination. Page-level print remains available separately.

## Start locally

Requires Node.js 22.13+ and Python 3.12+.

```sh
npm install
python3 -m venv .venv
.venv/bin/pip install -r planner/requirements.txt
npm run db:setup
npm run dev
```

The dependencies and database are already set up in this workspace. Open [localhost:3000](http://localhost:3000). The launcher starts the app on `127.0.0.1:3000` and its private prediction/optimization service on `127.0.0.1:8008`. Logs are written to `.wrangler/logs/app.log` and `.wrangler/logs/planner.log`, so service logging does not depend on an old chat terminal. Stop the launcher with Ctrl+C. No deployment command is needed.

## Accounts and pages

All demo accounts use **RailOps@123**.

| Role | Login | Page |
| --- | --- | --- |
| Main controller | CONTROL-01 | /control-centre |
| Track head | HEAD-TRK | /login |
| Signal head | HEAD-SIG | /login |
| Traction head | HEAD-TRC | /login |
| Workers | W0001–W0203 | /worker-login |

The homepage offers a separate entrance for each role. Every page includes a live IST timestamp and **Save as PDF**, which opens the browser print dialog; choose **Save as PDF** as the destination. Print styles hide navigation and expand scrollable content. The export covers the current page, including the currently displayed table page and filter selections. Planner runs can also be downloaded as JSON.

Tabs in the same browser profile share a session. Use separate browser profiles to demonstrate multiple accounts simultaneously. Credentials are for this local demonstration, not railway identity services.

## Department and worker workflow

1. Sign in as a department head and open **Maintenance requests**. Search and filter by corridor, line, severity, and planning status.
2. Choose a request, reporting station, crew size, priority, and future work start. The end time retains the source-required duration. Alternatively, create a job directly.
3. The crew picker shows workers only at the reporting station and its configured neighboring roster stations. Their names remain unchecked until the head selects them manually.
4. The entire job must fit each selected worker's shift. Workers must be available in the roster, in the owning department, and free of overlapping active assignments. The server independently enforces these rules.
5. Sign in as a selected worker. The assigned job, location, reporting time, instructions and source details appear in **My assignments**.
6. The worker acknowledges, starts work, and reports completion. Once every assigned worker reports completion, the job awaits head review.
7. The owning department head confirms completion. Control Centre progress updates on its next refresh, normally within 15 seconds.

For a six-worker demonstration, Thane (`TNA`) has suitable nearby morning-shift crews in all three departments. Actual eligibility still depends on existing bookings.

### Neighboring station policy

`lib/stations.ts` contains a symmetric regional dispatch-neighbor configuration. The picker explicitly lists the included station codes. It does not expose every roster station through the station filter. Intermediate stations without roster workers are omitted; large gaps between regions are excluded. Solapur currently has only its own roster workers.

The topology is informed by the [official Central Railway division maps](https://cr.indianrailways.gov.in/cris/uploads/files/1561376559029-all_div_merged.pdf), with the Vasai/Diva connection also described in the [Central Railway service notice](https://cr.indianrailways.gov.in/view_detail.jsp?dcd=6751&id=0%2C4%2C268&lang=0). The selected regional neighbor policy is an implementation assumption, not an official staffing rule or a travel-time model.

## Control Centre

- **Department overview:** all three departments, active work, completed work, crew reports, and unplanned source requests. Month and year filters select jobs by their scheduled start in IST. Completion percentage is confirmed completed jobs divided by all planned jobs in that selected period.
- **Demo completion history:** nine separate completed records, three per department across three months, demonstrate nonzero percentages. They are explicitly marked as sample/demo history, have no fabricated worker reports, and do not overwrite existing user jobs.
- **Simulation planner:** the earlier generated 7-day/30-day scenario, block calendar, timeline, matched-work comparison, accept/modify/reject and simulated disruptions. It is separate from the operational Block planner described above.
- **Maintenance intelligence:** canonical tasks, weighted priority explanations, asset links, requirements, dependencies, and predicted 7/30/90-day risks.
- **Network & assets:** the generated 20-station, 19-section graph and linked department assets.
- **Data & models:** model validation, resource assumptions, and saved review feedback. The data integration panel is removed as requested.

A simulation plan does not automatically assign real workers. Named crew allocation remains the department head's manual action.

## Prediction and scheduling implementation

`planner/scenario.py` deterministically generates 570 assets (300 Track, 150 Signal, 120 Traction), 500 maintenance tasks, 100 defects, and 30 future days with 200 passenger services and 80 freight services each day. Each service traverses one to three adjacent sections, producing multiple section movements. `data/synthetic-scenario.json` is a reviewable export; regenerate it with `npm run data:scenario`.

Failure models are fitted random forests using 4,800 synthetic historical assets, with 1,200 independent assets held out. Output probabilities are made monotonic across 7/30/90 days. Reported Brier scores apply the same postprocessing. The model uses asset age, previous defects, overdue days, load, deterioration, and weather stress.

The freight model trains on a separate synthetic 21-day historical period and validates on the next nine historical days. None of the future 30-day planning scenario is used for training. Hour/section forecast costs influence candidate times. Listed passenger and freight movements remain protected independently of the model forecast.

**These models are trained and tested only on synthetic data. Their outputs are not validated operational railway failure estimates.** The imported maintenance CSV has no failure outcomes, asset IDs, due dates, authorization windows or train schedules; these fields are not silently invented for its source requests.

### Optimization

The engine greedily constructs pairwise-compatible, same-section/line candidate bundles, then uses [OR-Tools CP-SAT](https://developers.google.com/optimization/scheduling/job_shop) to optimize optional interval placement, shared resources and precedence. Bundling is heuristic; a feasible solver result is not claimed to be a globally optimal joint bundling/scheduling solution.

Declared constraints include full task duration plus ten minutes setup/clearance, a generated 00:00–06:00 daily authorization, five-minute headway around both listed trains and freight disruptions, department crew pools, machines, adjacent station-yard exclusion, power isolation, release days and predecessor completion. Both lines are conservatively reserved. Every pair in a joint bundle must be compatible. Track-machine work cannot share with track-circuit testing; conditional OHE combinations require the generated separation flag.

Weekly solve limits are eight seconds per schedule; monthly limits are fourteen seconds. The UI compares separate-department blocks against joint blocks under the same constraints. Savings use only entire joint bundles whose tasks were served in both schedules. This controls for dropped work. The baseline is a traditional separate-block policy solved by the same engine, not measured human planner performance. Unscheduled work is returned with reasons.

Availability is 1 − possession minutes / (19 sections × horizon minutes). Utilization is parallel critical-path work divided by possession duration, excluding setup. Both schedules exclude listed train conflicts; train delay avoided is not manufactured. Actual worker completion is shown separately in department progress.

Accept/reject feedback adds bounded soft section preferences to later planning runs. It never changes hard constraints or retrains the failure model. Reviews use revision checks. Manual time changes run full validation and invalidate stale comparison figures. Rejecting a block with required successors is rejected unless the remaining schedule is feasible.

Reoptimization records a new immutable run, preserving the previous run. Freight delays, machine outages and urgent defects revise affected work; dependency successors are included in impact analysis. Unaffected blocks retain their times. Revised work returns to draft review. Overlapping machine outages are merged. These are planning simulations; live dispatch execution and started-block tracking are not connected.

## Source data and persistence

- `data/workers.csv` and `data/maintenance-requests.csv` are unchanged copies of the two provided datasets. All 203 workers and 1,000 maintenance requests are retained.
- Source mapping: TMS → TRK (549 requests), SMMS → SIG (292), TDMS → TRC (159). Raw codes and fields remain stored.
- Maintenance timestamps have no timezone; they are displayed verbatim, separately from explicitly IST work schedules. Backlog and roster availability remain source snapshots.
- Request imports are append-only: editing/removing existing source IDs is rejected. A unique source-job link prevents duplicate plans under concurrent requests.
- Operational jobs, assignments, sessions, completion timestamps, simulation runs and planner feedback persist in `.wrangler/state/v3/d1/`. Do not delete this folder to preserve work.
- Applied migrations are retained; migration 0002 adds controller planning/history fields and extends active-booking overlap protection.
- Controller provisioning and demo history seed idempotently even on an existing database. Existing password hashes and user records are preserved.
- The private engine token is passed through a server binding and never placed in the Vite client environment. Direct engine data/compute requests require it; app routes additionally require the controller session.

## Validation

```sh
npm run test:local
npm run test:control
npm run test:operations
npm run test:planner
node scripts/test-shifts.mjs
node scripts/test-request-import.mjs
npx tsc --noEmit
npm run build
```

The API tests create uniquely identified jobs/plans and remove only their own records. They cover role isolation, nearby-station restrictions, shifts, crew counts, concurrency, exact CSV preservation, completion review, controller summaries, private service access, safe/unsafe plan changes, stale review protection, and persisted feedback. Planner tests cover exact data counts, valid weekly/monthly schedules, matched-work metrics, incompatible bundles, power/headway violations, overlapping outages and dynamic revisions. Browser interaction and PDF print-dialog validation are not part of these automated checks.

Operations API checks cover role isolation, invalid CSV rollback, stale revisions, concurrent release, head/worker handoff, approved-time protection, changed-traffic alerts and four direct PDF exports. Scheduler/model tests include input-driven constraints and observed-history data-quality gates. Generated report pages have been rendered and inspected. Browser interaction testing is not claimed.

The workspace contains framework hosting metadata, but remains localhost only. No live COA/FOIS feed, railway authorization, production model validation, travel-time model or railway deployment is represented as complete.
