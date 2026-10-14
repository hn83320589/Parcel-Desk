# Parcel Desk 測試報告

| 項目 | 內容 |
|---|---|
| 測試日期 | 2026-10-14（第一輪）、2026-10-14（第二輪：review 修正後回歸，見第 7 節） |
| 受測版本 | `main` 分支（本報告隨附的 commit） |
| 測試環境 | macOS（Apple Silicon）、Python 3.12.15 / 3.13.16、SQLite（檔案型） |
| 主要套件 | FastAPI 0.143.1、SQLAlchemy 2.1.4、Alembic 1.20.0、Pydantic 2.14.1、APScheduler 3.11.3、pytest 9.1.1 |
| **結論** | **全部通過**：自動化測試 75/75，實機 E2E 15/15，Swagger 手動操作 12 個情境、Excel 開啟 CSV 皆符合預期 |

## 1. 測試範圍與方法

共分三層，每一層各自涵蓋不同的風險：

| 層級 | 方法 | 工具 | 涵蓋重點 |
|---|---|---|---|
| 自動化測試 | service 單元測試 + API 整合測試 | pytest、FastAPI TestClient、可注入時鐘 `FixedClock` | 所有商業規則，包含需要「時間前進」的逾期提醒與通知合併 |
| 實機 E2E | 對真正啟動的 API 做黑箱測試 | `scripts/e2e_acceptance.py`（httpx） | 一鍵啟動、seed 資料、各角色實際登入後的完整流程 |
| 手動操作 | 在 Swagger UI 實際點擊操作並截圖；用 Excel 開啟匯出的 CSV | Playwright（Chromium）、Microsoft Excel for Mac | 驗證 OpenAPI 文件與 Authorize 流程可用、CSV 中文不亂碼，截圖收錄於 README |

**測試資料庫**：依題目規定使用**檔案型 SQLite**，不使用 `:memory:`。整個測試階段只對放在 `tmp_path_factory` 的模板 DB 執行一次 `alembic upgrade head`，每個測試再複製一份到自己的 `tmp_path`。因此每個測試都走過真正的 migration，彼此之間的資料也完全隔離。

## 2. 自動化測試結果

```bash
uv run pytest --cov=parcel_desk --cov-report=term-missing
```

| 測試檔 | 件數 | 內容 | 結果 |
|---|---:|---|---|
| `test_migrations.py` | 2 | 空檔案 `upgrade head` 建好所有資料表；ORM model 與 migration 一致 | ✅ |
| `test_auth_units.py` | 6 | 三種角色登入、401、戶號 422 指出欄位、建立戶別權限、住戶查他戶住戶名單 404 | ✅ |
| `test_packages.py` | 12 | 6 位數領取碼、**1,000 件不重複**、碰撞重抽、5 種錯誤戶號格式、查詢條件、住戶隔離 | ✅ |
| `test_notifications.py` | 5 | **10 分鐘內 3 件合成 1 則、第 11 分鐘開新的一則**、固定視窗邊界、跨戶不合併、通知內容、住戶隔離 | ✅ |
| `test_pickups.py` | 8 | 簽收紀錄四要素、**重複簽收 409 且紀錄不變**、**過期代領人 403**、撤銷或他戶代領人 403、代領權限 | ✅ |
| `test_exceptions.py` | 8 | **退回 / 遺失後原碼簽收失敗**、**原碼可被新包裹重用**、原因必填、只能標記待領包裹 | ✅ |
| `test_reminders.py` | 9 | **第 7 天 09:00 提醒、同一天不重複**、隔天再提醒、晚開機補送、**冷藏 24h 提醒 / 48h 需處理** | ✅ |
| `test_reports.py` | 5 | **平均領取時間與手算一致**、台北時區月界、**CSV 含 BOM**、權限、空月份 | ✅ |
| `test_scheduler.py` | 1 | API 啟動時註冊每 10 分鐘的提醒排程，關閉時停止 | ✅ |
| `test_seed.py` | 5 | seed 涵蓋 2 棟、20 戶以上、50 件以上且四種狀態都有；冪等；帳號可登入；CLI 重建 | ✅ |
| `test_edge_cases.py` | 14 | **兩櫃台同時簽收只成功一次**、簽收與標記遺失同時發生、帳號停用立即生效、重設密碼、建立帳號規則、刪除戶別保護、領取碼耗盡 503 | ✅ |
| **合計** | **75** | | **75 passed**（約 17 秒） |

