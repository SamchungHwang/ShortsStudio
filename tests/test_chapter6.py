"""6장: 소재 요약과 장면 사양의 초안. 글 모델은 가짜 응답으로 대신한다."""
from __future__ import annotations

import json

import pytest

from ass import authoring, cli
from ass.guards.cost_guard import UnknownPrice, estimate_text_cost
from ass.policy import load_policy
from ass.production import drafting, text_client
from ass.production.product_bible import load_product_bible
from ass.settings import SAMPLE_DIR

SOURCE = authoring.source_text(SAMPLE_DIR, "product_intro")


@pytest.fixture
def serum():
    return load_product_bible(SAMPLE_DIR / "product_bible.yaml").get("moalab_aqua_serum")


@pytest.fixture
def spec():
    return load_policy("production_spec").data


def good_brief():
    return {"title_ko": "오후에 당기는 피부, 수분 세럼 하나로",
            "promise_ko": "수분 세럼이 어떤 제형이고 어떻게 쓰는지 알려 준다",
            "key_points": [
                {"text_ko": "오후 세 시쯤 볼이 당기는 사람을 위한 제품이다", "quote": "오후 세 시쯤 볼이 당긴다", "evidence": []},
                {"text_ko": "묽은 젤 제형이고 향이 없다", "quote": "묽은 젤 제형이라 손에서 흘러내리지 않고, 향이 없다",
                 "evidence": ["serum_texture", "serum_fragrance"]},
                {"text_ko": "세안 후 두세 방울을 덜어 가볍게 두드린다", "quote": "세안 후 두세 방울을 손바닥에 덜어",
                 "evidence": ["serum_usage"]}]}


# ---------------------------------------------------------------- 글 모델 요청
def test_글_요청은_공식_문서의_모양이다():
    request = text_client.build_request("안녕", model="gemini-3.8-flash", system_instruction=" 지시 \n", temperature=0.2)
    assert request == {"model": "gemini-3.8-flash", "input": "안녕", "system_instruction": "지시",
                       "generation_config": {"temperature": 0.2}}
    assert text_client.build_request("안녕", model="m") == {"model": "m", "input": "안녕"}
    with pytest.raises(ValueError):
        text_client.build_request("안녕", model="")


def test_생성은_output_text_를_읽고_usage_가_있으면_남긴다():
    class Interactions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return type("I", (), {"id": "i-9", "output_text": '{"a": 1}', "usage": {"total_tokens": 12}})()

    client = type("C", (), {"interactions": Interactions()})()
    result = text_client.generate({"model": "m", "input": "x"}, client=client)
    assert result.text == '{"a": 1}' and result.interaction_id == "i-9" and result.usage == {"total_tokens": 12}
    assert client.interactions.kwargs == {"model": "m", "input": "x"}
    empty = type("C", (), {"interactions": type("X", (), {"create": lambda self, **k: type("I", (), {"output_text": ""})()})()})()
    with pytest.raises(RuntimeError):
        text_client.generate({"model": "m", "input": "x"}, client=empty)


def test_답에서_JSON_만_읽는다():
    assert text_client.parse_json('```json\n{"a": [1, 2]}\n```\n이상입니다.') == {"a": [1, 2]}
    for bad in ("JSON 이 없습니다", '{"a": 1', "[1, 2]"):
        with pytest.raises(text_client.DraftParseError):
            text_client.parse_json(bad)


def test_글_비용은_어림_상한이다():
    models = load_policy("models").data
    assert estimate_text_cost(2000, models, 4000) == round(2000 * 1.5 / 1e6 + 4000 * 7.5 / 1e6, 4)
    with pytest.raises(UnknownPrice):
        estimate_text_cost(10, {"text": {}})


# ---------------------------------------------------------------- 소재 요약 초안
def test_보내는_글에는_원문과_제품_사실과_쓰지_않는_표현이_들어간다(serum, spec):
    policy = load_policy("draft_policy").data
    prompt = drafting.brief_prompt(policy, source_type="own_blog", fmt="product_intro",
                                   format_spec=spec["formats"]["product_intro"], products=[serum], source_text=SOURCE)
    assert "사실 serum_texture: 묽은 젤 제형" in prompt and "쓰지 않는 표현: 24시간 촉촉" in prompt
    assert "오후 세 시쯤 볼이 당긴다" in prompt and "본인 블로그 글" in prompt and "문제 → 해결 → 사용법" in prompt
    with pytest.raises(ValueError):
        drafting.brief_prompt(policy, source_type="idea", fmt="info", format_spec=spec["formats"]["info"],
                              products=[], source_text="  ")
    with pytest.raises(ValueError):
        drafting.brief_prompt(policy, source_type="own_blog", fmt="info", format_spec=spec["formats"]["info"],
                              products=[], source_text="가" * 12001)


