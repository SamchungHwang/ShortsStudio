"""5장: 제품 바이블 점검(ass bible), 레퍼런스 시트(ass sheet), 선택 기록."""
from __future__ import annotations

import base64
import json
import shutil
import struct
import zlib

import pytest

from ass import cli, ledger
from ass.guards.cost_guard import UnknownPrice, estimate_image_cost
from ass.policy import load_policy
from ass.production import bible_lint, image_client, reference_sheet
from ass.production.claims_guard import ClaimsGuard
from ass.production.product_bible import DontSay, Fact, Product, Say, find_dont_say, load_product_bible
from ass.production.scene_compiler import CompileError, compile_scene
from ass.settings import EXAMPLE_DIR

RULES = load_policy("bible_rules").data
RECIPE = load_policy("reference_sheet").data
MODELS = load_policy("models").data


def png(color=(200, 220, 240), size=8) -> bytes:
    """작은 단색 PNG. 가짜 생성 결과로 쓴다."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    row = b"\x00" + bytes(color) * size
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


def product(**changes) -> Product:
    base = dict(id="p", brand="B", name_ko="제품", name_en="Product",
                appearance_en="a 30 ml frosted glass dropper bottle with a white cap and a blue label reading BRAND",
                appearance_ko="30ml 병", label_text="BRAND",
                facts=[Fact(id="f1", text_ko="용량 30ml", source="상세 페이지 2026-11-01")],
                say=[Say(text_ko="용량 30ml", evidence=["f1"])],
                dont_say=[DontSay(text_ko="24시간 촉촉", reason="시험 자료가 없다")])
    base.update(changes)
    return Product(**base)


def messages(p: Product, level: str) -> str:
    return " / ".join(f.message for f in bible_lint.lint_product(p, RULES, ClaimsGuard()) if f.level == level)


# ---------------------------------------------------------------- 제품 바이블
def test_예제_바이블은_막힘이_없고_예제용_출처만_알려_준다():
    bible = load_product_bible(EXAMPLE_DIR / "product_bible.yaml")
    findings = bible_lint.lint_bible(bible, RULES)
    assert not bible_lint.has_errors(findings)
    assert findings and all("예제용" in f.message for f in findings)


def test_좋은_정의는_아무것도_걸리지_않는다():
    assert bible_lint.lint_product(product(), RULES, ClaimsGuard()) == []


@pytest.mark.parametrize("appearance, expected", [
    ("a nice serum bottle", "너무 짧다"),
    ("a premium 30 ml glass bottle with a white cap and a blue label reading BRAND", "눈에 보이지 않는 것"),
    ("a 30 ml glass dropper bottle with a white cap and a blue label", "라벨 글자 'BRAND' 가 외형 서술에 없다"),
])
def test_나쁜_외형_서술은_막는다(appearance, expected):
    assert expected in messages(product(appearance_en=appearance), "error")


def test_빠진_것은_알려_준다():
    text = messages(product(appearance_en="a slim container with a cap and a label reading BRAND on it"), "note")
    assert "용기의 종류" in text and "색이 보이지 않는다" in text and "크기나 용량" in text


def test_사실은_출처가_있어야_한다():
    assert "출처가 없다" in messages(product(facts=[Fact(id="f1", text_ko="용량 30ml", source=" ")]), "error")
    assert "출처가 막연하다" in messages(product(facts=[Fact(id="f1", text_ko="용량 30ml", source="블로그 후기")]), "error")
    assert "표현 사전" in messages(product(facts=[Fact(id="f1", text_ko="여드름 치료에 좋다", source="상세 페이지")]), "error")


def test_표현은_사실에서_나와야_한다():
    assert "근거 ['f9'] 가 facts 에 없다" in messages(product(say=[Say(text_ko="가볍다", evidence=["f9"])]), "error")
    assert "근거가 없다" in messages(product(say=[Say(text_ko="가볍다")]), "error")
    assert "쓰지 않는 표현 '24시간 촉촉' 를 담고 있다" in messages(
        product(say=[Say(text_ko="24 시간 촉촉하다", evidence=["f1"])]), "error")
    assert "쓰지 않는 이유가 없다" in messages(product(dont_say=[DontSay(text_ko="순하다", reason="")]), "error")


def test_쓰지_않는_표현은_띄어쓰기를_바꿔도_찾는다():
    assert [d.text_ko for d in find_dont_say(product(), "하루 종일, 24 시간 촉촉!")] == ["24시간 촉촉"]
    assert find_dont_say(product(), "세안 후 두세 방울") == []


def test_대본에_쓰지_않는_표현이_있으면_컴파일이_막는다(scenes, bible, production_spec):
    scene = scenes[1].model_copy(deep=True)
    scene.beats[0].narration_ko = "바르면 24시간 촉촉하다"
    with pytest.raises(CompileError, match="쓰지 않기로 한 표현"):
        compile_scene(scene, bible, production_spec)


# ---------------------------------------------------------------- 요청과 비용
def test_이미지_요청은_공식_문서의_모양이다(tmp_path):
    plain = image_client.build_request("a bottle", model="gemini-nano-banana-2.1")
    assert plain == {"model": "gemini-nano-banana-2.1", "input": "a bottle",
                     "response_format": {"type": "image", "mime_type": "image/png", "aspect_ratio": "1:1", "image_size": "1K"}}
    photo = tmp_path / "front.jpg"
    photo.write_bytes(b"jpeg-bytes")
    request = image_client.build_request("a bottle", model="m", image_paths=[photo], image_size="2K")
    assert request["input"][0] == {"type": "text", "text": "a bottle"}
    assert request["input"][1] == {"type": "image", "mime_type": "image/jpeg",
                                   "data": base64.b64encode(b"jpeg-bytes").decode()}
    summary = image_client.summarize_request(request, [photo])
    assert summary["images"] == ["front.jpg"] and "data" not in json.dumps(summary)      # 기록에는 사진을 싣지 않는다


def test_image_size_는_대문자_K_만_받는다(tmp_path):
    with pytest.raises(ValueError, match="대문자 K"):
        image_client.build_request("x", model="m", image_size="1k")
    with pytest.raises(ValueError, match="14장까지"):
        image_client.build_request("x", model="m", image_paths=[tmp_path / f"{i}.png" for i in range(15)])


def test_이미지_비용은_장수_곱하기_단가다():
    assert estimate_image_cost("1K", MODELS) == 0.0336
    assert estimate_image_cost("1K", MODELS, count=5) == 0.168
    assert estimate_image_cost("4K", MODELS) == 0.113
    with pytest.raises(UnknownPrice):
        estimate_image_cost("8K", MODELS)


def test_generate_는_base64_를_풀어_파일로_쓴다(tmp_path):
    class Interactions:
        def create(self, **request):
            self.request = request
            return type("I", (), {"id": "i-1", "output_image": type("O", (), {"data": base64.b64encode(png()).decode()})()})()

    client = type("C", (), {"interactions": Interactions()})()
    result = image_client.generate(image_client.build_request("x", model="m"), tmp_path / "a" / "front.png", client=client)
    assert (tmp_path / "a" / "front.png").read_bytes() == png() and result.interaction_id == "i-1"
    empty = type("C", (), {"interactions": type("X", (), {"create": lambda self, **k: type("I", (), {"output_image": None})()})()})()
    with pytest.raises(RuntimeError, match="이미지가 없다"):
        image_client.generate(image_client.build_request("x", model="m"), tmp_path / "b.png", client=empty)


# ---------------------------------------------------------------- 계획
def test_사진이_없으면_기준_방향을_먼저_만들고_나머지는_그것을_본다(tmp_path):
    plans = reference_sheet.plan_views(product(), RECIPE, [], tmp_path / "v001")
    assert [p.view_id for p in plans] == ["front", "three_quarter", "side", "label", "in_hand"]
    assert plans[0].image_paths == [] and "attached images" not in plans[0].prompt
    assert all(p.uses_anchor and p.image_paths == [str(tmp_path / "v001" / "front.png")] for p in plans[1:])
    assert "Keep its shape, proportions, colors, cap and label unchanged" in plans[1].prompt
    assert "no people" in plans[0].prompt and "no people" not in plans[4].prompt          # 손이 나오는 방향
    assert "a 30 ml frosted glass dropper bottle" in plans[3].prompt


def test_사진이_있으면_모든_방향이_사진을_본다(tmp_path):
    photos = [tmp_path / f"{n}.jpg" for n in range(3)]
    plans = reference_sheet.plan_views(product(), RECIPE, photos, tmp_path / "v001", ["label", "front"])
    assert [p.view_id for p in plans] == ["front", "label"]                               # 레시피의 순서
    assert all(len(p.image_paths) == 3 and not p.uses_anchor for p in plans)


def test_기준_방향_없이_다른_방향만_만들_수는_없다(tmp_path):
    with pytest.raises(reference_sheet.SheetError, match="기준 방향"):
        reference_sheet.plan_views(product(), RECIPE, [], tmp_path / "v001", ["side"])
    with pytest.raises(reference_sheet.SheetError, match="레시피에 없는 방향"):
        reference_sheet.plan_views(product(), RECIPE, [], tmp_path / "v001", ["top"])


def test_사진은_이름_순으로_정해진_장수만_쓴다(tmp_path):
    folder = tmp_path / "assets" / "products" / "p" / "photos"
    folder.mkdir(parents=True)
    for n in range(8):
        (folder / f"{n}.jpg").write_bytes(b"x")
    (folder / "memo.txt").write_text("x")
    found = reference_sheet.photo_paths("p", RECIPE, tmp_path)
    assert [p.name for p in found] == [f"{n}.jpg" for n in range(6)]
    assert reference_sheet.photo_paths("none", RECIPE, tmp_path) == []


def test_버전은_v001_부터_하나씩_는다(tmp_path):
    assert reference_sheet.next_version(tmp_path / "none") == "v001"
    (tmp_path / "v001").mkdir()
    (tmp_path / "v007").mkdir()
    (tmp_path / "memo").mkdir()
    assert reference_sheet.list_versions(tmp_path) == ["v001", "v007"] and reference_sheet.next_version(tmp_path) == "v008"


# ---------------------------------------------------------------- 명령: 만들기와 고르기
@pytest.fixture
def studio(tmp_path, monkeypatch):
    """예제 폴더를 복사해 쓰고, 생성 호출은 가짜로 바꾼다."""
    example = tmp_path / "example"
    shutil.copytree(EXAMPLE_DIR, example)
    out = tmp_path / "outputs"
    monkeypatch.setattr(cli, "EXAMPLE_DIR", example)
    monkeypatch.setattr(cli, "OUTPUT_DIR", out)
    monkeypatch.setattr(cli, "_setup", lambda: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    calls = []

    def fake(request, path, api_version):
        calls.append(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png((len(calls) * 40 % 255, 100, 200)))
        return image_client.ImageResult(image_path=str(path), interaction_id=f"i-{len(calls)}", model=request["model"],
                                        elapsed_s=8.0, bytes_written=path.stat().st_size, usage={"total_tokens": 1500})

    monkeypatch.setattr(image_client, "generate", fake)
    return example, out, calls


def test_dry_run_은_계획만_보여_주고_아무것도_쓰지_않는다(studio, capsys):
    example, out, calls = studio
    assert cli.main(["sheet", "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "후보 v001 · 방향 5개" in text and "$0.0336 × 5 = $0.17" in text and "사진이 없다" in text
    assert calls == [] and not out.exists()


def test_sheet_는_후보를_만들고_기록을_남긴다(studio, capsys):
    example, out, calls = studio
    assert cli.main(["sheet"]) == 0
    folder = out / "sheets" / "moalab_aqua_serum" / "v001"
    assert sorted(p.name for p in folder.glob("*.png") if p.name != "contact_sheet.png") == [
        "front.png", "in_hand.png", "label.png", "side.png", "three_quarter.png"]
    assert isinstance(calls[0]["input"], str) and calls[1]["input"][1]["type"] == "image"   # 둘째부터 기준 방향을 본다
    record = json.loads((folder / "label.api_run.json").read_text(encoding="utf-8"))
    assert record["episode"] == "sheet" and record["scene_id"] == "moalab_aqua_serum/label"
    assert record["estimated_cost_usd"] == 0.0336 and record["attempts"] == 1 and record["request"]["images"] == ["front.png"]
    sheet = json.loads((folder / "sheet.json").read_text(encoding="utf-8"))
    assert sheet["mode"] == "text" and sheet["views"][0] == "front" and sheet["estimated_cost_usd"] == 0.168
    assert "보고 고른다: ass sheet --product moalab_aqua_serum --select v001 --by 이름" in capsys.readouterr().out
    assert cli.main(["sheet", "--views", "front"]) == 0                                    # 다시 만들면 새 버전
    assert (out / "sheets" / "moalab_aqua_serum" / "v002" / "front.png").is_file()
    rows = ledger.collect(out)
    assert len(rows) == 6 and rows[0].resolution == "1K" and ledger.summarize(rows).ok_usd == 0.2016


def test_본인_사진이_있으면_그_사진을_보낸다(studio, capsys):
    example, out, calls = studio
    photos = example / "assets" / "products" / "moalab_aqua_serum" / "photos"
    photos.mkdir(parents=True)
    (photos / "a.jpg").write_bytes(b"1")
    (photos / "b.png").write_bytes(b"2")
    assert cli.main(["sheet", "--views", "front,label"]) == 0
    assert "본인 사진 2장을 보고 그린다" in capsys.readouterr().out
    assert [len(c["input"]) for c in calls] == [3, 3]                                      # 글 1 + 사진 2
    sheet = json.loads((out / "sheets" / "moalab_aqua_serum" / "v001" / "sheet.json").read_text(encoding="utf-8"))
    assert sheet["mode"] == "photo" and [p["file"] for p in sheet["photos"]] == ["a.jpg", "b.png"]


def test_고르는_일은_사람이_하고_기록에_남는다(studio, capsys):
    example, out, calls = studio
    cli.main(["sheet"])
    cli.main(["sheet", "--views", "front,label"])
    capsys.readouterr()
    assert cli.main(["sheet", "--select", "v001"]) == 4                                    # 이름이 없으면 막는다
    assert "누가 골랐는지" in capsys.readouterr().out
    assert cli.main(["sheet", "--select", "v001", "--by", "황삼청", "--note", "첫 후보"]) == 0
    base = example / "assets" / "products" / "moalab_aqua_serum"
    manifest = json.loads((base / "reference_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1 and manifest["selected_by"] == "황삼청" and manifest["source_mode"] == "text"
    assert [i["view"] for i in manifest["images"]] == ["front", "three_quarter", "side", "label", "in_hand"]
    assert (base / "reference" / "label.png").read_bytes() == (out / "sheets/moalab_aqua_serum/v001/label.png").read_bytes()
    assert manifest["images"][0]["sha256"] == reference_sheet.sha256_file(base / "reference" / "front.png")

    assert cli.main(["sheet", "--select", "label=v002", "--by", "황삼청", "--note", "라벨이 더 또렷하다"]) == 0
    manifest = json.loads((base / "reference_manifest.json").read_text(encoding="utf-8"))
    versions = {i["view"]: i["from_version"] for i in manifest["images"]}
    assert versions == {"front": "v001", "three_quarter": "v001", "side": "v001", "label": "v002", "in_hand": "v001"}
    assert manifest["manifest_version"] == 2 and manifest["history"][0]["images"]["label"] == "v001"
    assert cli.main(["sheet", "--select", "side=v002", "--by", "황삼청"]) == 4               # v002 에는 옆면이 없다
    assert cli.main(["sheet", "--select", "v002", "--by", "황삼청"]) == 0                    # 통째로 고르면 있는 것만
    assert cli.main(["sheet", "--select", "v9", "--by", "황삼청"]) == 4


def test_고른_뒤에_바뀐_것을_알아챈다(studio):
    example, out, calls = studio
    cli.main(["sheet"])
    cli.main(["sheet", "--select", "v001", "--by", "황삼청"])
    bible = load_product_bible(example / "product_bible.yaml")
    p = bible.get("moalab_aqua_serum")
    path = reference_sheet.manifest_path(p.id, RECIPE, example)
    assert reference_sheet.manifest_problems(p, reference_sheet.load_manifest(path), RECIPE, example) == []
    assert "5장 · v001 에서 고름" in reference_sheet.manifest_line(reference_sheet.load_manifest(path))
    changed = p.model_copy(update={"appearance_en": p.appearance_en.replace("white cap", "black cap")})
    assert "외형 서술이 바뀌었다" in reference_sheet.manifest_problems(changed, reference_sheet.load_manifest(path), RECIPE, example)[0]
    (path.parent / "reference" / "side.png").write_bytes(b"edited")
    assert any("파일이 바뀌었다" in m for m in reference_sheet.manifest_problems(p, reference_sheet.load_manifest(path), RECIPE, example))
    assert reference_sheet.manifest_problems(p, None, RECIPE, example) == ["레퍼런스를 아직 고르지 않았다"]


def test_타사_제품은_승인한_사람이_있어야_만든다(studio, capsys):
    example, out, calls = studio
    assert cli.main(["sheet", "--product", "haruon_cream_sunscreen", "--dry-run"]) == 4
    assert "타사 제품이다" in capsys.readouterr().out
    assert cli.main(["sheet", "--product", "haruon_cream_sunscreen", "--approved-by", "황삼청", "--views", "front"]) == 0
    sheet = json.loads((out / "sheets" / "haruon_cream_sunscreen" / "v001" / "sheet.json").read_text(encoding="utf-8"))
    assert sheet["approved_by"] == "황삼청"
    assert cli.main(["sheet", "--product", "nothing"]) == 2


def test_바이블에_막힘이_있으면_레퍼런스를_만들지_않는다(studio, capsys):
    example, out, calls = studio
    path = example / "product_bible.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("a 30 ml frosted glass", "a premium 30 ml frosted glass"),
                    encoding="utf-8")
    assert cli.main(["sheet"]) == 4 and calls == []
    assert "눈에 보이지 않는 것" in capsys.readouterr().out
    assert cli.main(["bible", "--product", "moalab_aqua_serum"]) == 4
    assert "막힘 1건" in capsys.readouterr().out


def test_실패하면_기록을_남기고_멈춘다(studio, monkeypatch, capsys):
    example, out, calls = studio

    def broken(request, path, api_version):
        raise RuntimeError("Error code: 402 - Your prepayment credits are depleted")

    monkeypatch.setattr(image_client, "generate", broken)
    assert cli.main(["sheet"]) == 1
    folder = out / "sheets" / "moalab_aqua_serum" / "v001"
    record = json.loads((folder / "front.api_run.json").read_text(encoding="utf-8"))
    assert record["status"] == "error" and record["attempts"] == 1 and not (folder / "sheet.json").exists()
    assert "조치:" in capsys.readouterr().out


def test_bible_명령은_레퍼런스_상태를_함께_보여_준다(studio, capsys):
    example, out, calls = studio
    assert cli.main(["bible"]) == 0
    text = capsys.readouterr().out
    assert "제품 3개" in text and "레퍼런스: 없음" in text and "막힘 0건" in text
    cli.main(["sheet"])
    cli.main(["sheet", "--select", "v001", "--by", "황삼청"])
    capsys.readouterr()
    cli.main(["bible", "--product", "moalab_aqua_serum"])
    assert "레퍼런스: 5장 · v001 에서 고름" in capsys.readouterr().out


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg 가 없다")
def test_이음판은_낱장을_가로로_붙인다(tmp_path):
    from ass.production import assembler

    images = []
    for n in range(3):
        path = tmp_path / f"{n}.png"
        path.write_bytes(png((n * 80, 100, 200), size=16))
        images.append(path)
    sheet = reference_sheet.contact_sheet(images, tmp_path / "contact_sheet.png", cell_px=64)
    info = assembler.probe(sheet)
    assert (info.width, info.height) == (192, 64)


# ---------------------------------------------------------------- 콘솔
def test_콘솔은_편에_나오는_제품마다_sheet_를_실행한다(studio):
    from ass import console_model as model

    example, out, calls = studio
    assert [p.id for p in model.episode_products("product_intro", example)] == ["moalab_aqua_serum"]
    assert model.build_runs("sheet", "product_intro", dry_run=True, example_dir=example) == [
        ["sheet", "--product", "moalab_aqua_serum", "--dry-run"]]
    assert model.build_runs("sheet", "product_intro", dry_run=False, example_dir=example) == [
        ["sheet", "--product", "moalab_aqua_serum"]]
    assert model.paid_estimate("sheet", "product_intro", dry_run=False, example_dir=example) == 0.17
    assert model.paid_estimate("sheet", "product_intro", dry_run=True, example_dir=example) == 0.0
    assert model.build_runs("bible", "product_intro") == [["bible"]]


def test_콘솔은_sheet_가_읽고_쓰는_파일을_보여_준다(studio):
    from ass import console_model as model

    example, out, calls = studio
    rows = model.command_files("sheet", "product_intro", example_dir=example, output_dir=out)
    assert [r.mark for r in rows] == ["①", "②", "③", "④", "⑤", "⑥", "⑦"] + ["→"] * 7
    assert "없으면 외형 서술만으로 만든다" in rows[1].what and "v001" in rows[7].path
    photos = example / "assets" / "products" / "moalab_aqua_serum" / "photos"
    photos.mkdir(parents=True)
    (photos / "a.jpg").write_bytes(b"1")
    rows = model.command_files("sheet", "product_intro", example_dir=example, output_dir=out)
    assert rows[1].exists and "이 사진을 보고 그린다" in rows[1].what


def test_콘솔에서_고른_후보는_select_명령이_된다(studio):
    from ass import console_model as model

    example, out, calls = studio
    assert not any(c.versions for c in model.sheet_choices("product_intro", example, out))
    cli.main(["sheet"])
    cli.main(["sheet", "--views", "front,label"])
    choices = {c.view_id: c for c in model.sheet_choices("product_intro", example, out)}
    assert choices["label"].versions == ["v002", "v001"] and choices["side"].versions == ["v001"]
    assert choices["label"].current == ""
    runs = model.select_runs({("moalab_aqua_serum", "front"): "v001", ("moalab_aqua_serum", "label"): "v002"}, "황삼청", "라벨")
    assert runs == [["sheet", "--product", "moalab_aqua_serum", "--select", "front=v001", "--select", "label=v002",
                     "--by", "황삼청", "--note", "라벨"]]
    assert cli.main(runs[0]) == 0
    assert {c.view_id: c.current for c in model.sheet_choices("product_intro", example, out)}["label"] == "v002"
