"""gen_mode — 생성 모드와 레퍼런스 배분 (7장).

    글만(text)            프롬프트만 보낸다. 4장까지 쓴 방식
    제품 레퍼런스(reference)  5장에서 고른 레퍼런스 이미지를 함께 보낸다
    첫 프레임(image)       이미지 한 장에서 시작한다
    첫·끝 프레임(frames)    두 장 사이를 잇는다

이미지를 어떤 역할로 쓸지는 요청의 필드가 아니라 프롬프트의 태그로 알린다 (Gemini API Omni 가이드):
    [# References <IMAGE_REF_0>@Image1 <IMAGE_REF_1>@Image2]     태그 번호는 0부터, 파일 표지(Image1)는 1부터
    [# Sources <FIRST_FRAME>@Image1 <LAST_FRAME>@Image2]
가이드의 예제는 1.1 기준이다. 1.2 에서 같은지, 태그가 실제로 일관성을 높이는지는 실험(E01, E12)으로 확인한다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ass.production import reference_sheet as rs
from ass.production.product_bible import Product


class ModeError(Exception):
    """이 모드로 생성할 수 없다. 메시지에 무엇을 먼저 해야 하는지 적는다."""


class InputImage(BaseModel):
    path: str
    tag: str                       # <IMAGE_REF_0>, <FIRST_FRAME>, <LAST_FRAME>
    product_id: str | None = None
    view: str | None = None
    sha256: str


class GenPlan(BaseModel):
    mode: str
    name_ko: str
    task: str | None = None        # send_task 가 켜져 있을 때만 요청에 넣는다
    images: list[InputImage] = []
    prompt: str                    # 선언과 안내 줄을 앞에 붙인, 실제로 보낼 프롬프트
    prompt_sha256: str             # 프롬프트와 이미지의 sha256 을 함께 넣어 만든다. 모드가 다르면 다른 요청이다

    def image_paths(self) -> list[str]:
        return [i.path for i in self.images]

    def summary(self) -> list[dict[str, Any]]:
        return [{"tag": i.tag, "product_id": i.product_id, "view": i.view, "file": Path(i.path).name,
                 "sha256": i.sha256[:12]} for i in self.images]


def _sha(prompt: str, images: list[InputImage]) -> str:
    h = hashlib.sha256(prompt.encode("utf-8"))
    for image in images:
        h.update(image.sha256.encode("ascii"))
    return h.hexdigest()


def reference_views(policy: dict[str, Any], product_count: int, override: list[str] | None = None) -> list[str]:
    """제품 하나에 보낼 방향. 제품이 많을수록 제품마다 적게 보낸다."""
    if override:
        return override
    table = {int(k): v for k, v in policy["reference"]["views_by_product_count"].items()}
    return list(table.get(product_count) or table[max(table)])


def allocate(products: list[Product], policy: dict[str, Any], sheet_recipe: dict[str, Any], project_dir: Path,
             override: list[str] | None = None) -> list[InputImage]:
    """장면에 나오는 제품의 레퍼런스를 고른다. 사람이 고른 기록(reference_manifest.json)이 있는 것만 쓴다."""
    if not products:
        raise ModeError("이 장면에는 제품이 없다. 제품 레퍼런스 모드는 제품이 나오는 장면에만 쓴다. 글만(text)으로 생성한다")
    views = reference_views(policy, len(products), override)
    known = {v["id"] for v in sheet_recipe["views"]}
    unknown = [v for v in views if v not in known]
    if unknown:
        raise ModeError(f"없는 방향: {', '.join(unknown)}. 있는 것: {', '.join(sorted(known))}")
    images: list[InputImage] = []
    for product in products:
        manifest = rs.load_manifest(rs.manifest_path(product.id, sheet_recipe, project_dir))
        if manifest is None:
            raise ModeError(f"{product.name_ko}의 레퍼런스를 아직 고르지 않았다. 5장의 순서대로 한다: "
                            f"단계 “3. 제품 레퍼런스” → [실행], 그다음 [작업] → 레퍼런스 고르기")
        chosen = {i["view"]: i for i in manifest.get("images", [])}
        folder = rs.reference_dir(product.id, sheet_recipe, project_dir)
        for view in views:
            entry = chosen.get(view)
            path = folder / Path(entry["file"]).name if entry else None
            if path is None or not path.is_file():
                raise ModeError(f"{product.name_ko}의 {view} 레퍼런스가 없다. [작업] → 레퍼런스 고르기에서 고른다")
            images.append(InputImage(path=str(path), tag=f"<IMAGE_REF_{len(images)}>", product_id=product.id,
                                     view=view, sha256=rs.sha256_file(path)))
    limit = int(policy["reference"]["max_images"])
    if len(images) > limit:
        raise ModeError(f"레퍼런스가 {len(images)}장이다. {limit}장까지 보낸다. --views 로 방향을 줄인다")
    return images


def _declaration(kind: str, images: list[InputImage]) -> str:
    return f"[# {kind} " + " ".join(f"{image.tag}@Image{n}" for n, image in enumerate(images, 1)) + "]"


def plan(mode: str, prompt: str, policy: dict[str, Any], *, products: list[Product] | None = None,
         sheet_recipe: dict[str, Any] | None = None, project_dir: Path | None = None,
         views: list[str] | None = None, first_frame: str | Path | None = None,
         last_frame: str | Path | None = None) -> GenPlan:
    """모드에 맞게 보낼 이미지와 프롬프트를 정한다. 네트워크를 쓰지 않는다."""
    if mode not in policy["modes"]:
        raise ModeError(f"없는 모드: {mode}. 있는 것: {', '.join(policy['modes'])}")
    spec = policy["modes"][mode]
    task = spec.get("task") if policy.get("send_task") else None
    if mode == "text":
        if first_frame or last_frame or views:
            raise ModeError("글만(text) 모드에는 이미지를 주지 않는다. --mode 를 바꾼다")
        return GenPlan(mode=mode, name_ko=spec["name_ko"], task=task, prompt=prompt,
                       prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest())
    if mode == "reference":
        if sheet_recipe is None or project_dir is None:
            raise ModeError("레퍼런스 모드는 장면 사양으로 생성할 때만 쓴다 (--prompt 와 함께 쓰지 않는다)")
        images = allocate(products or [], policy, sheet_recipe, project_dir, views)
        names = []
        for product in products or []:
            tags = " ".join(i.tag for i in images if i.product_id == product.id)
            shown = ", ".join(str(i.view).replace("_", " ") for i in images if i.product_id == product.id)
            names.append(f"{tags} show {product.name_en} ({shown})")
        head = (f"{_declaration('References', images)}\nReference images: " + "; ".join(names) + ". "
                + policy["reference"]["keep_line_en"])
        full = f"{head}\n{prompt}"
        return GenPlan(mode=mode, name_ko=spec["name_ko"], task=task, images=images, prompt=full,
                       prompt_sha256=_sha(full, images))
    wanted = [("<FIRST_FRAME>", first_frame)] + ([("<LAST_FRAME>", last_frame)] if mode == "frames" else [])
    if mode == "image" and last_frame:
        raise ModeError("첫 프레임(image) 모드에는 끝 프레임을 주지 않는다. 첫·끝 프레임은 --mode frames")
    images = []
    for tag, path in wanted:
        if not path:
            raise ModeError(f"{spec['name_ko']} 모드에는 {'--first-frame' if tag == '<FIRST_FRAME>' else '--last-frame'} 이 있어야 한다")
        file = Path(path)
        if not file.is_file():
            raise ModeError(f"이미지가 없다: {file}")
        images.append(InputImage(path=str(file), tag=tag, sha256=rs.sha256_file(file)))
    full = f"{_declaration('Sources', images)}\n{' '.join(i.tag for i in images)} {prompt}"
    return GenPlan(mode=mode, name_ko=spec["name_ko"], task=task, images=images, prompt=full,
                   prompt_sha256=_sha(full, images))
