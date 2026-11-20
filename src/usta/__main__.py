"""`python -m usta` ile başlatma (Windows'ta `usta` komutu PATH'te değilse işe yarar)."""

try:
    from usta.cli import main
except ImportError as e:
    from usta import winblock

    if (message := winblock.explain(e)) is None:
        raise
    winblock.show(message)
    raise SystemExit(1) from None

raise SystemExit(main())
