"""7장: 생성 모드, 레퍼런스 배분, 타사 제품 승인, 일관성 점검표. 모델은 부르지 않는다."""
from __future__ import annotations

import json
import shutil

import pytest

from ass import cli
from ass.policy import load_policy
from ass.production import consistency, gen_mode, omni_client
from ass.production import reference_sheet as rs
from ass.production.product_bible import load_product_bible
from ass.settings import SAMPLE_DIR

POLICY = load_policy("generation_modes").data
RECIPE = load_policy("reference_sheet").data


@pytest.fixture
def bible():
    return load_product_bible(SAMPLE_DIR / "product_bible.yaml")


def put_reference(project, product_id, views=("front", "three_quarter", "side", "label", "in_hand")):
    """사람이 레퍼런스를 고른 뒤의 모습을 만든다."""
    folder = rs.reference_dir(product_id, RECIPE, project)
    folder.mkdir(parents=True, exist_ok=True)
    images = []
    for view in views:
        (folder / f"{view}.jpg").write_bytes(f"{product_id}-{view}".encode())
        images.append({"view": view, "file": f"reference/{view}.jpg"})
    rs.manifest_path(product_id, RECIPE, project).write_text(json.dumps({"images": images}), encoding="utf-8")


def test_글만_모드는_프롬프트를_건드리지_않는다():
    plan = gen_mode.plan("text", "A bottle.", POLICY)
    assert plan.prompt == "A bottle." and plan.images == [] and plan.task is None
    with pytest.raises(gen_mode.ModeError):
        gen_mode.plan("text", "A bottle.", POLICY, first_frame="x.jpg")
    with pytest.raises(gen_mode.ModeError):
        gen_mode.plan("morph", "A bottle.", POLICY)


def test_제품_하나면_정면_비스듬히_라벨_석_장을_보낸다(bible, tmp_path):
    serum = bible.get("moalab_aqua_serum")
    with pytest.raises(gen_mode.ModeError, match="레퍼런스를 아직 고르지 않았다"):
        gen_mode.plan("reference", "P", POLICY, products=[serum], sheet_recipe=RECIPE, project_dir=tmp_path)
    put_reference(tmp_path, serum.id)
    plan = gen_mode.plan("reference", "P", POLICY, products=[serum], sheet_recipe=RECIPE, project_dir=tmp_path)
    assert [(i.tag, i.view) for i in plan.images] == [("<IMAGE_REF_0>", "front"), ("<IMAGE_REF_1>", "three_quarter"),
                                                       ("<IMAGE_REF_2>", "label")]
    lines = plan.prompt.split("\n")
    assert lines[0] == "[# References <IMAGE_REF_0>@Image1 <IMAGE_REF_1>@Image2 <IMAGE_REF_2>@Image3]"   # 태그는 0부터, 표지는 1부터
    assert "show MOALAB Aqua Serum (front, three quarter, label)" in lines[1] and "Do not redesign" in lines[1]
    assert lines[2] == "P"
    text = gen_mode.plan("text", "P", POLICY)
    assert plan.prompt_sha256 != text.prompt_sha256                # 모드가 다르면 다른 요청이다. 가져오기가 섞지 않는다
    (rs.reference_dir(serum.id, RECIPE, tmp_path) / "label.jpg").write_bytes(b"new label")
    again = gen_mode.plan("reference", "P", POLICY, products=[serum], sheet_recipe=RECIPE, project_dir=tmp_path)
    assert again.prompt == plan.prompt and again.prompt_sha256 != plan.prompt_sha256    # 레퍼런스를 바꾸면 다른 요청이다


def test_제품이_둘이면_제품마다_두_장씩_보내고_상한을_지킨다(bible, tmp_path):
    products = [bible.get("moalab_gel_sunscreen"), bible.get("haruon_cream_sunscreen")]
    for p in products:
        put_reference(tmp_path, p.id)
    plan = gen_mode.plan("reference", "P", POLICY, products=products, sheet_recipe=RECIPE, project_dir=tmp_path)
    assert [(i.product_id, i.view) for i in plan.images] == [
        ("moalab_gel_sunscreen", "front"), ("moalab_gel_sunscreen", "label"),
        ("haruon_cream_sunscreen", "front"), ("haruon_cream_sunscreen", "label")]
    assert "<IMAGE_REF_2> <IMAGE_REF_3> show HARUON Cream Sunscreen" in plan.prompt
    with pytest.raises(gen_mode.ModeError, match="6장까지"):
        gen_mode.plan("reference", "P", POLICY, products=products, sheet_recipe=RECIPE, project_dir=tmp_path,
                      views=["front", "three_quarter", "side", "label"])
    with pytest.raises(gen_mode.ModeError, match="없는 방향"):
        gen_mode.plan("reference", "P", POLICY, products=products, sheet_recipe=RECIPE, project_dir=tmp_path, views=["top"])
    with pytest.raises(gen_mode.ModeError, match="제품이 없다"):
        gen_mode.plan("reference", "P", POLICY, products=[], sheet_recipe=RECIPE, project_dir=tmp_path)


