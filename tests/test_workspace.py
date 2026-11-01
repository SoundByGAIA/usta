from usta.workspace import diff, revert, snapshot


def test_no_changes_empty_diff(tmp_path):
    (tmp_path / "a.txt").write_text("x\n")
    assert diff(snapshot(tmp_path), tmp_path) == ""


def test_modified_added_deleted(tmp_path):
    (tmp_path / "a.txt").write_text("bir\niki\n")
    (tmp_path / "sil.txt").write_text("gidecek\n")
    snap = snapshot(tmp_path)
    (tmp_path / "a.txt").write_text("bir\n2\n")
    (tmp_path / "sil.txt").unlink()
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "yeni.py").write_text("print(1)\n")
    out = diff(snap, tmp_path)
    assert "--- a/a.txt\n+++ b/a.txt" in out and "-iki\n+2" in out
    assert "--- a/sil.txt\n+++ /dev/null" in out and "-gidecek" in out
    assert "--- /dev/null\n+++ b/d/yeni.py" in out and "+print(1)" in out


def test_binary_and_ignored(tmp_path):
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    snap = snapshot(tmp_path)
    (tmp_path / "b.bin").write_bytes(b"\x00\x02")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x").write_text("yok sayılır")
    out = diff(snap, tmp_path)
    assert "Binary files a/b.bin and b/b.bin differ" in out and ".git" not in out


def test_revert_restores_everything(tmp_path):
    (tmp_path / "a.txt").write_text("orijinal")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    snap = snapshot(tmp_path)
    (tmp_path / "a.txt").write_text("bozuk")
    (tmp_path / "b.bin").unlink()
    (tmp_path / "yeni.txt").write_text("z")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "i.txt").write_text("z")
    revert(snap, tmp_path)
    assert (tmp_path / "a.txt").read_text() == "orijinal"
    assert (tmp_path / "b.bin").read_bytes() == b"\x00\x01"
    assert not (tmp_path / "yeni.txt").exists() and not (tmp_path / "d").exists()
    assert diff(snap, tmp_path) == ""


def test_large_files_are_skipped_not_loaded(tmp_path):
    (tmp_path / "big").write_bytes(b"x" * 100)
    snap = snapshot(tmp_path, max_file=10)
    (tmp_path / "big").write_bytes(b"y" * 100)
    assert diff(snap, tmp_path) == ""  # kapsam dışı; snapshot.skipped'ta listelenir
    assert snap.skipped == ["big"]


def test_symlinks_are_not_followed(tmp_path):
    outside = tmp_path / "dis.txt"
    outside.write_text("gizli")
    root = tmp_path / "ws"
    root.mkdir()
    (root / "l").symlink_to(outside)
    snap = snapshot(root)
    outside.write_text("değişti")
    assert diff(snap, root) == "" and "l" not in snap.files


def test_revert_removes_nested_new_dirs_but_keeps_preexisting_empty_dirs(tmp_path):
    (tmp_path / "bos").mkdir()
    snap = snapshot(tmp_path)
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.txt").write_text("z")
    revert(snap, tmp_path)
    assert (tmp_path / "bos").is_dir() and not (tmp_path / "a").exists()


def test_revert_never_touches_ignored_dirs(tmp_path):
    (tmp_path / "x.txt").write_text("1")
    snap = snapshot(tmp_path)
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    (tmp_path / "x.txt").write_text("2")
    revert(snap, tmp_path)
    assert (tmp_path / ".git" / "refs" / "heads").is_dir()


def test_snapshot_caps_skip_extra_files_and_revert_never_deletes_them(tmp_path):
    from usta.workspace import diff, revert, snapshot

    for i in range(6):
        (tmp_path / f"f{i}.txt").write_text("x" * 10)
    snap = snapshot(tmp_path, max_total=35, max_files=100)
    assert snap.truncated and len(snap.files) == 3 and len(snap.skipped) == 3
    (tmp_path / "f0.txt").write_text("degisti")  # izlenen dosya
    (tmp_path / "yeni.txt").write_text("y")
    skipped_file = tmp_path / snap.skipped[0]
    skipped_file.write_text("degisti-ama-izlenmiyor")
    assert skipped_file.name not in diff(snap, tmp_path)
    revert(snap, tmp_path)
    assert skipped_file.read_text() == "degisti-ama-izlenmiyor"  # silinmedi, dokunulmadı
    assert not (tmp_path / "yeni.txt").exists()
    assert (tmp_path / "f0.txt").read_text() == "x" * 10


def test_snapshot_file_count_cap(tmp_path):
    from usta.workspace import snapshot

    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("a")
    snap = snapshot(tmp_path, max_files=2)
    assert snap.truncated and len(snap.files) == 2


def _setup_snapshot(tmp_path):
    from usta.workspace import snapshot

    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.txt").write_text("orijinal")
    (root / "top.txt").write_text("üst")
    outside = tmp_path / "dis"
    outside.mkdir()
    (outside / "a.txt").write_text("DISARIDAKI-ONEMLI")
    return root, outside, snapshot(root)


def test_revert_never_writes_through_a_symlinked_parent_dir(tmp_path):
    import shutil

    from usta.workspace import revert

    root, outside, snap = _setup_snapshot(tmp_path)
    shutil.rmtree(root / "sub")
    (root / "sub").symlink_to(outside)  # ajan klasörü dışarıya işaret eden bağla değiştirdi
    revert(snap, root)
    assert (outside / "a.txt").read_text() == "DISARIDAKI-ONEMLI"  # hedef dokunulmadı
    assert not (root / "sub").is_symlink()
    assert (root / "sub" / "a.txt").read_text() == "orijinal"  # gerçek klasör geri geldi


def test_revert_never_writes_through_a_symlinked_leaf(tmp_path):
    from usta.workspace import revert

    root, outside, snap = _setup_snapshot(tmp_path)
    (root / "top.txt").unlink()
    (root / "top.txt").symlink_to(outside / "a.txt")
    revert(snap, root)
    assert (outside / "a.txt").read_text() == "DISARIDAKI-ONEMLI"
    assert not (root / "top.txt").is_symlink() and (root / "top.txt").read_text() == "üst"


def test_revert_replaces_directory_that_took_a_files_place(tmp_path):
    from usta.workspace import revert

    root, _, snap = _setup_snapshot(tmp_path)
    (root / "top.txt").unlink()
    (root / "top.txt").mkdir()
    (root / "top.txt" / "x").write_text("y")
    revert(snap, root)
    assert (root / "top.txt").is_file() and (root / "top.txt").read_text() == "üst"
