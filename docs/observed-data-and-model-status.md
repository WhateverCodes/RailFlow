# Observed data and model status

Updated 7 September 2026. Everything runs on localhost.

## What has been researched and added

The maintenance dataset uses Pune–Lonavala, Pune–Daund and Pune–Miraj. The public reference catalogue contains 42 service/direction records across these three corridors. A dated seven-day import creates 299 movements, including five carry-over movements from the preceding night. Records include the train number, actual source URL, retrieval date, direction and explicit IST times.

These are selected public passenger timetable records, not a complete working timetable. Each train conservatively occupies its entire named corridor for the published endpoint journey. Intermediate passing times, track directions, freight trains and operating clearances are not invented. Daund Junction (`DD`) is kept separate from Daund Chord Line (`DDCC`); records with different endpoints are excluded from this catalogue.

Source tables, read on 7 September 2026:

- [Pune to Lonavala](https://www.confirmtkt.com/trains/pune-to-lonavala-train-tickets)
- [Lonavala to Pune](https://www.confirmtkt.com/trains/lonavala-to-pune-train-tickets)
- [Pune to Daund](https://www.confirmtkt.com/trains/pune-to-daund-train-tickets)
- [Daund to Pune](https://www.confirmtkt.com/trains/daund-to-pune-train-tickets)
- [Pune to Miraj](https://www.confirmtkt.com/trains/pune-to-miraj-train-tickets)
- [Miraj to Pune](https://www.confirmtkt.com/trains/miraj-to-pune-train-tickets)

Route identity is supported by the [Central Railway division system map](https://cr.indianrailways.gov.in/cris/uploads/files/1561376559029-all_div_merged.pdf), whose Pune map is dated 2019. That map is not used to assert present-day signalling topology or line capacities. The official suburban timetable page was located, but a direct download was declined; the public secondary timetable records therefore retain their reference-only status.

## What the official sources establish

[CRIS COA](https://cris.org.in/loadpage?page=proCOA) describes controller-entered train movement data and its exchange with other railway systems. [CRIS FOIS](https://cris.org.in/loadpage?page=proFOIS) describes monitoring freight trains and their movements. These pages describe systems; they do not supply a downloaded historical dataset for our three corridors.

The [official passenger schedule enquiry](https://www.indianrail.gov.in/enquiry/SCHEDULE/TrainSchedule.jsp) states that its schedule covers reserved trains defined in PRS. That does not establish complete passenger and goods traffic coverage for maintenance planning. Public searches also returned aggregate railway statistics and derailment counts, which do not provide section/hour freight labels or asset inspection-to-failure histories.

No suitable downloadable historical freight movement series for the three selected corridors has been obtained. No credentials or railway system access are available in this workspace. This is a data dependency, not evidence that such data does not exist.

## Working model-training pipeline

The Control Centre's Block planner → Sources & settings includes a freight-history template, CSV upload, candidate training, held-out evaluation, candidate history and separate activation.

Required CSV columns:

`section_id,hour_start,freight_count,coverage_complete,source_reference`

Each row represents a complete observed IST hour. Zero is accepted only as an explicitly observed zero-count hour. The input validator rejects incomplete coverage, duplicates, unknown sections, missing hours, future observations and passenger timetable schemas. At least 42 consecutive complete days per included section and 100 observed freight entries are required by the current project gate.

The first 28 or more days train a Random Forest regressor. The last 14 days are held out chronologically. Features are section identity and calendar values; holdout observations do not become training features. The comparison baseline is the training-period mean for the same section, weekday and hour. Results include MAE, RMSE, per-section MAE, input SHA-256 and training/holdout dates.

A candidate must reduce overall holdout MAE by at least 5% and avoid a per-section regression to qualify for activation. This is a configurable project acceptance policy, not railway certification. Eligible candidates are refitted on all supplied history; reported holdout metrics belong to the earlier training-only model. The controller separately activates a candidate. Only internally generated model files are loaded, with a saved SHA-256 check; users upload CSV, not model executables.

An active model provides expected hourly freight counts for covered sections within the next 30 days after observed history. Forecasts influence a bounded scheduling preference. They never remove listed trains, bypass traffic completeness, or grant a work window. A plan saves the forecast values and model reference it used.

**Current state:** the pipeline is implemented and tested, but no model trained on observed railway freight history is active. Test observations are clearly labelled generated fixtures stored in temporary directories and removed after tests. The earlier synthetic scenario models remain separate.

## Maintenance failure prediction

The supplied maintenance CSV has severity, backlog and required duration. It lacks asset identities, repeated inspection history and observed failure outcomes. Operational priority currently uses the visible rule score `min(100, 15 × severity + min(backlog_days, 25))`. Backlog is the source snapshot; it is not silently advanced by the clock.

Training a failure probability against that same rule would only reproduce the rule. Before failure-risk training, obtain asset-linked observation dates and outcomes, define a prediction horizon, exclude information recorded after each prediction date, and evaluate on later observations with asset separation where required. No operational failure probabilities are claimed yet.

## Remaining operational boundaries

Named crews are manually selected by heads after accepted blocks are released as jobs. The optimizer checks that an eligible allocation exists; its internal crew witness is not an automatic assignment or a worker reservation. Assignment performs fresh roster, nearby-station, shift and overlap checks.

Exact work locations, crew requirements, compatible joint-work reviews, machine capacity and complete work-window traffic records still need recorded inputs. Public timetable import creates no work authorization. Released times are locked, and updated traffic conflicts raise controller alerts and block new crew assignment/start. Replanning currently creates revised drafts for unreleased plans; released or started work is not silently moved. A formal cancellation/reissue workflow and authenticated live railway integrations remain future work.
