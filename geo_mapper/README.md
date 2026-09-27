# Geo Mapper

Geo Mapper is an independent, read-only add-on for an archive already created by Photo Archive Organizer. It reads media metadata and generates monthly memory maps plus annual navigation pages. It never copies, moves, renames, deletes, or edits photos and never writes `map_notes.md`.

## Prerequisites

- Python 3.12 or newer
- ExifTool available on `PATH`, or its executable path in `GEO_MAPPER_EXIFTOOL`
- An organized `YEAR/NN-Mmm` archive tree

V1 reads JPG/JPEG and common RAW files. JPG/RAW files with the same stem in the same folder become one logical photo event, with JPEG preferred. XMP, AAE, JSON, and THM sidecars never create events.

## Run it

```bat
geo_mapper\geo_mapper.bat D:\Photos\2026\03-Mar.Ecuador
geo_mapper\geo_mapper.bat D:\Photos\2026
geo_mapper\geo_mapper.bat D:\Photos
```

Python CLI equivalents:

```bat
python -m geo_mapper D:\Photos\2026
python -m geo_mapper D:\Photos\2026 --offline
python -m geo_mapper D:\Photos --dry-run
python -m geo_mapper D:\Photos --scope archive
```

The target path is optional. Running `geo_mapper.bat` or `python -m geo_mapper` without one uses the current directory. Scope is inferred conservatively as `MONTH`, `YEAR`, or `ARCHIVE`. `--scope month|year|archive` validates the inferred scope for scripts; it cannot force a year folder to behave as a month.

A month target creates only that month's `travel_map.html` and `.geo_mapper/geo_data.json`; it does not replace the parent annual page. A year or archive target rebuilds every non-empty recognized month and creates `travel_map_YEAR.html` plus `.geo_mapper/year_data.json` for each complete year scope.

Batch processing isolates fatal month failures. Later months and years continue, but an annual page is regenerated only when every discovered non-empty month for that year succeeds. A known-good annual page is therefore never replaced with a knowingly incomplete view. Exit code `0` means complete success, `1` means the batch completed with month/year failures, and `2` means invalid invocation or a global prerequisite failure.

Demo launchers are included beside the main launcher:

- `demo_month.bat`
- `demo_year.bat`
- `demo_archive.bat`
- `demo_offline_dry_run.bat`

`--offline` prohibits network calls and still uses cached labels. `--no-geocode` disables live reverse geocoding. `--dry-run` performs hierarchy/media discovery without ExifTool, network calls, or writes. Generated HTML can be opened directly from disk. Leaflet and normal basemap tiles load from public web assets when connectivity exists; summaries, notes, month links, event data, and the coordinate list remain embedded and useful without tiles.

## Folder Context And Notes

Fixed English month prefixes are required: `01-Jan` through `12-Dec`. A display-only suffix is allowed:

```text
03-Mar.Ecuador
03-Mar_Africa
03-Mar Ecuador
03-Mar [Ecuador]
```

The number and abbreviation must agree. Context text is displayed but never geocoded.

Optional `map_notes.md` files may appear in month and year folders. Plain Markdown works. Optional front matter supports human labels:

```markdown
---
title: Ecuador
places:
  - Quito
  - Cotopaxi
---

Our first trip to Ecuador.
```

Only limited, escaped Markdown is rendered. Raw HTML is displayed as text, unsafe link schemes are not linked, and notes never create GPS points. Generated artifacts are disposable; rerunning deterministically rebuilds them from current photos, notes, context, and cache.

## Geocoding And Privacy

Core mapping is local and geocoding is optional. Live GeoNames enrichment occurs only when `GEO_MAPPER_GEONAMES_USERNAME` is set and neither `--offline` nor `--no-geocode` is used. Geo Mapper sends one cluster coordinate per cache miss. It never uploads photos, filenames, EXIF payloads, folder context, notes, or human `places` labels. Cache data stays under each month's `.geo_mapper/cache.json`.

## Outputs

```text
2026/
├── travel_map_2026.html
├── .geo_mapper/year_data.json
└── 03-Mar.Ecuador/
    ├── map_notes.md
    ├── travel_map.html
    └── .geo_mapper/
        ├── geo_data.json
        └── cache.json
```

Months with photos but no GPS still receive a useful narrative/summary page and remain in annual navigation. Empty month folders are omitted.

## Troubleshooting

- **ExifTool not found:** install ExifTool or set `GEO_MAPPER_EXIFTOOL`; no map output is written after this failure.
- **No GPS shown:** inspect `.geo_mapper/geo_data.json` warnings. Both latitude and longitude must be valid.
- **No place names:** GPS maps do not require names. Set a GeoNames username, or rerun without `--offline` after credentials are configured.
- **Map tiles unavailable:** reconnect to the Internet; embedded summaries and coordinates remain available.
- **Month rejected:** use a fixed matching prefix such as `03-Mar`; `03-May` is invalid.

Geo Mapper is not a route tracker, GIS editor, photo organizer, database, web service, or AI description system. Dotted lines are labeled **Photo sequence** and show only trustworthy same-day capture order within conservative time/distance gaps.
