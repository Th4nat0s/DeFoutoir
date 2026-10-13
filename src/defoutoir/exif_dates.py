"""Add a missing capture date to EXIF without re-encoding image pixels."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import zlib
from collections.abc import Iterator
from datetime import datetime
from enum import Enum
from pathlib import Path

from PIL import Image

from defoutoir.log import get_logger
from defoutoir.metadata import EXIF_DATETIME_ORIGINAL, extract_media_date

WRITABLE_EXIF_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png"})
JPEG_START = b"\xff\xd8"
JPEG_APP0 = 0xE0
JPEG_APP1 = 0xE1
JPEG_START_OF_SCAN = 0xDA
JPEG_END = 0xD9
JPEG_EXIF_PREFIX = b"Exif\x00\x00"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_EXIF_CHUNK = b"eXIf"
STREAM_CHUNK_SIZE = 1024 * 1024


class ExifDateStatus(str, Enum):
    """Outcome of one conditional EXIF date write."""

    WRITTEN = "written"
    ALREADY_DATED = "already-dated"
    UNSUPPORTED = "unsupported"


def supports_exif_date(path: str | Path) -> bool:
    """Return whether the file format has a lossless EXIF update adapter."""
    return Path(path).suffix.casefold() in WRITABLE_EXIF_EXTENSIONS


def calculate_dated_sha1(path: str | Path, captured: datetime) -> str:
    """Hash the exact bytes produced by adding ``captured`` to EXIF."""
    digest = hashlib.sha1(usedforsecurity=False)
    for chunk in _dated_chunks(Path(path), captured):
        digest.update(chunk)
    return digest.hexdigest()


def write_missing_exif_date(
    path: str | Path,
    captured: datetime,
    logger: logging.Logger | None = None,
) -> ExifDateStatus:
    """Atomically add ``DateTimeOriginal`` when no usable date already exists."""
    media_path = Path(path)
    active_logger = logger or get_logger("exif_dates")
    if not supports_exif_date(media_path):
        active_logger.warning(
            "Cannot add an EXIF date to unsupported format: %s", media_path
        )
        return ExifDateStatus.UNSUPPORTED
    if extract_media_date(media_path, active_logger) is not None:
        active_logger.info("Keeping existing media date in %s", media_path)
        return ExifDateStatus.ALREADY_DATED

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=media_path.parent,
            prefix=f".{media_path.name}.exif-",
            suffix=media_path.suffix,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            for chunk in _dated_chunks(media_path, captured):
                temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        shutil.copystat(media_path, temporary_path)
        os.replace(temporary_path, media_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    active_logger.info(
        "Added EXIF DateTimeOriginal %s to %s",
        captured.isoformat(sep=" "),
        media_path,
    )
    return ExifDateStatus.WRITTEN


def _dated_chunks(path: Path, captured: datetime) -> Iterator[bytes]:
    """Yield a losslessly enriched JPEG or PNG as bounded byte chunks."""
    exif_bytes = _updated_exif_bytes(path, captured)
    suffix = path.suffix.casefold()
    if suffix in {".jpeg", ".jpg"}:
        yield from _dated_jpeg_chunks(path, exif_bytes)
        return
    if suffix == ".png":
        yield from _dated_png_chunks(path, exif_bytes)
        return
    raise ValueError(f"unsupported EXIF output format: {path.suffix}")


def _updated_exif_bytes(path: Path, captured: datetime) -> bytes:
    """Serialize existing EXIF plus the canonical original-capture tag."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            exif[EXIF_DATETIME_ORIGINAL] = captured.strftime("%Y:%m:%d %H:%M:%S")
            return exif.tobytes()
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot prepare EXIF metadata for {path}: {error}") from error


