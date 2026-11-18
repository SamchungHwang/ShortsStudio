import base64
from types import SimpleNamespace

import pytest

from ass.production import omni_client

MODEL = "gemini-omni-1.2-flash"


def test_text_to_video_request():
    req = omni_client.build_request("A cat.", model=MODEL, duration_s=15)
    assert req == {
        "model": MODEL,
        "input": "A cat.",
        "response_format": {"type": "video", "aspect_ratio": "9:16", "resolution": "720p", "duration": "15s"},
    }


@pytest.mark.parametrize("bad", [2, 16])
def test_duration_outside_3_to_15_is_rejected(bad):
    with pytest.raises(ValueError, match="3~15"):
        omni_client.build_request("A cat.", model=MODEL, duration_s=bad)


def test_edit_request_carries_previous_interaction_id():
    req = omni_client.build_request(
        "Make the mug red. Keep everything else the same.", model=MODEL, previous_interaction_id="int_1"
    )
    assert req["previous_interaction_id"] == "int_1"
    assert "duration" not in req["response_format"]


def test_reference_images_come_before_text_and_are_stripped_from_summary(tmp_path):
    img = tmp_path / "serum.png"
    img.write_bytes(b"\x89PNG fake")
    req = omni_client.build_request("The bottle rotates.", model=MODEL, duration_s=5, image_paths=[img])
    assert [i["type"] for i in req["input"]] == ["image", "text"]
    assert req["input"][0]["mime_type"] == "image/png"
    assert "data" not in omni_client.summarize_request(req)["input"][0]


def test_upscaled_resolutions_are_not_sent_inline():
    with pytest.raises(ValueError, match="delivery"):
        omni_client.build_request("A cat.", model=MODEL, resolution="1080p")


def test_generate_saves_video_with_fake_client(tmp_path):
    payload = b"fake-mp4-bytes"

    class FakeInteractions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                id="int_42", output_video=SimpleNamespace(data=base64.b64encode(payload).decode())
            )

    client = SimpleNamespace(interactions=FakeInteractions())
    req = omni_client.build_request("A cat.", model=MODEL, duration_s=3)
    result = omni_client.generate(req, tmp_path / "out" / "a.mp4", client=client)
    assert (tmp_path / "out" / "a.mp4").read_bytes() == payload
    assert result.interaction_id == "int_42"
    assert client.interactions.kwargs["model"] == MODEL


def test_generate_fails_loudly_when_no_video(tmp_path):
    client = SimpleNamespace(
        interactions=SimpleNamespace(create=lambda **k: SimpleNamespace(id="int_0", output_video=None))
    )
    req = omni_client.build_request("A cat.", model=MODEL, duration_s=3)
    with pytest.raises(RuntimeError, match="output_video"):
        omni_client.generate(req, tmp_path / "a.mp4", client=client)
