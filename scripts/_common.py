"""설치하지 않고 저장소에서 바로 실행할 때 쓰는 경로 설정. 명령의 본체는 ass/cli.py 에 있다."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