def test_원문에_있는_인용과_있는_사실만_단_초안은_걸리지_않는다(serum):
    assert drafting.check_brief(good_brief(), source_text=SOURCE, source_type="own_blog", products=[serum]) == []


def test_지어낸_것은_확인할_것으로_나온다(serum):
    draft = good_brief()
    draft["key_points"][0] = {"text_ko": "피부 수분이 48시간 유지된다", "quote": "수분이 48시간 유지된다", "evidence": []}
    draft["key_points"][1]["evidence"] = ["serum_ph"]
    draft["key_points"][2] = {"text_ko": "24시간 촉촉하게 지켜 준다", "quote": "", "evidence": []}
    issues = drafting.check_brief(draft, source_text=SOURCE, source_type="own_blog", products=[serum])
    text = "\n".join(issues)
    assert "요점 1: 인용이 원문에 없다" in text and "요점 1: 원문과 제품 사실에 없는 숫자 48" in text
    assert "요점 2: 제품 바이블에 없는 사실 id serum_ph" in text
    assert "요점 3: 원문의 인용도 제품 사실도 없다" in text
    assert "요점 3: 모아랩 수분 세럼에 쓰지 않기로 한 표현 “24시간 촉촉”" in text


def test_아이디어_한_줄에서_모델이_채운_요점은_출처를_달라고_한다():
    draft = {"title_ko": "스킨케어 바르는 순서", "promise_ko": "세 단계로 알려 준다",
             "key_points": [{"text_ko": "묽은 것부터 바른다", "quote": "", "evidence": []}]}
    issues = drafting.check_brief(draft, source_text="스킨케어 바르는 순서를 세 단계로", source_type="idea", products=[])
    assert issues == ["요점 1: 모델이 채운 내용이다. 출처를 확인해 근거에 적는다"]


def test_초안_문서의_소유_확인은_언제나_꺼져_있다():
    doc = drafting.brief_draft_doc(good_brief(), episode="product_intro", source_type="own_blog", fmt="product_intro",
                                   origin="https://example.com/a", product_ids=["moalab_aqua_serum"], issues=["x"],
                                   model="gemini-3.8-flash", created_at="2026-11-23T00:00:00")
    assert doc["owner_confirmed"] is False and doc["draft"] == {"by": "gemini-3.8-flash", "created_at": "2026-11-23T00:00:00", "check": ["x"]}
    assert doc["key_points"][0] == {"text_ko": "오후 세 시쯤 볼이 당기는 사람을 위한 제품이다", "quote": "오후 세 시쯤 볼이 당긴다"}


# ---------------------------------------------------------------- 장면 초안
def scene_answer():
    """견본의 세 장면을 모델의 답 모양으로 옮긴 것."""
    scenes = []
    for n in (1, 2, 3):
        doc = authoring.sample_scene("product_intro", n)
        scenes.append({"role": doc["role"], "setting_en": doc["setting_en"], "audio_en": doc.get("audio_en", ""),
                       "beats": doc["beats"], "scene_id": "모델이 적은 id 는 쓰지 않는다"})
    return {"scenes": scenes}


def test_장면_초안의_id_와_형식은_프로그램이_정한다(spec):
    docs = drafting.scene_docs(scene_answer(), episode="my_ep", fmt="product_intro",
                               format_spec=spec["formats"]["product_intro"], product_ids=["moalab_aqua_serum"])
    assert [d["scene_id"] for d in docs] == ["my_ep_s01", "my_ep_s02", "my_ep_s03"]
    assert [d["role"] for d in docs] == ["problem", "solution", "usage"] and docs[0]["duration_s"] == 15
    with pytest.raises(ValueError):
        drafting.scene_docs({}, episode="e", fmt="info", format_spec=spec["formats"]["info"], product_ids=[])


def test_견본과_같은_장면_초안은_걸리지_않는다(serum, spec):
    docs = drafting.scene_docs(scene_answer(), episode="product_intro", fmt="product_intro",
                               format_spec=spec["formats"]["product_intro"], product_ids=["moalab_aqua_serum"])
    assert drafting.check_scenes(docs, products=[serum], production_spec=spec) == []


