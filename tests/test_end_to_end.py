"""End-to-end workflows using only temporary input, output, and database paths."""

# pylint: disable=missing-function-docstring,too-many-locals

from pathlib import Path

from defoutoir.cli import main


def test_complete_copy_learn_dry_run_and_move_workflows(tmp_path: Path, capsys) -> None:
    first_input = tmp_path / "phone"
    second_input = tmp_path / "camera"
    output = tmp_path / "sorted"
    database = tmp_path / "catalog.sqlite3"
    (first_input / "nested").mkdir(parents=True)
    second_input.mkdir()

    dated_picture = first_input / "nested" / "holiday_2024-01-02.jpg"
    dated_movie = first_input / "nested" / "clip_20240203.mp4"
    first_collision = first_input / "same.jpg"
    second_collision = second_input / "same.jpg"
    duplicate = second_input / "duplicate.jpg"
    unknown = second_input / "unknown.jpg"
    dated_picture.write_bytes(b"picture")
    dated_movie.write_bytes(b"movie")
    first_collision.write_bytes(b"first collision")
    second_collision.write_bytes(b"second collision")
    duplicate.write_bytes(b"picture")
    unknown.write_bytes(b"unknown")

    command = [
        "--input",
        str(first_input),
        "--input",
        str(second_input),
        "--output",
        str(output),
        "--database",
        str(database),
    ]
    assert main(command) == 0
    assert dated_picture.exists()
    assert (output / "2024/01/02/holiday_2024-01-02.jpg").read_bytes() == b"picture"
    assert (output / "2024/02/03/clip_20240203.mp4").read_bytes() == b"movie"
    collision_files = [output / "unknown/same.jpg"] + list(
        (output / "unknown").glob("same__*.jpg")
    )
    assert len(collision_files) == 2
    assert {path.read_bytes() for path in collision_files} == {
        b"first collision",
        b"second collision",
    }
    assert (output / "unknown/unknown.jpg").read_bytes() == b"unknown"

    output_snapshot = {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert main(command + ["--dry-run", "--move"]) == 0
    assert output_snapshot == {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert dated_picture.exists()
    assert "DRY-RUN" in capsys.readouterr().err

    assert (
        main(
            [
                "--input",
                str(first_input),
                "--input",
                str(second_input),
                "--learn",
                "--database",
                str(database),
            ]
        )
        == 0
    )
    assert "duplicate" in capsys.readouterr().err

    move_input = tmp_path / "move-input"
    move_output = tmp_path / "move-output"
    move_input.mkdir()
    move_source = move_input / "move_2024-04-05.jpg"
    move_source.write_bytes(b"move")
    assert (
        main(
            [
                "--input",
                str(move_input),
                "--output",
                str(move_output),
                "--move",
                "--database",
                str(tmp_path / "move.sqlite3"),
            ]
        )
        == 0
    )
    assert not move_source.exists()
    assert (move_output / "2024/04/05/move_2024-04-05.jpg").read_bytes() == b"move"