def test_첫_프레임과_끝_프레임은_선언과_태그로_알린다(tmp_path):
    first, last = tmp_path / "a.jpg", tmp_path / "b.jpg"
    first.write_bytes(b"a")
    last.write_bytes(b"b")
    one = gen_mode.plan("image", "The cap opens.", POLICY, first_frame=first)
    assert one.prompt == "[# Sources <FIRST_FRAME>@Image1]\n<FIRST_FRAME> The cap opens."
    two = gen_mode.plan("frames", "The cap opens.", POLICY, first_frame=first, last_frame=last)
    assert two.prompt == "[# Sources <FIRST_FRAME>@Image1 <LAST_FRAME>@Image2]\n<FIRST_FRAME> <LAST_FRAME> The cap opens."
    for bad in (dict(mode="image"), dict(mode="frames", first_frame=first), dict(mode="image", first_frame=first, last_frame=last)):
        with pytest.raises(gen_mode.ModeError):
            gen_mode.plan(bad.pop("mode"), "x", POLICY, **bad)


def test_task_는_설정을_켰을_때만_요청에_들어간다(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"a")
    request = omni_client.build_request("p", model="m", duration_s=5, image_paths=[image])
    assert "generation_config" not in request and [i["type"] for i in request["input"]] == ["image", "text"]
    request = omni_client.build_request("p", model="m", duration_s=5, task="reference_to_video")
    assert request["generation_config"] == {"video_config": {"task": "reference_to_video"}}
    assert gen_mode.plan("image", "x", {**POLICY, "send_task": True}, first_frame=image).task == "image_to_video"


# ---------------------------------------------------------------- 명령
@pytest.fixture
def project(tmp_path, monkeypatch):
    work = tmp_path / "example"
    shutil.copytree(SAMPLE_DIR, work)
    monkeypatch.setattr(cli, "EXAMPLE_DIR", work)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(omni_client, "generate", lambda *a, **k: pytest.fail("호출하면 안 된다"))
    return work, tmp_path / "outputs"


def last_record(out, episode):
    return json.loads(sorted((out / "renders" / episode).glob("*.api_run.json"))[-1].read_text(encoding="utf-8"))