def _dated_jpeg_chunks(  # pylint: disable=too-many-branches
    path: Path, exif_bytes: bytes
) -> Iterator[bytes]:
    """Insert one JPEG EXIF APP1 segment while preserving scan data exactly."""
    if not exif_bytes.startswith(JPEG_EXIF_PREFIX):
        raise ValueError("Pillow returned invalid JPEG EXIF data")
    if len(exif_bytes) > 65533:
        raise ValueError("JPEG EXIF data exceeds the APP1 segment limit")
    exif_segment = b"\xff\xe1" + (len(exif_bytes) + 2).to_bytes(2, "big") + exif_bytes

    with path.open("rb") as stream:
        if stream.read(2) != JPEG_START:
            raise ValueError(f"invalid JPEG signature: {path}")
        yield JPEG_START
        inserted = False
        while True:
            marker_prefix = stream.read(1)
            if not marker_prefix:
                raise ValueError(f"JPEG ended before image data: {path}")
            if marker_prefix != b"\xff":
                raise ValueError(f"invalid JPEG marker in {path}")
            marker_bytes = bytearray(marker_prefix)
            marker = stream.read(1)
            while marker == b"\xff":
                marker_bytes.extend(marker)
                marker = stream.read(1)
            if not marker:
                raise ValueError(f"truncated JPEG marker in {path}")
            marker_bytes.extend(marker)
            marker_value = marker[0]

            if not inserted and marker_value != JPEG_APP0:
                yield exif_segment
                inserted = True
            if marker_value == JPEG_END:
                yield bytes(marker_bytes)
                return
            if marker_value in {0x01, *range(0xD0, 0xD8)}:
                yield bytes(marker_bytes)
                continue

            length_bytes = stream.read(2)
            if len(length_bytes) != 2:
                raise ValueError(f"truncated JPEG segment length in {path}")
            length = int.from_bytes(length_bytes, "big")
            if length < 2:
                raise ValueError(f"invalid JPEG segment length in {path}")
            payload = stream.read(length - 2)
            if len(payload) != length - 2:
                raise ValueError(f"truncated JPEG segment in {path}")

            is_old_exif = marker_value == JPEG_APP1 and payload.startswith(
                JPEG_EXIF_PREFIX
            )
            if not is_old_exif:
                yield bytes(marker_bytes) + length_bytes + payload
            if marker_value == JPEG_START_OF_SCAN:
                yield from iter(lambda: stream.read(STREAM_CHUNK_SIZE), b"")
                return


def _dated_png_chunks(path: Path, exif_bytes: bytes) -> Iterator[bytes]:
    """Insert one PNG eXIf chunk while preserving every other chunk exactly."""
    if not exif_bytes.startswith(JPEG_EXIF_PREFIX):
        raise ValueError("Pillow returned invalid PNG EXIF data")
    payload = exif_bytes[len(JPEG_EXIF_PREFIX) :]
    chunk_body = PNG_EXIF_CHUNK + payload
    exif_chunk = (
        len(payload).to_bytes(4, "big")
        + chunk_body
        + (zlib.crc32(chunk_body) & 0xFFFFFFFF).to_bytes(4, "big")
    )

    with path.open("rb") as stream:
        if stream.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            raise ValueError(f"invalid PNG signature: {path}")
        yield PNG_SIGNATURE
        inserted = False
        while True:
            length_bytes = stream.read(4)
            if not length_bytes:
                raise ValueError(f"PNG ended before IEND: {path}")
            if len(length_bytes) != 4:
                raise ValueError(f"truncated PNG chunk length in {path}")
            length = int.from_bytes(length_bytes, "big")
            chunk_type = stream.read(4)
            data = stream.read(length)
            checksum = stream.read(4)
            if len(chunk_type) != 4 or len(data) != length or len(checksum) != 4:
                raise ValueError(f"truncated PNG chunk in {path}")

            if chunk_type != PNG_EXIF_CHUNK:
                yield length_bytes + chunk_type + data + checksum
            if not inserted and chunk_type == b"IHDR":
                yield exif_chunk
                inserted = True
            if chunk_type == b"IEND":
                return
