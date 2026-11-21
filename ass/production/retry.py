"""한도와 오류를 만났을 때 다시 시도하는 규칙 (4.4절).

다시 해도 되는 오류(429, 500, 503)와 다시 해도 같은 오류(400, 401, 402, 403, 404)를 가른다.
규칙은 configs/retry_policy.yaml 에 있다. 응답이 끊긴 호출은 기본으로 다시 시도하지 않는다.
서버에서 생성이 끝나 청구됐을 수 있어서다.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")
_CODE = re.compile(r"(?:Error code:\s*|^\s*)(\d{3})\b")


def status_code(exc: BaseException) -> int | None:
    """예외에서 HTTP 상태 코드를 꺼낸다. SDK 마다 자리가 달라 속성과 메시지를 차례로 본다."""
    for name in ("code", "status_code", "status"):
        value = getattr(exc, name, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    match = _CODE.search(str(exc))
    return int(match.group(1)) if match else None


def is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower()


def should_retry(exc: BaseException, policy: dict[str, Any]) -> bool:
    code = status_code(exc)
    if code is not None:
        if code in policy.get("never_retry_status", []):
            return False
        return code in policy.get("retry_on_status", [])
    if is_timeout(exc):
        return bool(policy.get("retry_on_timeout", False))
    return False


def delay_s(attempt: int, policy: dict[str, Any]) -> float:
    """attempt 번째 시도가 실패한 뒤 기다릴 시간. 30초, 60초, 120초처럼 두 배씩 는다."""
    return float(policy.get("base_delay_s", 30)) * (2 ** (attempt - 1))


def call_with_retry(
    call: Callable[[], T],
    policy: dict[str, Any],
    *,
    before_attempt: Callable[[int], None] | None = None,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, list[str]]:
    """call 을 부르고, 다시 해도 되는 오류면 기다렸다가 다시 부른다.

    before_attempt(n) 은 n 번째 시도 직전에 불린다. 비용 가드가 여기서 추정 비용을 한 번 더 뺀다.
    돌려주는 값은 (결과, 앞선 시도들의 오류 목록)이다. 끝내 실패하면 마지막 예외를 그대로 올리고,
    그 예외의 attempt_errors 속성에 앞선 오류를 붙여 둔다.
    """
    max_attempts = max(1, int(policy.get("max_attempts", 1)))
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        if before_attempt:
            before_attempt(attempt)
        try:
            return call(), errors
        except Exception as exc:
            if attempt == max_attempts or not should_retry(exc, policy):
                exc.attempt_errors = errors          # type: ignore[attr-defined]
                exc.attempts = attempt               # type: ignore[attr-defined]
                raise
            errors.append(f"{type(exc).__name__}: {exc}")
            wait = delay_s(attempt, policy)
            if on_retry:
                on_retry(attempt, exc, wait)
            sleep(wait)
    raise AssertionError("도달하지 않는다")
