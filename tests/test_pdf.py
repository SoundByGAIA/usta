import json
import subprocess
import sys
from pathlib import Path

import pytest

from pdfutil import make_pdf

INNER = Path(__file__).parent.parent / "src" / "usta" / "pdf_inner.py"


def run_inner(tmp_path, pdf: bytes, pages=30, chars=10_000):
    (tmp_path / "in.pdf").write_bytes(pdf)
    r = subprocess.run(
        [sys.executable, "-I", str(INNER), str(tmp_path / "in.pdf"), str(pages), str(chars)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_extracts_text_per_page(tmp_path):
    d = run_inner(tmp_path, make_pdf(["Birinci sayfa", "Ikinci sayfa"]))
    assert d["error"] is None and d["total_pages"] == 2 and d["read_pages"] == 2
    assert [p.strip() for p in d["pages"]] == ["Birinci sayfa", "Ikinci sayfa"]


def test_page_limit(tmp_path):
    d = run_inner(tmp_path, make_pdf([f"s{i}" for i in range(10)]), pages=3)
    assert d["total_pages"] == 10 and d["read_pages"] == 3 and len(d["pages"]) == 3


def test_char_limit_truncates(tmp_path):
    d = run_inner(tmp_path, make_pdf(["a" * 500, "b" * 500]), chars=300)
    assert sum(len(p) for p in d["pages"]) <= 300 and d["truncated"] is True


@pytest.mark.parametrize(
    "junk", [b"", b"merhaba", b"%PDF-1.4\n\x00\x01 bozuk", make_pdf(["x"])[:60]]
)
def test_garbage_or_truncated_is_error_not_crash(tmp_path, junk):
    d = run_inner(tmp_path, junk)
    assert d["error"] and d["pages"] == []


def test_encrypted_pdf_is_rejected(tmp_path):
    from pypdf import PdfReader, PdfWriter

    (tmp_path / "plain.pdf").write_bytes(make_pdf(["gizli"]))
    w = PdfWriter(clone_from=PdfReader(tmp_path / "plain.pdf"))
    w.encrypt("sifre", algorithm="RC4-128")
    with (tmp_path / "enc.pdf").open("wb") as f:
        w.write(f)
    d = run_inner(tmp_path, (tmp_path / "enc.pdf").read_bytes())
    assert d["error"] and "şifre" in d["error"].lower() and d["pages"] == []


def test_blank_pdf_reports_no_text(tmp_path):
    d = run_inner(tmp_path, make_pdf([""]))
    assert d["error"] is None and d["empty"] is True
