import argparse
from pathlib import Path

from .application import ArchiveOrganizer
from .config import ConfigError, ConfigLoader


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze and copy media into a verified chronological archive. Sources are read-only.")
    parser.add_argument("--config", type=Path, required=True, help="JSON configuration path")
    parser.add_argument("command", choices=["validate", "analyze", "plan", "run"])
    args = parser.parse_args(argv)
    try:
        config = ConfigLoader().load(args.config)
    except ConfigError as exc:
        print(f"FATAL: {exc}")
        return 2
    return ArchiveOrganizer(config).execute(args.command)
