"""`ass compile` 과 같다. 패키지를 설치하지 않았을 때 쓴다.

    python scripts/compile_scenes.py [--episode product_intro]
"""
import sys

import _common  # noqa: F401
from ass.cli import main

raise SystemExit(main(["compile", *sys.argv[1:]]))
