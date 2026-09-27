# Implementation status

The v1 CLI, safety checks, recursive inventory, metadata/date resolution, deterministic planning, verified copy engine, independent reconciliation, TXT/HTML reporting, and Windows launchers are implemented.

## Validation performed

On the Windows development host:

| Interpreter | Test result |
| --- | --- |
| Python 3.12 | 83 passed, 1 skipped |
| Python 3.14 | 83 passed, 1 skipped |

Real-provider tests used official ExifTool **13.59** with the host's Perl interpreter. Fixtures were generated JPEGs, a BMP without a date, and a minimal ISO-BMFF movie metadata fixture. Tests covered renamed generic JPEGs, Unicode names, all supplied filename families, the 54-file `flist2.txt` layout, source immutability, the 97-file success case, the 96-of-97 failure case, collision refusal, publication races, retries, disk-full stop, interruption, and report failures.

The skipped case requires Windows symbolic-link creation privileges. A separate junction test passed and covers skipping a source junction and rejecting a junction as a configured root.

The one-click `start.bat` launcher, Python CLI help, and Python compilation were also exercised. No actual photo collection was processed.

## Before using a real collection

Install the production ExifTool executable or point `PHOTO_ORGANIZER_EXIFTOOL` at it, edit the example source/destination paths, and run a preview into its own empty destination. The ignored development `.tools/` cache is not a production installation. Follow [QUICK_START.md](QUICK_START.md).

RAW/HEIC samples from individual cameras are not bundled or individually qualified by these tests. Those formats are delegated to ExifTool; inspect preview results from your collection. POSIX release qualification, hard-kill/power-loss recovery, resume, and append are outside v1's validated scope.

The original v2 specification and revised implementation plan remain under `plan/`; current user-facing configuration and behavior are documented in this README/doc set. The priority-only timestamp configuration and mandatory SHA-256/collision invariants supersede the original specification's redundant JSON switches.
