# Changelog

## Unreleased

- Read capture EXIF dates from embedded JPEG previews in Fujifilm RAF files,
  including uppercase `.RAF` names.
- Add mutually exclusive `--only-video` and `--only-photo` filters for copy
  and move operations, including dry-run, catalog-only, and all list workflows.
- Prefer the explicit date in WhatsApp `VID-YYYYMMDD-WA####` video names over
  unreliable MP4 container processing dates.
- Recognize Signal export timestamps with compact or hyphenated times and
  prefer them over embedded processing dates.
- Recognize authoritative `video_YYMMDD#####` names as a short date followed
  by an identifier.
- Add a durable SQLite copy/move journal with safe restart and resume support,
  including recovery of moves interrupted between destination publication and
  source deletion.
- Add `--do-not-rescan` to plan directly from an existing catalog, with an
  optional `--input` path filter and read-only dry-run behavior.
- Reuse cached SHA-1 and metadata for files whose size and filesystem times
  have not changed.
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
