import json
import os
from datetime import datetime
from datetime import time
from zoneinfo import ZoneInfo

import gspread
import requests
from google.oauth2.service_account import Credentials

# =========================
# 深夜帯は実行しない
# =========================
jst = ZoneInfo("Asia/Tokyo")
now = datetime.now(jst)
current_time = now.time()

if current_time >= time(23, 10) or current_time < time(5, 20):
    raise SystemExit

# =========================
# Google Sheets接続
# =========================
if os.path.exists("credentials.json"):
    creds = Credentials.from_service_account_file(
        "credentials.json",
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
else:
    service_account_info = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(
        service_account_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )

gc = gspread.authorize(creds)

spreadsheet = gc.open("北九州市営時刻表(平日)")
bus_sheet = spreadsheet.worksheet("系統運用対照表")
routes_sheet = spreadsheet.worksheet("シート23")

# =========================
# 系統運用対照表のA列マッピング取得
# =========================
# A列（suji_id）の値と「何行目にあるか」を記録する辞書作成
rows_a = bus_sheet.col_values(1)  # A列のデータをすべて取得
suji_row_map = {}

for idx, val in enumerate(rows_a[1:], start=2):  # ヘッダーを除外して2行目から
    if val:
        suji_row_map[str(val)] = idx

# =========================
# 路線一覧取得
# =========================
route_rows = routes_sheet.get_all_values()
route_ids = [row[0] for row in route_rows[1:] if row and row[0]]

# =========================
# バスデータ収集 & 更新セル準備
# =========================
cells_to_update = []
processed_sujis = set()  # 同一実行内の重複防止

for route_id in route_ids:
    try:
        data = requests.get(
            f"https://kitakyushu.busyohou.jp/api/v1/busstop/bus_maps?rid={route_id}",
            timeout=30
        ).json()

        sujis = data.get("Sujis", [])

        for suji in sujis:
            suji_id = str(suji.get("SujiId", ""))

            if not suji_id or suji_id in processed_sujis:
                continue

            # A列に該当するsuji_idが存在するかチェック
            if suji_id in suji_row_map:
                bus = suji.get("Bus", {})
                plate_no = str(bus.get("PlateNo", "")).strip()

                if plate_no:
                    # 先頭に0を補填して4桁に整形（例: "6" -> "0006"）
                    formatted_plate = plate_no.zfill(4)
                    target_row = suji_row_map[suji_id]

                    # 更新用セルオブジェクトの作成 (F列 = 6列目)
                    cells_to_update.append(
                        gspread.Cell(row=target_row, col=6, value=formatted_plate)
                    )

            processed_sujis.add(suji_id)

    except Exception:
        pass  # 必要最小限の出力のため失敗時はスキップ

# =========================
# まとめて書き込み（一括更新）
# =========================
if cells_to_update:
    import time
    for attempt in range(3):
        try:
            # 1回のAPIリクエストでまとめてF列を更新
            bus_sheet.update_cells(cells_to_update, value_input_option="USER_ENTERED")
            print(f"{len(cells_to_update)}件のナンバー情報を更新しました")
            break
        except Exception as e:
            time.sleep(10)
            if attempt == 2:
                raise Exception(f"Google Sheetsへの書き込み失敗: {e}")
