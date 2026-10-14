# Parcel Desk 架構規劃與設計（v1.1）

> 實作與 README 為準；本文件保留設計脈絡。

## 1. 技術選型

| 項目 | 選擇 | 理由 |
|---|---|---|
| Python | `requires-python = ">=3.12"`，`.python-version` 固定 3.12 | 符合題目；本機為 3.15，以 uv 固定 3.12 驗證最低版本 |
| 套件管理 | **uv**（`pyproject.toml` + `uv.lock`） | lock 檔即「鎖定的相依版本」；`uv sync` 後一個指令啟動 |
| Web | FastAPI + uvicorn | 題目指定 |
| ORM / Migration | SQLAlchemy 2.x（**同步** Session）+ Alembic | SQLite 下 async 沒有實質效益，同步較易測試、易讀 |
| 驗證 | Pydantic v2 + pydantic-settings | FastAPI 原生，422 自動帶欄位位置 |
| JWT | PyJWT（HS256） | 輕量 |
| 密碼雜湊 | `bcrypt`（直接使用） | passlib 已停止維護且與新版 bcrypt 不相容 |
| 表單登入 | python-multipart | Swagger「Authorize」按鈕的 OAuth2 password flow 需要 |
| 排程 | APScheduler 3.x（內嵌於 API 程序） | 見 §7 |
| 時區 | `zoneinfo` + **tzdata** | Windows 沒有內建 IANA 時區資料庫，不裝 tzdata 會找不到 `Asia/Taipei` |
| 測試 | pytest + httpx（TestClient） | 題目指定 |
| Lint / Format | ruff | 單一工具涵蓋 lint + format |

## 2. 專案結構

```
Parcel-Desk/
├── pyproject.toml / uv.lock / .python-version / .gitignore
├── alembic.ini
├── migrations/                # Alembic env.py + versions/
├── src/parcel_desk/
│   ├── main.py                # create_app()：路由、例外處理、排程器 lifespan
│   ├── cli.py                 # `parcel-desk` 指令：serve（預設）/ seed / migrate
│   ├── config.py              # Settings（DB 路徑、JWT secret、時區…）
│   ├── db.py                  # engine、SessionLocal、SQLite PRAGMA
│   ├── clock.py               # Clock 介面、SystemClock、（測試用）FixedClock
│   ├── security.py            # JWT 簽發/解析、bcrypt
│   ├── deps.py                # get_db / get_clock / get_current_user / require_roles
│   ├── errors.py              # 領域例外 → HTTP 狀態碼
│   ├── models/                # SQLAlchemy ORM
│   ├── schemas/               # Pydantic request / response
│   ├── services/              # 商業邏輯（不認識 HTTP）
│   │   ├── pickup_codes.py    # 領取碼產生
│   │   ├── packages.py        # 登記、查詢、退件/遺失
│   │   ├── notifications.py   # 到件通知合併
│   │   ├── pickups.py         # 簽收
│   │   ├── reminders.py       # 逾期提醒（純函式 run_reminders(session, now)）
│   │   └── reports.py         # 月報 + CSV
│   ├── api/                   # 各資源 router（薄層：驗證 → 呼叫 service → 回應）
│   ├── scheduler.py           # APScheduler 掛載
│   └── seed.py
├── tests/
└── README.md
```

分層原則：`api → services → models`。Service 收 `session` 與 `now`（或 clock），丟出領域例外（`NotFound` / `Conflict` / `Forbidden` / `ValidationFailed`），由 `errors.py` 統一轉成 HTTP 狀態碼。這讓逾期提醒、通知合併等核心規則可以不經 HTTP 直接測。

## 3. 資料模型

所有時間以 **UTC** 存入（自訂 `UTCDateTime` TypeDecorator，SQLite 無時區型別），商業規則中的「09:00」「哪一天」「哪個月」一律以 **Asia/Taipei** 換算。

