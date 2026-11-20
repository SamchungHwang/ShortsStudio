"""2.3절: ASS 를 거치지 않고 SDK 만으로 하는 첫 호출. 5초, 720p 기준 추정 $0.35.

    conda activate ass
    python scripts/ch02_first_call.py

GEMINI_API_KEY 환경 변수가 필요하다. 같은 일을 가드와 실행 기록을 붙여서 하는 것이
    ass render --prompt "..." --duration 5 --name first_call
이다. 이 파일은 그 안에서 무슨 일이 일어나는지 보여 주기 위한 것이다.
"""
import base64
import os
from pathlib import Path

from google import genai

PROMPT = (
    "A frosted glass dropper bottle with a white cap and a pale blue label stands on a bright white "
    "bathroom counter by a window. Soft afternoon daylight. The camera slowly pushes in. "
    "Quiet room tone. No speech, no music, no added text."
)

if not os.environ.get("GEMINI_API_KEY"):
    raise SystemExit("GEMINI_API_KEY 가 없다. ass doctor 로 확인한다.")

# GEMINI_API_KEY 환경 변수를 읽는다. API 버전을 v1beta 로 정한다.
# 정하지 않으면 "404 Model 'gemini-omni-1.2-flash' not found" 가 난다 (2026-11-19 실제 호출).
client = genai.Client(http_options={"api_version": "v1beta"})
# 선불 크레딧이 0 이면 여기서 "402 ... Your prepayment credits are depleted" 가 난다.
# AI Studio 의 Billing 화면에서 충전한 뒤 다시 실행한다.
interaction = client.interactions.create(
    model="gemini-omni-1.2-flash",
    input=PROMPT,
    response_format={
        "type": "video",
        "aspect_ratio": "9:16",              # 지정하지 않으면 16:9 다
        "resolution": "720p",
        "duration": "5s",                    # 길이 지정 방식은 실험 E00 에서 확정한다
    },
)

out = Path("outputs/renders/adhoc/first_call.mp4")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(base64.b64decode(interaction.output_video.data))
print(f"저장: {out}")
print(f"interaction id: {interaction.id}")
