"""입력 (3장). 콘솔의 입력 화면과 명령이 함께 쓰는, 내용을 파일로 적는 일.

독자가 적는 것은 셋이다. 제품, 소재 요약, 장면. 적은 것은 프로젝트 폴더의 YAML 파일이 된다.
파일의 모양은 견본(examples/moalab_skincare)과 같다. 그래서 이후의 검사, 생성, 조립은 그대로 쓴다.

  제품        projects/<이름>/product_bible.yaml
  사진        projects/<이름>/assets/products/<제품 id>/photos/
  소재 요약    projects/<이름>/source_briefs/<편>.yaml   (붙여 넣은 원문은 sources/<편>.txt)
  장면        projects/<이름>/episodes/<편>/scene_0N_<역할>.yaml

저장하기 전에 모양을 검사한다(pydantic). 검사에 걸리면 파일을 쓰지 않고 이유를 말한다.
화면에서 여러 줄로 적는 칸(사실, 표현)은 한 줄에 하나씩, 세로줄(|)로 나눠 적는다.
"""
from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ass.production.product_bible import Product
from ass.production.scene_spec import SceneSpec
from ass.production.source_brief import SourceBrief
from ass.settings import PROJECTS_DIR, SAMPLE_DIR, load_yaml, valid_project_name

ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{1,39}")
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
SOURCE_TYPES = {"idea": "아이디어 한 줄", "own_blog": "내가 쓴 블로그 글", "own_video_script": "내 영상의 대본"}


class InputError(Exception):
    """적은 내용으로는 파일을 만들 수 없다. 메시지를 그대로 화면에 보인다."""


def _dump(doc: dict[str, Any], path: Path, header: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False)
    path.write_text((header + "\n" if header else "") + text, encoding="utf-8")


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    where = ".".join(str(p) for p in err.get("loc", ()))
    message = str(err.get("msg", "")).replace("Value error, ", "")
    return f"{where}: {message}" if where else message


def check_id(value: str, what: str) -> str:
    value = value.strip()
    if not ID_PATTERN.fullmatch(value):
        raise InputError(f"{what}은(는) 영문 소문자로 시작하고 영문 소문자, 숫자, 밑줄만 쓴다 (2~40자): {value!r}")
    return value