```
units                      戶別
  id, code UNIQUE ("A-12F-3"), building ("A"), floor (12), number (3), created_at

users                      所有登入帳號（admin / staff / resident）
  id, username UNIQUE, password_hash, display_name, role,
  unit_id FK NULL          ← resident 必填、其他角色必為 NULL（CHECK constraint）
  is_active, created_at

proxies                    代領人（不需帳號）
  id, unit_id FK, name, phone NULL, id_last4 NULL（證件末四碼，供核對）,
  valid_from, valid_until, revoked_at NULL, created_by FK users, created_at

packages                   包裹
  id, unit_id FK, recipient_name NULL, carrier, tracking_no NULL,
  type: normal | large | cold
  status: pending | picked_up | returned | lost
  pickup_code CHAR(6)
  registered_at, registered_by FK users
  needs_attention_at NULL  ← 冷藏 48h 標記「需處理」（旗標，不是狀態，仍可簽收）
  exception_reason NULL, exception_at NULL, exception_by FK NULL
  ── 部分唯一索引：UNIQUE(pickup_code) WHERE status = 'pending'

pickups                    簽收紀錄（與 packages 1:1）
  id, package_id FK UNIQUE, picker_type: resident | proxy,
  picker_user_id FK NULL, picker_proxy_id FK NULL, picker_name（快照）,
  staff_id FK users, counter: A | B, picked_up_at

notifications              通知紀錄
  id, kind: arrival | overdue_reminder | cold_reminder | needs_attention
  unit_id FK NULL, title, body, created_at,
  window_ends_at NULL      ← 只有 arrival 使用（合併視窗結束時間）
notification_packages      (notification_id, package_id)  通知涵蓋哪些包裹
notification_recipients    (notification_id, user_id)      通知給誰（快照）

package_reminders          提醒去重紀錄
  id, package_id FK, kind: overdue_daily | cold_24h | cold_48h,
  remind_date (台北日期), notification_id FK, created_at
  ── UNIQUE(package_id, kind, remind_date)
```

設計重點：
- **領取碼唯一性交給資料庫保證**：SQLite 支援 partial index，只有 `pending` 的包裹參與唯一性檢查。簽收、退回、遺失後狀態改變 → 自動離開索引 → 碼「立即失效」且「可被重新使用」，不需要額外清除欄位，歷史資料也保留原碼。
- **防止重複簽收**：簽收用條件式更新 `UPDATE packages SET status='picked_up' WHERE id=? AND status='pending'`，影響 0 列即 409；`pickups.package_id UNIQUE` 是最後一道防線（兩個櫃台同時按簽收也只會成功一次）。
- **「沒收到通知」可稽核**：`notification_recipients` 記錄當下該戶有哪些住戶被通知。
- **提醒冪等**：`package_reminders` 的唯一鍵讓「同一天不重複提醒」由資料庫保證，排程重跑、重啟補跑都安全。

## 4. 核心規則

### 4.1 戶號驗證
- 格式：`^[A-Z]-([1-9]\d{0,2})F-([1-9]\d{0,2})$`，例 `A-12F-3`。
- 以 Pydantic 型別 `UnitCode` 實作，用在 body / query / path，錯誤時回 422，`detail[].loc` 會指出欄位（如 `["body","unit_code"]`）。
- 格式正確但戶別不存在：登記包裹時回 422（`loc` 同樣指向 `unit_code`），查詢時回 404。

### 4.2 領取碼產生
1. `secrets.randbelow(1_000_000)` → 補零成 6 位字串（允許 `000123`）。
2. 寫入時若撞到 partial unique index（`IntegrityError`）→ 以 SAVEPOINT 回滾並重抽，最多 20 次，仍失敗回 503。
3. 碰撞機率：同時待領件數上限估約 數千件 / 1,000,000，平均重抽次數趨近 0。
- 用 `secrets` 而非 `random`：領取碼等同取件憑證，不可被預測。

### 4.3 到件通知合併（固定視窗）
登記包裹時（同一交易內）：
1. 找該戶最新一則 `arrival` 通知，且 `now < window_ends_at`。
2. 有 → 把包裹加入該通知，更新 body（「您有 N 件包裹…」）。
3. 沒有 → 建新通知，`window_ends_at = now + 10 分鐘`，收件者 = 該戶所有啟用中的住戶。

