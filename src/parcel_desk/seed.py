"""示範（seed）資料，只會寫入 `parcel-desk demo` 使用的示範資料庫。

透過與 API 相同的 service 層、依時間順序「重演」過去約 40 天的作業，
因此通知合併、逾期提醒、簽收紀錄都與真實流程一致。

帳號（密碼）：
  admin / admin1234            管委會
  staff_a / staff1234          A 棟櫃台管理員
  staff_b / staff1234          B 棟櫃台管理員
  a12f3_1 / resident1234       住戶（帳號規則：棟別小寫 + 樓層 + f + 號 + _序號）
"""

import heapq
import os
import random
from collections import Counter as Tally
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from itertools import count
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from parcel_desk.clock import local_date, local_datetime
from parcel_desk.db import make_engine, make_session_factory, run_migrations
from parcel_desk.models import (
    Counter,
    Package,
    PackageStatus,
    PackageType,
    PickerType,
    Proxy,
    Role,
    Unit,
    User,
)
from parcel_desk.schemas.packages import PickupRequest
from parcel_desk.services.packages import mark_exception, register_package
from parcel_desk.services.pickups import pick_up
from parcel_desk.services.proxies import create_proxy
from parcel_desk.services.reminders import run_reminders
from parcel_desk.services.units import create_unit, list_residents
from parcel_desk.services.users import create_user

BUILDINGS = ("A", "B")
FLOORS = (10, 11, 12)
NUMBERS = (1, 2, 3, 4)
HISTORY_DAYS = 40
RANDOM_PACKAGES = 60

CARRIERS = (
    "黑貓宅急便",
    "新竹物流",
    "中華郵政",
    "統一速達",
    "嘉里大榮",
    "蝦皮店到店",
    "momo 富昇物流",
)
SURNAMES = "陳林黃張李王吳劉蔡楊許鄭謝郭洪"
GIVEN_NAMES = ("志明", "春嬌", "怡君", "家豪", "雅婷", "冠宇", "淑芬", "俊傑", "佳穎", "宗翰")


@dataclass
class SeedSummary:
    units: int = 0
    users: int = 0
    proxies: int = 0
    packages: Tally = field(default_factory=Tally)

    def __str__(self) -> str:
        statuses = "、".join(f"{k} {v}" for k, v in sorted(self.packages.items()))
        return (
            f"戶別 {self.units}、帳號 {self.users}、代領人 {self.proxies}、"
            f"包裹 {sum(self.packages.values())} 件（{statuses}）"
        )


def _remove_sqlite_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def build_demo_database(path: Path, now: datetime) -> SeedSummary:
    """建立示範資料庫，具原子性。

    seed 依 service 流程逐步 commit，本身不具原子性；因此先在暫存檔完成 migration 與 seed，
    全部成功後才以 os.replace 改名成正式檔名。中途中斷時不會留下半套資料，
    已存在的舊示範資料庫也要等新的建好才會被取代。
    """
    building = path.with_name(path.name + ".building")
    _remove_sqlite_files(building)  # 上次中斷留下的暫存檔
    try:
        run_migrations(building)
        engine = make_engine(building)
        try:
            with make_session_factory(engine)() as session:
                summary = seed(session, now)
            # 把 WAL 內容寫回主檔，改名後的資料庫檔才是完整的
            with engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            engine.dispose()
        _remove_sqlite_files(path)
        os.replace(building, path)
    finally:
        _remove_sqlite_files(building)
    return summary


def seed(session: Session, now: datetime, rng_seed: int = 2026) -> SeedSummary:
    rng = random.Random(rng_seed)
    origin = local_datetime(local_date(now) - timedelta(days=HISTORY_DAYS))
    summary = SeedSummary()

    staff = _create_accounts(session, origin)
    units = _create_units_and_residents(session, origin, rng)
    summary.units = len(units)
    valid_proxies = _create_proxies(session, units, staff["admin"], now)

    _replay_history(session, rng, units, staff, valid_proxies, origin, now)

    summary.users = session.scalar(select(func.count()).select_from(User))
    summary.proxies = session.scalar(select(func.count()).select_from(Proxy))
    summary.packages = Tally(p.status.value for p in session.scalars(select(Package)).unique())
    return summary


