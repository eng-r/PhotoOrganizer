# Architecture and design

## Boundaries

`photo_organizer.py` and `cli.py` parse/delegate. `ArchiveOrganizer` runs the stages. Algorithms do not live in the launcher.

| Module | Responsibility |
| --- | --- |
| `config.py` | Effective JSON defaults, strict validation, config-relative paths. |
| `models.py` | Inventory, metadata, timestamp provenance, immutable planned entries, copy/reconciliation/run records. |
| `safety.py` | Disjoint canonical roots, no reparse traversal, empty destination, ownership claim, valid target names, space estimation. |
| `discovery.py` | Stable recursive inventory of ordinary source files; exclusions and coverage gaps. |
| `metadata.py` | Provider interface and batched ExifTool subprocess adapter with cancellation and timeout. |
| `timestamp_resolver.py` | Generic embedded tags, explicit filename fallback formats, sanity checks, confidence/provenance. |
| `event_grouper.py`, `planner.py` | Pure deterministic placement, event numbering, complete plan and case-insensitive collision checks. |
| `copier.py`, `verifier.py` | Bounded streaming workers, retry policy, source stability checks, SHA-256, exclusive publication. |
| `reconciler.py` | Independent source and destination scans and membership/stability checks. |
| `reporting.py` | Shared not-archived outcomes, final status/summary, CSV/JSON/JSONL, TXT chapter and static HTML. |
| `progress.py` | Independent heartbeat so a large file or metadata process cannot silence progress. |

## Destination ownership

Validation rejects an existing non-empty destination. The run creates only the `_process` container before opening `_process/.archive_organizer_claim` using mode `x` (exclusive creation). The claim records `run_id`, process ID, hostname, start time, and tool version. If simultaneous invocations pass the initial empty check, only one can create the claim. Losers never remove/replace it. Only the winner creates other artifacts.

Ownership is rechecked using claim content and filesystem identities. Before the first copy, the root must contain only this run's process directory. Reparse paths are rejected. Failed/interrupted claims remain for inspection: there is no implicit takeover, resume, or append.

## Inventory and timestamp decisions

File extension and explicit ignore patterns determine eligibility, never filename prefix or camera vendor. Ignored directories are recursively enumerated so every ordinary descendant is explainable; their files have no metadata request, timestamp decision, destination, or copy. Unknown extensions are recorded too. Links/reparse points are reported without traversal. Unreadable areas make inventory coverage incomplete and prevent successful reconciliation.

ExifTool processes bounded batches (128 inputs per normal batch), not a subprocess per image. Absolute paths go through line-delimited argument input. Raw qualified tags and rejected candidates accompany each decision. Common EXIF/XMP creation tags and QuickTime creation fields are mapped explicitly. System file dates reported by ExifTool are not mistaken for embedded capture dates.

The configured priority list alone enables and orders categories. Embedded categories must precede fallbacks. Filename matching is anchored to accepted whole-stem formats. No arbitrary substring dates or semantic names are inferred. Unknown values go to `_UNKNOWN_DATE/`; metadata extraction errors remain reportable even if copying succeeds.

The run freezes one clock for future-date checks and records it with versions and effective config. Placement is deterministic for the same inventory, metadata, configuration, and validation clock; run IDs/timing/log order are naturally not byte-identical between runs.

## Planning and copying

Sort by selected civil timestamp (unknown last), casefolded source-relative path, then exact path. Count files by day within each month. Sparse days remain in `_sparse`; consecutive dense days become numbered events, split at the configured maximum span. Months/years always split events. RAW/JPEG companions are separate files.

Every eligible source gets exactly one target preserving its basename. Case-insensitive target collisions are fatal before any media copy, including collisions in `_UNKNOWN_DATE`. The complete manifest/plan is persisted before free-space preflight and copy scheduling.

Each worker opens the source read-only, verifies planned size/mtime/identity, streams bytes into an exclusively created owned partial under `_process/tmp`, and computes SHA-256. The staged file is reread independently for size/hash verification. Supported destination timestamps are preserved. A verified file is published with a Windows no-replace rename. POSIX uses exclusive same-volume hard-link publication rather than a replacing rename. Unsupported filesystems fail safely.

Recoverable operations retry using JSON policy. Source mutation and collision errors do not silently retry into a new plan. Disk-full/write-access loss stops new scheduling. Ctrl+C sets a cancellation event, workers check it at chunk boundaries, and metadata subprocesses are terminated. Blocking operating-system reads may delay cancellation until they return.

## Reconciliation and results

Independent scans compare initial versus final source paths, identities, sizes, and mtimes, including ordinary excluded files. Destination enumeration excludes `_process` and checks exact expected file paths/sizes and unexpected files; source ignore rules do not hide destination errors.

Required media accounting:

```text
initial eligible = final eligible = planned = verified published copies = destination media recount
failed media = 0
source inventory stable; exact destination membership/sizes correct
```

Reconciliation can PASS while the overall run fails because metadata extraction errors occurred. Shared run records generate every report and the exit code. The not-archived chapter distinguishes exclusion, failure, not-attempted, and unconfirmed outcomes; present-but-unverified files are not described as physically absent.

## Practical limits

- No archive append/resume/merge, camera alignment, deduplication, sidecar association, or historical scan-date inference.
- Directory/file ownership checks reduce accidental interference, but this is not a filesystem snapshot or protection against an adversary continuously replacing paths. Keep the source and destination otherwise idle during the run.
- Reads may update filesystem-managed access times. The application never writes source content or timestamps; immutability tests cover names, bytes, size, and mtime.
- Source stability uses identity/size/mtime; deliberate same-size changes with restored timestamps are outside that inventory check. Copied bytes are still SHA-256 verified. Final reconciliation does not rehash all source media a second time.
- Memory grows with the inventory and metadata/audit records, not with video file size. Content streaming uses 1 MiB buffers per copy/hash operation.
- Timestamp selection cannot prove a camera clock was correct. Unknown offsets remain unknown, and supplied metadata may represent digitization rather than original historical capture.