def test_레퍼런스_모드의_요청만_확인(project, capsys):
    work, out = project
    assert cli.main(["render", "--episode", "product_intro", "--scene", "2", "--mode", "reference", "--dry-run"]) == 2
    assert "레퍼런스를 아직 고르지 않았다" in capsys.readouterr().out
    put_reference(work, "moalab_aqua_serum")
    assert cli.main(["render", "--episode", "product_intro", "--scene", "2", "--mode", "reference", "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "모드 reference(제품 레퍼런스)" in printed and "<IMAGE_REF_2> ← label.jpg (moalab_aqua_serum · label)" in printed
    assert "이미지가 따로 청구되는지는 확인하지 못했다" in printed
    record = last_record(out, "product_intro")
    assert record["mode"] == "reference" and [i["view"] for i in record["inputs"]] == ["front", "three_quarter", "label"]
    assert "data" not in json.dumps(record["request"])                # 이미지 본문은 기록에 남기지 않는다
    assert cli.main(["render", "--episode", "product_intro", "--scene", "2", "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "모드" not in printed.splitlines()[0]                       # 글만 모드의 출력은 4장과 같다
    assert last_record(out, "product_intro")["mode"] == "text"


def test_제품이_없는_편은_레퍼런스_모드로_생성하지_않는다(project, capsys):
    assert cli.main(["render", "--episode", "watering_plants", "--scene", "1", "--mode", "reference", "--dry-run"]) == 2
    assert "제품이 없다" in capsys.readouterr().out
    assert cli.main(["render", "--episode", "watering_plants", "--scene", "1", "--dry-run"]) == 0


def test_타사_제품이_나오는_장면은_승인한_사람의_이름이_있어야_생성한다(project, monkeypatch, capsys):
    work, out = project
    assert cli.main(["render", "--episode", "sunscreen_compare", "--scene", "2", "--dry-run"]) == 0     # 요청만 확인은 된다
    assert cli.main(["render", "--episode", "sunscreen_compare", "--scene", "2"]) == 3
    assert "--approved-by" in capsys.readouterr().out
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_setup", lambda: None)   # .env 를 읽지 않게. 읽으면 PC 의 키가 다시 들어온다
    assert cli.main(["render", "--episode", "sunscreen_compare", "--scene", "2", "--approved-by", "황삼청"]) == 2   # 승인은 지났고 키에서 멈춘다
    assert "승인: 황삼청" in capsys.readouterr().out


# ---------------------------------------------------------------- 일관성 점검
def fake_render(out, episode, scene_id, run_id, mode="text", status="ok", inputs=0):
    folder = out / "renders" / episode
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{scene_id}.{run_id}.mp4").write_bytes(b"v")
    (folder / f"{scene_id}.{run_id}.api_run.json").write_text(json.dumps({
        "run_id": run_id, "scene_id": scene_id, "status": status, "mode": mode, "inputs": [{}] * inputs,
        "elapsed_s": 61.0, "estimated_cost_usd": 1.05, "attempts": 1,
        "request": {"response_format": {"duration": "15s"}}}), encoding="utf-8")


def test_점검은_장면과_모드마다_가장_최근_성공한_것을_모은다(tmp_path):
    fake_render(tmp_path, "e", "s01", "20261121-1", "text")
    fake_render(tmp_path, "e", "s01", "20261126-1", "text")
    fake_render(tmp_path, "e", "s01", "20261126-2", "reference", inputs=3)
    fake_render(tmp_path, "e", "s02", "20261126-3", "text", status="error")
    rows = consistency.collect(tmp_path / "renders" / "e")
    assert [(r.scene_id, r.mode, r.run_id, r.images) for r in rows] == [("s01", "reference", "20261126-2", 3),
                                                                         ("s01", "text", "20261126-1", 0)]
    assert len(consistency.collect(tmp_path / "renders" / "e", latest_only=False)) == 3


def test_점검표는_사람이_적을_칸을_비워_둔다(project, monkeypatch, capsys):
    work, out = project
    monkeypatch.setattr(consistency, "extract_stills", lambda row, folder, fractions: [])     # FFmpeg 없이
    assert cli.main(["consistency", "--episode", "product_intro"]) == 2
    fake_render(out, "product_intro", "serum_s02", "20261126-1", "reference", inputs=3)
    assert cli.main(["consistency", "--episode", "product_intro"]) == 0
    folder = out / "consistency" / "product_intro"
    rows = (folder / "mode_experiment.csv").read_text(encoding="utf-8-sig").splitlines()
    assert rows[0].endswith("video,shape,color,label,note") and rows[1].startswith("serum_s02,reference,20261126-1,3,61.0,1.05,1,")
    report = (folder / "consistency_report.md").read_text(encoding="utf-8")
    assert "| serum_s02 | reference | 20261126-1 |" in report and "**라벨**" in report and "판정" not in report.split("## 보는 것")[1]
    (folder / "consistency_report.md").write_text("사람이 적었다", encoding="utf-8")
    assert cli.main(["consistency", "--episode", "product_intro"]) == 0
    assert (folder / "consistency_report.md").read_text(encoding="utf-8") == "사람이 적었다"   # 덮어쓰지 않는다
    assert len(list(folder.glob("consistency_report.*.md"))) == 1


def test_콘솔의_생성_실행에_모드와_승인이_붙는다():
    from ass import console_model as m

    assert m.build_runs("render", "product_intro", scene="2", dry_run=False, mode="reference") == [
        ["render", "--episode", "product_intro", "--scene", "2", "--mode", "reference"]]
    assert m.build_runs("render", "product_intro", scene="2", dry_run=False) == [
        ["render", "--episode", "product_intro", "--scene", "2"]]
    runs = m.build_runs("render", "sunscreen_compare", scene="2", dry_run=False, approved_by="황삼청")
    assert runs == [["render", "--episode", "sunscreen_compare", "--scene", "2", "--approved-by", "황삼청"]]
    assert m.mode_of(m.MODE_LABELS["reference"]) == "reference" and m.mode_of("?") == "text"
