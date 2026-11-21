"""환경 점검 (2.3절). `ass doctor` 가 첫 호출 전에 빠진 것을 찾아 준다.

점검 결과에는 API 키의 값을 넣지 않는다. 설정 여부만 적는다.
"""
from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
from datetime import datetime
from importlib import metadata
from typing import Literal

from pydantic import BaseModel

from ass.settings import ROOT, load_config

Status = Literal["ok", "warn", "fail"]
MARK = {"ok": "[확인]", "warn": "[주의]", "fail": "[실패]"}


class Check(BaseModel):
    name: str
    status: Status
    detail: str
    fix: str = ""


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def run_checks(env: dict[str, str] | None = None) -> list[Check]:
    env = dict(os.environ) if env is None else env
    checks: list[Check] = []

    py = platform.python_version()
    ok = sys.version_info >= (3, 11)
    checks.append(Check(name="Python", status="ok" if ok else "fail", detail=py,
                        fix="" if ok else "Python 3.11 이상이 필요하다. conda create -n ass python=3.13"))

    conda = env.get("CONDA_DEFAULT_ENV", "")
    checks.append(Check(
        name="Anaconda 환경", status="ok" if conda == "ass" else "warn",
        detail=conda or "conda 환경이 아니다",
        fix="" if conda == "ass" else "conda activate ass 를 먼저 실행한다"))

    for package, module in (("pydantic", "pydantic"), ("pyyaml", "yaml"), ("google-genai", "google.genai")):
        version = _version(package)
        try:
            importlib.import_module(module)
            checks.append(Check(name=package, status="ok", detail=version or "설치됨"))
        except ImportError:
            checks.append(Check(name=package, status="fail", detail="없음",
                                fix='저장소 폴더에서 pip install -e ".[dev]"'))

    try:
        importlib.import_module("tkinter")
        checks.append(Check(name="tkinter (콘솔)", status="ok", detail="있음"))
    except ImportError:
        checks.append(Check(name="tkinter (콘솔)", status="warn", detail="없음",
                            fix="콘솔만 못 쓴다. 명령은 그대로 쓸 수 있다"))

    key = env.get("GEMINI_API_KEY", "").strip()
    env_file = (ROOT / ".env").is_file()
    checks.append(Check(
        name="GEMINI_API_KEY", status="ok" if key else "fail",
        detail="설정됨" if key else ("없음 (.env 파일은 있음)" if env_file else "없음"),
        fix="" if key else ".env.example 을 .env 로 복사하고 AI Studio 에서 받은 키를 넣는다"))

    ffmpeg = shutil.which("ffmpeg")
    checks.append(Check(name="FFmpeg", status="ok" if ffmpeg else "warn", detail=ffmpeg or "없음",
                        fix="" if ffmpeg else "4장의 조립부터 필요하다. winget install -e --id Gyan.FFmpeg 로 설치하고 창을 새로 연다"))

    try:
        models = load_config("models")
        checks.append(Check(name="configs/models.yaml", status="ok",
                            detail=f"영상 모델 {models['video']['id']}, 확인일 {models['verified_on']}"))
    except Exception as exc:
        checks.append(Check(name="configs/models.yaml", status="fail", detail=str(exc),
                            fix="저장소를 다시 받거나 파일을 되돌린다"))
    return checks


def render_text(checks: list[Check]) -> str:
    lines = ["ASS 환경 점검", ""]
    for c in checks:
        lines.append(f"{MARK[c.status]} {c.name}: {c.detail}")
        if c.fix:
            lines.append(f"        → {c.fix}")
    fails = sum(c.status == "fail" for c in checks)
    warns = sum(c.status == "warn" for c in checks)
    lines.append("")
    lines.append("첫 호출을 할 수 있다." if not fails else f"실패 {fails}건을 먼저 고친다.")
    if warns:
        lines.append(f"주의 {warns}건은 지금 당장 막히지는 않는다.")
    return "\n".join(lines)


def render_markdown(checks: list[Check]) -> str:
    out = ["# ASS 환경 점검 기록 (setup.md)", "",
           f"`ass doctor --write` 가 {datetime.now().strftime('%Y-%m-%d %H:%M')} 에 만든 파일이다. "
           "API 키의 값은 적지 않는다.", "",
           "| 항목 | 상태 | 내용 | 조치 |", "|---|---|---|---|"]
    for c in checks:
        out.append(f"| {c.name} | {MARK[c.status].strip('[]')} | {c.detail} | {c.fix or '—'} |")
    return "\n".join(out) + "\n"
