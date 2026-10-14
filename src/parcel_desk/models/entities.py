from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from parcel_desk.models.base import Base, UTCDateTime, str_enum


class Role(StrEnum):
    ADMIN = "admin"
    STAFF = "staff"
    RESIDENT = "resident"


class PackageType(StrEnum):
    NORMAL = "normal"
    LARGE = "large"
    COLD = "cold"


class PackageStatus(StrEnum):
    PENDING = "pending"
    PICKED_UP = "picked_up"
    RETURNED = "returned"
    LOST = "lost"


class Counter(StrEnum):
    A = "A"
    B = "B"


class PickerType(StrEnum):
    RESIDENT = "resident"
    PROXY = "proxy"


class NotificationKind(StrEnum):
    ARRIVAL = "arrival"
    OVERDUE_REMINDER = "overdue_reminder"
    COLD_REMINDER = "cold_reminder"
    NEEDS_ATTENTION = "needs_attention"


class ReminderKind(StrEnum):
    OVERDUE_DAILY = "overdue_daily"
    COLD_24H = "cold_24h"
    COLD_48H = "cold_48h"


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    building: Mapped[str] = mapped_column(String(1))
    floor: Mapped[int]
    number: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    residents: Mapped[list["User"]] = relationship(back_populates="unit")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # 住戶必須屬於一戶；管委會、管理員不屬於任何戶
        CheckConstraint("(role = 'resident') = (unit_id IS NOT NULL)", name="resident_has_unit"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(50))
    role: Mapped[Role] = mapped_column(str_enum(Role))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"), index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    unit: Mapped[Unit | None] = relationship(back_populates="residents")

    @property
    def unit_code(self) -> str | None:
        return self.unit.code if self.unit else None


class Proxy(Base):
    """代領人：不需要帳號，簽收時由管理員從名單選擇並核對證件。"""

    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(20))
    id_last4: Mapped[str | None] = mapped_column(String(4))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    unit: Mapped[Unit] = relationship()

    def is_valid_at(self, now: datetime) -> bool:
        return self.revoked_at is None and self.valid_from <= now <= self.valid_until


class Package(Base):
    __tablename__ = "packages"
    __table_args__ = (
        # 領取碼只在「待領」的包裹之間唯一；簽收/退回/遺失後自動釋出，可被新包裹重用
        Index(
            "uq_packages_active_pickup_code",
            "pickup_code",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_packages_unit_id_registered_at", "unit_id", "registered_at"),
        Index("ix_packages_status_registered_at", "status", "registered_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    recipient_name: Mapped[str | None] = mapped_column(String(50))
    carrier: Mapped[str] = mapped_column(String(50))
    tracking_no: Mapped[str | None] = mapped_column(String(100))
    type: Mapped[PackageType] = mapped_column(str_enum(PackageType))
    status: Mapped[PackageStatus] = mapped_column(str_enum(PackageStatus))
    pickup_code: Mapped[str] = mapped_column(String(6))
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime())
    registered_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # 冷藏超過 48 小時的「需處理」旗標；不是狀態，包裹仍可簽收
    needs_attention_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    exception_reason: Mapped[str | None] = mapped_column(String(500))
    exception_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    exception_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    unit: Mapped[Unit] = relationship(lazy="joined")
    pickup: Mapped["Pickup | None"] = relationship(back_populates="package", lazy="joined")

    @property
    def unit_code(self) -> str:
        return self.unit.code


class Pickup(Base):
    """簽收紀錄，與包裹 1:1；package_id UNIQUE 是防止重複簽收的最後一道防線。"""

    __tablename__ = "pickups"

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), unique=True)
    picker_type: Mapped[PickerType] = mapped_column(str_enum(PickerType))
    picker_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    picker_proxy_id: Mapped[int | None] = mapped_column(ForeignKey("proxies.id"))
    picker_name: Mapped[str] = mapped_column(String(50))
    staff_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    counter: Mapped[Counter] = mapped_column(str_enum(Counter))
    picked_up_at: Mapped[datetime] = mapped_column(UTCDateTime())

    package: Mapped[Package] = relationship(back_populates="pickup")
    staff: Mapped[User] = relationship(foreign_keys=[staff_id], lazy="joined")


notification_packages = Table(
    "notification_packages",
    Base.metadata,
    Column("notification_id", ForeignKey("notifications.id"), primary_key=True),
    Column("package_id", ForeignKey("packages.id"), primary_key=True),
)

notification_recipients = Table(
    "notification_recipients",
    Base.metadata,
    Column("notification_id", ForeignKey("notifications.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_unit_id_created_at", "unit_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[NotificationKind] = mapped_column(str_enum(NotificationKind))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"))
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    # 只有到件通知使用：這個時間之前同戶登記的包裹會併入此通知
    window_ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    unit: Mapped[Unit | None] = relationship()
    packages: Mapped[list[Package]] = relationship(
        secondary=notification_packages, order_by=Package.id
    )
    recipients: Mapped[list[User]] = relationship(secondary=notification_recipients)

    @property
    def unit_code(self) -> str | None:
        return self.unit.code if self.unit else None

    @property
    def package_ids(self) -> list[int]:
        return [p.id for p in self.packages]

    @property
    def recipient_ids(self) -> list[int]:
        return [u.id for u in self.recipients]


class PackageReminder(Base):
    """提醒去重紀錄：唯一鍵保證同一件包裹同一種提醒一天最多一則。"""

    __tablename__ = "package_reminders"
    __table_args__ = (UniqueConstraint("package_id", "kind", "remind_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"))
    kind: Mapped[ReminderKind] = mapped_column(str_enum(ReminderKind))
    remind_date: Mapped[date] = mapped_column(Date())
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
