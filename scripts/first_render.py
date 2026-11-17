"""2장: 첫 15초. 장면 하나를 컴파일해 Gemini Omni Flash로 생성하고 실행 기록을 남긴다.

    python scripts/first_render.py --dry-run            # 요청만 확인. 비용 없음
    python scripts/first_render.py                      # 1장면 15초 생성 (720p 기준 추정 $1.05)
    python scripts/first_render.py --scene 2 --duration 5

산출물: outputs/ch02/first_render.mp4, outputs/ch02/api_run.json
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime

import _common
from acs.guards.cost_guard import BudgetGuard, estimate_video_cost
from acs.policy import load_policy
from acs.production import omni_client
from acs.production.character_bible import load_character_bible
from acs.production.run_record import RunRecord
from acs.production.scene_compiler import compile_scene
from acs.production.scene_spec import load_scene
from acs.settings import EXAMPLE_DIR, OUTPUT_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--duration", type=int, default=None, help="초(3~15). 기본은 장면 사양의 길이")
    parser.add_argument("--dry-run", action="store_true", help="API를 호출하지 않고 요청만 출력")
    args = parser.parse_args()

    spec = load_policy("production_spec")
    models = load_policy("models")
    budget = load_policy("budget_policy")
    bible = load_character_bible(EXAMPLE_DIR / "character_bible.yaml")
    scene_path = sorted((EXAMPLE_DIR / "scenes").glob(f"scene_{args.scene:02d}_*.yaml"))[0]
    scene = load_scene(scene_path)
    compiled = compile_scene(scene, bible, spec.data)

    duration = args.duration or scene.duration_s
    resolution = spec.data["shot"]["draft_resolution"]
    model_id = models.data["video"]["id"]
    request = omni_client.build_request(
        compiled.prompt,
        model=model_id,
        duration_s=duration,
        aspect_ratio=scene.aspect_ratio,
        resolution=resolution,
    )
    cost = estimate_video_cost(duration, resolution, models.data)
    guard = BudgetGuard(_common.run_budget_usd(budget.data))
    guard.charge(cost, f"{scene.scene_id} {duration}초 {resolution}")

    out_dir = OUTPUT_DIR / "ch02"
    record = RunRecord(
        run_id=datetime.now().strftime("%Y%m%d-%H%M%S"),
        purpose=f"ch02 first render ({scene.scene_id})",
        model=model_id,
        request=omni_client.summarize_request(request),
        prompt_sha256=compiled.prompt_sha256,
        policy_hashes={p.name: p.policy_hash for p in (spec, models, budget)},
        estimated_cost_usd=cost,
    )

    print(f"모델 {model_id} | {duration}초 | {resolution} | {scene.aspect_ratio} | 추정 ${cost:.2f} "
          f"(실행 예산 ${guard.cap_usd:.2f})")
    print(compiled.prompt)

    if args.dry_run:
        record.status = "dry_run"
        print(f"\n[dry-run] 호출하지 않았다. 기록: {record.save(out_dir / 'api_run.dry_run.json')}")
        return 0

    if not os.environ.get("GEMINI_API_KEY"):
        print("\nGEMINI_API_KEY 가 없다. .env.example 을 .env 로 복사해 키를 넣는다.")
        return 2

    try:
        result = omni_client.generate(request, out_dir / "first_render.mp4")
    except Exception as exc:  # 실패도 기록으로 남긴다 ('자주 나는 오류' 상자의 재료)
        record.status = "error"
        record.error = f"{type(exc).__name__}: {exc}"
        print(f"\n실패: {record.error}\n기록: {record.save(out_dir / 'api_run.json')}")
        return 1

    record.interaction_id = result.interaction_id
    record.output_path = result.video_path
    record.elapsed_s = result.elapsed_s
    print(f"\n저장: {result.video_path} ({result.bytes_written / 1e6:.1f}MB, {result.elapsed_s}초 소요)")
    print(f"interaction id: {result.interaction_id}  ← 대화형 편집(9장)에 쓴다")
    print(f"기록: {record.save(out_dir / 'api_run.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
