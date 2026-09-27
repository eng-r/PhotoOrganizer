import html
import re
from pathlib import Path
from urllib.parse import urlparse

from .models import HumanNotes


def _safe_link(match):
    label, url = match.group(1), html.unescape(match.group(2)).strip()
    if urlparse(url).scheme not in {"http", "https"}:
        return label
    return f'<a href="{html.escape(url, quote=True)}" rel="noopener noreferrer">{label}</a>'


def render_safe_markdown(text: str) -> str:
    blocks = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        lines = raw.splitlines()
        escaped = [html.escape(line) for line in lines]
        if all(line.lstrip().startswith("- ") for line in lines):
            items = "".join(f"<li>{re.sub(r'\[([^]]+)\]\(([^)]+)\)', _safe_link, line.lstrip()[2:])}</li>" for line in escaped)
            blocks.append(f"<ul>{items}</ul>")
        elif len(lines) == 1 and re.match(r"^#{1,3} ", lines[0]):
            level = len(lines[0]) - len(lines[0].lstrip("#"))
            blocks.append(f"<h{level}>{html.escape(lines[0][level + 1:])}</h{level}>")
        else:
            value = "<br>".join(escaped)
            value = re.sub(r"\[([^]]+)\]\(([^)]+)\)", _safe_link, value)
            blocks.append(f"<p>{value}</p>")
    return "".join(blocks)


def _parse_front_matter(text: str):
    title, places, body, warnings = None, [], text, []
    if not text.startswith("---\n"):
        return title, places, body, warnings
    end = text.find("\n---", 4)
    if end < 0:
        return None, [], text, ["malformed notes front matter: closing --- is missing"]
    header, body = text[4:end], text[end + 4:].lstrip("\r\n")
    active = None
    for line in header.splitlines():
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip('"\'') or None
            active = None
        elif line.startswith("places:"):
            active = "places"
        elif active == "places" and re.match(r"^\s*-\s+", line):
            places.append(re.sub(r"^\s*-\s+", "", line).strip().strip('"\''))
        elif line.strip():
            warnings.append(f"unsupported notes front-matter line: {line.strip()}")
    return title, places, body, warnings


def read_notes(directory: Path) -> HumanNotes | None:
    path = directory / "map_notes.md"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return HumanNotes(None, (), "", "", None, (f"could not read map_notes.md: {exc}",))
    title, places, body, warnings = _parse_front_matter(text)
    plain = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", body)
    plain = re.sub(r"[#*_`>-]", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    excerpt = (plain[:197].rstrip() + "...") if len(plain) > 200 else plain or None
    return HumanNotes(title, tuple(places), body, render_safe_markdown(body), excerpt, tuple(warnings))
