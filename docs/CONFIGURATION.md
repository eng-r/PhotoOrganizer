# Configuration reference

JSON contains user policy. Mandatory verification, collision failure, source immutability, empty destination, no overwrite, and no AI are code invariants.

For normal use, edit only `source_root` and `destination_root` in the root `config.json`. All other settings use safe defaults. The optional settings below are an advanced reference. Relative paths are resolved against the config file's directory. Unknown keys, duplicate keys, invalid types, non-finite numbers, and invalid threshold combinations are rejected. Array values replace the default array; they are not merged.

| Section / field | Default / meaning |
| --- | --- |
| `media.include_extensions` | JPEG, HEIC, PNG, TIFF, BMP, CR2, CR3, ARW, DNG, MP4, MOV, M4V; include a leading dot. Case-insensitive. Add other camera/media extensions explicitly. |
| `media.ignore_name_patterns` | `.trashed.*`, `.trashed-*`, `Thumbs.db`, `.DS_Store`. Case-insensitive basename globs. |
| `media.ignore_directory_patterns` | `@eaDir`, `.Trash-*`. Descendants are still inventoried but never metadata-analyzed, dated, planned, or copied. |
| `timestamp.priority` | `DateTimeOriginal`, `XMPDateCreated`, `CreateDate`, `VideoCreationDate`, `FilenameDate`. First usable configured category wins. |
| `timestamp.minimum_year` | `1980` — lower it if your embedded/filename dates legitimately predate 1980. |
| `timestamp.future_tolerance_days` | `2` days beyond the frozen run clock. |
| `event_grouping.sparse_max_files_per_day` | `3` — sparse days go to `_sparse`. |
| `event_grouping.dense_min_files_per_day` | `4` — must equal sparse maximum + 1. |
| `event_grouping.event_max_span_days` | `3` — split consecutive dense runs into at most this many calendar days; never span months. |
| `copy.retry_count` | `2` retries after the initial attempt. |
| `copy.retry_delays_seconds` | `[1, 3]`; length must equal retry count. |
| `copy.copy_workers` | `2` streaming copy/verification workers. |
| `copy.free_space_margin_percent` | `10` above planned bytes plus conservative concurrent-partial overhead. |
| `runtime.progress_interval_seconds` | `5`; independent heartbeat during long operations. |
| `runtime.metadata_timeout_seconds` | `120` per ExifTool batch attempt. |

## Timestamp policy has one control

Remove `FilenameDate` from priority to disable filename parsing. Append `FilesystemMTime` to explicitly opt in to filesystem modification times. Missing categories are disabled. An empty priority list deliberately sends every eligible file to `_UNKNOWN_DATE/` after metadata extraction. There are no `allow_filename_fallback` or `allow_filesystem_fallback` switches.

Embedded categories must precede fallback categories. `FilesystemMTime` must follow `FilenameDate` when both are enabled. Original capture, XMP capture, image creation, and video creation categories may be reordered within the embedded group.

For metadata-only behavior, remove `FilenameDate` from the priority list. To opt into modification time, add `FilesystemMTime` last. Keep these advanced settings in the same root `config.json`; no additional JSON file is needed.

Common filename formats include `IMG_20180729_093414`, compact `IMG20240518125418_01`, `VID20251225164957`, `PXL_20260927_142355123`, `2024-02-03_002850`, `2026-09-27 14.23.55`, `IMG-20260927-WA0001`, and `Screenshot_20260927-142355`. Parsing matches the whole stem. A descriptive name containing a date substring is not one of these formats. Metadata is always inspected first.

Capture timestamps retain their recorded calendar date and explicit offset when available. Unknown timezones remain unknown. Offset-free video dates are not automatically shifted through the computer's timezone. Filesystem mtime is UTC and LOW confidence; it may reflect copying/restoration rather than capture. Day-only filename dates retain day precision.

No automatic scan/film-date inference is performed. Unknown-date media are preserved. Old collections should deliberately choose `minimum_year` and avoid assuming digitization dates are historical capture dates.

## Migrating the original specification's example

Remove `timestamp.allow_filename_fallback`, `timestamp.allow_filesystem_fallback`, `copy.verify`, and `copy.collision_policy`. Those old keys are rejected, not silently ignored. Add/remove timestamp categories instead; verification and collision handling cannot be disabled.