def _create_accounts(session: Session, now: datetime) -> dict[str, User]:
    specs = [
        ("admin", "admin1234", "管委會主委", Role.ADMIN),
        ("staff_a", "staff1234", "A 棟管理員", Role.STAFF),
        ("staff_b", "staff1234", "B 棟管理員", Role.STAFF),
    ]
    return {
        username: create_user(
            session,
            username=username,
            password=password,
            display_name=name,
            role=role,
            unit_code=None,
            now=now,
        )
        for username, password, name, role in specs
    }


def _create_units_and_residents(session: Session, now: datetime, rng: random.Random) -> list[Unit]:
    units = []
    for building in BUILDINGS:
        for floor in FLOORS:
            for number in NUMBERS:
                code = f"{building}-{floor}F-{number}"
                unit = create_unit(session, code, now)
                surname = rng.choice(SURNAMES)
                # A-12F-3 固定 2 位住戶，方便依 README 示範
                residents = 2 if code == "A-12F-3" else rng.randint(1, 3)
                for i in range(1, residents + 1):
                    create_user(
                        session,
                        username=f"{building.lower()}{floor}f{number}_{i}",
                        password="resident1234",
                        display_name=surname + rng.choice(GIVEN_NAMES),
                        role=Role.RESIDENT,
                        unit_code=code,
                        now=now,
                    )
                units.append(unit)
    return units


def _create_proxies(
    session: Session, units: list[Unit], admin: User, now: datetime
) -> dict[int, Proxy]:
    """前 8 戶各有一位有效代領人；另有過期與已撤銷的代領人各數位。"""
    valid: dict[int, Proxy] = {}
    long_ago = now - timedelta(days=HISTORY_DAYS + 5)
    for i, unit in enumerate(units[:8]):
        valid[unit.id] = create_proxy(
            session,
            admin,
            unit_code=unit.code,
            name=f"代領人{i + 1}號（家人）",
            phone=f"0912-000-{i:03d}",
            id_last4=f"{1000 + i}",
            valid_from=long_ago,
            valid_until=now + timedelta(days=60),
            now=long_ago,
        )
    for i, unit in enumerate(units[8:12]):
        create_proxy(
            session,
            admin,
            unit_code=unit.code,
            name=f"已過期代領人{i + 1}號",
            phone=None,
            id_last4=None,
            valid_from=long_ago,
            valid_until=now - timedelta(days=3),
            now=long_ago,
        )
    revoked = create_proxy(
        session,
        admin,
        unit_code=units[12].code,
        name="已撤銷代領人",
        phone=None,
        id_last4=None,
        valid_from=long_ago,
        valid_until=now + timedelta(days=30),
        now=long_ago,
    )
    revoked.revoked_at = now - timedelta(days=1)
    session.commit()
    return valid


@dataclass
class _Plan:
    unit: Unit
    type: PackageType
    outcome: str  # pickup / proxy（指定代領）/ returned / lost / pending
    outcome_after: timedelta = timedelta()


def _random_plans(rng: random.Random, units: list[Unit], origin: datetime, now: datetime):
    span = (now - origin).total_seconds()
    for _ in range(RANDOM_PACKAGES):
        registered = origin + timedelta(seconds=rng.uniform(0, span - 6 * 3600))
        registered = registered.replace(minute=rng.randrange(60))
        package_type = rng.choices(list(PackageType), weights=(75, 15, 10))[0]
        roll = rng.random()
        if roll < 0.70:
            hours = (
                rng.uniform(0.5, 30) if package_type == PackageType.COLD else rng.uniform(0.5, 220)
            )
            plan = _Plan(rng.choice(units), package_type, "pickup", timedelta(hours=hours))
        elif roll < 0.78:
            plan = _Plan(rng.choice(units), package_type, "returned", timedelta(days=2))
        elif roll < 0.83:
            plan = _Plan(rng.choice(units), package_type, "lost", timedelta(days=1))
        else:
            plan = _Plan(rng.choice(units), package_type, "pending")
        yield registered, plan


