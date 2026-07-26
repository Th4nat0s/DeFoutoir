# DeFoutoir

DeFoutoir is a simple Python tool for cleaning and sorting pictures and movies.

It accepts an unstructured input folder, including subfolders, and organizes the media files by date.

> DeFoutoir 0.1.0 is the first usable release. Review the dry-run preview
> before applying a large organization operation.

## How it works

DeFoutoir:

1. Scans the input folder and its subfolders.
2. Creates a clean SQLite database with file information, including the SHA-1 hash and date.
3. Reads the timestamp from the media metadata when it is available.
4. Uses the filename to find the date when media metadata is not available.
5. Copies the files into folders organized by date by default.

The original files are kept unless the move option is explicitly selected.

## Organization plan

The canonical destination layout is `YYYY/MM/DD/filename`. Media without a
usable date goes into `unknown/filename`. Planning happens before file
operations and does not create directories or modify files. Existing files
with the same SHA-1 are marked as duplicates; a different file with the same
name receives a deterministic `filename__<sha1-prefix>.ext` alternate name.

## Multiple input folders

DeFoutoir can scan several input folders in one operation.
Repeat the `--input` option for each folder:

```bash
python defoutoir.py \
  --input ./phone-media \
  --input ./camera-media \
  --input ./old-media \
  --output ./sorted-media
```

All input folders are scanned and organized in the same output folder.

## Dry run

The `dry run` option previews the planned changes without moving, copying, or modifying media files.
It is useful for checking the result before applying it.
Dry runs also use an in-memory catalog, so the configured SQLite database is
not created or changed.

Example:

```bash
python defoutoir.py --input ./unstructured-media --output ./sorted-media --dry-run
```

When the result is correct, run the command without `--dry-run` to apply the operation.

## Learn mode

The `--learn` option scans the input folder and learns the media information without copying or moving any files.
It creates or updates the SQLite database with file hashes and dates.
This mode is useful for preparing the database before a later organization operation.

Example:

```bash
python defoutoir.py --input ./unstructured-media --learn
```

Learn mode only reads the media files and updates the database. It does not change the input or output folders.
Each learned file is classified as `learned`, `updated`, `unchanged`, or
`duplicate`; files previously cataloged but no longer present under the input
folders are marked `missing`.

## File operations

DeFoutoir can:

- copy files to the date-based folders by default, while keeping the originals; or
- move files to the date-based folders with the `--move` option.

Default copy:

```bash
python defoutoir.py --input ./unstructured-media --output ./sorted-media
```

Explicit move:

```bash
python defoutoir.py --input ./unstructured-media --output ./sorted-media --move
```

Move removes a source only after its destination has been written
successfully. Existing destination files are never overwritten; identical
content is skipped and different content receives a deterministic alternate
name.

## Supported media discovery

The discovery layer scans every input directory recursively and accepts
multiple inputs in one operation. Duplicate and overlapping inputs are scanned
only once, and results are returned in deterministic path order.

Supported picture extensions:

```text
arw, bmp, cr2, cr3, dng, gif, heic, heif, jpeg, jpg, nef, nrw, orf,
pef, png, raf, raw, rw2, sr2, srf, tif, tiff, webp, x3f
```

Supported movie extensions:

```text
3g2, 3gp, avi, m2ts, m4v, mkv, mov, mp4, mpeg, mpg, mts, webm, wmv
```

Symbolic links found inside an input tree are skipped. An input path that is
itself a symbolic link is resolved once before scanning. Unreadable or invalid
paths produce warnings without stopping the remaining inputs. macOS metadata
directories such as `.AppleDouble` and `__MACOSX` are ignored.

## SQLite catalog

The catalog is stored in `defoutoir.sqlite3` by default. The database path is
configurable with `--database` or through the Python catalog API. Dry-run uses
an in-memory catalog and never creates or changes the configured database.

The catalog uses schema version 1 and stores the normalized source path,
incremental SHA-1 identity, file size, modification timestamps, resolved media
date, date source, and processing state. A SHA-1 index makes duplicate-content
groups queryable without changing or deleting the original files.

List the catalog without scanning or modifying anything:

```bash
python defoutoir.py --list --database ./defoutoir.sqlite3
```

The output contains the selected `timestamp`, its `date_source`, `name`,
`sha1`, and the normalized `pathname`.

Show only files without a resolved date, or files that ended in an error:

```bash
python defoutoir.py --list-no-date --database ./defoutoir.sqlite3
python defoutoir.py --list-errors --database ./defoutoir.sqlite3
python defoutoir.py --list-duplicates --database ./defoutoir.sqlite3
```

`--list-duplicates` shows every cataloged file whose SHA-1 is shared by at
least one other file.

## Metadata date precedence

The metadata extractor reads dates without modifying the source file. When
several timestamps are available, it uses this order:

1. EXIF `DateTimeOriginal`;
2. EXIF `DateTimeDigitized`;
3. XMP `photoshop:DateCreated` or `xmp:CreateDate`;
4. generic EXIF `DateTime`;
5. container creation date from RAW or video metadata.

Dates are normalized to UTC when a timezone is present. Invalid or missing
metadata produces a warning or a clean no-date result.

## Filename date fallback

When no usable metadata date exists, DeFoutoir can read an explicit date from
the filename. The supported patterns are `YYYYMMDD`, `YYYY-MM-DD`,
`YYYY_MM_DD`, and `YYYY.MM.DD`. An optional capture time is also read when it
follows the date as `HHMMSS` (for example `IMG_20240102_123456.JPG`) or as
`at HH.MM.SS` (for example a WhatsApp export). Invalid dates, ambiguous short
formats, and filenames containing multiple different dates are ignored.
Metadata always takes precedence over a filename date.

## Development setup

DeFoutoir requires Python 3.10 or newer.

Install the package from a checkout and its runtime dependencies with:

```bash
python -m pip install -r requirements.txt
```

Create a virtual environment and install the project with its development
tools:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

The package provides both module and console entry points:

```bash
python defoutoir.py --help
```

## Quality checks

Every code change must pass the tests, Black, and Pylint:

```bash
python -m pytest
python -m black --check src tests
python -m pylint src tests
```

GitHub Actions runs the same checks with Python 3.10.

## Recovery and troubleshooting

Use `--dry-run` first to inspect every planned destination. Copy mode keeps
all source files, so it is the safest recovery path. Move mode is protected by
an atomic destination transfer and removes a source only after success; a
failed transfer leaves the source in place. Re-running the same command is
safe: identical destinations are reported as duplicates and are not copied
again.

Common errors:

- `--output is required`: add an output directory, unless using `--learn`.
- `must not overlap`: choose an output directory outside every input tree.
- `Processing completed with errors`: inspect the logged source and rerun
  after fixing its permissions or destination.
- A file in `unknown/`: no valid metadata or explicit filename date was found.

The command returns `0` for success, `1` for processing failures, and `2` for
invalid command-line options or paths.

## Release readiness

The quality workflow runs on Python 3.10 and enforces Black, Pylint, and the
complete pytest suite. The project is licensed under AGPL-3.0-or-later.

## License

Copyright (C) 2026 Th4nat0s.

DeFoutoir is free software licensed under the
[GNU Affero General Public License version 3 or later](LICENSE).
