import datetime
import os

import pytest

from trash30 import Can, TrashError, main


def make(tmp_path, **kw):
    return Can(tmp_path / "can", **kw)


def test_put_list_restore_round_trip(tmp_path):
    f = tmp_path / "work" / "a.txt"
    f.parent.mkdir()
    f.write_text("hello")
    can = make(tmp_path)
    dest = can.put(f, "old draft")
    assert not f.exists() and dest.read_text() == "hello"
    rows = can.listing()
    assert len(rows) == 1 and rows[0][3] == str(f) and rows[0][4] == "old draft"
    can.restore(f)
    assert f.read_text() == "hello" and can.listing() == []


def test_restore_refuses_when_target_exists(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("1")
    can = make(tmp_path)
    can.put(f)
    f.write_text("2")
    with pytest.raises(TrashError):
        can.restore(f)
    assert f.read_text() == "2"


def test_put_refuses_never_paths_and_holders(tmp_path):
    keep = tmp_path / "proj" / "keys"
    keep.mkdir(parents=True)
    (keep / "k").write_text("x")
    can = make(tmp_path, never=[str(keep), "*.bundle"])
    with pytest.raises(TrashError):
        can.put(keep / "k")  # under a never folder
    with pytest.raises(TrashError):
        can.put(tmp_path / "proj")  # holds a never folder
    b = tmp_path / "x.bundle"
    b.write_text("b")
    with pytest.raises(TrashError):
        can.put(b)  # glob on the base name
    assert (keep / "k").exists() and b.exists()


def test_purge_removes_by_folder_name_not_mtime(tmp_path):
    can = make(tmp_path, days=30, today=datetime.date(2026, 6, 1))
    old, new = can.root / "2026-04-01", can.root / "2026-05-25"
    for d in (old, new):
        (d / "f").mkdir(parents=True)
        (d / "f" / "x").write_text("x")
    os.utime(new, (0, 0))  # ancient mtime must not matter
    os.utime(old, None)  # fresh mtime must not matter
    (can.root / "stray").mkdir()
    out = can.purge()
    assert [a for a, _, _ in out if a == "purged"] == ["purged"]
    assert not old.exists() and new.exists() and (can.root / "stray").exists()


def test_purge_never_follows_links_out_of_the_trash(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_text("keep me")
    can = make(tmp_path, days=30, today=datetime.date(2026, 6, 1))
    old = can.root / "2026-04-01"
    old.mkdir(parents=True)
    os.symlink(outside, old / "link-to-outside")  # a link inside an old date folder
    os.symlink(outside, can.root / "2026-03-01")  # a date-named link itself
    can.purge()
    assert (outside / "precious").read_text() == "keep me"
    assert not old.exists() and not os.path.lexists(can.root / "2026-03-01")


def test_purge_opens_read_only_folders(tmp_path):
    can = make(tmp_path, days=30, today=datetime.date(2026, 6, 1))
    d = can.root / "2026-04-01" / "ro"
    d.mkdir(parents=True)
    (d / "f").write_text("x")
    os.chmod(d, 0o500)
    can.purge()
    assert not (can.root / "2026-04-01").exists()


def test_purge_refuses_a_symlinked_root(tmp_path):
    real = tmp_path / "real"
    (real / "2020-01-01").mkdir(parents=True)
    os.symlink(real, tmp_path / "can")
    with pytest.raises(TrashError):
        Can(tmp_path / "can", today=datetime.date(2026, 6, 1)).purge()
    assert (real / "2020-01-01").exists()


def test_dry_run_changes_nothing_and_cli_works(tmp_path, capsys):
    f = tmp_path / "a.txt"
    f.write_text("1")
    root = str(tmp_path / "can")
    assert main(["--root", root, "put", str(f), "because", "reasons"]) == 0
    assert main(["--root", root, "--days", "0", "purge", "--dry-run"]) == 0
    assert (tmp_path / "can" / datetime.date.today().isoformat()).exists()
    assert main(["--root", root, "list"]) == 0
    assert "because reasons" in capsys.readouterr().out
    assert main(["--root", root, "restore", str(tmp_path / "nope")]) == 2
