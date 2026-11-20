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
from ass.settings import CONFIG_DIR, EXAMPLE_DIR, OUTPUT_DIR, ROOT
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


class FileRow(BaseModel):
    """명령이 읽거나 쓰는 파일 한 줄. 콘솔의 '읽고 쓰는 파일' 탭에 보인다."""
    mark: str              # ①~⑧ 또는 →
    kind: str              # "읽음" | "씀"
    path: str              # 저장소 기준 상대 경로
    what: str              # 여기서 가져오는 것 / 여기에 쓰는 것
    status: str            # "2026-11-20 10:15" | "없음" | "실행하면 생김"
    exists: bool


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_row(mark: str, path: Path, what: str, root: Path, optional: bool = False) -> FileRow:
    if path.is_file():
        status = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    else:
        status = "없음 (없어도 된다)" if optional else "없음"
    return FileRow(mark=mark, kind="읽음", path=_rel(path, root), what=what, status=status, exists=path.is_file())


def _write_row(path: Path, what: str, root: Path) -> FileRow:
    if path.is_file():
        status = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M") + " (다시 쓴다)"
    else:
        status = "실행하면 생김"
    return FileRow(mark="→", kind="씀", path=_rel(path, root), what=what, status=status, exists=path.is_file())


def command_files(command: str, episode: str, scene: str = ALL_SCENES, *, root: Path = ROOT,
                  example_dir: Path = EXAMPLE_DIR, config_dir: Path = CONFIG_DIR,
                  output_dir: Path = OUTPUT_DIR) -> list[FileRow]:
    """이 명령이 읽는 파일과 쓰는 파일을 순서대로 돌려준다. 실행하지 않고 경로만 따진다."""
    if command not in ("compile", "render") or not episode:
        return []
    folder = example_dir / "episodes" / episode
    paths = sorted(folder.glob("scene_*.yaml"))
    numbered = list(enumerate(paths, 1))
    if command == "render" and scene != ALL_SCENES:
        numbered = [(n, p) for n, p in numbered if str(n) == scene]

    rows: list[FileRow] = []
    scene_ids: list[str] = []
    episode_id = ""
    for n, path in numbered:
        what = f"장면 {n}의 사양: 구간, 화면, 내레이션, 자막, 근거"
        try:
            spec = load_scene(path)
            scene_ids.append(spec.scene_id)
            episode_id = spec.episode_id
            what = f"장면 {n} ({spec.role}, {spec.duration_s}초): 구간 {len(spec.beats)}개의 화면, 내레이션, 자막, 근거"
        except Exception as exc:        # 깨진 파일도 목록에는 보여야 고칠 수 있다
            what = f"장면 {n}: 읽지 못했다 — {str(exc).splitlines()[0]}"
        rows.append(_read_row("①", path, what, root))
    if not paths:
        rows.append(FileRow(mark="①", kind="읽음", path=_rel(folder, root) + "/scene_*.yaml",
                            what="장면 사양", status="없음", exists=False))

    rows.append(_read_row("②", example_dir / "product_bible.yaml", "제품의 영어 외형 서술과 근거로 쓸 수 있는 사실", root))
    if command == "compile":
        brief = example_dir / "source_briefs" / f"{episode_id or episode}.yaml"
        rows.append(_read_row("③", brief, "장면 설계표 머리에 적을 제목과 약속", root, optional=True))
    rows.append(_read_row("④", config_dir / "production_spec.yaml", "형식별 장면 순서, 길이 정책, 스타일, 제외 지시, 문법 기준", root))
    rows.append(_read_row("⑤", config_dir / "claims_lexicon.yaml", "쓸 수 없는 표현의 목록 (제품 표현 가드)", root))
    rows.append(_read_row("⑥", config_dir / "models.yaml",
                          "해상도별 단가" + (", 모델 ID, API 버전" if command == "render" else " (추정 비용)"), root))

    if command == "compile":
        out = output_dir / "compiled" / episode
        for sid in scene_ids:
            rows.append(_write_row(out / f"{sid}.prompt.txt", "모델에게 보낼 영어 프롬프트", root))
            rows.append(_write_row(out / f"{sid}.compiled.json", "프롬프트 + 내레이션 대본 + 버전 정보", root))
        rows.append(_write_row(out / "storyboard.md", "장면 설계표", root))
    else:
        rows.append(_read_row("⑦", config_dir / "budget_policy.yaml", "실행 예산 상한", root))
        rows.append(_read_row("⑧", root / ".env", "API 키 (값은 어디에도 보여 주지 않는다)", root))
        out = output_dir / "renders" / episode
        for sid in scene_ids:
            rows.append(FileRow(mark="→", kind="씀", path=_rel(out, root) + f"/{sid}.<실행 시각>.mp4",
                                what="생성된 영상 (요청만 확인할 때는 만들지 않는다)", status="실행하면 생김", exists=False))
            rows.append(FileRow(mark="→", kind="씀", path=_rel(out, root) + f"/{sid}.<실행 시각>.api_run.json",
                                what="실행 기록: 요청, 추정 비용, 정책 버전", status="실행하면 생김", exists=False))
    return rows


def files_summary(rows: list[FileRow]) -> str:
    """실행 버튼 옆 안내문에 붙일 한 줄."""
    reads = [r for r in rows if r.kind == "읽음"]
    writes = [r for r in rows if r.kind == "씀"]
    missing = [r for r in reads if not r.exists and "없어도" not in r.status]
    if not rows:
        return ""
    text = f"파일 {len(reads)}개를 읽고 {len(writes)}개를 쓴다"
    if missing:
        text += f" · 없는 파일 {len(missing)}개: {', '.join(r.path for r in missing)}"
    return text


def finish_state(code: int, stopped: bool = False) -> tuple[str, str]:
    """종료코드를 사람이 읽는 말과 종류(ok, guard, stop, fail)로 바꾼다."""
    if stopped and code != 0:
        return "멈췄습니다", "stop"
    if code == 0:
        return "끝났습니다", "ok"
    if code == 4:
        return "가드가 막았습니다", "guard"
    return f"실패했습니다 (종료코드 {code})", "fail"


def finish_mark(code: int, stopped: bool = False) -> str:
    return {"ok": "✔", "guard": "■", "stop": "■", "fail": "✖"}[finish_state(code, stopped)[1]]
