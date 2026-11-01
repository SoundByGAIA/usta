import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"sk-[A-Za-z0-9]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"AKIA[0-9A-Z]{16}",
    r"xox[abp]-[A-Za-z0-9-]{10,}",
]


def test_tracked_files_have_no_secret_patterns():
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    hits = []
    for f in files:
        if f == "tests/test_no_secrets.py":
            continue
        text = (ROOT / f).read_text(errors="ignore")
        hits += [f for p in PATTERNS if re.search(p, text)]
    assert not hits, f"olası sır: {hits}"
