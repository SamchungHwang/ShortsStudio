"""2장: 환경 점검, 프롬프트 한 줄 생성, 해상도·화면비, URI 수신."""
import base64
import json
from types import SimpleNamespace

import pytest

from ass import cli, doctor
from ass.guards.cost_guard import UnknownPrice
from ass.production import omni_client


@pytest.fixture(autouse=True)
def _tmp_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cli, "_setup", lambda: None)
    monkeypatch.delenv("ASS_RUN_BUDGET_USD", raising=False)
    return tmp_path


def test_doctor_reports_missing_key_without_leaking_values():
    checks = doctor.run_checks(env={"CONDA_DEFAULT_ENV": "base"})
    by = {c.name: c for c in checks}
    assert by["GEMINI_API_KEY"].status == "fail"
    assert by["Anaconda 환경"].status == "warn" and "conda activate ass" in by["Anaconda 환경"].fix
    checks = doctor.run_checks(env={"CONDA_DEFAULT_ENV": "ass", "GEMINI_API_KEY": "SECRET-VALUE-123"})
    by = {c.name: c for c in checks}
    assert by["GEMINI_API_KEY"].status == "ok" and by["Anaconda 환경"].status == "ok"
    text = doctor.render_text(checks) + doctor.render_markdown(checks)
    assert "SECRET-VALUE-123" not in text and "설정됨" in text


def test_prompt_render_dry_run_with_name(tmp_path, capsys):
    rc = cli.main(["render", "--prompt", "A frosted glass dropper bottle on a white counter.",
                   "--duration", "5", "--name", "first_render", "--dry-run"])
    assert rc == 0
    record = json.loads((tmp_path / "renders" / "adhoc" / "first_render.api_run.json").read_text(encoding="utf-8"))
    assert record["estimated_cost_usd"] == 0.35
    assert record["request"]["response_format"] == {
        "type": "video", "aspect_ratio": "9:16", "resolution": "720p", "duration": "5s"}
    assert "추정 $0.35" in capsys.readouterr().out


def test_prompt_render_needs_duration_and_passes_claims_guard(capsys):
    with pytest.raises(SystemExit, match="--duration"):
        cli.main(["render", "--prompt", "A bottle.", "--dry-run"])
    assert cli.main(["render", "--prompt", "The best serum that cures dryness.", "--duration", "5", "--dry-run"]) == 4
    assert "[막힘] 제품 표현 가드 위반" in capsys.readouterr().out


def test_aspect_can_be_changed_but_unverified_resolution_price_blocks():
    assert cli.main(["render", "--scene", "1", "--aspect", "16:9", "--dry-run"]) == 0
    with pytest.raises(UnknownPrice):
        cli.main(["render", "--scene", "1", "--resolution", "360p", "--dry-run"])


def test_uri_delivery_request_and_download(tmp_path, monkeypatch):
    req = omni_client.build_request("A cat.", model="m", duration_s=3, resolution="1080p", delivery="uri")
    assert req["response_format"]["delivery"] == "uri"
    assert omni_client._file_name("https://x/v1beta/files/abc123:download?alt=media") == "abc123"

    states = iter(["PROCESSING", "ACTIVE"])
    calls = {}

    class Files:
        def get(self, name):
            calls["name"] = name
            return SimpleNamespace(state=next(states))

        def download(self, file, destination):
            calls["file"] = file
            open(destination, "wb").write(b"video-bytes")

    client = SimpleNamespace(
        files=Files(),
        interactions=SimpleNamespace(create=lambda **k: SimpleNamespace(
            id="int_9", output_video=SimpleNamespace(data=None, uri="https://x/v1beta/files/abc123"))))
    monkeypatch.setattr(omni_client.time, "sleep", lambda s: None)
    result = omni_client.generate(req, tmp_path / "v.mp4", client=client)
    assert (tmp_path / "v.mp4").read_bytes() == b"video-bytes"
    assert calls == {"name": "files/abc123", "file": "https://x/v1beta/files/abc123"}
    assert result.bytes_written == 11


def test_inline_still_works_and_is_default(tmp_path):
    client = SimpleNamespace(interactions=SimpleNamespace(create=lambda **k: SimpleNamespace(
        id="int_1", output_video=SimpleNamespace(data=base64.b64encode(b"abc").decode(), uri=None))))
    req = omni_client.build_request("A cat.", model="m", duration_s=3)
    assert "delivery" not in req["response_format"]
    assert omni_client.generate(req, tmp_path / "a.mp4", client=client).bytes_written == 3


def test_default_client_is_created_on_v1beta(monkeypatch):
    """E00(2026-11-19): 버전을 정하지 않으면 404 Model not found 가 났다."""
    import sys
    import types

    made = {}
    genai = types.SimpleNamespace(Client=lambda **kwargs: made.update(kwargs) or "client")
    monkeypatch.setitem(sys.modules, "google", types.SimpleNamespace(genai=genai))
    assert omni_client.make_client() == "client"
    assert made == {"http_options": {"api_version": "v1beta"}}


def test_known_errors_get_a_one_line_fix():
    depleted = RuntimeError("Error code: 402 - [{'error': {'code': 402, 'message': "
                            "'Your prepayment credits are depleted. Please go to AI Studio', 'status': 'RESOURCE_EXHAUSTED'}}]")
    assert "Buy credits" in omni_client.explain_error(depleted)
    not_found = RuntimeError("Error code: 404 - Model 'gemini-omni-1.2-flash' not found. If this model or "
                             "capability is only available in v1beta, set the API version to 'v1beta'")
    assert "api_version" in omni_client.explain_error(not_found)
    assert omni_client.explain_error(RuntimeError("something new")) is None


def test_failed_render_records_error_and_hint(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    def boom(request, output_path, **kwargs):
        raise RuntimeError("Error code: 402 - Your prepayment credits are depleted.")

    monkeypatch.setattr(omni_client, "generate", boom)
    rc = cli.main(["render", "--prompt", "A bottle on a counter.", "--duration", "5", "--name", "t"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "실패: RuntimeError: Error code: 402" in out and "조치: 선불 크레딧이 바닥났다" in out
    record = json.loads((tmp_path / "renders" / "adhoc" / "t.api_run.json").read_text(encoding="utf-8"))
    assert record["status"] == "error" and "api_version=v1beta" in record["notes"]
