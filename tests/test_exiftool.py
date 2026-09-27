import json
import os
import shutil
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from photo_archive_organizer.application import ArchiveOrganizer
from photo_archive_organizer.metadata import ExifToolMetadataProvider
from conftest import NOW


def exif_command():
    override = os.environ.get("EXIFTOOL_TEST_COMMAND")
    if override:
        return json.loads(override)
    if shutil.which("exiftool"):
        return ["exiftool"]
    local = Path(__file__).parents[1] / ".tools/exiftool-13.59/exiftool"
    if local.is_file() and shutil.which("perl"):
        return ["perl", str(local)]
    pytest.skip("real ExifTool not available; set EXIFTOOL_TEST_COMMAND or install exiftool")


def atom(kind, payload):
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def make_metadata_mp4(path):
    """Generated ISO-BMFF metadata fixture (no playable video frames)."""
    date = int((datetime(2020, 6, 7, 8, 9, 10, tzinfo=timezone.utc) - datetime(1904, 1, 1, tzinfo=timezone.utc)).total_seconds())
    mvhd = b"\0" * 4 + struct.pack(">IIII", date, date, 1000, 1000)
    mvhd += struct.pack(">Ih", 0x10000, 0x100) + b"\0" * 10
    mvhd += struct.pack(">9I", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    mvhd += b"\0" * 24 + struct.pack(">I", 1)
    path.write_bytes(atom(b"ftyp", b"isom\0\0\0\0isommp42") + atom(b"moov", atom(b"mvhd", mvhd)))


@pytest.mark.exiftool
def test_real_generic_jpeg_bmp_and_video(roots, make_config):
    from PIL import Image
    source, dest = roots
    command = exif_command()
    names = ["007.JPG", "Pasha4.jpg", "DSCN1277.JPG", "--- Travels 2025-12-07_001202.jpg",
             "--------- ! 2021 travels 2025-12-07_000949.jpg", "Unicode café.jpg"]
    exif = Image.Exif()
    exif[36867] = "2003:04:05 06:07:08"  # DateTimeOriginal; no camera Make/Model required.
    for name in names:
        Image.new("RGB", (4, 4), (40, 90, 120)).save(source / name, exif=exif)
    Image.new("RGB", (4, 4)).save(source / "random name.BMP")
    make_metadata_mp4(source / "video.mp4")
    provider = ExifToolMetadataProvider(command=command)
    app = ArchiveOrganizer(make_config(), provider, NOW)
    assert app.execute("run") == 0
    assert app.summary["successful_copies"] == 8
    for name in names:
        assert app.state.timestamps[name].value.year == 2003
        assert (dest / "2003/04-Apr/_sparse" / name).is_file()
    assert (dest / "_UNKNOWN_DATE/random name.BMP").is_file()
    assert app.state.timestamps["video.mp4"].value.isoformat() == "2020-06-07T08:09:10"
    assert not app.state.timestamps["video.mp4"].timezone_known


def test_metadata_timeout(tmp_path):
    import sys
    helper = tmp_path / "slow.py"
    helper.write_text("import time; time.sleep(10)")
    provider = ExifToolMetadataProvider(timeout=.05, command=[sys.executable, str(helper)])
    result = provider.read_batch([tmp_path / "x.jpg"])
    assert "timed out" in result[tmp_path / "x.jpg"].error


def test_partial_batch_failure_is_per_file(tmp_path, monkeypatch):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    provider = ExifToolMetadataProvider()
    monkeypatch.setattr(provider, "_execute", lambda *args: (1, json.dumps([
        {"SourceFile": str(a), "ExifIFD:DateTimeOriginal": "2001:01:01 01:01:01"},
        {"SourceFile": str(b), "ExifTool:Error": "corrupt media"}]), "error"))
    result = provider.read_batch([a, b])
    assert not result[a].error
    assert result[b].error == "corrupt media"
