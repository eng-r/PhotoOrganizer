import re
from pathlib import Path

from .config import MEDIA_EXTENSIONS, MONTH_ABBR
from .models import MonthFolder


class DiscoveryError(ValueError):
    pass


def parse_month_folder(path: Path, year: int | None = None) -> MonthFolder:
    match = re.fullmatch(r"(0[1-9]|1[0-2])-([A-Za-z]{3})(.*)", path.name)
    if not match:
        raise DiscoveryError(f"not a month folder: {path.name}")
    month = int(match.group(1))
    abbreviation = match.group(2)
    if abbreviation != MONTH_ABBR[month]:
        raise DiscoveryError(f"month number and abbreviation disagree: {path.name}")
    suffix = match.group(3)
    context = None
    if suffix:
        if suffix.startswith(" [") and suffix.endswith("]"):
            context = suffix[2:-1].strip()
        elif suffix[0] in "._ ":
            context = suffix.lstrip("._ ").strip()
        else:
            raise DiscoveryError(f"invalid month suffix: {path.name}")
        if not context:
            raise DiscoveryError(f"empty month context: {path.name}")
    resolved_year = year if year is not None else int(path.parent.name)
    return MonthFolder(path, resolved_year, month, f"{month:02d}-{MONTH_ABBR[month]}", context)


def discover_media(month: MonthFolder) -> list[Path]:
    files = []
    for path in month.path.rglob("*"):
        if not path.is_file() or ".geo_mapper" in path.parts:
            continue
        if path.suffix.lower() in MEDIA_EXTENSIONS:
            files.append(path)
    return sorted(files, key=lambda p: (p.relative_to(month.path).as_posix().casefold(), p.relative_to(month.path).as_posix()))


def _months_in_year(path: Path) -> list[MonthFolder]:
    if not re.fullmatch(r"\d{4}", path.name):
        raise DiscoveryError(f"year folder must be four digits: {path}")
    year = int(path.name)
    months = []
    for child in sorted((p for p in path.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        try:
            month = parse_month_folder(child, year)
        except DiscoveryError:
            if re.match(r"^\d{2}-[A-Za-z]{3}", child.name):
                raise
            continue
        if discover_media(month):
            months.append(month)
    return sorted(months, key=lambda m: m.month)


def resolve_scope(target: Path):
    target = target.resolve()
    if not target.is_dir():
        raise DiscoveryError(f"target does not exist or is not a directory: {target}")
    try:
        month = parse_month_folder(target)
        if not re.fullmatch(r"\d{4}", target.parent.name):
            raise DiscoveryError(f"month parent must be a four-digit year: {target.parent}")
        return "month", {month.year: [month]}
    except (DiscoveryError, ValueError):
        pass
    if re.fullmatch(r"\d{4}", target.name):
        return "year", {int(target.name): _months_in_year(target)}
    years = {}
    for child in sorted((p for p in target.iterdir() if p.is_dir()), key=lambda p: p.name):
        if re.fullmatch(r"\d{4}", child.name):
            months = _months_in_year(child)
            if months:
                years[int(child.name)] = months
    if not years:
        raise DiscoveryError(f"no processable year/month hierarchy found under {target}")
    return "archive", years
