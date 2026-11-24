"""drafting — 소재 요약과 장면 사양의 초안 (6장).

    ass brief    원문(아이디어 한 줄, 본인 블로그 글, 본인 영상의 대본) → 소재 요약 초안
    ass script   소재 요약 → 장면 사양 셋의 초안

초안은 drafts/<편>/ 아래에 따로 적는다. 저장본(source_briefs, episodes)은 건드리지 않는다.
사람이 입력 화면에서 초안을 불러와 고치고 저장해야 저장본이 된다.
모델이 지어냈는지는 프로그램이 다 가려내지 못한다. 가려낼 수 있는 것만 가려 '확인할 것'으로 적는다.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from ass.production.claims_guard import ClaimsGuard
from ass.production.grammar import check_grammar
from ass.production.product_bible import Product, find_dont_say, squeeze
from ass.production.scene_spec import SceneSpec, check_episode

# 프로그램이 대조하지 않는 칸. 초안을 보여 줄 때마다 함께 알린다 (E15 2회: 약속에 원문에 없는 효능이 들어왔다)
UNCHECKED_NOTE = "알림(오류가 아니다): 제목과 약속은 프로그램이 대조하지 않는 칸이다. 원문에 없는 효능이나 결과를 약속하고 있지 않은지 직접 읽는다."

SOURCE_NAMES = {"idea": "아이디어 한 줄", "own_blog": "본인 블로그 글", "own_video_script": "본인 영상의 대본"}


# ---------------------------------------------------------------- 지시문에 넣는 것
def facts_block(products: list[Product]) -> str:
    """모델에 보여 주는 제품 사실. 외형, 사실(id), 쓰지 않는 표현. 타사 제품의 say 는 없다."""
    if not products:
        return "(이 편에는 제품이 없다)"
    lines: list[str] = []
    for p in products:
        lines.append(f"- 제품 id {p.id} · {p.name_ko}" + ("" if p.is_own else " · 타사 제품 (평가하지 않는다)"))
        if p.appearance_ko:
            lines.append(f"  외형: {p.appearance_ko}")
        for f in p.facts:
            lines.append(f"  사실 {f.id}: {f.text_ko}")
        for d in p.dont_say:
            lines.append(f"  쓰지 않는 표현: {d.text_ko}")
    return "\n".join(lines)


def brief_prompt(policy: dict[str, Any], *, source_type: str, fmt: str, format_spec: dict[str, Any],
                 products: list[Product], source_text: str) -> str:
    text = source_text.strip()
    if not text:
        raise ValueError("원문이 비어 있다. 아이디어 한 줄이라도 적는다")
    limit = int(policy["max_source_chars"])
    if len(text) > limit:
        raise ValueError(f"원문이 {len(text)}자다. {limit}자까지 보낸다. 이 편에 쓸 부분만 남긴다")
    roles = " → ".join(format_spec["role_names_ko"])
    return (
        f"형식: {format_spec['name_ko']} (장면 셋: {roles})\n"
        f"소재의 종류: {SOURCE_NAMES[source_type]}\n\n"
        f"제품 사실:\n{facts_block(products)}\n\n"
        f"원문:\n<<<\n{text}\n>>>\n\n"
        f"이 원문으로 45초 영상 한 편의 소재 요약을 만든다. 요점 셋은 장면 셋에 하나씩 대응한다.\n"
        f"답의 모양:\n{policy['brief']['output_shape'].strip()}"
    )


def script_prompt(policy: dict[str, Any], *, brief: dict[str, Any], format_spec: dict[str, Any],
                  production_spec: dict[str, Any], products: list[Product]) -> str:
    grammar, caption = production_spec.get("grammar", {}), production_spec.get("caption", {})
    points = "\n".join(
        f"  {n}. {p.get('text_ko', '')}" + (f" (근거: {', '.join(p['evidence'])})" if p.get("evidence") else "")
        for n, p in enumerate(brief.get("key_points", []), 1))
    roles = ", ".join(f"{r}({k})" for r, k in zip(format_spec["scene_roles"], format_spec["role_names_ko"]))
    return (
        f"형식: {format_spec['name_ko']}\n장면의 역할과 순서: {roles}\n"
        f"제목: {brief.get('title_ko', '')}\n시청자에게 하는 약속: {brief.get('promise_ko', '')}\n요점:\n{points}\n\n"
        f"제품 사실:\n{facts_block(products)}\n\n"
        f"지킬 것:\n"
        f"  첫 장면의 첫 구간은 {grammar.get('hook_max_s', 3)}초 안에 끝나고 내레이션이나 자막이 있다.\n"
        f"  내레이션은 공백을 빼고 1초에 {grammar.get('narration_max_chars_per_s', 7)}자를 넘지 않는다.\n"
        f"  자막은 공백을 빼고 {caption.get('max_chars', 12)}자를 넘지 않는다.\n"
        f"  마지막 장면의 마지막 구간에는 다음 행동을 말하는 내레이션이나 자막이 있다.\n"
        f"  화면의 분위기: {format_spec.get('style_en', production_spec['shot']['style_en'])}\n\n"
        f"답의 모양:\n{policy['script']['output_shape'].strip()}"
    )


# ---------------------------------------------------------------- 소재 요약 초안의 대조
def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def check_brief(draft: dict[str, Any], *, source_text: str, source_type: str, products: list[Product],
                quote_min_chars: int = 6) -> list[str]:
    """초안을 원문과 제품 사실에 대조한다. 사람이 확인할 것의 목록을 돌려준다. 막지 않는다."""
    issues: list[str] = []
    for key, label in (("title_ko", "제목"), ("promise_ko", "약속")):
        if not str(draft.get(key, "")).strip():
            issues.append(f"{label}이 비어 있다")
    points = draft.get("key_points") or []
    if not isinstance(points, list) or not points:
        return issues + ["요점이 없다"]
    if len(points) > 3:
        issues.append(f"요점이 {len(points)}개다. 셋까지 쓴다. 넷째부터는 화면에 싣지 않는다")
    facts = {f.id: f.text_ko for p in products for f in p.facts}
    flat_source = squeeze(source_text)
    known_numbers = _numbers(source_text) | {n for t in facts.values() for n in _numbers(t)}
    for n, point in enumerate(points[:3], 1):
        text = str(point.get("text_ko", "")).strip()
        quote = str(point.get("quote", "")).strip()
        evidence = [e for e in (point.get("evidence") or []) if isinstance(e, str)]
        if not text:
            issues.append(f"요점 {n}: 비어 있다")
            continue
        unknown = [e for e in evidence if e not in facts]
        if unknown:
            issues.append(f"요점 {n}: 제품 바이블에 없는 사실 id {', '.join(unknown)}")
        flat_quote = squeeze(quote)
        if flat_quote and flat_quote not in flat_source:
            issues.append(f"요점 {n}: 인용이 원문에 없다 — “{quote}”")
        elif flat_quote and len(flat_quote) < quote_min_chars:
            issues.append(f"요점 {n}: 인용이 너무 짧아 대조가 되지 않는다 — “{quote}”")
        if not flat_quote and not [e for e in evidence if e in facts]:
            issues.append(f"요점 {n}: 모델이 채운 내용이다. 출처를 확인해 근거에 적는다" if source_type == "idea"
                          else f"요점 {n}: 원문의 인용도 제품 사실도 없다. 어디서 나온 말인지 확인한다")
        extra = sorted(_numbers(text) - known_numbers)
        if extra:
            issues.append(f"요점 {n}: 원문과 제품 사실에 없는 숫자 {', '.join(extra)}")
    guard = ClaimsGuard()
    for key in ("title_ko", "promise_ko"):
        for v in guard.find(str(draft.get(key, "")), key):
            issues.append(f"{key}: 표현 사전에 걸리는 말 “{v.term}”")
    for n, point in enumerate(points[:3], 1):
        for v in guard.find(str(point.get("text_ko", "")), ""):
            issues.append(f"요점 {n}: 표현 사전에 걸리는 말 “{v.term}”")
        for p in products:
            for d in find_dont_say(p, str(point.get("text_ko", ""))):
                issues.append(f"요점 {n}: {p.name_ko}에 쓰지 않기로 한 표현 “{d.text_ko}”")
    return issues


def brief_draft_doc(draft: dict[str, Any], *, episode: str, source_type: str, fmt: str, origin: str | None,
                    product_ids: list[str], issues: list[str], model: str, created_at: str) -> dict[str, Any]:
    """drafts/<편>/brief.yaml 에 적을 문서. owner_confirmed 는 언제나 false 다. 사람이 표시한다."""
    points = []
    for point in (draft.get("key_points") or [])[:3]:
        item: dict[str, Any] = {"text_ko": str(point.get("text_ko", "")).strip()}
        if point.get("evidence"):
            item["evidence"] = [e for e in point["evidence"] if isinstance(e, str)]
        if str(point.get("quote", "")).strip():
            item["quote"] = str(point["quote"]).strip()
        points.append(item)
    return {
        "brief_id": episode, "source_type": source_type, "origin": origin or None, "owner_confirmed": False,
        "format": fmt, "title_ko": str(draft.get("title_ko", "")).strip(),
        "promise_ko": str(draft.get("promise_ko", "")).strip(), "products": product_ids, "key_points": points,
        "draft": {"by": model, "created_at": created_at, "check": issues},
    }


# ---------------------------------------------------------------- 장면 초안
def scene_docs(draft: dict[str, Any], *, episode: str, fmt: str, format_spec: dict[str, Any],
               product_ids: list[str]) -> list[dict[str, Any]]:
    """모델의 답을 장면 사양 문서 셋으로 옮긴다. 편 이름, 장면 id, 형식, 길이, 제품은 모델이 아니라 여기서 정한다."""
    scenes = draft.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("답에 scenes 가 없다")
    roles = format_spec["scene_roles"]
    docs = []
    for n, scene in enumerate(scenes[:len(roles)], 1):
        beats = []
        for beat in scene.get("beats") or []:
            item = {k: beat.get(k) for k in ("start_s", "end_s", "visual_ko", "visual_en", "camera_en",
                                             "narration_ko", "caption_ko") if beat.get(k) not in (None, "")}
            if beat.get("evidence"):
                item["evidence"] = [e for e in beat["evidence"] if isinstance(e, str)]
            beats.append(item)
        docs.append({
            "scene_id": f"{episode}_s{n:02d}", "episode_id": episode, "format": fmt, "role": roles[n - 1],
            "duration_s": 15, "products": list(product_ids), "setting_en": str(scene.get("setting_en", "")).strip(),
            "beats": beats, "audio_en": str(scene.get("audio_en", "")).strip(),
        })
    return docs


def check_scenes(docs: list[dict[str, Any]], *, products: list[Product], production_spec: dict[str, Any]) -> list[str]:
    """장면 초안을 3장의 검사와 같은 기준으로 본다. 확인할 것의 목록을 돌려준다. 막지 않는다."""
    issues: list[str] = []
    scenes: list[SceneSpec] = []
    for n, doc in enumerate(docs, 1):
        try:
            scenes.append(SceneSpec.model_validate(doc))
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(x) for x in first.get("loc", ()))
            issues.append(f"장면 {n}: 사양에 맞지 않는다 — {where} {first.get('msg', '')}".rstrip())
    if len(scenes) != len(docs):
        return issues
    issues += [f"형식·길이: {p}" for p in check_episode(scenes, production_spec)]
    issues += [f"문법:{note}" for note in check_grammar(scenes, production_spec)]
    fact_ids = {f.id for p in products for f in p.facts}
    guard = ClaimsGuard()
    for n, scene in enumerate(scenes, 1):
        for v in guard.check_scene(scene):
            issues.append(f"장면 {n}: 표현 사전에 걸리는 말 “{v.term}” ({v.where.split('.', 1)[-1]})")
        for i, beat in enumerate(scene.beats, 1):
            unknown = [e for e in beat.evidence if e not in fact_ids]
            if unknown:
                issues.append(f"장면 {n} 구간 {i}: 제품 바이블에 없는 사실 id {', '.join(unknown)}")
            if not beat.visual_en:
                issues.append(f"장면 {n} 구간 {i}: 화면(영어)이 비어 있다")
            spoken = " ".join(x for x in (beat.narration_ko, beat.caption_ko) if x)
            for p in products:
                for d in find_dont_say(p, spoken):
                    issues.append(f"장면 {n} 구간 {i}: {p.name_ko}에 쓰지 않기로 한 표현 “{d.text_ko}”")
            known = {x for p in products for f in p.facts if f.id in beat.evidence for x in _numbers(f.text_ko)}
            extra = sorted(_numbers(spoken) - known)
            if extra:
                issues.append(f"장면 {n} 구간 {i}: 근거로 단 사실에 없는 숫자 {', '.join(extra)}")
    return issues
