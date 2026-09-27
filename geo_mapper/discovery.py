import re
from pathlib import Path

from .config import MEDIA_EXTENSIONS, MONTH_ABBR
from .models import MonthFolder, ResolvedTarget, TargetScope


class DiscoveryError(ValueError):
    pass


MIN_YEAR = 1800
MAX_YEAR = 9999


def parse_year_folder(path: Path) -> int:
    if not re.fullmatch(r"\d{4}", path.name):
        raise DiscoveryError(f"not a canonical year folder: {path.name}")
    year = int(path.name)
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise DiscoveryError(f"year folder is outside the supported range {MIN_YEAR}..{MAX_YEAR}: {path.name}")
    return year


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
    year = parse_year_folder(path)
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


def discover_months(year_path: Path):
    return _months_in_year(year_path)


def discover_years(archive_path: Path):
    years = []
    for child in archive_path.iterdir():
        if not child.is_dir():
            continue
        try:
            year = parse_year_folder(child)
        except DiscoveryError:
            continue
        years.append((year, child))
    return sorted(years, key=lambda item: item[0])


def resolve_target(target: Path, explicit_scope: TargetScope | str | None = None) -> ResolvedTarget:
    target = target.resolve()
    if not target.is_dir():
        raise DiscoveryError(f"target does not exist or is not a directory: {target}")
    detected = None
    try:
        month = parse_month_folder(target)
        year = parse_year_folder(target.parent)
        detected = ResolvedTarget(target, TargetScope.MONTH, year, month.month, month.context)
    except (DiscoveryError, ValueError):
        pass
    if detected is None:
        try:
            year = parse_year_folder(target)
            detected = ResolvedTarget(target, TargetScope.YEAR, year)
        except DiscoveryError:
            pass
    if detected is None and discover_years(target):
        detected = ResolvedTarget(target, TargetScope.ARCHIVE)
    if detected is None:
        raise DiscoveryError("Unable to determine Geo Mapper target scope. Expected MONTH NN-Mmm[optional suffix], YEAR YYYY, or ARCHIVE with immediate YYYY child folders.")
    if explicit_scope is not None:
        expected = TargetScope(explicit_scope)
        if detected.scope != expected:
            raise DiscoveryError(f"Target does not satisfy {expected.value.upper()} scope rules; detected {detected.scope.value.upper()} instead.")
    return detected


def discover_target(resolved: ResolvedTarget):
    if resolved.scope == TargetScope.MONTH:
        return {resolved.year: [parse_month_folder(resolved.path, resolved.year)]}
    if resolved.scope == TargetScope.YEAR:
        return {resolved.year: discover_months(resolved.path)}
    return {year: discover_months(path) for year, path in discover_years(resolved.path)}


def resolve_scope(target: Path):
    """Compatibility wrapper returning the typed scope and discovered months."""
    resolved = resolve_target(target)
    return resolved.scope, discover_target(resolved)
