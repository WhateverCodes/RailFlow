# Run RailFlow

1. If using the ZIP, extract it first. Open the extracted **RailFlow4** folder.
2. Double-click **START_RAILFLOW.cmd**. Keep its window open.
3. Wait for **RailFlow READY**, then open **http://localhost:3010** in your browser.
4. Choose City authority, Station master or Customer. Use password **RailFlow@123**. For Station master, choose a station first.

You already have Python installed. The core app uses Python's built-in libraries. PDF downloads additionally need `python -m pip install -r requirements-reports.txt`; those packages are already installed on this computer. Python 3.10 or newer is required; your Python 3.12 works.

This is the new standalone version. Do not run the old SIH ROUND 2 launch commands for this folder. Your original project has not been overwritten.

## Try the changes

- **City authority → Simulation:** edit a row's arrival/departure or required platform, enter a short reason, and click **Generate new schedule**. Review the changes, conflicts and independent validation, then **Push to official schedule**.
- **Station master → Simulation:** edit calls at your station and use **Generate new schedule**. The map marks your station in orange. Train schedules contains platform cards with train name, origin and arrival; hover a card for details.
- **Customer:** choose departure and arrival stations, then **Find trains**. Red means delayed; yellow means a tight platform turnaround could cause a delay; green means on time or early. Results are direct journeys in the fictional timetable.
- **Disruptions & replanning:** enter a delay or timed platform closure, then review the independently validated proposal.
- **Maintenance blocks:** the authority proposes work; the station master accepts/refuses it, assigns compatible crews, and reports progress.

## Updated UI and exports

- Simulation and large timetable views now offer CSV downloads. Revision history, Backlogs and Disruptions also offer PDF downloads.
- Platform reassignments have purple text badges. Departures earlier than the advertised time have dark-green Early departure badges.
- Incomplete drafts show constraints and cannot be published. The original scheduler remains available in the strategy comparison.
- The plain-language and reproducible-scenario controls were removed from the disruption screen; their backend APIs remain available.

## Stop or restart

Press **Ctrl+C** in the server window to stop it. Double-click the launcher to start again. Edits persist in `local-data/railflow.sqlite3`.

If the browser says connection refused, check that the server window says READY and that you used port **3010**, not 3000. If the port is already in use, close the previous server with Ctrl+C before starting the updated folder. An old process can keep serving the old version even after extracting a new ZIP.

## Use your phone

Stop the normal launcher, then double-click **START_PHONE_ACCESS.cmd**. Put the phone and computer on the same trusted Wi-Fi. Find the computer's Wi-Fi IPv4 address using `ipconfig`, then open `http://THAT-ADDRESS:3010` on the phone. Allow Python through Windows Firewall for private networks if prompted. `localhost` on the phone refers to the phone, not your computer.

This uses shared demo credentials and a local HTTP server. It is for a private demonstration, not a public deployment.


## New in version 3

Open **Occupancy sheet** for the vertical time-by-platform grid. Authority accounts can switch to **All stations** or **All railway lines**. Use the date/time-window selectors; use Next/Previous to move through station columns.

Open **Backlogs** for delayed trains, possibly delayed trains and resolved occupancy conflicts.

Simulation previews now show both arrival and departure changes, downstream effects and the full new timetable. Review any explanation beside an unmet timing request. Click **Push to official schedule** to publish; incomplete drafts cannot be published.

For maintenance: **Refuse** opens a required reason box and optional alternative datetime fields. **Accept · assign crew** opens worker selection and **Approve with selected crew**. Review and publish the decision.

Close the previous RailFlow server before starting this version, since both normally use port 3010. Only PDF exports require the optional reporting dependencies described above.

## Version 4: recovery timetable

The fictional dataset now has varied morning, midday and evening services, with explicit minimum journey and station stop times. Spare time may absorb a delay; recovery is never guaranteed when platforms or closures interfere.

Try **REC01** in Simulation. Change its first departure from **09:25 to 10:25**, keeping arrival at **09:20**. With no extra disruptions, onward arrival/departure delays are **20/15**, **5/2**, then **0/0 minutes**. The draft lists recovered time and downstream effects. Publish only after reviewing it.

The occupancy sheet now covers **00:00–24:00**, with vertical scrolling and no two-hour selector. Select the next date for overnight calls. The theme is brighter blue with vivid red and yellow statuses.

On the first version-4 launch, built-in district services are replaced with this new dataset. Previous revisions, custom trains, maintenance jobs and incidents are retained; prior manual edits to the replaced built-in timetable remain in history. Your RailFlow3 folder is unchanged.
