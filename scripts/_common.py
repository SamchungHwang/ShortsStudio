"""스크립트 공통: 저장소 루트를 import 경로에 넣고 .env 를 읽는다."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # python-dotenv 없이도 환경 변수로 실행할 수 있다
    pass

if hasattr(sys.stdout, "reconfigure"):  # Windows 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")


def run_budget_usd(budget_policy: dict) -> float:
    override = os.environ.get("ACS_RUN_BUDGET_USD", "").strip()
    return float(override) if override else float(budget_policy["run_budget_usd"])
