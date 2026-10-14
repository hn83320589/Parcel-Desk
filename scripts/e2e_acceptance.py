"""對「實際啟動中的 API」逐項驗證驗收標準（黑箱測試）。

用法：
    uv run parcel-desk demo --reset   # 以乾淨的示範資料啟動 API（另開一個終端機執行下一行）
    uv run python scripts/e2e_acceptance.py [--base-url http://localhost:8000]

需要「時間前進」的項目（第 7 天提醒、冷藏 24/48 小時、10 分鐘合併的第 11 分鐘）
無法在真實時鐘下黑箱驗證，由 pytest 以可注入時鐘覆蓋；這裡改驗證 seed 中已重演出的結果。
"""

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from datetime import date

import httpx


@dataclass
class Result:
    item: str
    passed: bool
    evidence: str


results: list[Result] = []


def check(item: str, condition: bool, evidence: str) -> None:
    results.append(Result(item, bool(condition), evidence))


def login(client: httpx.Client, username: str, password: str) -> dict[str, str]:
    resp = client.post("/auth/token", data={"username": username, "password": password})
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    c = httpx.Client(base_url=args.base_url, timeout=30)

    # 1. Swagger 與三種角色登入
    check("Swagger UI 可開啟", c.get("/docs").status_code == 200, "GET /docs → 200")
    admin = login(c, "admin", "admin1234")
    staff_a = login(c, "staff_a", "staff1234")
    staff_b = login(c, "staff_b", "staff1234")
    resident = login(c, "a12f3_1", "resident1234")
    roles = [c.get("/auth/me", headers=h).json()["role"] for h in (admin, staff_a, resident)]
    check("seed 帳號可登入三種角色", roles == ["admin", "staff", "resident"], f"roles={roles}")

    # 2. seed 資料量
    units = c.get("/units", headers=admin).json()
    buildings = sorted({u["building"] for u in units})
    total = c.get("/packages?limit=1", headers=admin).json()["total"]
    statuses = {
        s: c.get(f"/packages?status={s}&limit=1", headers=admin).json()["total"]
        for s in ("pending", "picked_up", "returned", "lost")
    }
    check(
        "seed 至少 2 棟、20 戶、50 件不同狀態包裹",
        len(buildings) >= 2 and len(units) >= 20 and total >= 50 and all(statuses.values()),
        f"棟別={buildings} 戶數={len(units)} 包裹={total} 狀態={statuses}",
    )

    # 3. 戶號格式錯誤 422 並指出欄位
    resp = c.post("/packages", json={"unit_code": "A12F3", "carrier": "郵局"}, headers=staff_a)
    loc = resp.json()["detail"][0]["loc"]
    check(
        "戶號格式錯誤回 422 並指出欄位",
        resp.status_code == 422 and loc == ["body", "unit_code"],
        f"{resp.status_code} loc={loc}",
    )

    # 4. 登記包裹產生 6 位數領取碼
    me = c.get("/auth/me", headers=resident).json()
    residents = c.get("/units/A-12F-3/residents", headers=staff_a).json()
    body = {"unit_code": "A-12F-3", "carrier": "E2E 物流", "type": "normal"}
    pkg = c.post("/packages", json=body, headers=staff_a).json()
    code = pkg["pickup_code"]
    check("登記後產生 6 位數領取碼", len(code) == 6 and code.isdigit(), f"pickup_code={code}")

    # 5. 到件通知寫入紀錄，住戶可查到
    notes = c.get("/notifications?kind=arrival&limit=5", headers=resident).json()
    check(
        "登記後通知該戶住戶（寫入通知紀錄）",
        any(pkg["id"] in n["package_ids"] and me["id"] in n["recipient_ids"] for n in notes),
        f"最新通知 package_ids={notes[0]['package_ids'] if notes else None}",
    )

    # 6. 用領取碼簽收，紀錄完整
    pickup_body = {
        "pickup_code": code,
        "counter": "B",
        "picker_type": "resident",
        "picker_user_id": residents[0]["id"],
    }
    resp = c.post("/pickups/by-code", json=pickup_body, headers=staff_b)
    p = resp.json().get("pickup") or {}
    check(
        "用領取碼簽收，紀錄領取人/經手管理員/櫃台/時間",
        resp.status_code == 200
        and all(p.get(k) for k in ("picker_name", "staff_id", "counter", "picked_up_at")),
        f"picker={p.get('picker_name')} staff_id={p.get('staff_id')} "
        f"counter={p.get('counter')} at={p.get('picked_up_at')}",
    )

    # 7. 重複簽收 409，紀錄不變
    again = c.post(
        f"/packages/{pkg['id']}/pickup",
        json={"counter": "A", "picker_type": "resident", "picker_user_id": residents[0]["id"]},
        headers=staff_a,
    )
    after = c.get(f"/packages/{pkg['id']}", headers=admin).json()["pickup"]
    check(
        "已簽收再簽收回 409，紀錄不變",
        again.status_code == 409 and after == p,
        f"{again.status_code} {again.json().get('code')}",
    )

    # 8. 代領人：過期 403、有效可代領（seed：前 8 戶有效、第 9–12 戶過期）
    proxies = c.get("/proxies", headers=admin).json()
    valid = next(x for x in proxies if x["is_valid"])
    expired = next(x for x in proxies if "過期" in x["name"])

    def proxy_try(proxy):
        pk = c.post(
            "/packages", json={"unit_code": proxy["unit_code"], "carrier": "E2E"}, headers=staff_a
        ).json()
        return c.post(
            "/pickups/by-code",
            json={
                "pickup_code": pk["pickup_code"],
                "counter": "A",
                "picker_type": "proxy",
                "picker_proxy_id": proxy["id"],
            },
            headers=staff_a,
        )

    r_exp, r_ok = proxy_try(expired), proxy_try(valid)
    check(
        "過期代領人回 403；有效代領人可代領",
        r_exp.status_code == 403 and r_ok.status_code == 200,
        f"過期 {expired['unit_code']} → {r_exp.status_code} {r_exp.json().get('code')}；"
        f"有效 {valid['unit_code']} → {r_ok.status_code}",
    )

    # 9. 住戶查他戶 404，管理員可查
    all_items = c.get("/packages?limit=200", headers=admin).json()["items"]
    oid = next(x["id"] for x in all_items if x["unit_code"] != "A-12F-3")
    r_res = c.get(f"/packages/{oid}", headers=resident)
    r_staff = c.get(f"/packages/{oid}", headers=staff_a)
    check(
        "住戶查他戶包裹回 404；管理員可查所有戶",
        r_res.status_code == 404 and r_staff.status_code == 200,
        f"住戶 {r_res.status_code}／管理員 {r_staff.status_code}",
    )

    # 10. 退回/遺失：原碼失效、可被重用（以領取碼查詢驗證）
    pk = c.post(
        "/packages", json={"unit_code": "A-11F-1", "carrier": "E2E"}, headers=staff_a
    ).json()
    no_reason = c.post(
        f"/packages/{pk['id']}/exception",
        json={"status": "returned", "reason": " "},
        headers=staff_a,
    )
    marked = c.post(
        f"/packages/{pk['id']}/exception",
        json={"status": "returned", "reason": "E2E 退回"},
        headers=staff_a,
    )
    retry = c.post(
        "/pickups/by-code",
        json={
            "pickup_code": pk["pickup_code"],
            "counter": "A",
            "picker_type": "resident",
            "picker_user_id": 1,
        },
        headers=staff_a,
    )
    lookup = c.get(f"/packages/by-code/{pk['pickup_code']}", headers=staff_a)
    check(
        "退回需填原因；標記後原碼簽收失敗、碼已釋出",
        no_reason.status_code == 422
        and marked.status_code == 200
        and retry.status_code == 409
        and lookup.status_code == 409,
        f"無原因 {no_reason.status_code}／標記 {marked.status_code}／原碼簽收 {retry.status_code}",
    )

    # 11. seed 重演出的提醒結果
    kinds = {
        k: len(c.get(f"/notifications?kind={k}&limit=200", headers=admin).json())
        for k in ("arrival", "overdue_reminder", "cold_reminder", "needs_attention")
    }
    attention = c.get("/packages?needs_attention=true", headers=admin).json()["total"]
    check(
        "逾期提醒、冷藏提醒、需處理皆有紀錄（seed 重演）",
        all(kinds.values()) and attention >= 1,
        f"通知數={kinds} 需處理包裹={attention}",
    )
    resident_kinds = {n["kind"] for n in c.get("/notifications?limit=200", headers=resident).json()}
    check(
        "住戶看不到給管委會的「需處理」通知",
        "needs_attention" not in resident_kinds,
        f"住戶可見類型={sorted(resident_kinds)}",
    )

    # 12. 月報與 CSV
    month = date.today().strftime("%Y-%m")
    report = c.get(f"/reports/monthly?month={month}", headers=admin)
    csv_resp = c.get(f"/reports/monthly.csv?month={month}", headers=admin)
    rows = list(csv.reader(io.StringIO(csv_resp.content.decode("utf-8-sig"))))
    check(
        "月報可查詢；staff 無權限",
        report.status_code == 200
        and c.get(f"/reports/monthly?month={month}", headers=staff_a).status_code == 403,
        f"合計={report.json()['total']}",
    )
    check(
        "CSV 為 UTF-8 BOM，中文表頭正確",
        csv_resp.content.startswith(b"\xef\xbb\xbf") and rows[0][0] == "戶號",
        f"前 3 bytes={csv_resp.content[:3].hex()} 表頭={rows[0]}",
    )

    width = max(len(r.item) for r in results)
    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.item.ljust(width)}  {r.evidence}")
    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} 項通過")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
