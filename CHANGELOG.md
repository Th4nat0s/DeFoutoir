# Changelog

## Unreleased

- Use noon (`12:00:00`) for dates without a known time in filenames, paths,
  and date-only metadata; preserve explicit times.
- Add `--dateunk` to write filename/path fallback dates to missing destination
  EXIF metadata during copy or move operations, including dry-run previews.
- Read XMP metadata in bounded chunks to avoid loading complete RAW and video
  files into memory.
- Reuse persisted metadata for unchanged files so interrupted runs can resume
  without repeating completed metadata extraction.

## 0.1.2 - 2026-07-25

- Added read-only `--list` output with timestamp, date source, name, SHA-1,
  and pathname.
- Added path date fallback for album paths such as `2002/0208 Wicher`.

## 0.1.1 - 2026-07-25

- Added the standalone `defoutoir.py` launcher.
- Added a simple runtime `requirements.txt` installation path.

## 0.1.0 - 2026-07-25

- Added recursive media discovery for pictures and movies.
- Added metadata and filename date resolution.
- Added SQLite cataloging with SHA-1 identity and learn mode.
- Added deterministic date-based plans with safe copy and move execution.
- Added non-mutating dry-run support and the complete command-line interface.
