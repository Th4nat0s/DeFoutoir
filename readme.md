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
Source files are grouped by SHA-1 before planning, so only one representative
is published. A filename containing a recognized date is preferred, then the
shortest normalized filename, followed by stable lexical path ordering.
Groups without a resolved media timestamp are processed first. Dated groups
then run from the oldest capture timestamp to the newest, with stable path
ordering when timestamps are equal. The dry-run preview uses the same order.

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

### Use the catalog without rescanning

Add `--do-not-rescan` to build the organization plan only from an existing
SQLite catalog. DeFoutoir does not traverse input directories, hash source
files, or extract metadata in this mode:

```bash
python defoutoir.py \
  --database ./defoutoir.sqlite3 \
  --output ./sorted-media \
  --dry-run \
  --dateunk \
  --do-not-rescan
```

`--input` is optional with `--do-not-rescan`. When supplied, it filters the
catalog records to paths below that input directory without scanning it.
Because the catalog is trusted as-is, newly added, changed, or removed source
files are not detected. Run `--learn` or a normal organization command first
when the catalog needs refreshing. A dry run still keeps the SQLite database
byte-for-byte unchanged.

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
On later scans, unchanged files reuse their stored SHA-1 and metadata when
their size, modification time, and metadata-change time still match.

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

### Filter by media type

Use `--only-video` to copy or move only supported videos, or `--only-photo`
to process only supported pictures. The options are mutually exclusive and
can be combined with `--move`, `--dry-run`, `--dateunk`, and
`--do-not-rescan`.

Copy videos only:

```bash
python defoutoir.py --input ./media --output ./sorted --only-video
```

Move photos only without rescanning the input tree:

```bash
python defoutoir.py \
  --database ./defoutoir.sqlite3 \
  --output ./sorted \
  --move \
  --only-photo \
  --do-not-rescan
```

The non-selected media remain untouched. A normal scan still catalogs both
categories; the filter is applied only to the copy or move plan.

Move removes every selected source in a duplicate group only after their one
shared destination has been written and verified successfully. Copy keeps all
sources but publishes only the canonical representative. Existing destination
files are never overwritten; identical content is skipped and different
content receives a deterministic alternate name.
Destination filenames are normalized to Unicode NFC for compatibility with
network shares and filesystems. Visually identical decomposed and composed
names therefore collide safely: identical content is skipped, while different
content receives the usual deterministic SHA-1 suffix.

### Stop and resume

Every real copy or move is journaled in the SQLite database before files are
changed. The journal records `pending`, `copied`, `completed`, and `error`
checkpoints. If the process is stopped with Ctrl-C or interrupted by a machine
restart, launch the same command again with the same `--database`, `--output`,
and copy/move mode. Completed transfers are skipped. A move interrupted after
publishing its destination verifies the destination SHA-1 before removing each
remaining source. Every source deletion has its own checkpoint, so cleanup
continues safely after a restart.

For a large tree, resume directly from the database without traversing the
input again:

```bash
python defoutoir.py \
  --database ./defoutoir.sqlite3 \
  --output ./sorted-media \
  --move \
  --do-not-rescan
```

`--dry-run` never creates or updates journal entries.

### Add missing EXIF dates

Use `--dateunk` with the normal copy operation or with `--move` to write a
date detected from the filename or source path into the destination image's
EXIF `DateTimeOriginal` tag. A valid existing metadata date is never replaced.
JPEG and PNG files are updated without re-encoding their pixels. Other media
formats are organized normally and produce a warning when their date cannot be
written as EXIF.
When only a calendar date is known, DeFoutoir uses `12:00:00` for the missing
time. For example, `photo_2024-05-06.jpg` receives EXIF `DateTimeOriginal`
`2024:05:06 12:00:00`. An explicit time, including midnight, is preserved.

Copy and enrich the destination while keeping the source unchanged:

```bash
python defoutoir.py --input ./media --output ./sorted --dateunk
```

Move and enrich the destination:

