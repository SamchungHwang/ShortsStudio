"""콘솔(ass console)의 판단 부분. 화면 코드(tkinter)와 떼어 두어 화면 없이 테스트한다.

콘솔은 새 기능을 만들지 않는다. `ass <명령>` 을 대신 실행하고 결과를 보여 줄 뿐이다.
콘솔에서 되는 일은 모두 명령줄에서도 되고, 가드와 실행 기록도 똑같이 적용된다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ass.guards.cost_guard import UnknownPrice, estimate_image_cost, estimate_video_cost
from ass.policy import load_policy
from ass.production.product_bible import load_product_bible
from ass.production.scene_compiler import CompileError, compile_scene
from ass.production.scene_spec import SceneSpec, check_episode, load_scene
from ass import settings
from ass.settings import CONFIG_DIR, EXAMPLE_DIR, OUTPUT_DIR, ROOT
from ass.workflow import Workflow

RUNNABLE = ("compile", "sheet", "render", "assemble")      # 콘솔의 [실행] 으로 돌릴 수 있는 명령
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
               example_dir: Path = EXAMPLE_DIR, picks: dict[str, str] | None = None,
               approved_by: str = "") -> list[list[str]]:
    """콘솔의 선택을 `python -m ass` 뒤에 붙일 인자 목록들로 바꾼다. 장면이 여럿이면 한 장면씩 차례로 실행한다."""
    if command == "sheet":                    # 편에 나오는 제품마다 한 번씩
        runs = []
        for product in episode_products(episode, example_dir):
            argv = ["sheet", "--product", product.id]
            if not product.is_own and approved_by:
                argv += ["--approved-by", approved_by]
            runs.append(argv + (["--dry-run"] if dry_run else []))
        return runs
    if command == "bible":
        return [["bible"]]
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
    if command == "assemble":
        argv = ["assemble", "--episode", episode]
        for n, run_id in sorted((picks or {}).items()):       # 장면 번호=실행. 고르지 않은 장면은 가장 최근 것
            argv += ["--pick", f"{n}={run_id}"]
        return [argv + (["--dry-run"] if dry_run else [])]
    if command == "cost":
        return [["cost"] + (["--episode", episode] if episode else [])]
    if command == "doctor":
        return [["doctor"]]
    raise ValueError(f"콘솔에서 실행할 수 없는 명령: {command}")


def paid_estimate(command: str, episode: str, scene: str = ALL_SCENES,
                  duration: str = SPEC_DURATION, dry_run: bool = True,
                  example_dir: Path = EXAMPLE_DIR) -> float:
    """이 실행의 추정 비용(USD). 비용이 들지 않으면 0. 단가를 모르면 UnknownPrice."""
    if dry_run or command not in ("render", "sheet"):
        return 0.0
    models = load_policy("models").data
    if command == "sheet":
        recipe = load_policy("reference_sheet").data
        count = len(recipe["views"]) * len(episode_products(episode, example_dir))
        return round(estimate_image_cost(recipe["image"]["size"], models, count), 2)
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


def list_outputs(output_dir: Path = OUTPUT_DIR, limit: int = 200,
                 example_dir: Path | None = None) -> list[tuple[str, str, str]]:
    """산출물 목록: (산출물 폴더 기준 상대 경로, 수정 시각, 크기). 최근 것부터.

    사람이 고른 레퍼런스(assets/products/<제품>/reference/ 와 reference_manifest.json)와
    글 모델의 초안(drafts/<편>/)은 산출물 폴더 밖에 있지만 실행이 만든 것이므로 함께 보여 준다.
    경로가 ../ 로 시작한다."""
    import os

    if example_dir is None and output_dir == OUTPUT_DIR:
        example_dir = EXAMPLE_DIR
    files = [p for p in output_dir.rglob("*") if p.is_file() and p.name != ".gitkeep"] if output_dir.is_dir() else []
    products = (example_dir / "assets" / "products") if example_dir else None
    if products and products.is_dir():
        files += [p for p in products.glob("*/reference_manifest.json") if p.is_file()]
        files += [p for p in products.glob("*/reference/*") if p.is_file()]
    drafts = (example_dir / "drafts") if example_dir else None        # 글 모델이 만든 초안 (6장). 저장본이 아니다
    if drafts and drafts.is_dir():
        files += [p for p in drafts.rglob("*.yaml") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    for p in files[:limit]:
        st = p.stat()
        size = f"{st.st_size / 1e6:.1f}MB" if st.st_size >= 1e6 else f"{max(1, st.st_size // 1024)}KB"
        rows.append((Path(os.path.relpath(p, output_dir)).as_posix(),
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
                  output_dir: Path = OUTPUT_DIR, picks: dict[str, str] | None = None) -> list[FileRow]:
    """이 명령이 읽는 파일과 쓰는 파일을 순서대로 돌려준다. 실행하지 않고 경로만 따진다."""
    if command == "assemble" and episode:
        return _assemble_files(episode, root, example_dir, config_dir, output_dir, picks)
    if command == "sheet" and episode:
        return _sheet_files(episode, root, example_dir, config_dir, output_dir)
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


def _assemble_files(episode: str, root: Path, example_dir: Path, config_dir: Path, output_dir: Path,
                    picks: dict[str, str] | None = None) -> list[FileRow]:
    """ass assemble 이 읽고 쓰는 파일. 장면마다 어느 실행의 영상을 쓸지도 여기서 보인다."""
    from ass.production.assembler import AssembleError, find_render

    rows: list[FileRow] = []
    render_dir = output_dir / "renders" / episode
    for n, path in enumerate(sorted((example_dir / "episodes" / episode).glob("scene_*.yaml")), 1):
        try:
            spec = load_scene(path)
        except Exception as exc:
            rows.append(_read_row("②", path, f"장면 {n}: 읽지 못했다 — {str(exc).splitlines()[0]}", root))
            continue
        try:
            picked = (picks or {}).get(str(n))
            video, run_id = find_render(render_dir, spec.scene_id, picked)
            source = f"실행 {run_id}" if run_id else "실행 기록 없는 영상"
            how = "직접 고른 것" if picked else "성공한 실행 가운데 가장 최근 것"
            rows.append(_read_row("①", video, f"장면 {n} 영상 ({source}). {how}", root))
        except AssembleError:
            rows.append(FileRow(mark="①", kind="읽음", path=_rel(render_dir, root) + f"/{spec.scene_id}.<실행 시각>.mp4",
                                what=f"장면 {n} 영상. 아직 없다 — ass render --scene {n} 을 먼저 실행한다",
                                status="없음", exists=False))
        rows.append(_read_row("②", path, f"장면 {n}의 요청 길이({spec.duration_s}초)와 자막 문구", root))
    rows.sort(key=lambda r: r.mark)            # 영상 ① 을 먼저, 장면 사양 ② 를 다음에
    rows.append(_read_row("③", config_dir / "assemble_recipe.yaml", "크기, 프레임 수, 잘라 낼 길이, 인코딩 설정", root))
    rows.append(_read_row("④", config_dir / "production_spec.yaml", "길이 정책: 목표 42~48초, 상한 60초", root))
    try:
        name = str(load_policy("assemble_recipe").data.get("output_name", "draft_45s"))
    except Exception:
        name = "draft_45s"
    out = output_dir / "episodes" / episode
    rows.append(_write_row(out / f"{name}.mp4", "이어 붙인 초안 한 편 (요청만 확인할 때는 만들지 않는다)", root))
    rows.append(_write_row(out / f"{name}.srt", "자막 파일. 영상에 입히지 않는다", root))
    rows.append(_write_row(out / f"{name}.assembly.json", "조립 기록: 쓴 영상, 실제 길이, FFmpeg 명령", root))
    review = out / f"{name}.review.md"
    rows.append(FileRow(mark="→", kind="씀", path=_rel(review, root), what="검토 기록의 빈 양식. 사람이 초안을 보고 채운다",
                        status="이미 있다 (덮어쓰지 않는다)" if review.is_file() else "실행하면 생김", exists=review.is_file()))
    return rows


def episode_products(episode: str, example_dir: Path = EXAMPLE_DIR) -> list:
    """이 편의 장면들에 나오는 제품. 나오는 순서대로, 겹치지 않게."""
    bible = load_product_bible(example_dir / "product_bible.yaml")
    seen: list[str] = []
    for spec in load_episode(episode, example_dir):
        for pid in spec.products:
            if pid not in seen:
                seen.append(pid)
    return [bible.get(pid) for pid in seen]


def _sheet_files(episode: str, root: Path, example_dir: Path, config_dir: Path, output_dir: Path) -> list[FileRow]:
    """ass sheet 이 읽고 쓰는 파일. 본인 사진이 있는지, 다음 후보가 몇 번인지 여기서 보인다."""
    from ass.production import reference_sheet as rs

    recipe = load_policy("reference_sheet").data
    rows = [_read_row("①", example_dir / "product_bible.yaml", "제품의 외형 서술. 먼저 점검하고, 막힘이 있으면 만들지 않는다", root)]
    products = episode_products(episode, example_dir)
    for product in products:
        photos = rs.photo_paths(product.id, recipe, example_dir)
        folder = rs.photo_dir(product.id, recipe, example_dir)
        if photos:
            for photo in photos:
                rows.append(_read_row("②", photo, f"{product.name_ko}: 본인이 찍은 사진. 이 사진을 보고 그린다", root))
        else:
            rows.append(FileRow(mark="②", kind="읽음", path=_rel(folder, root) + "/*.jpg",
                                what=f"{product.name_ko}: 본인이 찍은 사진. 없으면 외형 서술만으로 만든다",
                                status="없음 (없어도 된다)", exists=False))
    rows.append(_read_row("③", config_dir / "reference_sheet.yaml", f"방향 {len(recipe['views'])}개, 촬영 조건, 이미지 크기", root))
    rows.append(_read_row("④", config_dir / "bible_rules.yaml", "제품 바이블 점검 규칙", root))
    rows.append(_read_row("⑤", config_dir / "models.yaml", "이미지 모델 ID, 한 장의 단가", root))
    rows.append(_read_row("⑥", config_dir / "budget_policy.yaml", "실행 예산 상한", root))
    rows.append(_read_row("⑦", root / ".env", "API 키 (값은 어디에도 보여 주지 않는다)", root))
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[recipe["image"]["mime_type"]]
    for product in products:
        version_dir = rs.sheet_root(product.id, output_dir) / rs.next_version(rs.sheet_root(product.id, output_dir))
        for view in recipe["views"]:
            rows.append(FileRow(mark="→", kind="씀", path=_rel(version_dir / f"{view['id']}{ext}", root),
                                what=f"{product.name_ko} 후보: {view['name_ko']} (요청만 확인할 때는 만들지 않는다)",
                                status="실행하면 생김", exists=False))
        rows.append(FileRow(mark="→", kind="씀", path=_rel(version_dir / "contact_sheet.png", root),
                            what="후보를 가로로 붙인 이음판. 한눈에 보고 고른다", status="실행하면 생김", exists=False))
        rows.append(FileRow(mark="→", kind="씀", path=_rel(version_dir, root) + "/*.api_run.json, sheet.json",
                            what="실행 기록과 후보 묶음의 기록", status="실행하면 생김", exists=False))
    return rows


class SheetChoice(BaseModel):
    """고를 수 있는 후보 하나. 콘솔의 '레퍼런스 고르기' 창에 보인다."""
    product_id: str
    product_name: str
    view_id: str
    view_name: str
    versions: list[str]            # 이 방향의 이미지가 있는 후보 버전. 최근 것부터
    current: str = ""              # 지금 골라져 있는 버전


def sheet_choices(episode: str, example_dir: Path = EXAMPLE_DIR, output_dir: Path = OUTPUT_DIR) -> list[SheetChoice]:
    from ass.production import reference_sheet as rs

    recipe = load_policy("reference_sheet").data
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[recipe["image"]["mime_type"]]
    result = []
    for product in episode_products(episode, example_dir):
        root = rs.sheet_root(product.id, output_dir)
        manifest = rs.load_manifest(rs.manifest_path(product.id, recipe, example_dir)) or {}
        current = {i["view"]: i.get("from_version", "") for i in manifest.get("images", [])}
        for view in recipe["views"]:
            versions = [v for v in reversed(rs.list_versions(root)) if (root / v / f"{view['id']}{ext}").is_file()]
            result.append(SheetChoice(product_id=product.id, product_name=product.name_ko, view_id=view["id"],
                                      view_name=view["name_ko"], versions=versions, current=current.get(view["id"], "")))
    return result


def reference_status(choice: SheetChoice) -> str:
    """레퍼런스 고르기 창의 오른쪽 칸. 지금 쓰는 레퍼런스가 무엇인지와, 그보다 새 후보가 있는지."""
    if not choice.versions and not choice.current:
        return "없음 · 만든 후보도 없음"
    if not choice.current:
        return f"없음 → [기록]을 누르면 {choice.versions[0]}"
    if choice.versions and choice.versions[0] != choice.current:
        return f"{choice.current} · 새 후보 {choice.versions[0]} 있음"
    return choice.current


def select_runs(picks: dict[tuple[str, str], str], by: str, note: str = "") -> list[list[str]]:
    """{(제품, 방향): 버전} 을 제품마다 `ass sheet --select …` 한 번으로 바꾼다."""
    runs = []
    for product_id in dict.fromkeys(pid for pid, _ in picks):
        argv = ["sheet", "--product", product_id]
        for (pid, view), version in picks.items():
            if pid == product_id:
                argv += ["--select", f"{view}={version}"]
        argv += ["--by", by]
        runs.append(argv + (["--note", note] if note else []))
    return runs


def brief_runs(episode: str, data: dict[str, Any], dry_run: bool = True) -> list[list[str]]:
    """소재 입력 화면의 값으로 `ass brief` 한 번. 소유 확인 표시가 없으면 만들지 않는다."""
    if not data.get("owner_confirmed"):
        raise ValueError("“내가 쓴 것이거나 쓸 권리가 있는 소재다”에 표시해야 초안을 만든다")
    argv = ["brief", "--episode", episode, "--type", data["source_type"], "--format", data["format"]]
    if data.get("products"):
        argv += ["--products", ",".join(data["products"])]
    if data.get("origin"):
        argv += ["--origin", data["origin"]]
    return [argv + ["--owner-confirmed"] + (["--dry-run"] if dry_run else [])]


def script_runs(episode: str, dry_run: bool = True) -> list[list[str]]:
    return [["script", "--episode", episode] + (["--dry-run"] if dry_run else [])]


def draft_cost(input_chars: int) -> float:
    """글 모델 한 번의 어림 상한. 지시문과 제품 사실의 몫으로 2000자를 더한다."""
    from ass.guards.cost_guard import estimate_text_cost

    policy = load_policy("draft_policy").data
    return estimate_text_cost(input_chars + 2000, load_policy("models").data, int(policy["output_tokens_ceiling"]))


class SheetView(BaseModel):
    """레퍼런스 시트의 방향 하나. 콘솔의 '일부 방향만 다시 만들기' 창에 보인다."""

    id: str
    name: str
    anchor: bool = False


def sheet_views() -> list[SheetView]:
    recipe = load_policy("reference_sheet").data
    return [SheetView(id=v["id"], name=v["name_ko"], anchor=v["id"] == recipe["anchor_view"]) for v in recipe["views"]]


def sheet_has_photos(product_id: str, example_dir: Path = EXAMPLE_DIR) -> bool:
    from ass.production import reference_sheet as rs

    return bool(rs.photo_paths(product_id, load_policy("reference_sheet").data, example_dir))


def partial_sheet_views(product_id: str, views: list[str], example_dir: Path = EXAMPLE_DIR) -> list[str]:
    """고른 방향을 레시피의 순서로 돌려준다. 사진이 없으면 기준 방향을 앞에 더한다.

    후보는 실행마다 새 폴더(v00N)에 생기고, 사진이 없는 길에서는 그 폴더의 기준 방향을 보고 나머지를 그린다."""
    recipe = load_policy("reference_sheet").data
    known = [v["id"] for v in recipe["views"]]
    unknown = [v for v in views if v not in known]
    if unknown:
        raise ValueError(f"없는 방향: {', '.join(unknown)}")
    wanted = set(views)
    if wanted and not sheet_has_photos(product_id, example_dir):
        wanted.add(recipe["anchor_view"])
    return [v for v in known if v in wanted]


def partial_sheet_runs(product_id: str, views: list[str], dry_run: bool = True, approved_by: str = "") -> list[list[str]]:
    """`ass sheet --product … --views a,b` 한 번."""
    if not views:
        raise ValueError("만들 방향을 하나 이상 고른다")
    argv = ["sheet", "--product", product_id, "--views", ",".join(views)]
    if approved_by:
        argv += ["--approved-by", approved_by]
    return [argv + (["--dry-run"] if dry_run else [])]


def partial_sheet_cost(count: int) -> float:
    recipe = load_policy("reference_sheet").data
    return round(estimate_image_cost(recipe["image"]["size"], load_policy("models").data, count), 2)


class RenderChoice(BaseModel):
    """조립에 쓸 수 있는 영상 하나. 콘솔의 '조립에 쓸 영상 고르기' 창에 보인다."""
    run_id: str
    label: str             # "20261120-110200 · 102초 걸림 · 4.8MB"


def render_choices(episode: str, example_dir: Path = EXAMPLE_DIR,
                   output_dir: Path = OUTPUT_DIR) -> list[tuple[int, str, list[RenderChoice]]]:
    """장면마다 성공한 실행을 최근 것부터 늘어놓는다. 돌려주는 값은 (장면 번호, scene_id, 고를 수 있는 실행들)."""
    import json

    render_dir = output_dir / "renders" / episode
    result = []
    for n, spec in enumerate(load_episode(episode, example_dir), 1):
        choices = []
        for record_path in sorted(render_dir.glob(f"{spec.scene_id}.*.api_run.json"), reverse=True):
            video = record_path.with_name(record_path.name.replace(".api_run.json", ".mp4"))
            try:
                doc = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if doc.get("status") != "ok" or not video.is_file():
                continue
            parts = [str(doc.get("run_id", ""))]
            if doc.get("elapsed_s"):
                parts.append(f"{float(doc['elapsed_s']):.0f}초 걸림")
            parts.append(f"{video.stat().st_size / 1e6:.1f}MB")
            choices.append(RenderChoice(run_id=str(doc.get("run_id", "")), label=" · ".join(parts)))
        choices.sort(key=lambda c: c.run_id, reverse=True)
        result.append((n, spec.scene_id, choices))
    return result


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


# ---------------------------------------------------------------- 글자 크기
DEFAULT_FONT_SIZE = 12
MIN_FONT_SIZE, MAX_FONT_SIZE = 9, 18
PREFS_PATH = settings.PREFS_PATH              # 이 PC 의 설정. 저장소에 올리지 않는다


def clamp_font_size(size: int) -> int:
    return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(size)))


def font_sizes(base: int) -> dict[str, int]:
    """기본 글자 크기에서 제목, 로그, 표의 줄 높이를 정한다."""
    base = clamp_font_size(base)
    return {"ui": base, "mono": base, "badge": base + 4, "title": base + 8, "row": int(base * 2.2) + 2}


def load_font_size(path: Path = PREFS_PATH) -> int:
    try:
        return clamp_font_size(settings.read_prefs(path)["font_size"])
    except (KeyError, TypeError, ValueError):
        return DEFAULT_FONT_SIZE


def save_font_size(size: int, path: Path = PREFS_PATH) -> None:
    settings.write_prefs({"font_size": clamp_font_size(size)}, path)     # 현재 프로젝트 같은 다른 설정은 그대로 둔다


# ---------------------------------------------------------------- 프로젝트
def project_line() -> str:
    """콘솔 맨 위에 보이는 한 줄. 지금 어느 폴더에서 일하는지."""
    if settings.PROJECT == settings.SAMPLE_NAME:
        return f"견본 (책의 예제) · {settings.PROJECT_DIR} · 내 것을 만들려면 [입력] → 새 프로젝트"
    return f"{settings.PROJECT} · {settings.PROJECT_DIR}"
