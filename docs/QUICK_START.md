# Quick start

You only need two files:

- `config.json` — source/destination paths plus all normal settings in one place.
- `start.bat` — double-click this to run.

## 1. Edit `config.json`

Replace both example paths and save. The complete JSON exposes every normal user setting: media extensions, ignore rules, timestamp order, the daily primary-media threshold, copy retries/workers/space margin, and progress/metadata timeout. Leave a setting at its shown value unless you want to change that behavior.

```json
{
  "source_root": "D:/My Original Photos",
  "destination_root": "E:/My New Photo Archive"
}
```

The source is your existing photo/video collection. The destination must be a different, empty folder. It may also be a new folder that does not exist yet. Do not put one folder inside the other.

The settings that are deliberately absent from JSON are safety guarantees: source read-only, destination initially empty, SHA-256 copy verification, failure on target-name collisions, and no overwriting.

## 2. Double-click `start.bat`

That is the complete workflow. The BAT checks Python, then the program validates paths and ExifTool before it copies anything. It inventories the source, reads metadata, prepares the complete plan, checks collisions and free space, copies and verifies each file, and performs final reconciliation.

If `config.json` still contains `CHANGE_ME`, the BAT opens it in Notepad and does not run.

## 3. Read the result

When the window says it finished, open:

```text
YOUR DESTINATION\_process\reports\report.html
```

The detailed TXT log is:

```text
YOUR DESTINATION\_process\logs\photo_organizer.txt
```

Both include **Source files not archived**, with a reason for every listed file. Files copied to `_UNKNOWN_DATE` were archived successfully and are not considered missing.

Dated media is stored under fixed `YYYY/MM-Mmm/DayDD` folders when a date reaches the configured threshold; smaller dates share that month's `_sparse`. CR2 files use a nested `CR2` folder, and unambiguous same-stem XMP/AAE sidecars follow their primary file.

If the BAT reports a problem, nothing in the source is modified. Read the message and see [operations and troubleshooting](OPERATIONS.md). A destination used by any prior attempt is no longer empty; use a new empty destination for another run.

Advanced `validate`, `analyze`, and `plan` commands still exist for technical use, but they are not required for the normal one-BAT workflow.