**跨版本**：Python 3.12.15 與 3.13.16 各跑一次，都是 75 passed。

**靜態檢查**：`ruff check .` 與 `ruff format --check .` 都沒有警告。

### 2.1 覆蓋率

整體 **97%**（1,351 行中 36 行未覆蓋）。核心商業邏輯的覆蓋率：

| 模組 | 覆蓋率 | 說明 |
|---|---:|---|
| `services/reminders.py` 逾期提醒 | 100% | |
| `services/reports.py` 月報 | 100% | |
| `services/pickups.py` 簽收 | 100% | 包含兩櫃台搶同一件時的衝突分支 |
| `services/pickup_codes.py` 領取碼 | 100% | 包含碼空間耗盡回 503 |
| `services/notifications.py` 通知 | 98% | |
| `services/packages.py` 包裹 | 88% | 未覆蓋的是「兩櫃台同時抽到同一組碼」由資料庫擋下後重做交易的分支，需要真正的併發寫入才會觸發，難以穩定重現。正常的碰撞重抽已有測試。 |
| `cli.py` 指令 | 80% | 未覆蓋的是啟動 uvicorn 的部分，由第 3 節的實機 E2E 驗證 |

## 3. 實機 E2E 測試結果

步驟：`uv run parcel-desk seed --reset`，接著 `uv run parcel-desk`，再執行 `uv run python scripts/e2e_acceptance.py`。

```
[PASS] Swagger UI 可開啟                         GET /docs → 200
[PASS] seed 帳號可登入三種角色                   roles=['admin', 'staff', 'resident']
[PASS] seed 至少 2 棟、20 戶、50 件不同狀態包裹  棟別=['A', 'B'] 戶數=24 包裹=70
                                                 狀態={'pending': 24, 'picked_up': 37, 'returned': 8, 'lost': 1}
[PASS] 戶號格式錯誤回 422 並指出欄位             422 loc=['body', 'unit_code']
[PASS] 登記後產生 6 位數領取碼                   pickup_code=911782
[PASS] 登記後通知該戶住戶（寫入通知紀錄）        最新通知 package_ids=[71]
[PASS] 用領取碼簽收，紀錄領取人/經手管理員/櫃台/時間
                                                 picker=鄭冠宇 staff_id=3 counter=B at=2026-10-14T22:42:17+08:00
[PASS] 已簽收再簽收回 409，紀錄不變              409 PACKAGE_CLOSED
[PASS] 過期代領人回 403；有效代領人可代領        過期 A-12F-1 → 403 PROXY_EXPIRED；有效 A-10F-1 → 200
[PASS] 住戶查他戶包裹回 404；管理員可查所有戶    住戶 404／管理員 200
[PASS] 退回需填原因；標記後原碼簽收失敗、碼已釋出 無原因 422／標記 200／原碼簽收 409
[PASS] 逾期提醒、冷藏提醒、需處理皆有紀錄        通知數={'arrival': 72, 'overdue_reminder': 168,
                                                 'cold_reminder': 4, 'needs_attention': 3} 需處理包裹=3
[PASS] 住戶看不到給管委會的「需處理」通知        住戶可見類型=['arrival', 'cold_reminder', 'overdue_reminder']
[PASS] 月報可查詢；staff 無權限                  合計={'received': 39, 'picked_up': 15, 'avg_pickup_hours': 69.93, ...}
[PASS] CSV 為 UTF-8 BOM，中文表頭正確            前 3 bytes=efbbbf 表頭=['戶號', '收件數', ...]

15/15 項通過
```

另外也驗證了：

- **從零建庫**：刪除 `data/` 後執行 `uv run alembic upgrade head`，所有資料表與 partial unique index（`... WHERE status = 'pending'`）都正確建立。
- **pip 安裝**：在全新的 Python 3.12 venv 中 `pip install -e .`，之後 `parcel-desk seed` 可正常執行。

## 4. 驗收標準對照

