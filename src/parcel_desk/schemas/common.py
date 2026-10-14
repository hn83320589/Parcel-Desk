import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer

from parcel_desk.clock import ensure_aware, to_local

UNIT_CODE_PATTERN = re.compile(r"^([A-Z])-([1-9]\d{0,2})F-([1-9]\d{0,2})$")
UNIT_CODE_EXAMPLE = "A-12F-3"


def parse_unit_code(value: str) -> tuple[str, int, int]:
    """回傳 (棟別, 樓層, 號)；格式錯誤時丟出 ValueError（Pydantic 會轉成 422）。"""
    match = UNIT_CODE_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"戶號格式錯誤，應為「棟別-樓層F-號」，例如 {UNIT_CODE_EXAMPLE}")
    building, floor, number = match.groups()
    return building, int(floor), int(number)


def _validate_unit_code(value: str) -> str:
    parse_unit_code(value)
    return value


UnitCode = Annotated[str, AfterValidator(_validate_unit_code)]

# 輸入：沒有時區的時間視為台北時間；輸出：一律以台北時間（+08:00）呈現，方便現場閱讀
InputDateTime = Annotated[datetime, AfterValidator(ensure_aware)]
LocalDateTime = Annotated[
    datetime, PlainSerializer(lambda dt: to_local(dt).isoformat(), return_type=str)
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
