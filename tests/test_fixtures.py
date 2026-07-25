"""Integrity tests for downloaded media fixtures."""

from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "media"
EXPECTED_SHA256 = {
    "jpeg/exif-gps.jpg": (
        "360eb3ce66533146584aa66576130c5ab98c763b7c7f51898892e7eaa7dcab49"
    ),
    "jpeg/flower.jpg": (
        "8a9d04b92d0de5836c59ede8ae421235488e4031e893e07b1fe7e4b78f6a9901"
    ),
    "jpeg/hopper.jpg": (
        "ffe89a0ab0e94114e10777e7313d7fa83d634e34ebc2ea7479085cffa504c920"
    ),
    "png/flower-thumbnail.png": (
        "24bcfb49a911b30cb29f5c375a9407a3e24a6e78383f76ca9eb728487e1021dc"
    ),
    "png/test-card.png": (
        "b4baeb18d77acc45766811978373a2f087eda5fb05b5c0aadc3291f4aa331fa4"
    ),
    "raw/jolstravatnet.pef": (
        "de99991add7af41a21aa8b86f9579f27d5544fdb4b40f4e97964d3adf1989d2b"
    ),
    "raw/sample.arw": (
        "a188d977540c9121e51ea45df41b1c24bfb80e12ed18d3ece9b45b4db73d5af2"
    ),
    "raw/sample.cr2": (
        "651f1c9090adbc1d2e8b69b973b89e051b519f0824d7d9d19c47ca4cf521d872"
    ),
    "raw/_MG_3055.dng": (
        "0d4188ef0771f5a74bd172781da4be23cac6c1dcc79fa2dbf43f63b8a6fb93a2"
    ),
    "raw/_MG_8968.CR2": (
        "7510508d3ee911b9a5ef88a16856baaacb5ef5a17ae563c58b937a315ff72e13"
    ),
    "raw/sample.dng": (
        "68e5f8554a17106c20525e4c0b8ade17403f906171e8a3d934fbeb426b8ccc05"
    ),
    "raw/sample.nef": (
        "d2807a93c95b14226a02c2f3c392fae6209b8bc477dd23818722e794e5c83a81"
    ),
}


def calculate_sha256(path: Path) -> str:
    """Calculate a file SHA-256 without loading it fully into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as fixture:
        for chunk in iter(lambda: fixture.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_fixture_set_contains_exactly_twelve_files() -> None:
    """The repository must contain the selected twelve media fixtures."""
    actual_paths = {
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_file() and path.name != "README.md"
    }

    assert actual_paths == set(EXPECTED_SHA256)


def test_fixture_checksums() -> None:
    """Downloaded fixture bytes must match their reviewed upstream versions."""
    for relative_path, expected_hash in EXPECTED_SHA256.items():
        assert calculate_sha256(FIXTURE_ROOT / relative_path) == expected_hash
