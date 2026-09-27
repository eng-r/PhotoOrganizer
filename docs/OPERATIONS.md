# Operations, reports, and troubleshooting

## Commands and destinations

| Command | Work | Persistent output |
| --- | --- | --- |
| `validate` | Config, root safety/access, empty destination, tooling | None; transient writable probe only. |
| `analyze` | Inventory, metadata, timestamp decisions | Claims empty destination; audit and reports. |
| `plan` | Analysis, grouping, targets, collisions and space estimate | Claims empty destination; complete plan and reports. |
| `run` | Full workflow with verified copies and reconciliation | New archive plus process artifacts. |

Each invocation after validation needs an empty destination. Preview output is not a resumable copy plan. Use a separate archive destination. Never manually delete a claim to bypass the non-empty rule.

## Files to inspect

| Artifact below `_process` | Purpose |
| --- | --- |
| `logs/photo_organizer.txt` | Timed stage/progress/error log, final summary, full Source files not archived chapter. |
| `reports/report.html` | Self-contained local report; works offline in a browser with relative audit links. |
| `reports/summary.json` | Authoritative run status, exit code, counts, timestamp quality, space, inventory coverage. |
| `reports/not_archived.csv` | One row for each original file not confirmed as archived; reason and destination presence. |
| `reports/ignored_files.csv` | Explicit exclusions and unsupported extensions. |
| `reports/errors.csv` | File-level and fatal errors. |
| `reports/plan.csv` | Source-to-target mapping, daily count/classification, media role, storage leaf, sidecar association and size; available after planning. |
| `_AuditTrail/manifest.jsonl` | One planning record per eligible file with raw/rejected timestamp candidates. |
| `_AuditTrail/timestamp_audit.csv` | Human-readable date provenance and assignments. |
| `_AuditTrail/copy_verification.csv` | Sizes, SHA-256, attempts, and final per-file verification results. |
| `_AuditTrail/copy_results.jsonl` | Incremental completed-copy outcomes. |
| `_AuditTrail/reconciliation.csv` | Independent scan findings or PASS/NOT_RUN result. |
| `_AuditTrail/source_inventory.json` | Original enumerated files, exclusions, and coverage gaps. |
| `_AuditTrail/run_context.json` | Tool versions, run ID, and frozen validation clock. |
| `config_snapshot.json` | Normalized effective configuration. |

CSV cells beginning with spreadsheet formula characters receive a leading apostrophe. This is display safety, not a renamed source file. JSON/JSONL preserve exact values; use them when importing exact filenames programmatically. TXT and HTML show the original path text.

## Source files not archived

The chapter is based on the entire ordinary-file inventory, including ignored directories and unsupported extensions. Every row includes source-relative path, intended destination when known, disposition, presence, reason, stage, and attempts.

- **UNSUPPORTED / IGNORED:** intentionally not archived; not a primary-media reconciliation failure.
- **UNASSOCIATED_SIDECAR:** no unique same-directory/same-stem primary was available, so the organizer did not guess.
- **FAILED:** a copy/read/hash/publication operation or planned collision failed.
- **NOT_ATTEMPTED:** preflight failure, interruption, stopped scheduling, or preview-only analysis.
- **UNCONFIRMED:** publication was reported but recount was incomplete, the source changed, or the expected destination is missing/mismatched.

A presence value of `PRESENT_UNVERIFIED` means a destination file exists but is not accepted as a confirmed result. `NOT_CHECKED` means the scan did not establish presence. Successfully copied `_UNKNOWN_DATE` files are archived and are absent from this list. Metadata errors alone do not put a verified copy in this list, though they still make the overall run fail.

The HTML report's Daily grouping summary lists every resolved date, primary-media count, associated-sidecar count, classification, and destination. Summary JSON reports primary-media and sidecar reconciliation separately; both must pass for an overall successful run.

Unreadable subtrees and skipped reparse points are reported as coverage gaps/skipped entries, not invented per-file rows. New files found at recount are separately identified as `SOURCE_ADDED_AFTER_PLANNING`.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Requested command completed successfully; warning-only/empty collections may be WARN. For `run`, reconciliation must PASS. |
| `1` | Workflow completed with file errors or reconciliation FAIL. |
| `2` | Fatal validation, preflight, unexpected run-level, or required output-writing failure. |
| `3` | User interrupted. Incomplete copies are never successful. |

Preview commands have reconciliation `NOT_RUN`. PASS means that command succeeded, not that files were archived. If validation fails before safe destination ownership, diagnostics are console-only. If the destination disk cannot accept reports, the final console/exit status reports that limitation; a partially written report cannot be trusted as a completed result.

## Common problems

- **ExifTool unavailable:** install it and set PATH or `PHOTO_ORGANIZER_EXIFTOOL` to the executable path. `pip install -r requirements.txt` does not install ExifTool.
- **Destination not empty / already claimed:** choose a new empty destination. The application does not remove any prior output or another run's claim.
- **Filename collisions:** inspect `errors.csv` and `plan.csv`. Multiple source paths targeted the same preserved filename in one folder. No media copies begin. Resolve collection scope or prepare a separate source copy yourself; the tool never renames/deletes originals.
- **Unexpected unknown dates:** inspect timestamp audit/manifest. Generic names are accepted; missing metadata is different from skipped files. Remove `FilenameDate` for metadata-only behavior, or deliberately add `FilesystemMTime` if modification times are an acceptable last resort.
- **Old photos rejected:** lower `timestamp.minimum_year` appropriately. The default is 1980.
- **Corrupt media or denied read:** per-file errors remain visible; other files continue when safe. A bad metadata extraction may still result in a verified byte copy to `_UNKNOWN_DATE`.
- **Insufficient space:** nothing is copied. Use a sufficiently large destination; preflight includes conservative partial-file overhead and the configured margin.
- **Source changed / unexpected destination file:** keep both trees otherwise idle and use a new destination for a new run. Equal counts cannot conceal different members.
- **Ctrl+C:** scheduling stops; workers abandon owned partials and retain verified published files. An interrupted report is written when possible. A hard process kill or power loss may leave partials and no final report; inspect the journal. There is no resume or automatic cleanup of that archive in a later run.

Keep the original collection until you have inspected the completed report and independently decided how to manage your backups. The organizer has no source-deletion command.
