"""Gemini Omni Flash 호출 (2.3~2.4절, 9장).

Interactions API(client.interactions.create)로 영상을 생성하고, previous_interaction_id 로
같은 영상을 대화형으로 편집한다.

확인 상태 (2026-11-19):
- 공식 가이드(ai.google.dev/gemini-api/docs/omni, 예제는 1.1 기준)로 확인: interactions.create 호출 형태,
  response_format 의 type / aspect_ratio(기본 16:9) / resolution(기본 720p) / delivery("uri"),
  interaction.output_video.data(base64), 4MB 를 넘으면 delivery="uri" 와 Files API,
  previous_interaction_id 편집, 이미지 입력({"type": "image", "data", "mime_type"}) 뒤에 텍스트 항목.
- 공식 가이드에 없는 것: 길이를 정하는 설정값. 가이드의 response_format 에는 duration 이 없다.
  2차 자료는 response_format.duration 에 "15s" 같은 문자열을 넣는다고 적는다. 텍스트 항목의 키 이름("text")도
  2차 자료 기준이다. 실험 E00 에서 실제 호출로 확정한 뒤 이 주석을 고친다.
- URI 응답에서 파일 이름을 꺼내는 방식(_file_name)은 가이드의 설명을 따랐으나 실제 응답으로 확인하지 못했다.
- 실제 호출로 확인(E00, 2026-11-19): API 버전을 정하지 않고 만든 클라이언트로 호출하면
  "404 Model 'gemini-omni-1.2-flash' not found ... set the API version to 'v1beta'" 가 돌아온다.
  그래서 클라이언트를 v1beta 로 만든다(configs/models.yaml 의 video.api_version).
- 실제 호출로 확인(E00, 2026-11-19, google-genai 3.6.1): 모델 목록에서 gemini-omni-1.2-flash 는 v1beta 에만 있다
  (v1 에는 gemini-omni-flash-preview 하나). v1beta 로 부르면 모델은 찾는다.
- 선불 크레딧이 0 이면 "402 ... Your prepayment credits are depleted" 가 돌아온다(같은 날 2차 실행).
- 영상이 실제로 돌아오는 호출은 아직 확인하지 못했다. 요청 조립과 저장 흐름은 가짜 클라이언트로 테스트한다.
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
    delivery: str = "inline",
    task: str | None = None,
) -> dict[str, Any]:
    """interactions.create 에 넘길 인자를 만든다. 네트워크를 쓰지 않는다."""
    if not prompt.strip():
        raise ValueError("프롬프트가 비어 있다")
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution 은 {sorted(RESOLUTIONS)} 중 하나여야 한다: {resolution}")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"aspect_ratio 는 {sorted(ASPECT_RATIOS)} 중 하나여야 한다: {aspect_ratio}")
    if delivery not in {"inline", "uri"}:
        raise ValueError(f"delivery 는 inline 또는 uri 여야 한다: {delivery}")
    if resolution in {"1080p", "4k"} and delivery != "uri":
        raise ValueError(f"{resolution}: {INLINE_LIMIT_NOTE}.")

    response_format: dict[str, Any] = {
        "type": "video",
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    if delivery == "uri":
        response_format["delivery"] = "uri"
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
    if task:                    # 가이드: 프롬프트로 안 될 때만 쓴다. 기본은 보내지 않는다 (generation_modes.yaml 의 send_task)
        request["generation_config"] = {"video_config": {"task": task}}
    return request


def summarize_request(request: dict[str, Any]) -> dict[str, Any]:
    """실행 기록용. 이미지의 base64 본문을 빼고 남긴다."""
    summary = dict(request)
    if isinstance(request["input"], list):
        summary["input"] = [
            {k: v for k, v in item.items() if k != "data"} for item in request["input"]
        ]
    return summary


DEFAULT_API_VERSION = "v1beta"


def make_client(api_version: str = DEFAULT_API_VERSION) -> Any:
    """Gemini API 클라이언트. Omni 모델은 v1beta 에서만 찾아지므로 버전을 명시한다."""
    from google import genai  # 설치: pip install google-genai

    return genai.Client(http_options={"api_version": api_version})


def generate(request: dict[str, Any], output_path: str | Path, *, client: Any | None = None,
             api_version: str = DEFAULT_API_VERSION) -> OmniResult:
    """영상을 생성(또는 편집)해 mp4로 저장한다. GEMINI_API_KEY 환경 변수가 필요하다.

    store 의 기본값을 바꾸지 않는다. store=False 로 만든 영상은 이후 턴에서 편집할 수 없다.
    """
    if client is None:
        client = make_client(api_version)

    started = time.monotonic()
    interaction = client.interactions.create(**request)
    elapsed = round(time.monotonic() - started, 2)

    video = getattr(interaction, "output_video", None)
    data = getattr(video, "data", None) if video is not None else None
    uri = getattr(video, "uri", None) if video is not None else None
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if data:
        raw = base64.b64decode(data)
        out.write_bytes(raw)
        size = len(raw)
    elif uri:
        _download(client, uri, out)
        size = out.stat().st_size
    else:
        raise RuntimeError(
            f"응답에 output_video.data 도 uri 도 없다 (interaction id: {getattr(interaction, 'id', '?')}). "
            "안전 필터에 걸렸거나 응답 형식이 바뀌었을 수 있다."
        )
    elapsed = round(time.monotonic() - started, 2)

    return OmniResult(
        interaction_id=interaction.id,
        model=request["model"],
        video_path=str(out),
        bytes_written=size,
        elapsed_s=elapsed,
        request=summarize_request(request),
    )


def explain_error(exc: BaseException) -> str | None:
    """자주 만나는 오류에 한 줄 조치를 붙인다. 모르는 오류면 None."""
    text = str(exc)
    if "prepayment credits are depleted" in text or "Error code: 402" in text:
        return ("선불 크레딧이 바닥났다. AI Studio 의 Billing 화면(aistudio.google.com/billing)에서 "
                "[Buy credits] 로 충전한 뒤 다시 실행한다. 충전 직후에는 반영까지 잠시 걸릴 수 있다.")
    if "not found" in text and "v1beta" in text:
        return ("API 버전 문제다. configs/models.yaml 의 video.api_version 이 v1beta 인지 확인하고, "
                "python scripts/list_omni_models.py 로 내 키에 보이는 모델을 본다.")
    if "API key not valid" in text or "Error code: 401" in text or "Error code: 403" in text:
        return "API 키를 확인한다. ass doctor 로 키가 읽히는지 보고, AI Studio 에서 키가 살아 있는지 본다."
    if "Error code: 429" in text:
        return "요청 한도에 걸렸다. 잠시 뒤에 다시 실행한다. 반복되면 AI Studio 에서 한도를 확인한다."
    return None


def _file_name(uri: str) -> str:
    """.../v1beta/files/abc123:download?alt=media → abc123"""
    tail = uri.split("?")[0].rstrip("/").split("/")[-1]
    return tail.split(":")[0]


def _download(client: Any, uri: str, out: Path, *, poll_s: float = 5.0, timeout_s: float = 600.0) -> None:
    """delivery="uri" 결과를 받는다. 파일이 ACTIVE 가 될 때까지 기다렸다가 내려받는다."""
    name = f"files/{_file_name(uri)}"
    waited = 0.0
    while True:
        state = str(getattr(client.files.get(name=name), "state", "ACTIVE"))
        if "FAILED" in state:
            raise RuntimeError(f"영상 생성이 실패했다 ({name})")
        if "ACTIVE" in state:
            break
        if waited >= timeout_s:
            raise TimeoutError(f"{timeout_s:.0f}초를 기다렸지만 파일이 준비되지 않았다 ({name})")
        time.sleep(poll_s)
        waited += poll_s
    client.files.download(file=uri, destination=str(out))


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
