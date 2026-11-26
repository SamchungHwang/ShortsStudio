"""consistency — 생성한 장면을 레퍼런스와 견주는 재료를 만든다 (7.4절).

프로그램은 판정하지 않는다. 정지 화면을 뽑아 레퍼런스 옆에 붙이고, 사람이 적을 점검표를 만든다.
    mode_experiment.csv     장면·모드별 실행 (시간, 추정 비용, 보낸 이미지 수) + 사람이 적을 칸
    consistency_report.md   점검표 (형태, 색, 라벨)
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class RenderRow(BaseModel):
    scene_id: str
    mode: str
    run_id: str
    video: str
    images: int = 0
    duration_s: float = 15.0
    elapsed_s: float | None = None
    estimated_cost_usd: float | None = None
    attempts: int = 0
    reused: bool = False
    stills: list[str] = []
    sheet: str | None = None


def collect(render_dir: Path, latest_only: bool = True) -> list[RenderRow]:
    """성공한 장면 생성을 모은다. 기본은 장면과 모드마다 가장 최근 것 하나."""
    rows: dict[tuple[str, str], RenderRow] | list[RenderRow] = {} if latest_only else []
    for path in sorted(render_dir.glob("*.api_run.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        video = path.with_name(path.name.replace(".api_run.json", ".mp4"))
        if record.get("status") not in ("ok", "reused") or not video.is_file() or not record.get("scene_id"):
            continue
        duration = str((record.get("request") or {}).get("response_format", {}).get("duration", "15s")).rstrip("s")
        row = RenderRow(scene_id=record["scene_id"], mode=record.get("mode") or "text", run_id=str(record.get("run_id")),
                        video=str(video), images=len(record.get("inputs") or []), duration_s=float(duration or 15),
                        elapsed_s=record.get("elapsed_s"), estimated_cost_usd=record.get("estimated_cost_usd"),
                        attempts=int(record.get("attempts") or 0), reused=bool(record.get("reused_from")))
        if latest_only:
            rows[(row.scene_id, row.mode)] = row            # 이름순이 곧 시간순이라 뒤의 것이 최근이다
        else:
            rows.append(row)
    return sorted(rows.values() if latest_only else rows, key=lambda r: (r.scene_id, r.mode, r.run_id))


def extract_stills(row: RenderRow, out_dir: Path, fractions: list[float]) -> list[Path]:
    """영상에서 정지 화면을 뽑는다. FFmpeg 가 없으면 빈 목록."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    stills = []
    for n, fraction in enumerate(fractions, 1):
        target = out_dir / f"{row.scene_id}.{row.mode}.{row.run_id}.t{n}.jpg"
        result = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{row.duration_s * fraction:.2f}",
                                 "-i", row.video, "-frames:v", "1", "-q:v", "3", str(target)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0 and target.is_file():
            stills.append(target)
    return stills


def write_csv(rows: list[RenderRow], path: Path, checklist: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["scene_id", "mode", "run_id", "images", "elapsed_s", "estimated_cost_usd", "attempts", "reused",
                         "video"] + [c["id"] for c in checklist] + ["note"])
        for r in rows:
            writer.writerow([r.scene_id, r.mode, r.run_id, r.images, r.elapsed_s if r.elapsed_s is not None else "",
                             r.estimated_cost_usd if r.estimated_cost_usd is not None else "", r.attempts,
                             "yes" if r.reused else "", Path(r.video).name] + ["" for _ in checklist] + [""])
    return path


def report_markdown(episode: str, rows: list[RenderRow], policy: dict[str, Any], references: dict[str, str],
                    made_at: str) -> str:
    checklist, marks = policy["consistency"]["checklist"], policy["consistency"]["marks"]
    lines = [f"# 일관성 점검표 — {episode}", "", f"만든 때: {made_at}",
             "프로그램은 정지 화면을 뽑아 나란히 놓았을 뿐이다. 아래 표는 사람이 보고 적는다.", "",
             "## 보는 것", ""]
    lines += [f"- **{c['name_ko']}**: {c['look_ko']}" for c in checklist]
    lines += ["", f"적는 말: {' / '.join(marks)}", ""]
    if references:
        lines += ["## 견줄 레퍼런스", ""] + [f"- {pid}: `{path}`" for pid, path in references.items()] + [""]
    lines += ["## 장면별", "", "| 장면 | 모드 | 실행 | 이음판 | " + " | ".join(c["name_ko"] for c in checklist) + " | 적을 것 |",
              "|---|---|---|---|" + "---|" * (len(checklist) + 1)]
    for r in rows:
        sheet = f"`{Path(r.sheet).name}`" if r.sheet else "(FFmpeg 없음)"
        lines.append(f"| {r.scene_id} | {r.mode} | {r.run_id} | {sheet} | " + " | ".join("" for _ in checklist) + " |  |")
    lines += ["", "## 장면 사이", "", "- 같은 제품이 장면마다 같은 것으로 보이는가:", "- 장소와 빛이 이어지는가:",
              "- 다시 뽑을 장면과 그 까닭:", "", "## 본 사람", "", "- 이름:", "- 본 날:", "- 걸린 시간:", ""]
    return "\n".join(lines)