def test_장면_초안의_틀린_곳은_확인할_것으로_나온다(serum, spec):
    answer = scene_answer()
    beat = answer["scenes"][1]["beats"][1]
    beat.update({"narration_ko": "바르면 24시간 촉촉하다.", "caption_ko": "이십사시간 내내 촉촉한 수분 세럼", "evidence": ["serum_ph"]})
    docs = drafting.scene_docs(answer, episode="product_intro", fmt="product_intro",
                               format_spec=spec["formats"]["product_intro"], product_ids=["moalab_aqua_serum"])
    text = "\n".join(drafting.check_scenes(docs, products=[serum], production_spec=spec))
    assert "장면 2 구간 2: 제품 바이블에 없는 사실 id serum_ph" in text
    assert "장면 2 구간 2: 모아랩 수분 세럼에 쓰지 않기로 한 표현 “24시간 촉촉”" in text
    assert "자막이 12자를 넘는다" in text and "근거로 단 사실에 없는 숫자 24" in text
    answer["scenes"][0]["beats"][0]["end_s"] = 4          # 구간 사이에 틈
    docs = drafting.scene_docs(answer, episode="product_intro", fmt="product_intro",
                               format_spec=spec["formats"]["product_intro"], product_ids=["moalab_aqua_serum"])
    assert any(x.startswith("장면 1: 사양에 맞지 않는다") for x in drafting.check_scenes(docs, products=[serum], production_spec=spec))