| # | 驗收標準 | 自動化測試 | 實機 / 截圖 | 結果 |
|---|---|---|---|---|
| 1 | 一個指令啟動 API、建立資料庫、載入 seed；可用 seed 帳號登入三種角色 | `test_seed.py` | E2E 1–3、截圖 02 | ✅ |
| 2 | 戶號格式錯誤回 422 並指出欄位 | `test_auth_units`、`test_packages` | E2E 4、截圖 04 | ✅ |
| 3 | 6 位數領取碼；連續 1,000 件不重複 | `test_thousand_pending_packages_have_unique_codes` | E2E 5、截圖 03 | ✅ |
| 4 | 10 分鐘內 3 件只產生 1 則通知；第 11 分鐘產生新通知 | `test_packages_within_ten_minutes_merge_into_one_notification` | 截圖 09 | ✅ |
| 5 | 簽收紀錄有領取人、經手管理員、櫃台、時間 | `test_pickup_by_code_records_...` | E2E 7、截圖 06 | ✅ |
| 6 | 已簽收再簽收回 409，紀錄不變 | `test_second_pickup_returns_409_and_record_unchanged` | E2E 8、截圖 07 | ✅ |
| 7 | 過期代領人 403；有效代領人可代領 | `test_expired_proxy_gets_403`、`test_valid_proxy_can_pick_up` | E2E 9、截圖 08 | ✅ |
| 8 | 住戶查他戶回 404（理由見 README）；管理員可查所有戶 | `test_resident_sees_only_own_unit_and_gets_404_for_others` | E2E 10、截圖 10 | ✅ |
| 9 | 退回 / 遺失後原碼簽收失敗，且該碼可被新包裹重用 | `test_marked_package_cannot_be_picked_up_with_its_code`、`test_released_code_can_be_reused_by_new_package` | E2E 11 | ✅ |
| 10 | 可注入時鐘：一般包裹第 7 天提醒、同一天不重複；冷藏 24h 提醒、48h 需處理 | `test_reminders.py`（9 件） | E2E 12、截圖 12 | ✅ |
| 11 | 月報平均領取時間與手算一致 | `test_monthly_report_matches_hand_calculation` | E2E 14 | ✅ |
| 12 | CSV 用 Excel 開啟中文不亂碼 | `test_csv_has_bom_and_opens_in_excel_without_mojibake` | E2E 15（BOM `efbbbf`）、截圖 11、**截圖 13（Excel 實際開啟）** | ✅ |
| 13 | 所有 schema 變更透過 Alembic；刪除 DB 後 `upgrade head` 可從零建好 | `test_migrations.py`（2 件） | 第 3 節實機驗證 | ✅ |
| 14 | 測試至少 20 個且全數通過 | 75 個 | | ✅ |
| 15 | `.gitignore` 排除資料庫檔，repo 中沒有 `.db` | | `git ls-files` 中 0 個 `.db` / `.sqlite` | ✅ |

### 月報手算驗證（驗收 #11）

測試中 A-12F-3 在 10 月登記的已簽收包裹：

| 包裹 | 登記（台北） | 簽收（台北） | 領取時間 |
|---|---|---|---:|
| p1 | 10/1 10:00 | 10/1 12:00 | 2.00 h |
| p2 | 10/1 10:00 | 10/2 15:30 | 29.50 h |
| p3 | 10/2 08:00 | 10/10 09:30 | 193.50 h |

平均 = (2 + 29.5 + 193.5) ÷ 3 = **75.00 小時**，與系統輸出一致。
合計列再加上 B-5F-1 的冷藏包裹（72 h）：(2 + 29.5 + 193.5 + 72) ÷ 4 = **74.25 小時**，也一致。

## 5. 測試過程中發現並已修正的問題

| # | 問題 | 原因 | 處理 |
|---|---|---|---|
| 1 | JWT 一簽發就過期 | token 用測試時鐘（10/1）簽發，PyJWT 驗證 `exp` 時用的卻是真實時間 | token 效期屬於安全機制，改為固定使用真實時間；商業規則仍使用可注入時鐘 |
| 2 | 月報測試的預期值錯誤 | 測試案例的手算錯誤（193.5 h 誤算為 217.5 h），程式本身正確 | 修正測試的預期值，並在測試註解中寫明計算過程 |
| 3 | seed 中沒有「遺失」狀態 | 隨機資料剛好沒抽到 | 改為固定示範資料，明確放入退回、遺失、代領簽收各一件，不依賴亂數 |
| 4 | 截圖中露出 JWT | Swagger 會顯示 curl 指令，裡面帶有 token | 截圖時以 CSS 隱藏 curl 與 Request URL 區塊 |
| 5 | 無法擷取 Excel 視窗 | 終端機（iTerm2）尚未取得 macOS「螢幕錄製」權限 | 授權並重開 iTerm2 後，從 API 重新下載 CSV，以 Excel 開啟並只擷取該視窗 |

## 6. 未涵蓋與限制

