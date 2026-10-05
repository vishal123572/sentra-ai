# Upgrade to the supervisory workflow release

This update extends the existing app. It does not replace your workspace or require database deletion. The package and supervisory workflow are 1.3.0; new assessments use detector engine 1.2.0. Existing 1.0.0 assessments retain their original metrics, rules and decisions; new detectors are explicitly unassessed in those historical snapshots. The additional observation and expert-comparison tables is created automatically without deleting data.

1. Stop the existing server with Ctrl+C.
2. From your existing project folder, create a backup if you have saved imports or reviews:

   Windows: `py -3 manage.py backup backups/before-supervisory-upgrade.sqlite3`

   macOS/Linux: `python3 manage.py backup backups/before-supervisory-upgrade.sqlite3`

   If that filename already exists, choose another name. The command will not overwrite it.
3. Extract the updated ZIP and copy the contents of its `sat-sa` folder into your existing project folder, replacing source files. Keep your existing `data` and `backups` folders. Neither is included in the source ZIP.
4. Restart with `py -3 run.py --demo` on Windows or `python3 run.py --demo` on macOS/Linux. The changed synthetic exports create new versioned demo assessments on the first upgraded run. Existing assessments and decisions remain in history. Repeated loading of the new version is idempotent. Submission identity now includes the engine version, allowing explicit re-import under new rules.
5. Reload the browser to load the new JavaScript/CSS. In Overview, open an entity assessment, open **Required escalation absent → Evidence Investigation**, then **Check what the detectors missed** and save an independent observation.

The fixed default demo login remains `examiner` / `SatSaDemo2026!`. Existing account passwords are not reset by upgrading. If an older database used a different forgotten password, run `py -3 manage.py reset-demo-password` (or `python3 manage.py reset-demo-password`) before restarting.

The new peer benchmark works for historical periods and requires identical file-type sets rather than only equal file percentages. Missing inputs and zero eligible populations remain explicit. Review attention is a workload label, separate from the stored attention index. No examples or invented percentages are hard-coded into assessment results.

Acceptance checks on the demonstration laptop: open Atlas Grid's September assessment; inspect peer rates and the eight recommended records; save a group decision; inspect updated evidence; open Northstar's coverage and missing-case evidence; export reports; confirm previous saved reviews remain. Browser layout could not be verified from the build session because its cloud browser could not reach the loopback server.

Seven supported exports and thirteen detectors are available for newly imported assessments. Historical submissions show unsupported new detectors as unassessed and keep their original file-count denominator. Existing accounts are not reset. To demonstrate new category/workflow/profile signals, load the updated synthetic demo or explicitly re-import exports under the new engine. The Expert-review comparison panel does not fabricate expert labels or automatically accept findings.
