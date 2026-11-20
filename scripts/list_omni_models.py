"""내 API 키로 보이는 영상 모델을 확인한다. 비용 없음.

    conda activate ass
    python scripts/list_omni_models.py

"Model not found" 가 날 때 먼저 실행한다. v1 과 v1beta 양쪽에서 이름에 omni 가 들어간 모델을 찾는다.
"""
import os
from importlib import metadata

from google import genai

if not os.environ.get("GEMINI_API_KEY"):
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
if not os.environ.get("GEMINI_API_KEY"):
    raise SystemExit("GEMINI_API_KEY 가 없다. ass doctor 로 확인한다.")

print(f"google-genai {metadata.version('google-genai')}")
for version in ("v1", "v1beta"):
    try:
        client = genai.Client(http_options={"api_version": version})
        names = sorted(m.name for m in client.models.list())
    except Exception as exc:  # 버전별로 어떤 오류가 나는지도 정보다
        print(f"[{version}] 목록을 받지 못했다: {type(exc).__name__}: {exc}")
        continue
    omni = [n for n in names if "omni" in n.lower()]
    print(f"[{version}] 모델 {len(names)}개, omni {len(omni)}개: {', '.join(omni) or '없음'}")
