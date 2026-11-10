"""Windows kurulum dosyası: kullanıcı onu depodan ham hâliyle indirir, bu yüzden baytları önemlidir."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAT = ROOT / "kurulum" / "Usta-Kur.bat"


def test_installer_keeps_windows_line_endings_in_the_repo():
    # LF ile biten .bat, UTF-8 Türkçe karakterlerle birlikte cmd'de satır ortasından bölünür.
    data = BAT.read_bytes()
    assert b"\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert "*.bat -text" in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()


def test_installer_is_utf8_without_bom_and_sets_the_code_page():
    data = BAT.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")  # BOM ilk satırı ("@echo off") bozar
    text = data.decode("utf-8")
    assert text.splitlines()[1] == "chcp 65001 >nul"  # Türkçe yazılardan ÖNCE
    assert "-m pip install --upgrade" in text and "-m usta --kisayol" in text