- **真正的多執行緒併發寫入**沒有做壓力測試。兩櫃台的衝突情境是以兩個獨立的 DB session 模擬「同時讀到待領、先後送出」，藉此驗證條件式更新與唯一鍵的防護。
- **Windows 實機**沒有實測。已加入 `tzdata` 相依，以確保 Windows 上可以使用 `Asia/Taipei` 時區。（第二輪已加入 Windows CI，見 7.4）
- 時間相關的驗收（第 7 天、24 / 48 小時、第 11 分鐘）在實機 E2E 中無法讓真實時間前進，所以由自動化測試的可注入時鐘驗證；實機則確認 seed 重演出的提醒紀錄確實存在。

## 7. 第二輪：review 修正後的回歸測試

外部 review 指出三個問題。以下每一項都**先重現問題**，修正後**再以相同手法驗證**。

### 7.1 問題重現（修正前）

| # | 問題 | 重現方式 | 修正前結果 |
|---|---|---|---|
| 1 | JWT 預設密鑰公開在 repo | 用 repo 中的預設字串自行簽一個 `sub=1` 的 token，呼叫 `/reports/monthly` | **200**（取得管委會權限） |
| 2 | 一鍵啟動把示範資料寫進正式資料庫；seed 中斷後不再補齊 | 檢查 `is_seeded`：只要有任何一個帳號就判定已完成；seed 逐步 commit | 確認屬實 |
| 3 | `.coverage` 被 commit 進 repo；缺少 CI 與 LICENSE | `git ls-files` | 確認屬實 |

### 7.2 修正後驗證

| 項目 | 方法 | 結果 |
|---|---|---|
| 偽造 token | 對啟動中的 API 重跑 7.1 #1 的手法 | **401** ✅ |
| 正常登入不受影響 | 真實帳號登入後呼叫同一個 API | 200 ✅ |
| 密鑰檔 | `data/.jwt_secret` 權限、是否被 git 忽略 | `-rw-------`，被 `.gitignore` 的 `data/` 排除 ✅ |
| 不安全的密鑰 | 以舊預設值或過短的密鑰啟動 | exit 1，並顯示清楚的錯誤訊息；資料庫檔沒有被建立 ✅ |
| 正式模式首次啟動 | 刪除 `data/` 後執行 `parcel-desk` | 只有 1 個 admin，0 戶、0 件包裹；示範帳號 `staff_a` 登入回 401 ✅ |
| 強制改密碼 | 以一次性密碼登入，呼叫 `/units` | 403 `PASSWORD_CHANGE_REQUIRED`；改密碼回 204 後，`/units` 回 200 ✅ |
| 重啟不重建 admin | 再啟動一次正式模式 | 沒有再顯示首次啟動訊息 ✅ |
| **demo 建置中斷** | `parcel-desk demo` 啟動 5 秒後 **`kill -9`** | `demo.db` 不存在，只留下 `demo.db.building` 暫存檔 ✅ |
| 中斷後重新啟動 | 再次執行 `parcel-desk demo` | 清除暫存檔後完整重建：24 戶、52 帳號、70 件包裹 ✅ |
| 實機 E2E | 在示範模式執行 `scripts/e2e_acceptance.py` | **15/15** ✅ |

### 7.3 自動化測試

新增 13 個測試，總數 **86 個，全數通過**，覆蓋率 97%：

| 測試檔 | 件數 | 內容 |
|---|---:|---|
| `test_jwt_secret.py` | 7 | 自動產生並以權限 600 存檔、重啟沿用、每套安裝不同、拒絕過短與公開的預設值、**重現攻擊並確認回 401** |
| `test_startup.py` | 6 | 正式模式只建立 admin、不載入示範資料；重啟不重建；改密碼前回 403；**模擬中斷時 demo 建置不留半套資料**；重建時取代而非疊加；不安全密鑰在碰資料庫前就結束 |

`test_seed.py` 移除了 2 個測試舊行為（「空資料庫就 seed」的冪等性、`seed --reset` 指令）的測試，改由上表取代。

`cli.py` 的覆蓋率是 63%：未覆蓋的是實際啟動 uvicorn 與印出橫幅的部分，已由 7.2 的實機驗證涵蓋。

### 7.4 CI

新增 GitHub Actions（`.github/workflows/ci.yml`）：在 **Ubuntu、Windows、macOS** 上，分別以 **Python 3.12 與 3.13** 執行 `uv sync --locked`、ruff 與 pytest。這也補上了第 6 節「Windows 實機沒有實測」的缺口。
