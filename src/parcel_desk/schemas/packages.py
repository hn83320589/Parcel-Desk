from pydantic import BaseModel, Field, field_validator, model_validator

from parcel_desk.models import (
    Counter,
    NotificationKind,
    PackageStatus,
    PackageType,
    PickerType,
)
from parcel_desk.schemas.common import LocalDateTime, ORMModel, UnitCode


class PackageCreate(BaseModel):
    unit_code: UnitCode = Field(examples=["A-12F-3"])
    recipient_name: str | None = Field(default=None, max_length=50)
    carrier: str = Field(min_length=1, max_length=50, examples=["黑貓宅急便"])
    tracking_no: str | None = Field(default=None, max_length=100)
    type: PackageType = PackageType.NORMAL


class PickupRequest(BaseModel):
    counter: Counter
    picker_type: PickerType
    picker_user_id: int | None = Field(default=None, description="picker_type=resident 時必填")
    picker_proxy_id: int | None = Field(default=None, description="picker_type=proxy 時必填")

    @model_validator(mode="after")
    def _picker_matches_type(self):
        if self.picker_type == PickerType.RESIDENT and self.picker_user_id is None:
            raise ValueError("住戶本人領取時必須提供 picker_user_id")
        if self.picker_type == PickerType.PROXY and self.picker_proxy_id is None:
            raise ValueError("代領時必須提供 picker_proxy_id")
        return self


class PickupByCodeRequest(PickupRequest):
    pickup_code: str = Field(pattern=r"^\d{6}$", examples=["123456"])


class ExceptionRequest(BaseModel):
    status: PackageStatus = Field(description="returned（退回物流）或 lost（遺失）")
    reason: str = Field(max_length=500)

    @field_validator("status")
    @classmethod
    def _only_exception_status(cls, value: PackageStatus) -> PackageStatus:
        if value not in (PackageStatus.RETURNED, PackageStatus.LOST):
            raise ValueError("只能標記為 returned 或 lost")
        return value

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("必須填寫原因")
        return value


class PickupOut(ORMModel):
    picker_type: PickerType
    picker_name: str
    picker_user_id: int | None
    picker_proxy_id: int | None
    staff_id: int
    counter: Counter
    picked_up_at: LocalDateTime


class PackageOut(ORMModel):
    id: int
    unit_code: str
    recipient_name: str | None
    carrier: str
    tracking_no: str | None
    type: PackageType
    status: PackageStatus
    pickup_code: str
    registered_at: LocalDateTime
    registered_by: int
    needs_attention_at: LocalDateTime | None
    exception_reason: str | None
    exception_at: LocalDateTime | None
    pickup: PickupOut | None


class NotificationOut(ORMModel):
    id: int
    kind: NotificationKind
    unit_code: str | None
    title: str
    body: str
    created_at: LocalDateTime
    package_ids: list[int]
    recipient_ids: list[int]
