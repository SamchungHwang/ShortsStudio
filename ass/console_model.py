"""콘솔(ass console)의 판단 부분. 화면 코드(tkinter)와 떼어 두어 화면 없이 테스트한다.

콘솔은 새 기능을 만들지 않는다. `ass <명령>` 을 대신 실행하고 결과를 보여 줄 뿐이다.
콘솔에서 되는 일은 모두 명령줄에서도 되고, 가드와 실행 기록도 똑같이 적용된다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ass.guards.cost_guard import UnknownPrice, estimate_video_cost
from ass.policy import load_policy
from ass.production.product_bible import load_product_bible
from ass.production.scene_compiler import CompileError, compile_scene
from ass.production.scene_spec import SceneSpec, check_episode, load_scene
from ass.settings import EXAMPLE_DIR, OUTPUT_DIR
from ass.workflow import Workflow

ALL_SCENES = "전체"
SPEC_DURATION = "장면 사양대로"


class StageRow(BaseModel):
    number: int
    stage_id: str
    name: str
    question: str
    commands: str          # "compile [있음] · script [없음]"
    models: str
    guards: str
    chapters: str
    ready: int             # 있는 명령 수
    total: int


def stage_rows(workflow: Workflow, available: set[str], models_config: dict[str, Any]) -> list[StageRow]:
    rows = []
    for n, s in enumerate(workflow.stages, 1):
        marks = [f"{c} [{'있음' if c in available else '없음'}]" for c in s.commands]
        rows.append(StageRow(
            number=n, stage_id=s.id, name=s.name_ko, question=s.question_ko,
            commands=" · ".join(marks),
            models=", ".join(str(models_config[m]["name"]) for m in s.models if m in models_config) or "—",
            guards=", ".join(s.guards) or "—", chapters=s.chapters,
            ready=sum(c in available for c in s.commands), total=len(s.commands),
        ))
    return rows


def list_episodes(example_dir: Path = EXAMPLE_DIR) -> list[str]:
    folder = example_dir / "episodes"
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_dir() and any(p.glob("scene_*.yaml")))


def load_episode(episode: str, example_dir: Path = EXAMPLE_DIR) -> list[SceneSpec]:
    return [load_scene(p) for p in sorted((example_dir / "episodes" / episode).glob("scene_*.yaml"))]


def _selected(scenes: list[SceneSpec], scene: str) -> list[tuple[int, SceneSpec]]:
    if scene == ALL_SCENES:
        return list(enumerate(scenes, 1))
    n = int(scene)
    if not 1 <= n <= len(scenes):
        raise ValueError(f"장면 번호는 1~{len(scenes)} 이어야 한다")
    return [(n, scenes[n - 1])]


def _duration(scene: SceneSpec, duration: str) -> int:
    return scene.duration_s if duration == SPEC_DURATION else int(duration)


def build_runs(command: str, episode: str, scene: str = ALL_SCENES,
               duration: str = SPEC_DURATION, dry_run: bool = True,
               example_dir: Path = EXAMPLE_DIR) -> list[list[str]]:
    """콘솔의 선택을 `python -m ass` 뒤에 붙일 인자 목록들로 바꾼다. 장면이 여럿이면 한 장면씩 차례로 실행한다."""
    if command == "compile":
        return [["compile", "--episode", episode]]
    if command == "render":
        runs = []
        for n, _ in _selected(load_episode(episode, example_dir), scene):
            argv = ["render", "--episode", episode, "--scene", str(n)]
            if duration != SPEC_DURATION:
                argv += ["--duration", str(int(duration))]
            if dry_run:
                argv.append("--dry-run")
            runs.append(argv)
        return runs
    raise ValueError(f"콘솔에서 실행할 수 없는 명령: {command}")


def paid_estimate(command: str, episode: str, scene: str = ALL_SCENES,
                  duration: str = SPEC_DURATION, dry_run: bool = True,
                  example_dir: Path = EXAMPLE_DIR) -> float:
    """이 실행의 추정 비용(USD). 비용이 들지 않으면 0. 단가를 모르면 UnknownPrice."""
    if command != "render" or dry_run:
        return 0.0
    models = load_policy("models").data
    resolution = load_policy("production_spec").data["shot"]["draft_resolution"]
    total = 0.0
    for _, s in _selected(load_episode(episode, example_dir), scene):
        total += estimate_video_cost(_duration(s, duration), resolution, models)
    return round(total, 2)


def run_budget_usd() -> float:
    import os

    override = os.environ.get("ASS_RUN_BUDGET_USD", "").strip()
    return float(override) if override else float(load_policy("budget_policy").data["run_budget_usd"])


def episode_summary(episode: str, example_dir: Path = EXAMPLE_DIR) -> str:
    """편 선택 아래에 보여 줄 한 줄 요약."""
    spec = load_policy("production_spec").data
    scenes = load_episode(episode, example_dir)
    if not scenes:
        return f"{episode}: 장면 사양이 없다"
    fmt = spec["formats"][scenes[0].format]["name_ko"]
    total_s = sum(s.duration_s for s in scenes)
    resolution = spec["shot"]["draft_resolution"]
    try:
        cost = sum(estimate_video_cost(s.duration_s, resolution, load_policy("models").data) for s in scenes)
        cost_text = f"초안 1회 추정 ${cost:.2f} ({resolution})"
    except UnknownPrice:
        cost_text = f"{resolution} 단가 미확인"
    problems = check_episode(scenes, spec)
    tail = f" · 정책 위반 {len(problems)}건" if problems else ""
    return (f"{fmt} · 장면 {len(scenes)}개 · {total_s}초 · {cost_text} · "
            f"실행 예산 ${run_budget_usd():.2f}{tail}")


def preview(episode: str, scene: str, example_dir: Path = EXAMPLE_DIR) -> str:
    """선택한 장면의 프롬프트와 내레이션을 미리 본다. 가드에 막히면 그 이유를 보여 준다. 비용 없음."""
    spec = load_policy("production_spec").data
    bible = load_product_bible(example_dir / "product_bible.yaml")
    parts: list[str] = []
    for n, s in _selected(load_episode(episode, example_dir), scene):
        parts.append(f"=== 장면 {n}: {s.scene_id} ({s.role}, {s.duration_s}초) ===")
        try:
            compiled = compile_scene(s, bible, spec)
        except CompileError as exc:
            parts.append(f"[막힘] {exc}\n")
            continue
        parts.append(compiled.prompt)
        if compiled.narration:
            parts.append(f"--- 내레이션 ({compiled.narration_mode}) ---")
            for line in compiled.narration:
                caption = f"  [자막: {line.caption}]" if line.caption else ""
                evidence = f"  (근거: {', '.join(line.evidence)})" if line.evidence else ""
                parts.append(f"[{line.start_s}-{line.end_s}s] {line.text}{caption}{evidence}")
        if compiled.needs_human_approval:
            parts.append("!! 타사 제품이 나온다. 생성 전에 사람 승인이 필요하다.")
        parts.append("")
    return "\n".join(parts)


def list_outputs(output_dir: Path = OUTPUT_DIR, limit: int = 200) -> list[tuple[str, str, str]]:
    """산출물 목록: (상대 경로, 수정 시각, 크기). 최근 것부터."""
    if not output_dir.is_dir():
        return []
    files = [p for p in output_dir.rglob("*") if p.is_file() and p.name != ".gitkeep"]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    for p in files[:limit]:
        st = p.stat()
        size = f"{st.st_size / 1e6:.1f}MB" if st.st_size >= 1e6 else f"{max(1, st.st_size // 1024)}KB"
        rows.append((p.relative_to(output_dir).as_posix(),
                     datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"), size))
    return rows
