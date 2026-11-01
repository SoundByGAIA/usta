import os
from pathlib import Path

import pytest

from usta import projects


def test_slug_is_safe_and_matches_workspace_id_rules():
    import re

    for name in ("Benim Proje!", "çay", "..", "", "a" * 100, "-x", "UPPER_case"):
        s = projects.slug(name)
        assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,29}", s), (name, s)


def test_register_creates_symlink_to_the_project(tmp_path):
    home, proj = tmp_path / "home", tmp_path / "Benim Proje"
    proj.mkdir()
    wid = projects.register(home, proj)
    link = home / "workspaces" / wid
    assert link.is_symlink() and link.resolve() == proj.resolve()
    assert (link / ".").is_dir()


def test_register_is_stable_for_same_path_and_distinct_for_same_name(tmp_path):
    home = tmp_path / "home"
    a, b = tmp_path / "x" / "app", tmp_path / "y" / "app"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert projects.register(home, a) == projects.register(home, a)
    assert projects.register(home, a) != projects.register(home, b)


def test_register_does_not_overwrite_a_real_directory(tmp_path):
    home, proj = tmp_path / "home", tmp_path / "app"
    proj.mkdir()
    first = projects.register(home, proj)
    link = home / "workspaces" / first
    link.unlink()
    link.mkdir()  # aynı adlı gerçek dizin (ör. portaldan oluşturulmuş çalışma alanı)
    (link / "dosya.txt").write_text("silinmemeli")
    second = projects.register(home, proj)
    assert second != first and (link / "dosya.txt").read_text() == "silinmemeli"


def test_register_inside_workspaces_dir_returns_its_own_id(tmp_path):
    home = tmp_path / "home"
    inner = home / "workspaces" / "benim"
    inner.mkdir(parents=True)
    assert projects.register(home, inner) == "benim"
    assert not inner.is_symlink()


def test_register_refuses_non_directory(tmp_path):
    f = tmp_path / "dosya"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        projects.register(tmp_path / "home", f)


def test_register_repairs_stale_symlink(tmp_path):
    home, proj = tmp_path / "home", tmp_path / "app"
    proj.mkdir()
    wid = projects.register(home, proj)
    link = home / "workspaces" / wid
    link.unlink()
    os.symlink(tmp_path / "yok", link)  # kırık bağ
    assert projects.register(home, proj) == wid and link.resolve() == proj.resolve()


def test_check_root_refuses_home_root_and_ancestors_of_usta_home(tmp_path, monkeypatch):
    import pytest

    from usta import projects

    home = tmp_path / "kullanici" / ".usta"
    home.mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path / "kullanici"))
    for bad in (tmp_path / "kullanici", home, tmp_path, Path("/")):
        with pytest.raises(ValueError):
            projects.check_root(home, bad)
    proj = tmp_path / "kullanici" / "Desktop" / "proje"
    proj.mkdir(parents=True)
    projects.check_root(home, proj)  # normal proje klasörü serbest
    projects.check_root(home, tmp_path / "kullanici" / "Desktop")  # masaüstü serbest
