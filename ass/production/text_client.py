"""text_client — 글 모델(Gemini)을 Interactions API 로 부른다 (6장).

    interaction = client.interactions.create(
        model="gemini-3.8-flash",
        input="…",
        system_instruction="…",
        generation_config={"temperature": 0.2},
    )
    interaction.output_text

공식 문서(Interactions API 안내)에서 확인한 것: model, input, system_instruction, generation_config, output_text.
확인하지 못한 것: JSON 스키마를 강제하는 설정값의 이름. 그래서 JSON 을 지시문으로 요청하고, 받은 글을 직접 읽어
pydantic 으로 검사한다.
실제 응답으로 확인한 것(2026-11-24): 사용 토큰 수는 interaction.usage 에 온다. total_input_tokens,
total_output_tokens, total_thought_tokens, total_tokens. 사고 토큰은 출력 토큰과 따로 센다.
"""
from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel


class TextResult(BaseModel):
    text: str
    interaction_id: str | None = None
    elapsed_s: float
    usage: dict[str, Any] | None = None       # 응답의 usage 그대로


class DraftParseError(ValueError):
    """모델이 돌려준 글에서 JSON 을 읽지 못했다."""


def build_request(prompt: str, *, model: str, system_instruction: str | None = None,
                  temperature: float | None = None) -> dict[str, Any]:
    if not model:
        raise ValueError("글 모델의 ID 가 없다. configs/models.yaml 의 text.id 를 확인한다")
    request: dict[str, Any] = {"model": model, "input": prompt}
    if system_instruction:
        request["system_instruction"] = system_instruction.strip()
    if temperature is not None:
        request["generation_config"] = {"temperature": float(temperature)}
    return request


def generate(request: dict[str, Any], *, client: Any | None = None) -> TextResult:
    """한 번 부르고 글을 돌려준다. 다시 시도하지 않는다. 다시 시도는 부르는 쪽(retry)이 한다."""
    if client is None:
        from ass.production.omni_client import make_client

        client = make_client()
    started = time.monotonic()
    interaction = client.interactions.create(**request)
    elapsed = round(time.monotonic() - started, 2)
    text = getattr(interaction, "output_text", None)
    if not text:
        raise RuntimeError("응답에 글이 없다 (output_text 가 비어 있다)")
    usage = getattr(interaction, "usage", None)
    if usage is not None and not isinstance(usage, dict):
        dump = getattr(usage, "model_dump", None)
        usage = dump() if callable(dump) else {"raw": str(usage)}
    return TextResult(text=str(text), interaction_id=getattr(interaction, "id", None), elapsed_s=elapsed, usage=usage)


def parse_json(text: str) -> dict[str, Any]:
    """모델의 답에서 JSON 객체 하나를 읽는다. 앞뒤에 붙은 설명이나 ``` 울타리는 버린다."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise DraftParseError("답에 JSON 이 없다")
    try:
        doc = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise DraftParseError(f"JSON 으로 읽지 못했다: {exc.msg} (줄 {exc.lineno})") from None
    if not isinstance(doc, dict):
        raise DraftParseError("답이 JSON 객체가 아니다")
    return doc


def token_counts(usage: dict[str, Any] | None) -> dict[str, int] | None:
    """usage 에서 입력, 출력, 사고 토큰 수를 꺼낸다. 필드가 없으면 None."""
    if not usage or "total_input_tokens" not in usage or "total_output_tokens" not in usage:
        return None
    return {"input": int(usage["total_input_tokens"]), "output": int(usage["total_output_tokens"]),
            "thought": int(usage.get("total_thought_tokens") or 0)}
