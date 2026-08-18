import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
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
# 1. 系統運用対照表のA列マッピング取得（O(1)参照）
# =========================
rows_a = bus_sheet.col_values(1)
suji_row_map = {str(val): idx for idx, val in enumerate(rows_a[1:], start=2) if val}

# =========================
# 2. 路線一覧取得
# =========================
route_rows = routes_sheet.get_all_values()
route_ids = [row[0] for row in route_rows[1:] if row and row[0]]

# =========================
# 3. バスデータ並列収集（マルチスレッド処理）
# =========================
session = requests.Session()  # コネクション再利用で通信加速

def fetch_route_data(route_id):
    """単一の路線データを取得・解析する関数"""
    url = f"https://kitakyushu.busyohou.jp/api/v1/busstop/bus_maps?rid={route_id}"
    extracted = []
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            sujis = data.get("Sujis", [])
            for suji in sujis:
                suji_id = str(suji.get("SujiId", ""))
                if suji_id:
                    bus = suji.get("Bus", {})
                    plate_no = str(bus.get("PlateNo", "")).strip()
                    extracted.append((suji_id, plate_no))
    except Exception:
        pass
    return extracted

# 10スレッドで同時にAPIへアクセスしてデータ収集
all_results = []
with ThreadPoolExecutor(max_workers=10) as executor:
    results = executor.map(fetch_route_data, route_ids)
    for res in results:
        all_results.extend(res)

# =========================
# 4. 更新対象セルの整形・重複排除
# =========================
cells_to_update = []
processed_sujis = set()

for suji_id, plate_no in all_results:
    if suji_id in processed_sujis:
        continue

    if suji_id in suji_row_map and plate_no:
        formatted_plate = plate_no.zfill(4)
        target_row = suji_row_map[suji_id]
        cells_to_update.append(
            gspread.Cell(row=target_row, col=6, value=formatted_plate)
        )

    processed_sujis.add(suji_id)

# =========================
# 5. まとめて一括書き込み
# =========================
if cells_to_update:
    import time
    for attempt in range(3):
        try:
            bus_sheet.update_cells(cells_to_update, value_input_option="USER_ENTERED")
            print(f"{len(cells_to_update)}件のナンバー情報を更新しました")
            break
        except Exception as e:
            time.sleep(10)
            if attempt == 2:
                raise Exception(f"Google Sheetsへの書き込み失敗: {e}")