# ---------------------------------------------------------------- 명령
@pytest.fixture
def project(tmp_path, monkeypatch):
    """견본을 복사한 임시 프로젝트. 산출물과 초안이 저장소에 남지 않게 한다."""
    import shutil

    work = tmp_path / "example"
    shutil.copytree(SAMPLE_DIR, work)
    (work / "source_briefs" / "product_intro.yaml").write_text(
        (work / "source_briefs" / "aqua_serum_intro.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(cli, "EXAMPLE_DIR", work)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    return work, tmp_path / "outputs"


def fake_generate(answer):
    def generate(request, **kwargs):
        return text_client.TextResult(text=json.dumps(answer, ensure_ascii=False), interaction_id="i-1", elapsed_s=1.2,
                                      usage={"total_tokens": 900})
    return generate


def test_brief_는_소유_확인_없이는_보내지_않는다(project, capsys):
    assert cli.main(["brief", "--episode", "product_intro", "--type", "own_blog", "--origin", "x"]) == 2
    assert "쓸 권리가 있는 소재만 보낸다" in capsys.readouterr().out


def test_brief_요청만_확인은_호출하지_않고_기록만_남긴다(project, monkeypatch, capsys):
    work, out = project
    monkeypatch.setattr(text_client, "generate", lambda *a, **k: pytest.fail("호출하면 안 된다"))
    code = cli.main(["brief", "--episode", "product_intro", "--type", "own_blog", "--origin", "https://example.com/a",
                     "--products", "moalab_aqua_serum", "--owner-confirmed", "--dry-run"])
    printed = capsys.readouterr().out
    assert code == 0 and "[dry-run] 호출하지 않았다" in printed and "어림 상한 $" in printed
    record = json.loads(next((out / "drafts" / "product_intro").glob("brief.*.api_run.json")).read_text(encoding="utf-8"))
    assert record["status"] == "dry_run" and record["episode"] == "product_intro" and record["model"] == "gemini-3.8-flash"
    assert not (work / "drafts").exists()


def test_brief_는_초안을_따로_적고_저장본은_건드리지_않는다(project, monkeypatch, capsys):
    work, out = project
    saved = (work / "source_briefs" / "product_intro.yaml").read_text(encoding="utf-8")
    draft = good_brief()
    draft["key_points"][0]["quote"] = "피부가 사막처럼 마른다"
    monkeypatch.setattr(text_client, "generate", fake_generate(draft))
    code = cli.main(["brief", "--episode", "product_intro", "--type", "own_blog", "--origin", "https://example.com/a",
                     "--products", "moalab_aqua_serum", "--owner-confirmed"])
    printed = capsys.readouterr().out
    assert code == 0 and "확인할 것 1개" in printed and "요점 1: 인용이 원문에 없다" in printed
    assert "제목과 약속은 프로그램이 대조하지 않는 칸이다" in printed          # 대조하지 않는 칸은 늘 알린다
    doc = authoring.draft_brief_doc(work, "product_intro")
    assert doc["owner_confirmed"] is False and doc["draft"]["check"] == ["요점 1: 인용이 원문에 없다 — “피부가 사막처럼 마른다”"]
    assert (work / "source_briefs" / "product_intro.yaml").read_text(encoding="utf-8") == saved
    record = json.loads(next((out / "drafts" / "product_intro").glob("brief.*.api_run.json")).read_text(encoding="utf-8"))
    assert record["status"] == "ok" and record["attempts"] == 1 and "usage=" in record["notes"]


def test_답을_읽지_못하면_받은_글을_남기고_실패한다(project, monkeypatch, capsys):
    work, out = project
    monkeypatch.setattr(text_client, "generate", lambda request, **k: text_client.TextResult(text="죄송합니다", elapsed_s=0.5))
    assert cli.main(["brief", "--episode", "product_intro", "--idea", "수분 세럼 쓰는 법", "--owner-confirmed"]) == 1
    assert "모델의 답을 읽지 못했다" in capsys.readouterr().out
    assert next((out / "drafts" / "product_intro").glob("brief.*.answer.txt")).read_text(encoding="utf-8") == "죄송합니다"
    assert not (work / "drafts").exists()


def test_script_는_장면_초안_셋과_확인할_것을_적는다(project, monkeypatch, capsys):
    work, out = project
    before = sorted(p.read_text(encoding="utf-8") for p in (work / "episodes" / "product_intro").glob("*.yaml"))
    monkeypatch.setattr(text_client, "generate", fake_generate(scene_answer()))
    assert cli.main(["script", "--episode", "product_intro"]) == 0
    printed = capsys.readouterr().out
    assert "=== 장면 3 · usage ===" in printed and "프로그램이 찾은 것은 없다" in printed
    assert authoring.draft_scene_doc(work, "product_intro", 2)["scene_id"] == "product_intro_s02"
    assert authoring.draft_scene_check(work, "product_intro", 2) == []
    assert sorted(p.read_text(encoding="utf-8") for p in (work / "episodes" / "product_intro").glob("*.yaml")) == before


def test_script_는_소재_요약이_없으면_막는다(project, capsys):
    assert cli.main(["script", "--episode", "no_such"]) == 2
    assert "소재 요약이 없다" in capsys.readouterr().out


def test_콘솔의_초안_실행_인자():
    from ass import console_model as m

    data = {"owner_confirmed": True, "source_type": "own_blog", "format": "product_intro",
            "products": ["moalab_aqua_serum"], "origin": "https://example.com/a"}
    assert m.brief_runs("product_intro", data) == [[
        "brief", "--episode", "product_intro", "--type", "own_blog", "--format", "product_intro",
        "--products", "moalab_aqua_serum", "--origin", "https://example.com/a", "--owner-confirmed", "--dry-run"]]
    with pytest.raises(ValueError):
        m.brief_runs("product_intro", {**data, "owner_confirmed": False})
    assert m.script_runs("product_intro", dry_run=False) == [["script", "--episode", "product_intro"]]
    assert 0 < m.draft_cost(1000) < 0.1


# ---------------------------------------------------------------- 제품이 없는 편
def test_제품이_없는_견본_편도_검사와_컴파일을_지난다(spec):
    from ass.production.grammar import check_grammar
    from ass.production.scene_compiler import compile_scene
    from ass.production.scene_spec import check_episode, load_scene

    bible = load_product_bible(SAMPLE_DIR / "product_bible.yaml")
    scenes = [load_scene(p) for p in sorted((SAMPLE_DIR / "episodes" / "watering_plants").glob("scene_*.yaml"))]
    assert [s.role for s in scenes] == ["question", "methods", "wrap_up"] and all(not s.products for s in scenes)
    assert check_episode(scenes, spec) == [] and check_grammar(scenes, spec) == []
    prompt = compile_scene(scenes[1], bible, spec).prompt
    assert "Products" not in prompt and "product" not in prompt.lower()      # 제품 영상의 말투가 섞이지 않는다
    assert "Clean realistic everyday video" in prompt and "No human faces" in prompt


def test_형식이_따로_정하지_않으면_분위기와_제외_지시는_그대로다(spec):
    from ass.production.scene_compiler import compile_scene
    from ass.production.scene_spec import load_scene

    bible = load_product_bible(SAMPLE_DIR / "product_bible.yaml")
    scene = load_scene(SAMPLE_DIR / "episodes" / "product_intro" / "scene_02_solution.yaml")
    compiled = compile_scene(scene, bible, spec)
    assert "Clean realistic product video" in compiled.prompt and "(the product label itself stays)" in compiled.prompt
    # 4장에서 영상을 만든 프롬프트와 한 글자도 달라지지 않아야 가져오기(ass reuse)가 계속 맞는다
    assert compiled.prompt_sha256 == "b49ae43bf8bbc5ae2521708f6b5cf8007e5fab861cf325a1c1adcc3ae99f5a54"


def test_응답의_usage_에서_토큰을_꺼내_다시_어림한다():
    from ass.guards.cost_guard import estimate_token_cost

    usage = {"total_input_tokens": 691, "total_output_tokens": 247, "total_thought_tokens": 910, "total_tokens": 1848}
    tokens = text_client.token_counts(usage)             # 2026-11-24 첫 실제 호출의 값
    assert tokens == {"input": 691, "output": 247, "thought": 910}
    assert estimate_token_cost(tokens, load_policy("models").data) == 0.0097
    assert text_client.token_counts(None) is None and text_client.token_counts({"total_tokens": 12}) is None
