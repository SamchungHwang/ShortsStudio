"""제품 바이블 (5.1절).

영상에 나오는 제품의 외형과, 내레이션·자막에서 말해도 되는 사실을 한곳에 둔다.
대본은 여기 있는 사실(fact)만 근거로 쓴다. 써도 되는 표현(say)과 쓰지 않는 표현(dont_say)도
제품마다 적어 둔다. 점검은 bible_lint.py, 레퍼런스 이미지는 reference_sheet.py 가 맡는다.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from ass.settings import load_yaml


class Fact(BaseModel):
    id: str
    text_ko: str
    source: str                 # 근거. 예: 제품 상세 페이지, 성분표, 시험 성적서


class Say(BaseModel):
    """써도 되는 표현. 근거가 되는 사실을 단다."""
    text_ko: str
    evidence: list[str] = []


class DontSay(BaseModel):
    """이 제품에 쓰지 않는 표현과 이유. 대본에 나오면 컴파일이 막는다."""
    text_ko: str
    reason: str


class Product(BaseModel):
    id: str
    brand: str
    name_ko: str
    name_en: str
    appearance_en: str          # 모든 장면 프롬프트와 레퍼런스 시트가 공유하는 외형 서술
    appearance_ko: str = ""     # 사람이 읽고 확인하는 우리말 서술. 모델에는 보내지 않는다
    label_text: str = ""        # 라벨에 실제로 적힌 글자. 화면에서 이 글자가 읽히는지 본다
    is_own: bool = True         # False 면 타사 제품. 비교 표현은 사람 승인 대상
    facts: list[Fact] = []
    say: list[Say] = []
    dont_say: list[DontSay] = []

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


def squeeze(text: str) -> str:
    """띄어쓰기와 문장 부호를 빼고 견준다. '24 시간'과 '24시간'을 같은 것으로 본다."""
    return "".join(ch for ch in text if ch.isalnum())


def find_dont_say(product: Product, text: str) -> list[DontSay]:
    """글에 이 제품의 '쓰지 않는 표현'이 들어 있으면 돌려준다."""
    flat = squeeze(text)
    return [d for d in product.dont_say if squeeze(d.text_ko) and squeeze(d.text_ko) in flat]
