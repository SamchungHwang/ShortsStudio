"""Gemini Omni Flash 호출 (2.3~2.4절, 9장).

Interactions API(client.interactions.create)로 영상을 생성하고, previous_interaction_id 로
같은 영상을 대화형으로 편집한다.

확인 상태 (2026-11-17):
- 공식 문서(ai.google.dev/gemini-api/docs/omni)로 확인: interactions.create 호출 형태,
  response_format 의 type / aspect_ratio / resolution / delivery, interaction.output_video.data(base64),
  previous_interaction_id 편집, 이미지 입력({"type": "image", "data", "mime_type"}) 뒤에 텍스트 항목.
- 2차 자료로만 확인: response_format.duration 의 "15s" 문자열 형식, 텍스트 항목의 키 이름("text").
  실험 E00 에서 실제 호출로 확정한 뒤 이 주석을 고친다.
- 이 모듈은 아직 실제 API로 실행하지 않았다. 요청 조립(build_request)만 단위 테스트한다.
"""
from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

RESOLUTIONS = {"360p", "720p", "1080p", "4k"}
ASPECT_RATIOS = {"9:16", "16:9"}
MIN_DURATION_S = 3
MAX_DURATION_S = 15
INLINE_LIMIT_NOTE = "4MB를 넘는 결과(720p 초과)는 delivery='uri' 와 Files API가 필요하다"


class OmniResult(BaseModel):
    interaction_id: str
    model: str
    video_path: str
    bytes_written: int
    elapsed_s: float
    request: dict[str, Any]          # 이미지 데이터는 뺀 요청 요약


def build_request(
    prompt: str,
    *,
    model: str,
    duration_s: int | None = None,
    aspect_ratio: str = "9:16",
    resolution: str = "720p",
    image_paths: list[str | Path] | None = None,
    previous_interaction_id: str | None = None,
) -> dict[str, Any]:
    """interactions.create 에 넘길 인자를 만든다. 네트워크를 쓰지 않는다."""
    if not prompt.strip():
        raise ValueError("프롬프트가 비어 있다")
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution 은 {sorted(RESOLUTIONS)} 중 하나여야 한다: {resolution}")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"aspect_ratio 는 {sorted(ASPECT_RATIOS)} 중 하나여야 한다: {aspect_ratio}")
    if resolution in {"1080p", "4k"}:
        raise ValueError(f"{resolution}: {INLINE_LIMIT_NOTE}. 업스케일 경로는 8장에서 구현한다.")

    response_format: dict[str, Any] = {
        "type": "video",
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    if duration_s is not None:
        if not (MIN_DURATION_S <= duration_s <= MAX_DURATION_S):
            raise ValueError(f"duration_s 는 {MIN_DURATION_S}~{MAX_DURATION_S} 초여야 한다: {duration_s}")
        response_format["duration"] = f"{int(duration_s)}s"

    if image_paths:
        items: list[dict[str, Any]] = [_image_item(Path(p)) for p in image_paths]
        items.append({"type": "text", "text": prompt})
        input_value: str | list[dict[str, Any]] = items
    else:
        input_value = prompt

    request: dict[str, Any] = {
        "model": model,
        "input": input_value,
        "response_format": response_format,
    }
    if previous_interaction_id:
        request["previous_interaction_id"] = previous_interaction_id
    return request


def summarize_request(request: dict[str, Any]) -> dict[str, Any]:
    """실행 기록용. 이미지의 base64 본문을 빼고 남긴다."""
    summary = dict(request)
    if isinstance(request["input"], list):
        summary["input"] = [
            {k: v for k, v in item.items() if k != "data"} for item in request["input"]
        ]
    return summary


def generate(request: dict[str, Any], output_path: str | Path, *, client: Any | None = None) -> OmniResult:
    """영상을 생성(또는 편집)해 mp4로 저장한다. GEMINI_API_KEY 환경 변수가 필요하다.

    store 의 기본값을 바꾸지 않는다. store=False 로 만든 영상은 이후 턴에서 편집할 수 없다.
    """
    if client is None:
        from google import genai  # 설치: pip install google-genai

        client = genai.Client()

    started = time.monotonic()
    interaction = client.interactions.create(**request)
    elapsed = round(time.monotonic() - started, 2)

    video = getattr(interaction, "output_video", None)
    data = getattr(video, "data", None) if video is not None else None
    if not data:
        raise RuntimeError(
            f"응답에 output_video.data 가 없다 (interaction id: {getattr(interaction, 'id', '?')}). "
            "안전 필터에 걸렸거나 응답 형식이 바뀌었을 수 있다."
        )
    raw = base64.b64decode(data)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)

    return OmniResult(
        interaction_id=interaction.id,
        model=request["model"],
        video_path=str(out),
        bytes_written=len(raw),
        elapsed_s=elapsed,
        request=summarize_request(request),
    )


def _image_item(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"레퍼런스 이미지가 없다: {path}")
    mime, _ = mimetypes.guess_type(path.name)
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError(f"지원하지 않는 이미지 형식: {path.name}")
    return {
        "type": "image",
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        "mime_type": mime,
    }