```bash
python defoutoir.py --input ./media --output ./sorted --move --dateunk
```

Preview both the organization and EXIF updates without changing any file:

```bash
python defoutoir.py --input ./media --output ./sorted --dateunk --dry-run
```

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

Fujifilm `.RAF` files, including uppercase names such as `_DSF0044.RAF`, are
treated as photos. DeFoutoir reads the capture EXIF date from the JPEG preview
embedded in the RAF container without modifying the RAW file.

Symbolic links found inside an input tree are skipped. An input path that is
itself a symbolic link is resolved once before scanning. Unreadable or invalid
paths produce warnings without stopping the remaining inputs. macOS metadata
directories such as `.AppleDouble` and `__MACOSX` are ignored.

## SQLite catalog

The catalog is stored in `defoutoir.sqlite3` by default. The database path is
configurable with `--database` or through the Python catalog API. Dry-run uses
an in-memory catalog and never creates or changes the configured database.

The catalog uses schema version 3 and stores the normalized source path,
incremental SHA-1 identity, file size, modification timestamps, resolved media
date, date source, and processing state. A SHA-1 index makes duplicate-content
groups queryable without changing or deleting the original files.
The `operation_journal` table stores durable copy/move checkpoints and is
created automatically when an older catalog is opened. Output roots and their
content hashes are indexed separately, so the same source can be copied once
to each of several outputs while repeated runs never duplicate it within one
output. Unchanged output files reuse cached hashes after cheap filesystem
timestamp checks.

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
least one other file. Entries are sorted by SHA-1, so each duplicate group is
contiguous.

All list modes accept `--only-video` or `--only-photo`. The media filter is
combined with the selected list condition and remains read-only:

```bash
python defoutoir.py --list --only-video --database ./defoutoir.sqlite3
python defoutoir.py --list-errors --only-photo --database ./defoutoir.sqlite3
python defoutoir.py --list-no-date --only-video --database ./defoutoir.sqlite3
python defoutoir.py --list-duplicates --only-photo --database ./defoutoir.sqlite3
```

## Metadata date precedence

The metadata extractor reads dates without modifying the source file. When
several timestamps are available, it uses this order:

1. EXIF `DateTimeOriginal`;
2. EXIF `DateTimeDigitized`;
3. XMP `photoshop:DateCreated` or `xmp:CreateDate`;
4. generic EXIF `DateTime`;
5. container creation date from RAW or video metadata.

Dates are normalized to UTC when a timezone is present. A date-only metadata
value uses `12:00:00`. Invalid or missing metadata produces a warning or a
clean no-date result.

## Filename date fallback

When no usable metadata date exists, DeFoutoir can read an explicit date from
the filename. The supported patterns are `YYYYMMDD`, `YYYY-MM-DD`,
`YYYY_MM_DD`, and `YYYY.MM.DD`. An optional capture time is also read when it
follows the date as `HHMMSS` (for example `IMG_20240102_123456.JPG`) or as
`at HH.MM.SS` (for example a WhatsApp export). Invalid dates, ambiguous short
formats, and filenames containing multiple different dates are ignored.
Metadata normally takes precedence over a filename date.
When the filename or source path supplies only a date, the catalog records
`12:00:00`; a filename with an explicit time keeps that time.

WhatsApp video names in the form `VID-YYYYMMDD-WA####`, such as
`VID-20180728-WA0008.mp4`, are treated as authoritative because copied or
exported MP4 containers often contain a later processing date. This example is
therefore organized under `2018/07/28` with a time of `12:00:00`.
Signal export names are also authoritative. Both compact timestamps such as
`signal-2021-09-05-094323_002.jpeg` and hyphenated timestamps such as
`signal-2021-09-10-06-51-57-523.mp4` are supported; the latter resolves to
`2021-09-10 06:51:57`.
Names in the form `video_YYMMDD#####`, such as `video_23012929523`, are also
treated as authoritative. The first six digits encode the date, so this
example resolves to `2023-01-29 12:00:00`; the last five digits are an
identifier, not a time.

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
