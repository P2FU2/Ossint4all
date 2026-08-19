"""Encaminha o CLI antigo do Script_Jus para o OSINT4ALL (mesmo PORT do Railway)."""

from __future__ import annotations

import os
import sys


def app_entry() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in {"serve", "web"}:
        from osint4all.main import main

        extra = argv[1:] if argv else []
        main(["serve", "--host", "0.0.0.0", "--port", os.environ.get("PORT") or "8000", *extra])
        return
    from osint4all.main import main

    main(argv)


if __name__ == "__main__":
    app_entry()