def _fixed_plans(units: list[Unit], now: datetime):
    """確保 Swagger 示範時一定看得到的狀態。"""
    demo = units[2]  # A-10F-3
    a12f3 = next(u for u in units if u.code == "A-12F-3")
    yield now - timedelta(hours=30), _Plan(demo, PackageType.COLD, "pending")  # 已 24h 提醒
    yield now - timedelta(hours=60), _Plan(units[15], PackageType.COLD, "pending")  # 需處理
    yield now - timedelta(days=9), _Plan(a12f3, PackageType.NORMAL, "pending")  # 逾期提醒中
    yield now - timedelta(days=8, hours=3), _Plan(a12f3, PackageType.LARGE, "pending")
    yield (
        now - timedelta(days=5),
        _Plan(units[4], PackageType.NORMAL, "returned", timedelta(days=2)),
    )
    yield now - timedelta(days=6), _Plan(units[13], PackageType.LARGE, "lost", timedelta(days=1))
    yield now - timedelta(days=4), _Plan(units[0], PackageType.NORMAL, "proxy", timedelta(hours=6))
    for minutes in (95, 91, 87):  # 同一戶 10 分鐘內 3 件 → 合併成 1 則通知
        yield now - timedelta(minutes=minutes), _Plan(a12f3, PackageType.NORMAL, "pending")


def _replay_history(
    session: Session,
    rng: random.Random,
    units: list[Unit],
    staff: dict[str, User],
    valid_proxies: dict[int, Proxy],
    origin: datetime,
    now: datetime,
) -> None:
    seq = count()
    events: list[tuple[datetime, int, str, object]] = []
    for registered, plan in [*_random_plans(rng, units, origin, now), *_fixed_plans(units, now)]:
        heapq.heappush(events, (registered, next(seq), "register", plan))
    day = local_date(origin)
    while (run_at := local_datetime(day, time(9, 5))) < now:
        heapq.heappush(events, (run_at, next(seq), "remind", None))
        heapq.heappush(events, (run_at + timedelta(hours=12), next(seq), "remind", None))
        day += timedelta(days=1)

    while events:
        at, _, kind, payload = heapq.heappop(events)
        if at > now:
            continue
        if kind == "remind":
            run_reminders(session, at)
        elif kind == "register":
            package = _register(session, rng, payload, staff, at)
            if payload.outcome != "pending":
                outcome_at = at + payload.outcome_after
                heapq.heappush(events, (outcome_at, next(seq), payload.outcome, package.id))
        else:
            _close(session, rng, kind, payload, staff, valid_proxies, at)
    run_reminders(session, now)


def _staff_for(unit: Unit, staff: dict[str, User]) -> tuple[User, Counter]:
    return (staff["staff_a"], Counter.A) if unit.building == "A" else (staff["staff_b"], Counter.B)


def _register(session, rng, plan: _Plan, staff, at: datetime) -> Package:
    clerk, _ = _staff_for(plan.unit, staff)
    return register_package(
        session,
        unit_code=plan.unit.code,
        carrier=rng.choice(CARRIERS),
        type=plan.type,
        staff=clerk,
        now=at,
        recipient_name=rng.choice([None, rng.choice(SURNAMES) + rng.choice(GIVEN_NAMES)]),
        tracking_no=rng.choice([None, f"TW{rng.randrange(10**9, 10**10)}"]),
    )


def _close(session, rng, kind: str, package_id: int, staff, valid_proxies, at: datetime) -> None:
    package = session.get(Package, package_id)
    clerk, counter = _staff_for(package.unit, staff)
    if kind == "returned":
        mark_exception(
            session,
            package_id,
            status=PackageStatus.RETURNED,
            reason="地址不詳，退回物流",
            staff=clerk,
            now=at,
        )
    elif kind == "lost":
        mark_exception(
            session,
            package_id,
            status=PackageStatus.LOST,
            reason="盤點時找不到包裹",
            staff=clerk,
            now=at,
        )
    else:
        proxy = valid_proxies.get(package.unit_id)
        if proxy is not None and (kind == "proxy" or rng.random() < 0.4):
            request = PickupRequest(
                counter=counter, picker_type=PickerType.PROXY, picker_proxy_id=proxy.id
            )
        else:
            resident = rng.choice(list_residents(session, package.unit))
            request = PickupRequest(
                counter=counter, picker_type=PickerType.RESIDENT, picker_user_id=resident.id
            )
        pick_up(session, package, request, staff=clerk, now=at)