採**固定視窗**（以該批第一件為起點），而非滑動視窗：滑動視窗下每 9 分鐘來一件會無限延長，住戶永遠收不到。邊界：恰好第 10:00 登記屬新通知。
→ 0、3、9 分鐘 = 1 則（3 件）；第 11 分鐘 = 新的一則。

### 4.4 簽收
- 找包裹：`GET /packages/by-code/{code}`（只找 pending）、`GET /packages?unit_code=...&status=pending`。
- 簽收：`POST /packages/{id}/pickup` 或 `POST /pickups/by-code`，body：`counter`(A/B)、`picker_type`、`picker_user_id` 或 `picker_proxy_id`。
- 領取人檢查：
  - 住戶：必須是該包裹戶別的啟用住戶，否則 403。
  - 代領人：必須屬於該戶、`valid_from <= now <= valid_until`、未撤銷，否則 **403**。
- 經手管理員 = JWT 中的使用者；時間 = clock.now()。
- 狀態非 pending → **409**（訊息標明「已簽收 / 已退回 / 已遺失」），簽收紀錄不變。
- 以領取碼簽收時，找不到 pending 包裹：若該碼最近一件是終態 → 409；從未存在 → 404。

### 4.5 退件與異常
`POST /packages/{id}/exception`，body：`status`（returned | lost）、`reason`（必填、去空白後不可為空，否則 422）。只有 pending 可標記，否則 409。

### 4.6 逾期提醒（`run_reminders(session, now)`，冪等）
| 類型 | 條件 | 動作 |
|---|---|---|
| 一般/大型 | 台北時間 `now >= 當日 09:00`，且 `今日 − 登記日 >= 7 天`（以台北日曆日計），且今天尚未提醒 | 通知該戶住戶，記 `overdue_daily` |
| 冷藏 | `now − registered_at >= 24h`，且未提醒過 | 通知該戶住戶，記 `cold_24h`（一次） |
| 冷藏 | `now − registered_at >= 48h`，且未標記 | 設 `needs_attention_at`，通知所有 admin，記 `cold_48h`（一次） |

- 只處理 `pending` 包裹。
- 「第 7 天」以**日曆日**計：10/1 任何時間登記 → 10/8 09:00 起提醒。對住戶來說比「滿 168 小時」直覺。
- 冷藏僅有 24h / 48h 兩次事件，不再套用 7 天每日提醒。
- 同一戶同一次執行的多件逾期包裹 → 合併成一則提醒通知（與到件通知一致）。

### 4.7 月報
- 月份歸屬：包裹 `registered_at` 換成台北時間後的年月。
- 每戶欄位：戶號、收件數、已領件數、平均領取時間（小時，四捨五入至小數 2 位）、逾期件數、冷藏需處理件數；最後一列為全社區合計。
- 平均領取時間 = 該月登記且已簽收者 `avg(picked_up_at − registered_at)`；無已領件時為空值。
- 逾期件數：以時間戳計算，不依賴排程是否有跑——一般/大型 `(簽收時間 或 結案時間 或 查詢當下) − 登記時間 > 7 日曆日`；冷藏 `> 24h`。
- CSV：`UTF-8 with BOM`（`utf-8-sig`）+ CRLF，Excel 直接開啟中文不亂碼；`Content-Disposition` 檔名 `parcel-report-2026-10.csv`。

## 5. API 一覽與權限

admin ⊇ staff（管委會也在現場，可代行管理員操作）。