# ---------------------------------------------------------------- 프로젝트
def init_project(name: str, projects_dir: Path = PROJECTS_DIR) -> Path:
    """빈 프로젝트 폴더를 만든다. 이미 있으면 건드리지 않고 알려 준다."""
    if not valid_project_name(name):
        raise InputError(f"프로젝트 이름은 영문 소문자로 시작하고 영문 소문자, 숫자, 밑줄만 쓴다 (2~40자, sample 제외): {name!r}")
    folder = projects_dir / name
    if (folder / "product_bible.yaml").is_file():
        raise InputError(f"이미 있는 프로젝트다: {folder}")
    for sub in ("source_briefs", "sources", "episodes", "assets/products", "outputs"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    (folder / "outputs" / ".gitkeep").write_text("", encoding="utf-8")
    _dump({"version": "0.1", "products": {}}, folder / "product_bible.yaml",
          "# product_bible.yaml — 이 프로젝트의 제품 바이블. 콘솔의 [입력] → 제품 등록이 고친다.")
    return folder


# ---------------------------------------------------------------- 여러 줄 칸
def _rows(text: str, columns: int, what: str) -> list[list[str]]:
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != columns or not all(parts[:2]):
            raise InputError(f"{what} {number}번째 줄: 세로줄(|)로 나눈 칸이 {columns}개여야 한다 — {line.strip()}")
        rows.append(parts)
    return rows


def parse_facts(text: str) -> list[dict[str, str]]:
    """`id | 사실 | 출처` 를 한 줄에 하나씩."""
    return [{"id": check_id(i, "사실 id"), "text_ko": t, "source": s} for i, t, s in _rows(text, 3, "사실")]


def parse_say(text: str) -> list[dict[str, Any]]:
    """`표현 | 근거가 되는 사실 id (쉼표로 여럿)` 를 한 줄에 하나씩."""
    return [{"text_ko": t, "evidence": split_ids(e)} for t, e in _rows(text, 2, "써도 되는 표현")]


def parse_dont_say(text: str) -> list[dict[str, str]]:
    """`표현 | 쓰지 않는 이유` 를 한 줄에 하나씩."""
    return [{"text_ko": t, "reason": r} for t, r in _rows(text, 2, "쓰지 않는 표현")]


def split_ids(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,\s]+", text or "") if part.strip()]


def format_facts(facts: list[dict[str, Any]]) -> str:
    return "\n".join(f"{f['id']} | {f['text_ko']} | {f['source']}" for f in facts)


def format_say(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"{s['text_ko']} | {', '.join(s.get('evidence', []))}" for s in items)


def format_dont_say(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"{d['text_ko']} | {d['reason']}" for d in items)


# ---------------------------------------------------------------- 제품
def bible_doc(project_dir: Path) -> dict[str, Any]:
    path = project_dir / "product_bible.yaml"
    doc = load_yaml(path) if path.is_file() else {"version": "0.1", "products": {}}
    doc["products"] = doc.get("products") or {}
    return doc


def product_ids(project_dir: Path) -> list[str]:
    return list(bible_doc(project_dir)["products"])


def product_doc(project_dir: Path, product_id: str) -> dict[str, Any] | None:
    return copy.deepcopy(bible_doc(project_dir)["products"].get(product_id))


def save_product(project_dir: Path, product_id: str, data: dict[str, Any]) -> Product:
    """제품 하나를 제품 바이블에 적는다. 같은 id 가 있으면 바꾼다."""
    product_id = check_id(product_id, "제품 id")
    body = {k: v for k, v in data.items() if v not in ("", None)}
    for key in ("facts", "say", "dont_say"):
        body[key] = data.get(key) or []
    for key in ("brand", "name_ko", "name_en", "appearance_en"):
        if not str(data.get(key, "")).strip():
            raise InputError(f"{PRODUCT_LABELS[key]}을(를) 적는다")
    try:
        product = Product(id=product_id, **body)
    except ValidationError as exc:
        raise InputError(_first_error(exc)) from None
    known = product.fact_ids()
    for say in product.say:
        missing = [e for e in say.evidence if e not in known]
        if missing:
            raise InputError(f"써도 되는 표현 '{say.text_ko}' 의 근거 {missing} 가 사실에 없다")
    doc = bible_doc(project_dir)
    doc["products"][product_id] = product.model_dump(exclude={"id"})
    _dump(doc, project_dir / "product_bible.yaml",
          "# product_bible.yaml — 이 프로젝트의 제품 바이블. 콘솔의 [입력] → 제품 등록이 고친다.")
    return product


PRODUCT_LABELS = {"brand": "브랜드", "name_ko": "제품 이름(우리말)", "name_en": "제품 이름(영어)",
                  "appearance_en": "외형 서술(영어)"}


def add_photos(project_dir: Path, product_id: str, sources: list[str | Path]) -> list[Path]:
    """고른 사진을 제품의 photos 폴더로 복사한다. 원본은 건드리지 않는다."""
    product_id = check_id(product_id, "제품 id")
    folder = project_dir / "assets" / "products" / product_id / "photos"
    copied = []
    for source in (Path(s) for s in sources):
        if source.suffix.lower() not in PHOTO_EXTENSIONS:
            raise InputError(f"{source.name}: jpg, png, webp 사진만 넣는다")
        if not source.is_file():
            raise InputError(f"{source}: 파일이 없다")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / source.name
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        copied.append(target)
    return copied


# ---------------------------------------------------------------- 소재 요약
def episode_ids(project_dir: Path) -> list[str]:
    """소재 요약이나 장면이 있는 편."""
    names = {p.stem for p in (project_dir / "source_briefs").glob("*.yaml")} if (project_dir / "source_briefs").is_dir() else set()
    if (project_dir / "episodes").is_dir():
        names |= {p.name for p in (project_dir / "episodes").iterdir() if p.is_dir()}
    return sorted(names)


def brief_doc(project_dir: Path, episode: str) -> dict[str, Any] | None:
    path = project_dir / "source_briefs" / f"{episode}.yaml"
    return load_yaml(path) if path.is_file() else None


def save_brief(project_dir: Path, episode: str, data: dict[str, Any], source_text: str = "") -> SourceBrief:
    """소재 요약을 적는다. 붙여 넣은 원문은 sources/<편>.txt 로 따로 둔다."""
    episode = check_id(episode, "편 이름")
    known_products = set(product_ids(project_dir))
    unknown = [p for p in data.get("products", []) if p not in known_products]
    if unknown:
        raise InputError(f"제품 바이블에 없는 제품: {', '.join(unknown)}. 먼저 제품을 등록한다")
    points = [p for p in data.get("key_points", []) if str(p.get("text_ko", "")).strip()]
    body = {**data, "brief_id": episode, "key_points": points, "origin": data.get("origin") or None}
    for key, label in (("title_ko", "제목"), ("promise_ko", "시청자에게 하는 약속")):
        if not str(data.get(key, "")).strip():
            raise InputError(f"{label}을(를) 적는다")
    if not points:
        raise InputError("요점을 하나 이상 적는다 (셋까지)")
    try:
        brief = SourceBrief.model_validate(body)
    except ValidationError as exc:
        raise InputError(_first_error(exc)) from None
    doc = brief.model_dump(exclude_none=True)
    for point in doc["key_points"]:
        if not point.get("evidence"):
            point.pop("evidence", None)
    _dump(doc, project_dir / "source_briefs" / f"{episode}.yaml", f"# 소재 요약 — {brief.title_ko}")
    if source_text.strip():
        target = project_dir / "sources" / f"{episode}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source_text.strip() + "\n", encoding="utf-8")
    return brief


# ---------------------------------------------------------------- 장면
def scene_path(project_dir: Path, episode: str, number: int) -> Path | None:
    found = sorted((project_dir / "episodes" / episode).glob(f"scene_{number:02d}_*.yaml"))
    return found[0] if found else None


def scene_doc(project_dir: Path, episode: str, number: int) -> dict[str, Any] | None:
    path = scene_path(project_dir, episode, number)
    return load_yaml(path) if path else None


def blank_scene(episode: str, number: int, fmt: str, production_spec: dict[str, Any],
                products: list[str] | None = None) -> dict[str, Any]:
    """빈 장면. 형식에 맞는 역할과 15초를 셋으로 나눈 구간이 미리 들어 있다."""
    roles = production_spec["formats"][fmt]["scene_roles"]
    return {
        "scene_id": f"{episode}_s{number:02d}", "episode_id": episode, "format": fmt, "role": roles[number - 1],
        "duration_s": 15, "products": list(products or []), "setting_en": "",
        "beats": [{"start_s": a, "end_s": b, "visual_ko": "", "visual_en": "", "camera_en": "",
                   "narration_ko": "", "caption_ko": "", "evidence": []} for a, b in ((0, 5), (5, 10), (10, 15))],
        "audio_en": "",
    }


def save_scene(project_dir: Path, episode: str, number: int, data: dict[str, Any]) -> SceneSpec:
    """장면 하나를 적는다. 화면(우리말)이 빈 구간은 적지 않은 것으로 보고 뺀다."""
    episode = check_id(episode, "편 이름")
    beats = []
    for beat in data.get("beats", []):
        if not str(beat.get("visual_ko", "")).strip():
            continue
        clean = {k: v for k, v in beat.items() if v not in ("", None, [])}
        try:
            clean["start_s"], clean["end_s"] = int(beat["start_s"]), int(beat["end_s"])
        except (KeyError, TypeError, ValueError):
            raise InputError("구간의 시작과 끝은 초 단위의 정수로 적는다") from None
        beats.append(clean)
    if not beats:
        raise InputError("구간을 하나 이상 적는다. 화면(우리말)이 빈 구간은 저장하지 않는다")
    if not str(data.get("setting_en", "")).strip():
        raise InputError("장소(영어)를 적는다")
    body = {k: v for k, v in data.items() if v not in ("", None)}
    body.update({"episode_id": episode, "beats": beats, "products": data.get("products") or []})
    try:
        body["duration_s"] = int(data.get("duration_s", 15))
        scene = SceneSpec.model_validate(body)
    except ValidationError as exc:
        raise InputError(_first_error(exc)) from None
    except (TypeError, ValueError):
        raise InputError("길이는 초 단위의 정수로 적는다") from None
    unknown = [p for p in scene.products if p not in set(product_ids(project_dir))]
    if unknown:
        raise InputError(f"제품 바이블에 없는 제품: {', '.join(unknown)}")
    old = scene_path(project_dir, episode, number)
    target = project_dir / "episodes" / episode / f"scene_{number:02d}_{scene.role}.yaml"
    doc = scene.model_dump(exclude_none=True, exclude_defaults=False)
    for beat in doc["beats"]:
        if not beat.get("evidence"):
            beat.pop("evidence", None)
    if not doc.get("exclusions_en"):
        doc.pop("exclusions_en", None)
    _dump(doc, target, f"# 장면 {number} — {scene.role}")
    if old and old != target:            # 형식을 바꿔 역할 이름이 달라졌으면 옛 파일을 치운다
        old.rename(old.with_suffix(".yaml.old"))
    return scene


# ---------------------------------------------------------------- 견본으로 채우기
SAMPLE_EPISODE = "product_intro"             # 견본의 편 폴더 이름
SAMPLE_BRIEF = "aqua_serum_intro"
SAMPLE_PRODUCT = "moalab_aqua_serum"


def sample_product_ids(sample_dir: Path = SAMPLE_DIR) -> list[str]:
    return product_ids(sample_dir)


def sample_product(product_id: str = SAMPLE_PRODUCT, sample_dir: Path = SAMPLE_DIR) -> dict[str, Any]:
    doc = product_doc(sample_dir, product_id)
    if doc is None:
        raise InputError(f"견본에 없는 제품: {product_id}")
    return doc


def sample_brief(episode: str, sample_dir: Path = SAMPLE_DIR) -> dict[str, Any]:
    """견본의 소재 요약. 편 이름만 독자가 정한 것으로 바꾼다."""
    doc = load_yaml(sample_dir / "source_briefs" / f"{SAMPLE_BRIEF}.yaml")
    doc["brief_id"] = episode
    return doc


def sample_scene(episode: str, number: int, sample_dir: Path = SAMPLE_DIR) -> dict[str, Any]:
    """견본의 장면. scene_id 는 그대로 두어 책의 출력과 파일 이름이 같게 나온다."""
    doc = scene_doc(sample_dir, SAMPLE_EPISODE, number)
    if doc is None:
        raise InputError(f"견본에 장면 {number} 이 없다")
    doc["episode_id"] = episode
    return doc
