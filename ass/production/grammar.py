"""유용한 Shorts의 문법 검사와 장면 설계표 (3장).

네 가지를 본다: 첫 1초 훅, 약속 하나, 근거, 다음 행동. 그리고 내레이션이 구간 안에 읽히는 길이인가.
형식·길이 정책(check_episode)과 달리 여기서 나오는 것은 '주의'다. 막지 않고 알려 준다.
"""
from __future__ import annotations

from typing import Any

from ass.production.scene_spec import SceneSpec


def _chars(text: str | None) -> int:
    return len((text or "").replace(" ", ""))


def check_grammar(scenes: list[SceneSpec], production_spec: dict[str, Any]) -> list[str]:
    rules = production_spec.get("grammar", {})
    if not scenes or not rules:
        return []
    fmt = production_spec["formats"][scenes[0].format]
    notes: list[str] = []

    hook = scenes[0].beats[0]
    hook_max = rules.get("hook_max_s", 3)
    if hook.end_s - hook.start_s > hook_max:
        notes.append(f"[훅] 첫 구간이 {hook.end_s - hook.start_s}초다. {hook_max}초 안에 끝낸다")
    if not (hook.narration_ko or hook.caption_ko):
        notes.append("[훅] 첫 구간에 내레이션도 자막도 없다. 무엇에 대한 영상인지 첫 화면에서 알려 준다")

    for scene in scenes:
        if scene.role in fmt.get("evidence_roles", []) and not any(b.evidence for b in scene.beats):
            notes.append(f"[근거] {scene.scene_id}({scene.role}) 에 근거가 붙은 구간이 없다")

    last = scenes[-1].beats[-1]
    if rules.get("require_closing_line", True) and not (last.narration_ko or last.caption_ko):
        notes.append("[다음 행동] 마지막 구간에 내레이션도 자막도 없다. 시청자가 다음에 할 일을 한 줄로 말한다")

    rate = rules.get("narration_max_chars_per_s")
    if rate:
        for scene in scenes:
            for i, beat in enumerate(scene.beats):
                seconds = beat.end_s - beat.start_s
                n = _chars(beat.narration_ko)
                if n > rate * seconds:
                    notes.append(
                        f"[읽는 속도] {scene.scene_id}.beats[{i}] 내레이션 {n}자를 {seconds}초에 읽어야 한다 "
                        f"(기준 초당 {rate}자, 최대 {rate * seconds}자)")
    return notes


def storyboard_markdown(scenes: list[SceneSpec], production_spec: dict[str, Any],
                        title: str = "", promise: str = "") -> str:
    """장면 설계표 (3.4절). 장면 사양에서 만든다. 손으로 고치지 않는다."""
    fmt = production_spec["formats"][scenes[0].format]
    names = dict(zip(fmt["scene_roles"], fmt.get("role_names_ko", fmt["scene_roles"])))
    total = sum(s.duration_s for s in scenes)
    out = [f"# 장면 설계표 — {title or scenes[0].episode_id}", "",
           f"- 형식: {fmt['name_ko']} ({' → '.join(names.values())})",
           f"- 길이: {' + '.join(str(s.duration_s) for s in scenes)} = {total}초"]
    if promise:
        out.append(f"- 약속: {promise}")
    out.append("")
    for n, scene in enumerate(scenes, 1):
        products = ", ".join(scene.products) or "없음"
        out += [f"## 장면 {n} · {names.get(scene.role, scene.role)} ({scene.duration_s}초) — 제품: {products}", "",
                "| 구간 | 화면 | 내레이션 | 자막 | 근거 |", "|---|---|---|---|---|"]
        for b in scene.beats:
            out.append(f"| {b.start_s}~{b.end_s}초 | {b.visual_ko} | {b.narration_ko or '—'} "
                       f"| {b.caption_ko or '—'} | {', '.join(b.evidence) or '—'} |")
        out.append("")
    notes = check_grammar(scenes, production_spec)
    out.append("## 문법 검사")
    out += [f"- {n}" for n in notes] or ["- 주의 없음"]
    return "\n".join(out) + "\n"