| Method | Path | admin | staff | resident |
|---|---|:-:|:-:|:-:|
| POST | `/auth/token`（OAuth2 form） | ✓ | ✓ | ✓ |
| GET | `/auth/me` | ✓ | ✓ | ✓ |
| GET/POST/DELETE | `/units`（戶號即識別碼，不提供修改） | ✓ | 讀 | ✗ |
| GET/POST/PATCH | `/users`（建立住戶/管理員帳號） | ✓ | ✗ | ✗ |
| GET | `/units/{code}/residents` | ✓ | ✓ | 本戶 |
| GET/POST | `/proxies`、DELETE `/proxies/{id}`（撤銷） | ✓ | 讀 | 本戶 |
| POST | `/packages`（登記） | ✓ | ✓ | ✗ |
| GET | `/packages`（unit_code / status / date_from / date_to / needs_attention / 分頁） | ✓ 全部 | ✓ 全部 | 本戶 |
| GET | `/packages/{id}` | ✓ | ✓ | 本戶，他戶 **404** |
| GET | `/packages/by-code/{code}` | ✓ | ✓ | ✗ |
| POST | `/packages/{id}/pickup`、`/pickups/by-code` | ✓ | ✓ | ✗ |
| POST | `/packages/{id}/exception` | ✓ | ✓ | ✗ |
| GET | `/notifications`、`/notifications/{id}` | ✓ | ✓ | 本戶（不含給管委會的「需處理」） |
| GET | `/reports/monthly?month=2026-10`、`/reports/monthly.csv` | ✓ | ✗ | ✗ |
| POST | `/admin/run-reminders`（手動觸發，方便驗收） | ✓ | ✗ | ✗ |

**住戶查他戶包裹回 404**：403 等於告訴對方「這個 id 的包裹存在，只是你不能看」，可被用來列舉包裹數量；404 不洩漏任何資訊。

錯誤格式：`{"detail": "人類可讀訊息", "code": "ALREADY_PICKED_UP"}`；422 沿用 FastAPI 預設格式（含 `loc`）。

## 6. 時間與可注入時鐘
- `Clock` Protocol：`now() -> datetime`（aware UTC）。
### 6.1 JWT 密鑰（v1.1）
- 沒有預設值。未設定 `PARCEL_JWT_SECRET` 時，首次啟動以 `secrets.token_urlsafe(48)` 產生，
  以 `O_EXCL` 加上權限 600 建立 `data/.jwt_secret`，之後沿用，所以重啟不會登出使用者。
- 有設定時：少於 32 字元、或命中曾公開的舊預設值（黑名單），就拒絕啟動。
- 起因：v1.0 的預設值公開在 repo 中，任何人都能偽造管委會 token。

- 例外：JWT 效期使用真實時間（安全機制，且 PyJWT 驗證 `exp` 時也使用真實時間）。
- API 透過 `Depends(get_clock)` 從 `app.state.clock` 取得；測試以 `create_app(settings, clock=FixedClock(...))` 注入，可 `advance(minutes=11)`。
- 排程器與 seed 也透過同一介面，所以「第 7 天」「24h/48h」「第 11 分鐘」都能在測試中精準控制，不用 sleep、不用 freezegun。

## 7. 排程方式（二擇一）— APScheduler 內嵌

- API 啟動時（FastAPI lifespan）啟動 `BackgroundScheduler`，**每 10 分鐘**呼叫一次 `run_reminders(now)`。
- 為什麼不是「每天 09:00 跑一次」：冷藏 24h / 48h 不是固定時點，需要較密集的檢查；而一般包裹的「09:00」由 `run_reminders` 內部判斷（`now >= 當日 09:00` 且今天沒提醒過），所以 09:00 後第一次執行就會送出、之後同日不再送。
- 好處：電腦 08:00–10:00 關機，開機後第一次執行就會**補送**當天提醒；部署只要一個指令，管理室不用另外設定工作排程器。
- 已知限制（寫入 README）：API 程序沒在跑就沒有提醒；冷藏提醒最多延遲 10 分鐘；只能跑一個 API 程序（多 worker 會重複排程，但唯一鍵會擋下重複紀錄）。

## 8. 一鍵啟動（v1.1：示範與正式分離）
兩種模式使用不同的資料庫檔，示範資料不可能混入正式資料：

