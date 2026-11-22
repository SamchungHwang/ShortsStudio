"""이미 만든 영상을 다시 쓴다 (4장 '비용 줄이기').

같은 프롬프트, 같은 모델, 같은 길이·해상도·화면비로 만든 영상이 다른 프로젝트(또는 견본)에 있으면
다시 생성하지 않고 가져온다. 견본을 따라 입력한 프로젝트는 견본과 프롬프트가 같으므로,
견본에서 이미 생성했다면 그 영상을 그대로 쓸 수 있다.

같은지는 프롬프트의 지문(prompt_sha256)으로 가른다. 한 글자라도 다르면 가져오지 않는다.
가져온 영상의 실행 기록에는 어디서 왔는지(reused_from)를 적고, 추정 비용은 0 으로 둔다.
돈은 원래 만든 곳에서 이미 냈고, 그쪽 장부에 잡혀 있다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class Reusable(BaseModel):
    record_path: str
    video_path: str
    run_id: str
    estimated_cost_usd: float


def same_request(record: dict[str, Any], prompt_sha: str, model: str, response_format: dict[str, Any]) -> bool:
    theirs = (record.get("request") or {}).get("response_format") or {}
    keys = ("type", "aspect_ratio", "resolution", "duration")
    return (record.get("status") == "ok" and not record.get("reused_from")
            and record.get("prompt_sha256") == prompt_sha and record.get("model") == model
            and all(theirs.get(k) == response_format.get(k) for k in keys))


def find_reusable(source_output_dir: Path, prompt_sha: str, model: str,
                  response_format: dict[str, Any]) -> Reusable | None:
    """source 의 renders 아래에서 같은 요청으로 만든 영상을 찾는다. 여럿이면 가장 최근 것."""
    found: list[Reusable] = []
    for record_path in sorted((source_output_dir / "renders").rglob("*.api_run.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        video = record_path.with_name(record_path.name.replace(".api_run.json", ".mp4"))
        if video.is_file() and same_request(record, prompt_sha, model, response_format):
            found.append(Reusable(record_path=str(record_path), video_path=str(video),
                                  run_id=str(record.get("run_id", "")),
                                  estimated_cost_usd=float(record.get("estimated_cost_usd") or 0.0)))
    return max(found, key=lambda r: r.run_id) if found else None


def already_here(target_dir: Path, scene_id: str, prompt_sha: str) -> bool:
    """이 프로젝트에 같은 프롬프트로 만든(또는 가져온) 영상이 이미 있는가."""
    for record_path in target_dir.glob(f"{scene_id}.*.api_run.json"):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        video = record_path.with_name(record_path.name.replace(".api_run.json", ".mp4"))
        if record.get("status") == "ok" and record.get("prompt_sha256") == prompt_sha and video.is_file():
            return True
    return False


def bring(found: Reusable, target_dir: Path, scene_id: str, episode: str, source_name: str) -> Path:
    """영상과 실행 기록을 이 프로젝트로 복사한다. 원본은 건드리지 않는다."""
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{scene_id}.{found.run_id}"
    video = target_dir / f"{stem}.mp4"
    shutil.copyfile(found.video_path, video)
    record = json.loads(Path(found.record_path).read_text(encoding="utf-8"))
    record.update({
        "episode": episode, "scene_id": scene_id, "output_path": str(video),
        "purpose": f"ass reuse {episode} {scene_id}", "reused_from": f"{source_name}: {found.record_path}",
        "original_cost_usd": found.estimated_cost_usd, "estimated_cost_usd": 0.0,
    })
    (target_dir / f"{stem}.api_run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return video
