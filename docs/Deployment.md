# FFDC Analyzer release with a verified backup

## Release scope

The 2026-10-12 follow-up keeps the existing workspace upload flow and changes
JIRA credential gating so a local FFDC attachment can be analyzed without
signing in to JIRA. Explicit JIRA questions and JIRA-linked reports continue
to require the user's own JIRA session. The UI asset version is
`20261012-jira-auth1`.

The 2026-10-08 release includes the complete runtime, text conversation controls,
configuration parsing and persisted-job modules, static assets, NIC domain pack,
tests, documentation and sanitized configuration examples. The UI asset version
was `20261008-drop1`. Examples are reference files only: the release preserves
the actual production service, environment, credentials and runtime data.

This patch adds file drag-and-drop to the conversation workspace. Dropped files
use the existing attachment and submit workflow, and file drops prevent the
browser's default navigation/download behavior. Ordinary text dragging remains
available. Only one attachment is accepted at a time, and active requests do not
accept a replacement file.

The preceding patch restored Defect Review's Assignee sorting in the workspace view.
The wrapper retains page-specific styles before the original main and scripts
after it, without duplicating scripts already inside the content. Sortable
headers use plain dark text on a transparent background.

Production was inspected at `/home/zhuangxin2/ffdc_analyzer`, using
`ffdc-analyzer.service` and port `8088`. The service runs as root. Its existing
analysis-concurrency override is 16; source defaults do not override that value.

## Stage and verify

Use `work/deploy_release.py` with a staging directory containing `manifest.json`
and `files/`. Every manifest row records its relative path, release SHA-256 and
current production SHA-256 (or null for a new file). A null release SHA-256
deletes an existing non-required file only after the verified backup. The full runtime must include
`ffdc_config.py` and `ffdc_jobs.py`; the older `deploy_domain_authoring.py` file
list is incomplete for this release.

Run the current Python tests in a disposable staging copy, check JavaScript
syntax, and verify the stage against its manifest. Do not copy production
credentials into test directories. The
historical `test_jira_monitor_workflow.py` loads an old `app.py.jira_monitor` copy
and has known stale failures; it is not the current release gate.

## Back up before installing

The release script requires sudo. Enter the password only in your own terminal.
It uses an already mounted data disk (`/root/data2`, `/root/data3` or
`/root/data1`) with sufficient free space, creating a private
`ffdc-analyzer-backups/<release-id>/` directory. It does not resize disks,
change mounts or remove old backups.

The complete project, including uploads, reports, caches, saved jobs, protected
configuration and prior backups, is copied first while the service runs. The
service is then stopped, the backup synchronized again, and the copy verified
using content checksums. Actual service and nginx configuration plus environment
metadata are saved privately alongside the project backup. Source replacement
starts only after backup verification succeeds. Large datasets can make the
stopped-service verification take several minutes.

If backup verification fails, restore service without replacing source files.
If installation or HTTP verification fails, restore release-managed files from
the verified backup and restart the original service. Keep the full backup and
result JSON for later investigation or an explicit rollback.

## Verify the served release

- `systemctl is-active ffdc-analyzer.service` must report active.
- `/new-version` must return 200 and reference the staged release's assets.
- Served JavaScript and CSS must match the release checksums.
- An unauthenticated `/workspace-domain-author` request must return 401.
- Verify an existing report and a normal analysis/chat flow after restart.

The lightweight smoke route is `/new-version`; there is no `/health` route.
Do not print protected AI/JIRA configuration, cookies or server environment values.

## Browser acceptance

The user requested removal of voice input and answer playback on 2026-10-08.
The text-only release removes microphone and read-aloud controls, browser speech
API use, and related permission/HTTPS error messages. The retired voice test is
removed through a manifest deletion entry and remains available in prior backups.

Verify that the browser loads the new asset version, the microphone and playback
buttons are absent, and text submission, copying answers, file attachment and
new-analysis reset still work. Confirm the restored chat layout, including its
scrollable message area. The existing HTTP entry remains usable for text chat.

On an existing Defect Review result, click Assignee twice to verify ascending
and descending name order. Issue rows and their recommendation rows must move
together, preserving expanded recommendations and the original issue count.
Check that the header has no blue background during normal use or hover.

Run `node work/test_workspace_drop.js` for file-drop behavior regressions.
In the browser, drop one FFDC archive, confirm its attachment chip appears
without navigation, and submit it through the normal upload flow. Check that
removing the attachment and starting a new analysis clear it, and that multiple
files or a drop during an active request do not replace an existing attachment.
