from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from parcel_desk.models import Proxy
from parcel_desk.schemas.common import InputDateTime, LocalDateTime, UnitCode


class ProxyCreate(BaseModel):
    unit_code: UnitCode | None = Field(
        default=None, description="管委會代為建立時必填；住戶建立時固定為自家，可省略"
    )
    name: str = Field(min_length=1, max_length=50)
    phone: str | None = Field(default=None, max_length=20)
    id_last4: str | None = Field(default=None, pattern=r"^\d{4}$", description="證件末四碼")
    valid_from: InputDateTime | None = Field(default=None, description="省略時為現在")
    valid_until: InputDateTime = Field(description="到期時間，沒有時區時視為台北時間")

    @model_validator(mode="after")
    def _range(self):
        if self.valid_from is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until 必須晚於 valid_from")
        return self


class ProxyOut(BaseModel):
    id: int
    unit_code: str
    name: str
    phone: str | None
    id_last4: str | None
    valid_from: LocalDateTime
    valid_until: LocalDateTime
    revoked_at: LocalDateTime | None
    is_valid: bool = Field(description="以目前時間判斷是否可代領")

    @classmethod
    def build(cls, proxy: Proxy, now: datetime) -> "ProxyOut":
        return cls(
            id=proxy.id,
            unit_code=proxy.unit_code,
            name=proxy.name,
            phone=proxy.phone,
            id_last4=proxy.id_last4,
            valid_from=proxy.valid_from,
            valid_until=proxy.valid_until,
            revoked_at=proxy.revoked_at,
            is_valid=proxy.is_valid_at(now),
        )
