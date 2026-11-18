"""`ass render` 와 같다. 패키지를 설치하지 않았을 때 쓴다.

    python scripts/first_render.py --dry-run
    python scripts/first_render.py --scene 1
"""
import sys

import _common  # noqa: F401
from ass.cli import main

raise SystemExit(main(["render", *sys.argv[1:]]))
