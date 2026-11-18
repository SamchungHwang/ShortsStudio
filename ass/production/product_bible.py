"""제품 바이블 (5.1절).

영상에 나오는 제품의 외형과, 내레이션·자막에서 말해도 되는 사실을 한곳에 둔다.
대본은 여기 있는 사실(fact)만 근거로 쓴다.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from ass.settings import load_yaml


class Fact(BaseModel):
    id: str
    text_ko: str
    source: str                 # 근거. 예: 제품 상세 페이지, 성분표, 시험 성적서


class Product(BaseModel):
    id: str
    brand: str
    name_ko: str
    name_en: str
    appearance_en: str          # 모든 장면 프롬프트가 공유하는 외형 서술
    is_own: bool = True         # False 면 타사 제품. 비교 표현은 사람 승인 대상
    facts: list[Fact] = []
    reference_images: list[str] = []

    def fact_ids(self) -> set[str]:
        return {f.id for f in self.facts}


class ProductBible(BaseModel):
    version: str
    products: dict[str, Product]

    def get(self, product_id: str) -> Product:
        try:
            return self.products[product_id]
        except KeyError:
            raise KeyError(f"제품 바이블에 없는 제품: {product_id}") from None


def load_product_bible(path: str | Path) -> ProductBible:
    doc = load_yaml(path)
    products = {pid: Product(id=pid, **body) for pid, body in doc["products"].items()}
    return ProductBible(version=str(doc["version"]), products=products)
