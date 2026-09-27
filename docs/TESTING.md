# Testing and release checks

Tests use temporary synthetic source/destination trees. They do not read, migrate, rename, or delete the photo collections named in `_refs/`.

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

The development host has unrelated pytest plugins installed; isolated environments avoid that noise. If needed:

```bat
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
py -3.12 -m pytest -q
```

## Coverage

- Strict JSON, authoritative timestamp priority, invariant controls rejected, threshold/range validation.
- Root overlap, initially non-empty destination, concurrent claims and preserved ownership.
- Case-insensitive media matching, recursive ignored-directory inventory, skipped links.
- Common filename formats, unusual names, metadata precedence, missing/invalid dates, timezone provenance.
- Sparse/dense boundaries, consecutive-day limits, month/year boundaries, deterministic ordering, collisions and space.
- Verified copy, publication no-overwrite, retry, Ctrl+C, source immutability, final inventory membership.
- Mandatory 100-recognized / 3-ignored / 97-eligible success, and one-copy-failure (96 copied) accounting.
- `flist2.txt` 54-path regression built from synthetic contents.
- TXT/HTML/CSV omitted-file explanations and successful unknown-date copies.
- Real ExifTool integration on generated JPEG/BMP and ISO-BMFF metadata fixtures, including punctuation, spaces, and Unicode filenames.

## Real ExifTool tests

Tests marked `exiftool` require the executable on PATH or a JSON-array command override:

```bat
set EXIFTOOL_TEST_COMMAND=["C:/Tools/ExifTool/exiftool.exe"]
.venv\Scripts\python.exe -m pytest -m exiftool -q
```

Development can use a local official source distribution with an existing Perl interpreter:

```bat
set EXIFTOOL_TEST_COMMAND=["perl", "D:/Tools/exiftool/exiftool"]
```

The test helper also recognizes `.tools/exiftool-13.59/exiftool` if Perl is available. That directory is ignored and not shipped. If ExifTool is unavailable, these tests explicitly skip; a skipped real-provider test is not release validation. The generated MP4 fixture validates date extraction from a minimal ISO-BMFF movie header, not video decoding/playback.

## Limits to distinguish from passing tests

Symlink creation may be prohibited by Windows account policy; those tests explicitly skip on such hosts. Real camera RAW/HEIC samples are not bundled. ExifTool provides those format readers, but representative files from a new camera/source should be previewed before its first archive run. No throughput or power-loss recovery guarantee is inferred from synthetic tests. Resume and append remain unsupported.

The exact executed test counts and interpreter versions are recorded in the implementation handoff; do not treat a documentation claim as a substitute for running the suite in your environment.
