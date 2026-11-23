"""비용 가드 (4.3절, 5.3절, 8.5절).

호출 전에 추정 비용을 계산하고, 예산 상한을 넘으면 호출을 막는다.
단가가 공식 문서나 실험으로 확인되지 않은 해상도는 추정하지 않고 UnknownPrice 를 낸다.
"""
from __future__ import annotations

from typing import Any


class UnknownPrice(Exception):
    """단가가 확인되지 않은 호출."""


class BudgetExceeded(Exception):
    """예산 상한 초과."""


def estimate_video_cost(duration_s: int, resolution: str, models_config: dict[str, Any]) -> float:
    """영상 생성 1회의 추정 비용(USD) = 초 × 초당 단가."""
    prices = models_config["video"]["price_usd_per_second"]
    unit = prices.get(resolution)
    if unit is None:
        raise UnknownPrice(
            f"{resolution} 단가가 확인되지 않았다. configs/models.yaml 에 확인된 값을 넣은 뒤 호출한다."
        )
    return round(duration_s * float(unit), 4)


def estimate_image_cost(image_size: str, models_config: dict[str, Any], count: int = 1) -> float:
    """이미지 생성의 추정 비용(USD) = 장수 × 장당 단가. 출력 이미지 값만 센다.

    레퍼런스 이미지와 프롬프트의 입력 토큰, 사고(thinking) 토큰은 따로 청구되는데 여기에 넣지 않는다.
    한 장에 얼마가 붙는지 확인하지 못했다(E07). 그래서 실제 청구액은 이 값보다 조금 많다.
    """
    prices = models_config["image"].get("price_usd_per_image", {})
    unit = prices.get(image_size)
    if unit is None:
        raise UnknownPrice(
            f"이미지 크기 {image_size} 의 단가가 확인되지 않았다. 1K, 2K, 4K 가운데 하나를 대문자 K 로 적는다."
        )
    return round(count * float(unit), 4)


def estimate_text_cost(input_chars: int, models_config: dict[str, Any], output_tokens: int = 4000) -> float:
    """글 모델 한 번 호출의 어림 상한(USD). 입력은 글자 수를 토큰 수로 치고, 출력은 정해 둔 상한으로 센다.

    글자 하나가 토큰 몇 개인지, 사고 토큰이 얼마나 붙는지 확인하지 못했다. 단가도 확인하지 못해 높은 쪽 값을 쓴다.
    그래서 이 값은 '많아야 이만큼'이라는 어림이고, 실제 청구액은 대개 이보다 적을 것으로 본다(E15 에서 확인).
    """
    text = models_config.get("text") or {}
    price_in, price_out = text.get("price_usd_per_1m_input_tokens"), text.get("price_usd_per_1m_output_tokens")
    if price_in is None or price_out is None:
        raise UnknownPrice("글 모델의 단가가 없다. configs/models.yaml 의 text 를 확인한다")
    return round(input_chars * float(price_in) / 1e6 + output_tokens * float(price_out) / 1e6, 4)


class BudgetGuard:
    """누적 추정 비용이 상한을 넘지 않게 지킨다."""

    def __init__(self, cap_usd: float) -> None:
        if cap_usd <= 0:
            raise ValueError("예산 상한은 0보다 커야 한다")
        self.cap_usd = cap_usd
        self.spent_usd = 0.0

    @property
    def remaining_usd(self) -> float:
        return round(self.cap_usd - self.spent_usd, 4)

    def charge(self, amount_usd: float, label: str = "") -> None:
        """호출 직전에 부른다. 상한을 넘으면 누적하지 않고 예외를 낸다."""
        if self.spent_usd + amount_usd > self.cap_usd + 1e-9:
            raise BudgetExceeded(
                f"{label or '호출'} ${amount_usd:.2f} 는 남은 예산 ${self.remaining_usd:.2f} 를 넘는다 "
                f"(상한 ${self.cap_usd:.2f})"
            )
        self.spent_usd = round(self.spent_usd + amount_usd, 4)