- `uv run parcel-desk demo`（示範，滿足「一個指令啟動並載入 seed」）：使用 `data/demo.db`。
  不存在時（或加上 `--reset`）先在 `demo.db.building` 完成 migration 與 seed，成功後才
  `os.replace` 成正式檔名。seed 逐步 commit、本身不具原子性，改名這一步讓整體具有原子性。
- `uv run parcel-desk`（正式）：`alembic upgrade head` → 沒有任何帳號時建立 `admin`，
  於終端機顯示一次性隨機密碼並標記 `must_change_password`。永不載入示範資料。
- 兩者都會在碰資料庫之前先檢查 JWT 密鑰（見 §6.1），不安全就以 exit 1 結束。
- 最後啟動 uvicorn `0.0.0.0:8000`（兩個櫃台走區網連線），Swagger 在 `/docs`。

> v1.0 的做法是「空資料庫就自動 seed」。review 指出兩個問題：正式上線會建立密碼公開的帳號；
> seed 被中斷後，`is_seeded` 只檢查有沒有任何帳號，會誤判已完成而不再補齊。因此改為上述設計。

SQLite 設定：`foreign_keys=ON`、`journal_mode=WAL`（兩櫃台同時讀寫）、`busy_timeout=5000`。

## 9. Seed 資料
- 帳號：`admin / admin1234`、`staff_a / staff1234`（A 棟櫃台）、`staff_b / staff1234`、住戶如 `a12f3_1 / resident1234`。
- 戶別：A、B 兩棟，各 10–12F × 1–4 號 = **24 戶**（含 `A-12F-3`）；每戶 1–3 位住戶。
- 代領人：有效、已過期、已撤銷各數筆。
- 包裹 **70 件**，橫跨上月與本月：待領、一般逾期、冷藏 24h、冷藏需處理、住戶簽收、代領簽收、退回、遺失。
- 透過 service 層 + 固定時鐘產生，所以通知、提醒、簽收紀錄都與實際流程一致。

## 10. 測試策略（預計 30+ 個）
- **檔案型 SQLite**：session 開始時對 `tmp_path_factory` 下的模板 DB 執行一次 `alembic upgrade head`，每個測試再複製一份到自己的 `tmp_path`。既驗證 migration、又不必每個測試都重跑 migration。
- 對應驗收標準：

| 驗收項目 | 測試 |
|---|---|
| 戶號 422 指出欄位 | body / query 兩處各一 |
| 1,000 件領取碼不重複 | service 層連續登記 1,000 件 |
| 通知合併 | 0/3/9 分鐘 = 1 則 3 件；第 11 分鐘新通知；他戶不合併 |
| 簽收紀錄 | 領取人、經手管理員、櫃台、時間 |
| 重複簽收 409 | 紀錄不變 |
| 代領人 | 過期 403、撤銷 403、他戶代領人 403、有效成功 |
| 權限 | 住戶查他戶 404、住戶看不到他戶通知、staff 查全部、住戶不能登記 |
| 退件/遺失 | 原碼簽收失敗、該碼可被新包裹重用、reason 必填 |
| 逾期提醒 | 第 6 天不提醒、第 7 天 09:00 前不提醒/後提醒、同日重跑不重複、隔天再提醒；冷藏 23h/24h/48h；已簽收不提醒 |
| 月報 | 平均領取時間 = 手算值、逾期件數、需處理件數、跨月歸屬 |
| CSV | 開頭為 BOM、中文可解碼 |
| Migration | 空檔案 `upgrade head` 後表格齊全 |
| 認證 | 錯誤密碼 401、無 token 401 |

## 11. 開發順序（每步皆可編譯、測試通過後 commit）
1. 專案骨架：uv、ruff、pytest、git init、.gitignore
2. DB 基礎：models、第一版 migration、clock、測試 fixture
3. 認證 + 使用者 + 戶別（含戶號驗證）
4. 包裹登記 + 領取碼
5. 到件通知合併
6. 代領人 + 簽收
7. 退件/遺失
8. 逾期提醒 + APScheduler
9. 月報 + CSV
10. Seed + 一鍵啟動 CLI
11. README（啟動、帳號、API、權限、規則、排程、已知限制）
