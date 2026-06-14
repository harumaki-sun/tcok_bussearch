import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import requests
from google.oauth2.service_account import Credentials

# =========================
# 深夜帯は実行しない
# =========================

jst = ZoneInfo("Asia/Tokyo")
now = datetime.now(jst)

if 0 <= now.hour < 5:
    print("0:00～5:00のため終了")
    raise SystemExit

# =========================
# 日時情報
# =========================

date_str = now.strftime("%Y-%m-%d")
weekday_str = now.strftime("%a")
collected_at = now.strftime("%Y-%m-%d %H:%M:%S")

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

    service_account_info = json.loads(
        os.environ["GOOGLE_CREDENTIALS"]
    )

    creds = Credentials.from_service_account_info(
        service_account_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )

gc = gspread.authorize(creds)

spreadsheet = gc.open("北九州市営バス運用記録")

bus_sheet = spreadsheet.worksheet("BusData")
routes_sheet = spreadsheet.worksheet("Routes")

# =========================
# 既存データ読み込み（重複防止）
# =========================

print("既存データ取得中...")

known_entries = set()

rows = bus_sheet.get_all_values()

for row in rows[1:]:

    if len(row) < 5:
        continue

    date_value = row[0]
    suji_id = row[4]

    # ★ここが重複キー
    known_entries.add((date_value, suji_id))

print(f"既存キー数: {len(known_entries)}")

# =========================
# 路線一覧取得
# =========================

print("路線一覧取得中...")

route_rows = routes_sheet.get_all_values()

route_ids = [
    row[0]
    for row in route_rows[1:]
    if row and row[0]
]

# =========================
# バスデータ収集
# =========================

new_rows = []

for route_id in route_ids:

    print(f"処理中: {route_id}")

    try:

        data = requests.get(
            f"https://kitakyushu.busyohou.jp/api/v1/busstop/bus_maps?rid={route_id}",
            timeout=30
        ).json()

        sujis = data.get("Sujis", [])

        for suji in sujis:

            suji_id = suji.get("SujiId", "")

            if not suji_id:
                continue

            # =========================
            # ★重複チェック（ここが本体）
            # =========================
            key = (date_str, suji_id)

            if key in known_entries:
                continue

            bus = suji.get("Bus", {})

            bus_name = bus.get("BusName", "")
            plate_no = bus.get("PlateNo", "")

            # 始発時刻（sujiId末尾4桁）
            start_time = ""
            if len(suji_id) >= 4:
                hhmm = suji_id[-4:]
                start_time = f"{hhmm[:2]}:{hhmm[2:]}"

            new_rows.append([
                date_str,
                weekday_str,
                collected_at,
                route_id,
                suji_id,
                bus_name,
                plate_no,
                start_time
            ])

            # ★即時登録（同一実行内の重複防止）
            known_entries.add(key)

    except Exception as e:

        print(f"エラー: {route_id}")
        print(e)

# =========================
# まとめて書き込み
# =========================

if new_rows:

    print(f"{len(new_rows)}件追加")

    bus_sheet.append_rows(
        new_rows,
        value_input_option="USER_ENTERED"
    )

else:

    print("追加データなし")

print("完了")
