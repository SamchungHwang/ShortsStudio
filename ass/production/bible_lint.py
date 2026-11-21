"""제품 바이블 점검 (5.2절). 좋은 정의와 나쁜 정의를 가른다.

막는 것(error)과 알려 주는 것(note)을 나눈다. 막는 것이 있으면 `ass bible` 과 `ass sheet` 가 멈춘다.
규칙의 낱말 목록은 configs/bible_rules.yaml 에 있다. 이 점검은 형식을 본다. 사실이 참인지,
표현이 법에 맞는지는 판단하지 못한다.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from ass.production.claims_guard import ClaimsGuard
from ass.production.product_bible import Product, ProductBible, squeeze


class Finding(BaseModel):
    level: str          # error | note
    product_id: str
    where: str
    message: str


def lint_product(product: Product, rules: dict[str, Any], guard: ClaimsGuard) -> list[Finding]:
    found: list[Finding] = []

    def add(level: str, where: str, message: str) -> None:
        found.append(Finding(level=level, product_id=product.id, where=where, message=message))

    # --- 외형 서술: 눈에 보이는 것만
    ap = rules["appearance"]
    text = product.appearance_en.strip()
    words = text.split()
    low = text.lower()
    if len(words) < ap["min_words"]:
        add("error", "appearance_en", f"외형 서술이 너무 짧다({len(words)}낱말). 용기, 크기, 색, 뚜껑, 라벨을 적는다")
    if len(words) > ap["max_words"]:
        add("note", "appearance_en", f"외형 서술이 길다({len(words)}낱말). 장면 프롬프트마다 통째로 들어간다")
    banned = [w for w in ap["banned_en"] if re.search(rf"\b{re.escape(w)}\b", low)]
    if banned:
        add("error", "appearance_en", f"눈에 보이지 않는 것을 적었다: {', '.join(banned)}. 외형에는 모양과 색만 적는다")
    for violation in guard.find(text, "appearance_en"):
        add("error", "appearance_en", f"표현 사전에 걸리는 낱말: {violation.term}")
    if not any(re.search(rf"\b{re.escape(w)}\b", low) for w in ap["container_en"]):
        add("note", "appearance_en", "용기의 종류(bottle, tube, jar …)가 보이지 않는다")
    if not any(re.search(rf"\b{re.escape(w)}\b", low) for w in ap["color_en"]):
        add("note", "appearance_en", "색이 보이지 않는다")
    if not re.search(ap["size_pattern"], low):
        add("note", "appearance_en", "크기나 용량이 보이지 않는다. 없으면 장면마다 크기가 달라지기 쉽다")
    if product.label_text and product.label_text.lower() not in low:
        add("error", "label_text", f"라벨 글자 '{product.label_text}' 가 외형 서술에 없다")
    if not product.label_text:
        add("note", "label_text", "라벨 글자를 적지 않았다. 화면에서 무엇이 읽혀야 하는지 정해 둔다")
    if not product.appearance_ko:
        add("note", "appearance_ko", "우리말 외형 서술이 없다. 영어 서술이 맞는지 사람이 견줄 것이 없다")

    # --- 사실: 출처가 있는가
    fr = rules["fact"]
    seen: set[str] = set()
    for fact in product.facts:
        where = f"facts.{fact.id}"
        if fact.id in seen:
            add("error", where, "같은 id 의 사실이 두 번 있다")
        seen.add(fact.id)
        source = fact.source.strip()
        if not source:
            add("error", where, "출처가 없다. 출처 없는 문장은 사실이 아니라 주장이다")
        elif source in fr["placeholder_sources"]:
            add("note", where, f"출처가 예제용이다('{source}'). 내 제품에서는 실제 근거로 바꾼다")
        elif any(v in source for v in fr["vague_sources"]):
            add("error", where, f"출처가 막연하다('{source}'). 문서 이름이나 주소처럼 다시 찾을 수 있게 적는다")
        for violation in guard.find(fact.text_ko, where):
            add("error", where, f"사실 문장에 표현 사전에 걸리는 낱말이 있다: {violation.term}")
    if not product.facts:
        add("note", "facts", "사실이 하나도 없다. 이 제품에 대해서는 내레이션이 아무것도 말할 수 없다")

    # --- 써도 되는 표현과 쓰지 않는 표현
    for i, say in enumerate(product.say):
        where = f"say[{i}]"
        missing = [e for e in say.evidence if e not in seen]
        if missing:
            add("error", where, f"'{say.text_ko}' 의 근거 {missing} 가 facts 에 없다")
        if not say.evidence:
            add("error", where, f"'{say.text_ko}' 에 근거가 없다. 써도 되는 표현은 사실에서 나온다")
        for violation in guard.find(say.text_ko, where):
            add("error", where, f"써도 되는 표현에 표현 사전에 걸리는 낱말이 있다: {violation.term}")
        for dont in product.dont_say:
            if squeeze(dont.text_ko) and squeeze(dont.text_ko) in squeeze(say.text_ko):
                add("error", where, f"'{say.text_ko}' 가 쓰지 않는 표현 '{dont.text_ko}' 를 담고 있다")
    for i, dont in enumerate(product.dont_say):
        if not dont.reason.strip():
            add("error", f"dont_say[{i}]", f"'{dont.text_ko}' 를 쓰지 않는 이유가 없다")
    if not product.dont_say:
        add("note", "dont_say", "쓰지 않는 표현이 없다. 대본을 쓰기 전에 넘지 않을 선을 적어 둔다")
    if not product.is_own and product.say:
        add("note", "say", "타사 제품에 표현을 정해 두었다. 타사 제품은 사실만 말하고 평가하지 않는다")
    return found


def lint_bible(bible: ProductBible, rules: dict[str, Any], guard: ClaimsGuard | None = None) -> list[Finding]:
    guard = guard or ClaimsGuard()
    found: list[Finding] = []
    all_ids: dict[str, str] = {}
    for product in bible.products.values():
        found += lint_product(product, rules, guard)
        for fact in product.facts:
            if fact.id in all_ids and all_ids[fact.id] != product.id:
                found.append(Finding(level="error", product_id=product.id, where=f"facts.{fact.id}",
                                     message=f"다른 제품({all_ids[fact.id]})과 사실 id 가 겹친다"))
            all_ids.setdefault(fact.id, product.id)
    return found


def has_errors(findings: list[Finding], product_id: str | None = None) -> bool:
    return any(f.level == "error" and (product_id is None or f.product_id == product_id) for f in findings)
