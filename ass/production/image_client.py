"""Nano Banana 2.1 호출 (5.3절). 글과 레퍼런스 이미지를 보내 이미지 한 장을 받는다.

공식 문서(2026-11-21 확인)의 Interactions API 모양을 따른다.

    interaction = client.interactions.create(
        model="gemini-nano-banana-2.1",
        input=[{"type": "text", "text": ...}, {"type": "image", "data": <base64>, "mime_type": "image/png"}],
        response_format={"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "1:1", "image_size": "1K"},
    )
    base64.b64decode(interaction.output_image.data)

요청을 만드는 일(build_request)과 호출하는 일(generate)을 나눈다. 앞의 것은 SDK 없이 테스트한다.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ass.production.omni_client import DEFAULT_API_VERSION, make_client

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
IMAGE_SIZES = ("1K", "2K", "4K")


class ImageResult(BaseModel):
    image_path: str
    interaction_id: str | None
    model: str
    elapsed_s: float
    bytes_written: int
    usage: dict[str, Any] = {}


def build_request(prompt: str, *, model: str, image_paths: list[str | Path] | None = None,
                  aspect_ratio: str = "1:1", image_size: str = "1K", mime_type: str = "image/jpeg",
                  max_images: int = 14) -> dict[str, Any]:
    """interactions.create 에 넘길 인자를 만든다. 이미지는 base64 로 싣는다."""
    if image_size not in IMAGE_SIZES:
        raise ValueError(f"image_size 는 {', '.join(IMAGE_SIZES)} 가운데 하나다. 대문자 K 만 받는다: {image_size!r}")
    paths = [Path(p) for p in image_paths or []]
    if len(paths) > max_images:
        raise ValueError(f"레퍼런스 이미지는 {max_images}장까지다: {len(paths)}장")
    request: dict[str, Any] = {
        "model": model,
        "response_format": {"type": "image", "mime_type": mime_type,
                            "aspect_ratio": aspect_ratio, "image_size": image_size},
    }
    if not paths:
        request["input"] = prompt
        return request
    blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in paths:
        suffix = path.suffix.lower()
        if suffix not in MIME:
            raise ValueError(f"{path.name}: png, jpg, webp 만 보낸다")
        blocks.append({"type": "image", "mime_type": MIME[suffix],
                       "data": base64.b64encode(path.read_bytes()).decode("ascii")})
    request["input"] = blocks
    return request


def summarize_request(request: dict[str, Any], image_paths: list[str | Path] | None = None) -> dict[str, Any]:
    """실행 기록에 남길 요약. 이미지의 base64 는 빼고 파일 이름만 남긴다."""
    summary = {"model": request["model"], "response_format": request["response_format"]}
    if isinstance(request["input"], str):
        summary["input"] = request["input"]
    else:
        summary["input"] = request["input"][0]["text"]
        summary["images"] = [Path(p).name for p in image_paths or []]
    return summary


def _usage(interaction: Any) -> dict[str, Any]:
    """토큰 사용량이 있으면 꺼낸다. SDK 의 모양을 확인하지 못해 있는 것만 담는다."""
    usage = getattr(interaction, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        try:
            return {k: v for k, v in usage.model_dump().items() if v is not None}
        except Exception:
            return {}
    return dict(usage) if isinstance(usage, dict) else {}


def generate(request: dict[str, Any], output_path: str | Path, *, client: Any = None,
             api_version: str = DEFAULT_API_VERSION) -> ImageResult:
    """이미지 한 장을 생성해 파일로 쓴다. 비용이 든다."""
    client = client or make_client(api_version)
    started = time.monotonic()
    interaction = client.interactions.create(**request)
    image = getattr(interaction, "output_image", None)
    data = getattr(image, "data", None)
    if not data:
        raise RuntimeError("응답에 이미지가 없다. 프롬프트가 안전 정책에 걸렸거나 글만 돌아왔을 수 있다.")
    raw = base64.b64decode(data)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    return ImageResult(image_path=str(out), interaction_id=getattr(interaction, "id", None),
                       model=request["model"], elapsed_s=round(time.monotonic() - started, 1),
                       bytes_written=len(raw), usage=_usage(interaction))
