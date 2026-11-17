"""〈모모의 월요 회의〉 세 장면을 영어 프롬프트로 컴파일한다. API를 호출하지 않는다.

    python scripts/compile_scenes.py
"""
from __future__ import annotations

import json

import _common  # noqa: F401
from acs.guards.cost_guard import UnknownPrice, estimate_video_cost
from acs.policy import load_policy
from acs.production.character_bible import load_character_bible
from acs.production.scene_compiler import compile_scene
from acs.production.scene_spec import check_episode, load_scene
from acs.settings import EXAMPLE_DIR, OUTPUT_DIR


def main() -> int:
    spec = load_policy("production_spec")
    models = load_policy("models")
    bible = load_character_bible(EXAMPLE_DIR / "character_bible.yaml")
    scenes = [load_scene(p) for p in sorted((EXAMPLE_DIR / "scenes").glob("scene_*.yaml"))]

    problems = check_episode(scenes, spec.data)
    for p in problems:
        print(f"[길이 정책] {p}")

    resolution = spec.data["shot"]["draft_resolution"]
    out_dir = OUTPUT_DIR / "compiled"
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

    print(f"\n장면 {len(scenes)}개, 생성 길이 합 {sum(s.duration_s for s in scenes)}초, "
          f"초안 1회 추정 비용 ${total:.2f} ({resolution})")
    print(f"policy_hash  production_spec={spec.policy_hash}  models={models.policy_hash}")
    print(f"저장: {out_dir}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
