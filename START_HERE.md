# Run RailFlow

1. If using the ZIP, extract it first. Open the extracted **RailFlow4** folder.
2. Double-click **START_RAILFLOW.cmd**. Keep its window open.
3. Wait for **RailFlow READY**, then open **http://localhost:3010** in your browser.
4. Choose City authority, Station master or Customer. Use password **RailFlow@123**. For Station master, choose a station first.

You already have Python installed. This version uses Python's built-in libraries: **no npm install, pip install, database setup or file changes are needed**. Python 3.10 or newer is required; your Python 3.12 works.

This is the new standalone version. Do not run the old SIH ROUND 2 launch commands for this folder. Your original project has not been overwritten.

## Try the changes

- **City authority → Simulation:** edit a row's arrival/departure or required platform, enter a short reason, and click **Generate new schedule**. Review the changes, conflicts and independent validation, then **Push to official schedule**.
- **Station master → Simulation:** edit calls at your station and use **Generate new schedule**. The map marks your station in orange. Train schedules contains platform cards with train name, origin and arrival; hover a card for details.
- **Customer:** choose departure and arrival stations, then **Find trains**. Red means delayed; yellow means a tight platform turnaround could cause a delay; green means on time or early. Results are direct journeys in the fictional timetable.
- **Disruptions & replanning:** enter a delay or timed platform closure, or describe one in plain language and review the interpreted fields.
- **Maintenance blocks:** the authority proposes work; the station master accepts/refuses it, assigns compatible crews, and reports progress.

## Demonstrate the exact problem statement

As City authority, open **Disruptions & replanning → Rivergate · 8 trains**. Review and apply the scenario. This gives a small, entirely fictional station with three platforms, minimum gaps and required-platform trains. Select **Rivergate** when signing in as station master.

Try “Delay T01 at DEMO by 20 minutes” and “Close platform 1 at DEMO from 08:00 to 09:00”. Review the revised times/platforms and reasons. Try closing every platform for the full planning period to see explicit unscheduled calls rather than a false success.

Scenario switching replaces active trains/incidents/jobs. Prior snapshots remain in Revision history. Use **Pune district** to restore the district scenario.

## Stop or restart

Press **Ctrl+C** in the server window to stop it. Double-click the launcher to start again. Edits persist in `local-data/railflow.sqlite3`.

If the browser says connection refused, check that the server window says READY and that you used port **3010**, not 3000. If the port is already in use, keep using the existing RailFlow window or stop that window before restarting.

## Use your phone

Stop the normal launcher, then double-click **START_PHONE_ACCESS.cmd**. Put the phone and computer on the same trusted Wi-Fi. Find the computer's Wi-Fi IPv4 address using `ipconfig`, then open `http://THAT-ADDRESS:3010` on the phone. Allow Python through Windows Firewall for private networks if prompted. `localhost` on the phone refers to the phone, not your computer.

This uses shared demo credentials and a local HTTP server. It is for a private demonstration, not a public deployment.


## New in version 3

Open **Occupancy sheet** for the vertical time-by-platform grid. Authority accounts can switch to **All stations** or **All railway lines**. Use the date/time-window selectors; use Next/Previous to move through station columns.

Open **Backlogs** for delayed trains, possibly delayed trains and resolved occupancy conflicts.

Simulation previews now show both arrival and departure changes, downstream effects and the full new timetable. Review any explanation beside an unmet timing request. Click **Push to official schedule** to publish; incomplete drafts cannot be published.

For maintenance: **Refuse** opens a required reason box and optional alternative datetime fields. **Accept · assign crew** opens worker selection and **Approve with selected crew**. Review and publish the decision.

Close the previous RailFlow server before starting this version, since both normally use port 3010. No additional installation is required.

## Version 4: recovery timetable

The fictional dataset now has varied morning, midday and evening services, with explicit minimum journey and station stop times. Spare time may absorb a delay; recovery is never guaranteed when platforms or closures interfere.

Try **REC01** in Simulation. Change its first departure from **09:25 to 10:25**, keeping arrival at **09:20**. With no extra disruptions, onward arrival/departure delays are **20/15**, **5/2**, then **0/0 minutes**. The draft lists recovered time and downstream effects. Publish only after reviewing it.

The occupancy sheet now covers **00:00–24:00**, with vertical scrolling and no two-hour selector. Select the next date for overnight calls. The theme is brighter blue with vivid red and yellow statuses.

On the first version-4 launch, built-in district services are replaced with this new dataset. Previous revisions, custom trains, maintenance jobs and incidents are retained; prior manual edits to the replaced built-in timetable remain in history. Your RailFlow3 folder is unchanged.
