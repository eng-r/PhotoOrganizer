# Photo Archive Organizer

A local Python CLI that analyzes one source collection and copies media into a new chronological archive. It never intentionally modifies the source. Every published media copy is verified by size and SHA-256, and an independent recount checks source stability and exact destination membership.

For normal use there are only two files to care about: [config.json](config.json), which contains every user-adjustable setting, and [start.bat](start.bat). See the [quick start](docs/QUICK_START.md). Installation and deeper details remain in the `docs` folder.

The repository also includes an independent, optional [Geo Mapper](geo_mapper/README.md). It reads an already organized archive and creates monthly and annual GPS memory maps without changing media or participating in organization.

## What it does

- Recursively inventories ordinary files, including excluded files, so omissions can be explained.
- Extracts embedded dates using batched ExifTool requests, regardless of camera brand or filename. `007.JPG`, `Pasha4.jpg`, `DSCN1277.JPG`, random BMP names, and descriptive names all receive metadata extraction.
- Uses common full-filename date formats only as a configured fallback. Arbitrary names and parent folder names are never interpreted semantically.
- Counts primary image/video files by resolved calendar date. Dates meeting `day_grouping.threshold` go to `YYYY/MM-Mmm/DayDD/`; smaller dates share the month's `_sparse/` folder.
- Treats XMP and AAE as sidecars: an unambiguous same-stem sidecar follows its primary without affecting the daily threshold. CR2 is primary media and is stored in a `CR2/` leaf below its dated or unknown-date folder.
- Copies through temporary files, verifies content, then publishes without overwriting.
- Writes a TXT execution log, a self-contained HTML report, and machine-readable CSV/JSON/JSONL audits.
- Lists **Source files not archived** in both TXT and HTML, including the source path and reason for each exclusion/failure/unconfirmed result.

## Design principles

1. **Source safety:** source files are read only; no moves, renames, metadata edits, or cleanup in the source tree.
2. **Explicit ownership:** destination must initially be empty. An exclusive `.archive_organizer_claim` elects one run before other process artifacts are written.
3. **Deterministic placement:** fixed metadata priority, stable path sorting, calendar-day grouping, and an immutable plan precede copying.
4. **Content integrity:** size + SHA-256 verification and no-overwrite publication are mandatory, not JSON switches.
5. **Independent accounting:** counts alone are insufficient. Final scans compare expected paths/sizes and initial versus final source identity, size, and mtime.
6. **Explainable results:** TXT, HTML, CSV, JSON, and exit status derive from shared run results. Unknown dates are a normal classification, not a reason to discard files.
7. **Simple local operation:** no AI, database, web server, cloud, GUI, archive merging, deduplication, append, or resume.

## Architecture

```text
CLI → config/path/tool validation → atomic destination claim
    → recursive inventory → batched metadata → timestamp decisions
    → daily classification → complete plan + audit → collision/space preflight
    → streaming copy → SHA-256 verification → exclusive publication
    → independent source/destination scans → shared result → reports
```

The package separates configuration, filesystem safety, discovery and media roles, metadata providers, timestamp resolution, daily classification, planning, copy verification, reconciliation, and reporting. `ArchiveOrganizer` coordinates these services. The top-level `photo_organizer.py` only delegates to the CLI. Tests inject metadata providers, clocks, copy verifiers, and publishers without touching real collections.

## Quick example (Windows)

After installing Python 3.12+ and ExifTool:

1. Open `config.json` and replace the two `CHANGE_ME` paths.
2. Double-click `start.bat`.
3. When it finishes, open `DESTINATION\_process\reports\report.html`.

The BAT performs the complete safe workflow: validate, inventory, analyze metadata, plan, check collisions and free space, copy, verify, reconcile, and report. The source is read-only and the destination must be empty.

## Configuration notes

`timestamp.future_tolerance_days` rejects suspicious capture dates that are too far after the run clock. The default `2` accepts small camera, phone, metadata, or timezone mistakes while rejecting obvious future dates such as `2099-01-01`. When a candidate timestamp is beyond this tolerance, the organizer tries the next configured timestamp source; if none is usable, the file is archived under `_UNKNOWN_DATE/`.

`copy.copy_workers` controls how many files may be copied and verified at the same time. The default `2` keeps the process moving without making slower disks or USB drives fight too much for bandwidth. Raising it can help on fast SSDs; lowering it can make runs gentler on removable drives.

`copy.free_space_margin_percent` adds extra required free space above the planned archive size before copying starts. The default `10` means the destination needs the planned bytes plus a 10 percent safety margin, with additional allowance for temporary partial files created by concurrent copy workers.

`day_grouping.threshold` is the minimum number of primary image/video files on one resolved calendar date required to create that date's `DayDD` folder. The default is `15`. Sidecars do not count; separate JPG and CR2 files do. Values must be integers greater than or equal to `1`.

## Output

```text
Photo_Archive/
├── _process/
│   ├── .archive_organizer_claim
│   ├── config_snapshot.json
│   ├── _AuditTrail/      # provenance, manifest, copy journal, reconciliation
│   ├── logs/photo_organizer.txt
│   ├── reports/         # report.html, summary.json, CSV reports
│   └── tmp/             # owned partial files; normally empty on completion
├── 2018/07-Jul/_sparse/IMG_20180729_093414.jpg
├── 2024/02-Feb/Day03/2024-02-03_002850.jpg
├── 2024/02-Feb/Day03/CR2/IMG_1001.CR2
├── 2024/02-Feb/Day03/CR2/IMG_1001.XMP
└── _UNKNOWN_DATE/Pasha4.jpg
```

Exit codes: `0` successful run (possibly warnings); `1` completed with file errors or reconciliation failure; `2` fatal validation/preflight/report failure; `3` interrupted.

Windows is the primary target. POSIX no-overwrite publication uses exclusive hard links and requires a supporting destination filesystem; other-platform release qualification is not claimed. See the testing document for verified environments and remaining limits.
