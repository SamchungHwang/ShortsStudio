"""ass — ASS(Autonomous Shorts Studio)의 명령줄 진입점.

지금 있는 명령은 compile 과 render 둘이다. 나머지 명령은 해당 장에서 추가한다
(전체 목록과 상태는 README 와 시스템 정의서 6절).

    ass compile                      # 장면 사양 → 프롬프트·내레이션 대본. 비용 없음
    ass render --dry-run             # 첫 호출의 요청 확인. 비용 없음
    ass render --scene 1             # 15초 한 장면 생성
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from ass import __version__
from ass.guards.cost_guard import BudgetGuard, UnknownPrice, estimate_video_cost
from ass.policy import load_policy
from ass.production import omni_client
from ass.production.product_bible import load_product_bible
from ass.production.run_record import RunRecord
from ass.production.scene_compiler import compile_scene
from ass.production.scene_spec import check_episode, load_scene
from ass.settings import EXAMPLE_DIR, OUTPUT_DIR, ROOT


def _setup() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # python-dotenv 없이도 환경 변수로 실행할 수 있다
        pass
    if hasattr(sys.stdout, "reconfigure"):  # Windows 콘솔에서 한글이 깨지지 않게
        sys.stdout.reconfigure(encoding="utf-8")


def _run_budget_usd(budget_policy: dict) -> float:
    override = os.environ.get("ASS_RUN_BUDGET_USD", "").strip()
    return float(override) if override else float(budget_policy["run_budget_usd"])


def _load_episode(episode: str):
    folder = EXAMPLE_DIR / "episodes" / episode
    paths = sorted(folder.glob("scene_*.yaml"))
    if not paths:
        raise SystemExit(f"장면 사양이 없다: {folder}")
    return [load_scene(p) for p in paths]


def cmd_compile(args: argparse.Namespace) -> int:
    """장면 사양을 영어 프롬프트와 내레이션 대본으로 컴파일한다. API를 호출하지 않는다."""
    spec = load_policy("production_spec")
    models = load_policy("models")
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    scenes = _load_episode(args.episode)

    problems = check_episode(scenes, spec.data)
    for problem in problems:
        print(f"[형식·길이 정책] {problem}")

    resolution = spec.data["shot"]["draft_resolution"]
    out_dir = OUTPUT_DIR / "compiled" / args.episode
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for scene in scenes:
        compiled = compile_scene(scene, bible, spec.data)
        (out_dir / f"{scene.scene_id}.prompt.txt").write_text(compiled.prompt + "\n", encoding="utf-8")
        (out_dir / f"{scene.scene_id}.compiled.json").write_text(
            json.dumps(compiled.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        try:
            cost = estimate_video_cost(scene.duration_s, resolution, models.data)
            total += cost
            cost_text = f"${cost:.2f}"
        except UnknownPrice:
            cost_text = "단가 미확인"
        print(f"\n=== {scene.scene_id} ({scene.duration_s}초, {resolution}, 추정 {cost_text}) ===")
        print(compiled.prompt)
        if compiled.narration:
            print(f"--- 내레이션 ({compiled.narration_mode}) ---")
            for line in compiled.narration:
                caption = f"  [자막: {line.caption}]" if line.caption else ""
                print(f"[{line.start_s}-{line.end_s}s] {line.text}{caption}")
        if compiled.needs_human_approval:
            print("!! 타사 제품이 나온다. 생성 전에 사람 승인이 필요하다.")

    print(f"\n장면 {len(scenes)}개, 생성 길이 합 {sum(s.duration_s for s in scenes)}초, "
          f"초안 1회 추정 비용 ${total:.2f} ({resolution})")
    print(f"policy_hash  production_spec={spec.policy_hash}  models={models.policy_hash}")
    print(f"저장: {out_dir}")
    return 1 if problems else 0


def cmd_render(args: argparse.Namespace) -> int:
    """장면 하나를 Gemini Omni Flash로 생성하고 실행 기록(api_run.json)을 남긴다."""
    spec = load_policy("production_spec")
    models = load_policy("models")
    budget = load_policy("budget_policy")
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    scenes = _load_episode(args.episode)
    if not 1 <= args.scene <= len(scenes):
        raise SystemExit(f"--scene 은 1~{len(scenes)} 이어야 한다")
    scene = scenes[args.scene - 1]
    compiled = compile_scene(scene, bible, spec.data)

    if compiled.needs_human_approval:
        print("타사 제품이 나오는 장면이다. 사람 승인 절차(9.4절)를 거친 뒤 생성한다. "
              "승인 명령이 생기기 전까지는 생성하지 않는다.")
        return 3

    duration = args.duration or scene.duration_s
    resolution = spec.data["shot"]["draft_resolution"]
    model_id = models.data["video"]["id"]
    request = omni_client.build_request(
        compiled.prompt, model=model_id, duration_s=duration,
        aspect_ratio=scene.aspect_ratio, resolution=resolution,
    )
    cost = estimate_video_cost(duration, resolution, models.data)
    guard = BudgetGuard(_run_budget_usd(budget.data))
    guard.charge(cost, f"{scene.scene_id} {duration}초 {resolution}")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUTPUT_DIR / "renders" / args.episode
    record = RunRecord(
        run_id=run_id,
        purpose=f"ass render {args.episode} {scene.scene_id}",
        model=model_id,
        request=omni_client.summarize_request(request),
        prompt_sha256=compiled.prompt_sha256,
        policy_hashes={p.name: p.policy_hash for p in (spec, models, budget)},
        estimated_cost_usd=cost,
    )

    print(f"모델 {model_id} | {duration}초 | {resolution} | {scene.aspect_ratio} | 추정 ${cost:.2f} "
          f"(실행 예산 ${guard.cap_usd:.2f})")
    print(compiled.prompt)

    record_path = out_dir / f"{scene.scene_id}.{run_id}.api_run.json"
    if args.dry_run:
        record.status = "dry_run"
        print(f"\n[dry-run] 호출하지 않았다. 기록: {record.save(record_path)}")
        return 0

    if not os.environ.get("GEMINI_API_KEY"):
        print("\nGEMINI_API_KEY 가 없다. .env.example 을 .env 로 복사해 키를 넣는다.")
        return 2

    try:
        result = omni_client.generate(request, out_dir / f"{scene.scene_id}.{run_id}.mp4")
    except Exception as exc:  # 실패도 기록으로 남긴다 ('자주 나는 오류' 상자의 재료)
        record.status = "error"
        record.error = f"{type(exc).__name__}: {exc}"
        print(f"\n실패: {record.error}\n기록: {record.save(record_path)}")
        return 1

    record.interaction_id = result.interaction_id
    record.output_path = result.video_path
    record.elapsed_s = result.elapsed_s
    print(f"\n저장: {result.video_path} ({result.bytes_written / 1e6:.1f}MB, {result.elapsed_s}초 소요)")
    print(f"interaction id: {result.interaction_id}  ← 대화형 편집(9장)에 쓴다")
    print(f"기록: {record.save(record_path)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ass", description="ASS (Autonomous Shorts Studio)",
        epilog="다른 명령은 해당 장에서 추가한다. 목록과 상태는 README 를 본다.",
    )
    parser.add_argument("--version", action="version", version=f"ass {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("compile", help="장면 사양 → 프롬프트·내레이션 대본 (비용 없음)")
    c.add_argument("--episode", default="product_intro", help="예제 폴더의 episodes 아래 이름")
    c.set_defaults(func=cmd_compile)

    r = sub.add_parser("render", help="장면 하나를 생성하고 실행 기록을 남김")
    r.add_argument("--episode", default="product_intro")
    r.add_argument("--scene", type=int, default=1, help="장면 번호 (1부터)")
    r.add_argument("--duration", type=int, default=None, help="초(3~15). 기본은 장면 사양의 길이")
    r.add_argument("--dry-run", action="store_true", help="API를 호출하지 않고 요청만 출력")
    r.set_defaults(func=cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    _setup()
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
