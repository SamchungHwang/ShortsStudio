"""3장(개정): 내 프로젝트와 입력. 콘솔의 입력 화면이 만드는 파일이 견본과 같은 모양인지 본다."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ass import authoring, settings
from ass.authoring import InputError
from ass.policy import load_policy
from ass.production.product_bible import load_product_bible
from ass.production.scene_spec import load_scene
from ass.production.source_brief import load_source_brief

SPEC = load_policy("production_spec").data
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    return authoring.init_project("my_first", tmp_path / "projects")


def fill_from_sample(project: Path, episode: str = "product_intro") -> None:
    """책을 따라 하는 독자가 하는 일: 견본 값으로 제품 하나, 소재 요약, 장면 셋을 저장한다."""
    authoring.save_product(project, authoring.SAMPLE_PRODUCT, authoring.sample_product())
    brief = authoring.sample_brief(episode)
    authoring.save_brief(project, episode, brief, "블로그 글 원문")
    for n in (1, 2, 3):
        authoring.save_scene(project, episode, n, authoring.sample_scene(episode, n))


# ---------------------------------------------------------------- 프로젝트
def test_새_프로젝트는_빈_폴더_한_벌이다(project):
    assert sorted(p.name for p in project.iterdir()) == ["assets", "episodes", "outputs", "product_bible.yaml",
                                                         "source_briefs", "sources"]
    assert load_product_bible(project / "product_bible.yaml").products == {}
    assert settings.list_projects(project.parent) == ["my_first"]
    with pytest.raises(InputError, match="이미 있는 프로젝트"):
        authoring.init_project("my_first", project.parent)


@pytest.mark.parametrize("name", ["My", "1abc", "a", "sample", "내것", "has space", "a-b"])
def test_프로젝트_이름은_영문_소문자_숫자_밑줄만(name, tmp_path):
    with pytest.raises(InputError, match="프로젝트 이름"):
        authoring.init_project(name, tmp_path)


def test_현재_프로젝트는_환경_변수가_먼저고_없으면_적어_둔_것이다(project):
    projects = project.parent
    assert settings.resolve_project({}, {}, projects) == "sample"
    assert settings.resolve_project({}, {"project": "my_first"}, projects) == "my_first"
    assert settings.resolve_project({"ASS_PROJECT": "sample"}, {"project": "my_first"}, projects) == "sample"
    assert settings.resolve_project({}, {"project": "지워진것"}, projects) == "sample"          # 없는 프로젝트면 견본
    assert settings.resolve_project({"ASS_IGNORE_PREFS": "1", "ASS_PROJECT": "my_first"}, {}, projects) == "sample"
    assert settings.project_paths("my_first", projects) == (project, project / "outputs")
    assert settings.project_paths("sample")[0].name == "moalab_skincare"


def test_설정_파일은_다른_칸을_지우지_않는다(tmp_path):
    path = tmp_path / "prefs.json"
    settings.write_prefs({"project": "my_first"}, path)
    settings.write_prefs({"font_size": 14}, path)
    assert settings.read_prefs(path) == {"project": "my_first", "font_size": 14}
    assert settings.read_prefs(tmp_path / "none.json") == {}


# ---------------------------------------------------------------- 여러 줄 칸
def test_사실은_한_줄에_하나씩_세로줄로_나눠_적는다():
    text = "serum_volume | 용량 30ml | 상세 페이지\n\n# 메모는 건너뛴다\nserum_texture|묽은 젤 제형|성분표"
    facts = authoring.parse_facts(text)
    assert facts == [{"id": "serum_volume", "text_ko": "용량 30ml", "source": "상세 페이지"},
                     {"id": "serum_texture", "text_ko": "묽은 젤 제형", "source": "성분표"}]
    assert authoring.parse_facts(authoring.format_facts(facts)) == facts
    with pytest.raises(InputError, match="사실 1번째 줄"):
        authoring.parse_facts("용량 30ml | 상세 페이지")
    with pytest.raises(InputError, match="사실 id"):
        authoring.parse_facts("용량 | 30ml | 상세 페이지")


def test_표현_칸도_같은_방식이다():
    say = authoring.parse_say("묽은 젤 제형 | serum_texture, serum_volume")
    assert say == [{"text_ko": "묽은 젤 제형", "evidence": ["serum_texture", "serum_volume"]}]
    dont = authoring.parse_dont_say("24시간 촉촉 | 시험 자료가 없다")
    assert dont == [{"text_ko": "24시간 촉촉", "reason": "시험 자료가 없다"}]
    assert authoring.parse_say(authoring.format_say(say)) == say
    assert authoring.parse_dont_say(authoring.format_dont_say(dont)) == dont


# ---------------------------------------------------------------- 제품
def test_견본_제품을_저장하면_견본과_같은_제품이_된다(project):
    authoring.save_product(project, authoring.SAMPLE_PRODUCT, authoring.sample_product())
    mine = load_product_bible(project / "product_bible.yaml").get(authoring.SAMPLE_PRODUCT)
    sample = load_product_bible(settings.SAMPLE_DIR / "product_bible.yaml").get(authoring.SAMPLE_PRODUCT)
    assert mine == sample
    assert authoring.product_ids(project) == [authoring.SAMPLE_PRODUCT]
    changed = authoring.sample_product()
    changed["label_text"] = "MOALAB+"
    authoring.save_product(project, authoring.SAMPLE_PRODUCT, changed)                    # 같은 id 는 바꾼다
    assert authoring.product_doc(project, authoring.SAMPLE_PRODUCT)["label_text"] == "MOALAB+"


def test_빠진_칸과_틀린_근거는_저장하지_않는다(project):
    data = authoring.sample_product()
    with pytest.raises(InputError, match="외형 서술"):
        authoring.save_product(project, "p1", {**data, "appearance_en": " "})
    with pytest.raises(InputError, match="제품 id"):
        authoring.save_product(project, "모아랩", data)
    with pytest.raises(InputError, match="근거 \\['none'\\] 가 사실에 없다"):
        authoring.save_product(project, "p1", {**data, "say": [{"text_ko": "가볍다", "evidence": ["none"]}]})
    assert authoring.product_ids(project) == []


def test_사진은_제품의_photos_폴더로_복사한다(project, tmp_path):
    photo = tmp_path / "IMG_0001.JPG"
    photo.write_bytes(b"jpeg")
    copied = authoring.add_photos(project, "moalab_aqua_serum", [photo])
    assert copied == [project / "assets" / "products" / "moalab_aqua_serum" / "photos" / "IMG_0001.JPG"]
    assert copied[0].read_bytes() == b"jpeg" and photo.is_file()
    with pytest.raises(InputError, match="사진만"):
        authoring.add_photos(project, "moalab_aqua_serum", [tmp_path / "memo.txt"])


# ---------------------------------------------------------------- 소재 요약
def test_소재_요약은_편_이름의_파일이_되고_원문은_따로_둔다(project):
    authoring.save_product(project, authoring.SAMPLE_PRODUCT, authoring.sample_product())
    authoring.save_brief(project, "product_intro", authoring.sample_brief("product_intro"), "내 블로그 글 전문")
    brief = load_source_brief(project / "source_briefs" / "product_intro.yaml")
    assert brief.brief_id == "product_intro" and brief.format == "product_intro" and len(brief.key_points) == 3
    assert (project / "sources" / "product_intro.txt").read_text(encoding="utf-8") == "내 블로그 글 전문\n"
    assert authoring.episode_ids(project) == ["product_intro"]


def test_소재_요약이_막는_것(project):
    authoring.save_product(project, authoring.SAMPLE_PRODUCT, authoring.sample_product())
    good = authoring.sample_brief("ep")
    with pytest.raises(InputError, match="본인 소유가 확인되지 않은"):
        authoring.save_brief(project, "ep", {**good, "owner_confirmed": False})
    with pytest.raises(InputError, match="origin"):
        authoring.save_brief(project, "ep", {**good, "origin": ""})
    with pytest.raises(InputError, match="제품 바이블에 없는 제품"):
        authoring.save_brief(project, "ep", {**good, "products": ["nothing"]})
    with pytest.raises(InputError, match="요점을 하나 이상"):
        authoring.save_brief(project, "ep", {**good, "key_points": [{"text_ko": " "}]})
    with pytest.raises(InputError, match="제목"):
        authoring.save_brief(project, "ep", {**good, "title_ko": ""})
    idea = {**good, "source_type": "idea", "origin": "", "key_points": good["key_points"][:1]}
    assert authoring.save_brief(project, "ep", idea).origin is None                        # 아이디어는 출처가 없어도 된다


# ---------------------------------------------------------------- 장면
def test_빈_장면은_형식에_맞는_역할과_셋으로_나눈_구간을_갖는다():
    doc = authoring.blank_scene("my_ep", 2, "comparison", SPEC, ["a", "b"])
    assert (doc["scene_id"], doc["role"], doc["products"]) == ("my_ep_s02", "side_by_side", ["a", "b"])
    assert [(b["start_s"], b["end_s"]) for b in doc["beats"]] == [(0, 5), (5, 10), (10, 15)]


def test_견본_장면을_저장하면_견본과_같은_장면이_된다(project):
    fill_from_sample(project)
    for n in (1, 2, 3):
        mine = load_scene(authoring.scene_path(project, "product_intro", n))
        sample = load_scene(authoring.scene_path(settings.SAMPLE_DIR, "product_intro", n))
        assert mine.model_dump(exclude={"episode_id"}) == sample.model_dump(exclude={"episode_id"})
        assert mine.episode_id == "product_intro"
    assert [p.name for p in sorted((project / "episodes" / "product_intro").iterdir())] == [
        "scene_01_problem.yaml", "scene_02_solution.yaml", "scene_03_usage.yaml"]


def test_장면이_막는_것(project):
    authoring.save_product(project, authoring.SAMPLE_PRODUCT, authoring.sample_product())
    good = authoring.sample_scene("ep", 2)
    with pytest.raises(InputError, match="장소"):
        authoring.save_scene(project, "ep", 2, {**good, "setting_en": ""})
    broken = authoring.sample_scene("ep", 2)
    broken["beats"][1]["start_s"] = 6
    with pytest.raises(InputError, match="2번째 구간은 4초에서 시작해야 한다"):
        authoring.save_scene(project, "ep", 2, broken)
    empty = authoring.sample_scene("ep", 2)
    for beat in empty["beats"]:
        beat["visual_ko"] = ""
    with pytest.raises(InputError, match="구간을 하나 이상"):
        authoring.save_scene(project, "ep", 2, empty)
    with pytest.raises(InputError, match="제품 바이블에 없는 제품"):
        authoring.save_scene(project, "ep", 2, {**good, "products": ["nothing"]})
    assert authoring.scene_path(project, "ep", 2) is None


def test_화면이_빈_구간은_빼고_저장한다(project):
    authoring.save_product(project, authoring.SAMPLE_PRODUCT, authoring.sample_product())
    doc = authoring.blank_scene("ep", 1, "product_intro", SPEC)
    doc["setting_en"] = "A bathroom counter."
    doc["duration_s"] = "10"
    for beat, text in zip(doc["beats"], ("손이 스펀지를 누른다", "빈 유리컵", "")):
        beat["visual_ko"] = text
    scene = authoring.save_scene(project, "ep", 1, doc)
    assert scene.duration_s == 10 and len(scene.beats) == 2 and scene.beats[0].narration_ko is None


# ---------------------------------------------------------------- 명령: 내 프로젝트에서 그대로 돈다
def run(env_extra: dict, *argv: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ASS_IGNORE_PREFS", "ASS_PROJECT")}
    env.update(env_extra, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "ass", *argv], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8")


def test_init_부터_compile_까지_내_프로젝트에서_돈다(tmp_path):
    env = {"ASS_PROJECTS_DIR": str(tmp_path / "projects"), "ASS_PREFS_PATH": str(tmp_path / "prefs.json")}
    made = run(env, "init", "my_first")
    assert made.returncode == 0 and "현재 프로젝트: my_first" in made.stdout
    assert run(env, "init", "my_first").returncode == 4                                    # 두 번 만들지 않는다
    listing = run(env, "project").stdout
    assert "* my_first" in listing and "  sample" in listing

    fill_from_sample(tmp_path / "projects" / "my_first")
    done = run(env, "compile", "--episode", "product_intro")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "[프로젝트 my_first]" in done.stdout and "장면 3개" in done.stdout
    assert (tmp_path / "projects" / "my_first" / "outputs" / "compiled" / "product_intro" / "storyboard.md").is_file()
    bible = run(env, "bible")
    assert "제품 1개" in bible.stdout and "막힘 0건" in bible.stdout

    nothing = run(env, "reuse", "--dry-run")                                                # 견본에 만든 영상이 없으면 없다고 한다
    assert nothing.returncode == 0 and "가져올 수 있는 영상" in nothing.stdout
    assert run(env, "reuse", "--from", "my_first").returncode == 4                          # 자기 자신에게서는 못 가져온다

    back = run(env, "project", "sample")
    assert back.returncode == 0 and "[프로젝트" not in run(env, "compile").stdout             # 견본으로 돌아간다
    once = run(env, "--project", "my_first", "compile", "--episode", "product_intro")       # 한 번만 다른 곳에서
    assert once.returncode == 0 and "[프로젝트 my_first]" in once.stdout
    assert run(env, "--project", "nothing", "compile").returncode == 4
    assert run(env, "project", "nothing").returncode == 4
