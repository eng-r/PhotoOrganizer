# Installation

## Requirements

- Windows with Python **3.12 or newer** and the `py` launcher, or an explicitly selected Python interpreter.
- ExifTool available as an executable. This is a separate dependency, not a Python package.
- An accessible source folder and a separate empty destination with enough free space.

The application uses only the Python standard library. `requirements.txt` intentionally has no third-party runtime packages. Tests additionally use pytest and Pillow (for generating real image fixtures).

## 1. Install Python

Install Python from [python.org](https://www.python.org/downloads/windows/) if necessary. Make sure the Windows `py` launcher is included. Check it with:

```bat
py -3 --version
```

No Python packages are required for normal use. `start.bat` runs the application directly. Creating a virtual environment is optional:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No activation is required when using the full interpreter path or the supplied `.bat` launcher. Optional editable package installation enables `photo-organizer`:

```bat
.venv\Scripts\python.exe -m pip install -e .
```

## 2. Install ExifTool

Obtain the official Windows distribution from [ExifTool](https://exiftool.org/). Follow its installation instructions, including retaining companion files/directories beside the executable. If the executable is named `exiftool(-k).exe`, use the non-pausing name `exiftool.exe` for automation.

Add its directory to PATH, or set a process environment variable pointing directly to the executable:

```bat
set "PHOTO_ORGANIZER_EXIFTOOL=C:\Tools\ExifTool\exiftool.exe"
"%PHOTO_ORGANIZER_EXIFTOOL%" -ver
```

This variable is a single executable path, not a shell command. Paths with spaces are supported. The program never installs or updates ExifTool automatically and only invokes it for reading metadata.

## 3. Configure and start

Edit the two paths in `config.json`, save it, and double-click `start.bat`. See [QUICK_START.md](QUICK_START.md).

The BAT pauses at the end so its result remains visible. It refuses to run while the placeholder `CHANGE_ME` paths remain.

## Developer setup

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

See [TESTING.md](TESTING.md) for real ExifTool tests and platform-specific notes. The downloaded `.tools/` folder used during development is ignored and is not an installed production dependency.
