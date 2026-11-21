"""레퍼런스 시트 (5.3절, 5.4절).

제품 하나를 정해진 몇 방향에서 본 이미지 묶음을 만들고, 사람이 고른 것을 기록한다.

  만들기   outputs/sheets/<제품>/v001/<방향>.png   후보. 다시 만들면 v002 가 생긴다. 지우지 않는다
  고르기   <예제>/assets/products/<제품>/reference/<방향>.png   사람이 고른 것. 이후 장들이 이것을 쓴다
  기록     <예제>/assets/products/<제품>/reference_manifest.json   무엇을, 누가, 언제, 어느 후보에서

만드는 길은 둘이다. 본인이 찍은 제품 사진이 있으면 그 사진을 보고 그리게 한다(photo).
없으면 외형 서술로 기준 방향 하나를 먼저 만들고, 나머지 방향은 그 이미지를 보고 그리게 한다(text).
레시피는 configs/reference_sheet.yaml 에 있다.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ass.production.product_bible import Product


class SheetError(Exception):
    """레퍼런스 시트를 만들거나 고를 수 없다."""


class ViewPlan(BaseModel):
    view_id: str
    name_ko: str
    prompt: str
    image_paths: list[str] = []        # 함께 보낼 이미지 (본인 사진 또는 기준 방향)
    uses_anchor: bool = False
    output_path: str


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 자리
def photo_dir(product_id: str, recipe: dict[str, Any], example_dir: Path) -> Path:
    return example_dir / recipe["photos"]["folder"].format(product_id=product_id)


def photo_paths(product_id: str, recipe: dict[str, Any], example_dir: Path) -> list[Path]:
    """본인이 찍은 제품 사진. 이름 순으로 앞에서부터 max_per_call 장을 쓴다."""
    folder = photo_dir(product_id, recipe, example_dir)
    extensions = {e.lower() for e in recipe["photos"]["extensions"]}
    if not folder.is_dir():
        return []
    found = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in extensions)
    return found[: int(recipe["photos"]["max_per_call"])]


def reference_dir(product_id: str, recipe: dict[str, Any], example_dir: Path) -> Path:
    return example_dir / recipe["selected"]["folder"].format(product_id=product_id)


def manifest_path(product_id: str, recipe: dict[str, Any], example_dir: Path) -> Path:
    return example_dir / recipe["selected"]["manifest"].format(product_id=product_id)


def sheet_root(product_id: str, output_dir: Path) -> Path:
    return output_dir / "sheets" / product_id


def list_versions(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r"v\d{3}", p.name))


def next_version(root: Path) -> str:
    versions = list_versions(root)
    return f"v{(int(versions[-1][1:]) + 1 if versions else 1):03d}"


def _extension(recipe: dict[str, Any]) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[recipe["image"]["mime_type"]]


# ---------------------------------------------------------------- 계획
def view_prompt(product: Product, view: dict[str, Any], recipe: dict[str, Any], with_images: bool) -> str:
    style = " ".join(str(recipe["style_en"]).split())
    if view.get("allow_people"):
        style = style.replace("no people, ", "").replace("no people", "")
    parts = [style, f"Product: {product.appearance_en}.", str(view["prompt_en"])]
    if with_images:
        parts.append(" ".join(str(recipe["keep_en"]).split()))
    return " ".join(parts)


def plan_views(product: Product, recipe: dict[str, Any], photos: list[Path], version_dir: Path,
               only: list[str] | None = None) -> list[ViewPlan]:
    """어느 방향을 어떤 글과 이미지로 만들지 정한다. 호출하지 않는다.

    사진이 없으면 기준 방향을 맨 앞에 두고, 나머지 방향은 기준 방향의 결과를 함께 보낸다.
    """
    known = [v["id"] for v in recipe["views"]]
    wanted = only or known
    unknown = [v for v in wanted if v not in known]
    if unknown:
        raise SheetError(f"레시피에 없는 방향: {', '.join(unknown)}. 있는 방향: {', '.join(known)}")
    ext = _extension(recipe)
    anchor = str(recipe["anchor_view"])
    anchor_path = version_dir / f"{anchor}{ext}"
    views = [v for v in recipe["views"] if v["id"] in wanted]
    if not photos:
        views.sort(key=lambda v: v["id"] != anchor)          # 기준 방향을 먼저
        if anchor not in wanted and not anchor_path.is_file():
            raise SheetError(f"사진이 없을 때는 기준 방향({anchor})을 먼저 만든다. --views 에 {anchor} 를 넣는다")
    plans: list[ViewPlan] = []
    for view in views:
        if photos:
            images, uses_anchor = [str(p) for p in photos], False
        elif view["id"] == anchor:
            images, uses_anchor = [], False
        else:
            images, uses_anchor = [str(anchor_path)], True
        plans.append(ViewPlan(view_id=view["id"], name_ko=view["name_ko"],
                              prompt=view_prompt(product, view, recipe, bool(images)),
                              image_paths=images, uses_anchor=uses_anchor,
                              output_path=str(version_dir / f"{view['id']}{ext}")))
    return plans


# ---------------------------------------------------------------- 이음판
def contact_sheet(images: list[Path], out_path: Path, cell_px: int = 512) -> Path | None:
    """후보 이미지를 가로로 나란히 붙여 한 장으로 만든다. 사람이 한눈에 견주는 데 쓴다.

    FFmpeg 가 없으면 만들지 않고 None 을 돌려준다. 모델에 보내는 것은 이 이음판이 아니라 낱장이다.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not images:
        return None
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    chains, labels = [], ""
    for n, image in enumerate(images):
        command += ["-i", str(image)]
        chains.append(f"[{n}:v]scale={cell_px}:{cell_px}:force_original_aspect_ratio=decrease,"
                      f"pad={cell_px}:{cell_px}:(ow-iw)/2:(oh-ih)/2:white,setsar=1[c{n}]")
        labels += f"[c{n}]"
    tail = f"{labels}hstack=inputs={len(images)}[out]" if len(images) > 1 else "[c0]null[out]"
    command += ["-filter_complex", ";".join(chains + [tail]), "-map", "[out]", "-frames:v", "1", str(out_path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return out_path if result.returncode == 0 and out_path.is_file() else None


# ---------------------------------------------------------------- 고르기와 기록
def parse_picks(values: list[str], recipe: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    """`v002` (모든 방향) 또는 `front=v001` (방향 하나) 을 {방향: 버전} 으로 바꾼다. 뒤에 적은 것이 이긴다.

    둘째 값은 방향을 콕 집어 적은 것들이다. 통째로 고른 버전에 없는 방향은 건너뛰지만,
    콕 집은 방향이 없으면 오류다.
    """
    known = [v["id"] for v in recipe["views"]]
    picks: dict[str, str] = {}
    explicit: set[str] = set()
    for value in values:
        view, sep, version = value.partition("=")
        if not sep:
            view, version = "", value
        if not re.fullmatch(r"v\d{3}", version):
            raise SheetError(f"버전은 v001 처럼 적는다: {value}")
        if view and view not in known:
            raise SheetError(f"레시피에 없는 방향: {view}")
        for v in ([view] if view else known):
            picks[v] = version
        if view:
            explicit.add(view)
        else:
            explicit.clear()
    return picks, explicit


def load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def select(product: Product, picks: dict[str, str], recipe: dict[str, Any], example_dir: Path,
           output_dir: Path, bible_version: str, selected_by: str, note: str = "",
           now: str | None = None, explicit: set[str] | None = None) -> dict[str, Any]:
    """사람이 고른 후보를 reference 폴더로 옮기고 reference_manifest.json 을 쓴다.

    고르지 않은 방향은 앞서 고른 것을 그대로 둔다. 앞선 기록은 history 에 한 줄로 남긴다.
    """
    if not selected_by.strip():
        raise SheetError("누가 골랐는지 적는다 (--by 이름). 고르는 일은 사람이 한다")
    root = sheet_root(product.id, output_dir)
    ext = _extension(recipe)
    target = reference_dir(product.id, recipe, example_dir)
    path = manifest_path(product.id, recipe, example_dir)
    previous = load_manifest(path)
    images: dict[str, dict[str, Any]] = {i["view"]: i for i in (previous or {}).get("images", [])}

    chosen: list[tuple[str, str, Path]] = []
    for view, version in picks.items():
        source = root / version / f"{view}{ext}"
        if not source.is_file():
            if explicit is not None and view not in explicit:
                continue                      # `v002` 로 통째 골랐는데 그 버전에 없는 방향은 건너뛴다
            raise SheetError(f"{version} 에 {view} 이미지가 없다 ({source})")
        chosen.append((view, version, source))
    if not chosen:
        raise SheetError("고른 버전에 이미지가 하나도 없다")

    target.mkdir(parents=True, exist_ok=True)
    for view, version, source in chosen:
        dest = target / f"{view}{ext}"
        shutil.copyfile(source, dest)
        record_path = source.with_suffix(".api_run.json")
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
        images[view] = {
            "view": view, "file": f"{target.name}/{dest.name}", "sha256": sha256_file(dest),
            "bytes": dest.stat().st_size, "from_version": version, "run_id": record.get("run_id"),
            "model": record.get("model"), "prompt_sha256": record.get("prompt_sha256"),
        }

    order = [v["id"] for v in recipe["views"]]
    sheet_doc = root / chosen[0][1] / "sheet.json"
    mode = json.loads(sheet_doc.read_text(encoding="utf-8")).get("mode") if sheet_doc.is_file() else None
    history = list((previous or {}).get("history", []))
    if previous:
        history.append({"manifest_version": previous.get("manifest_version"), "selected_at": previous.get("selected_at"),
                        "selected_by": previous.get("selected_by"), "note": previous.get("note", ""),
                        "images": {i["view"]: i.get("from_version") for i in previous.get("images", [])}})
    manifest = {
        "product_id": product.id, "manifest_version": int((previous or {}).get("manifest_version", 0)) + 1,
        "selected_at": now or datetime.now().isoformat(timespec="seconds"), "selected_by": selected_by.strip(),
        "note": note, "bible_version": bible_version, "appearance_en": product.appearance_en,
        "appearance_sha256": sha256_text(product.appearance_en), "source_mode": mode,
        "images": sorted(images.values(), key=lambda i: order.index(i["view"]) if i["view"] in order else 99),
        "history": history,
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def manifest_problems(product: Product, manifest: dict[str, Any] | None, recipe: dict[str, Any],
                      example_dir: Path) -> list[str]:
    """고른 레퍼런스가 지금의 제품 바이블과 맞는지 본다. 비어 있으면 문제없다."""
    if manifest is None:
        return ["레퍼런스를 아직 고르지 않았다"]
    problems: list[str] = []
    if manifest.get("appearance_sha256") != sha256_text(product.appearance_en):
        problems.append("레퍼런스를 고른 뒤에 외형 서술이 바뀌었다. 레퍼런스를 다시 만들거나 서술을 되돌린다")
    base = manifest_path(product.id, recipe, example_dir).parent
    for image in manifest.get("images", []):
        file = base / image["file"]
        if not file.is_file():
            problems.append(f"{image['view']}: 파일이 없다 ({image['file']})")
        elif sha256_file(file) != image.get("sha256"):
            problems.append(f"{image['view']}: 고른 뒤에 파일이 바뀌었다 ({image['file']})")
    return problems


def manifest_line(manifest: dict[str, Any] | None) -> str:
    if manifest is None:
        return "없음"
    versions = sorted({i.get("from_version") or "?" for i in manifest.get("images", [])})
    return (f"{len(manifest.get('images', []))}장 · {', '.join(versions)} 에서 고름 · "
            f"{str(manifest.get('selected_at', ''))[:10]} · {manifest.get('selected_by', '')}")
