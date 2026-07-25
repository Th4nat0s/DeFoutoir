# DeFoutoir

DeFoutoir is a simple Python tool for cleaning and sorting pictures and movies.

It accepts an unstructured input folder, including subfolders, and organizes the media files by date.

> DeFoutoir is under active development. The package and quality foundation is
> available, while the media organization workflow is being implemented.

## How it works

DeFoutoir:

1. Scans the input folder and its subfolders.
2. Creates a clean SQLite database with file information, including the SHA-1 hash and date.
3. Reads the timestamp from the media metadata when it is available.
4. Uses the filename to find the date when media metadata is not available.
5. Copies the files into folders organized by date by default.

The original files are kept unless the move option is explicitly selected.

## Multiple input folders

DeFoutoir can scan several input folders in one operation.
Repeat the `--input` option for each folder:

```bash
python -m defoutoir \
  --input ./phone-media \
  --input ./camera-media \
  --input ./old-media \
  --output ./sorted-media
```

All input folders are scanned and organized in the same output folder.

## Dry run

The `dry run` option previews the planned changes without moving, copying, or modifying media files.
It is useful for checking the result before applying it.

Example:

```bash
python -m defoutoir --input ./unstructured-media --output ./sorted-media --dry-run
```

When the result is correct, run the command without `--dry-run` to apply the operation.

## Learn mode

The `--learn` option scans the input folder and learns the media information without copying or moving any files.
It creates or updates the SQLite database with file hashes and dates.
This mode is useful for preparing the database before a later organization operation.

Example:

```bash
python -m defoutoir --input ./unstructured-media --learn
```

Learn mode only reads the media files and updates the database. It does not change the input or output folders.

## File operations

DeFoutoir can:

- copy files to the date-based folders by default, while keeping the originals; or
- move files to the date-based folders with the `--move` option.

## Development setup

DeFoutoir requires Python 3.10 or newer.

Create a virtual environment and install the project with its development
tools:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The package provides both module and console entry points:

```bash
python -m defoutoir --help
defoutoir --help
```

## Quality checks

Every code change must pass the tests, Black, and Pylint:

```bash
python -m pytest
python -m black --check src tests
python -m pylint src tests
```

GitHub Actions runs the same checks with Python 3.10.
