"""Paketli Windows uygulamasının girişi: Usta pencere açmadan arka planda başlar, tarayıcıyı açar."""

import sys

from usta.cli import main

raise SystemExit(main(["--arka-plan", *sys.argv[1:]]))
