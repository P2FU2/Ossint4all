"""Encaminha o CLI antigo do Script_Jus para o OSINT4ALL (PORT do Railway)."""

from __future__ import annotations

import sys


def app_entry() -> None:
    argv = sys.argv[1:]
    from osint4all.main import main

    if not argv or argv[0] in {"serve", "web"}:
        main(["serve", "--host", "0.0.0.0"])
        return
    main(argv)


if __name__ == "__main__":
    app_entry()
