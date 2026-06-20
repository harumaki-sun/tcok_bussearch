import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import gspread
import requests
from google.oauth2.service_account import Credentials

# =========================
# 深夜帯は実行しない
# =========================

jst = ZoneInfo("Asia/Tokyo")
now = datetime.now(jst)

current_time = now.time()

from datetime import time

if (
    current_time >= time(23, 10)
    or
    current_time < time(5, 0)
):
    print("運行終了時間帯のため終了")
    raise SystemExit

# =========================
# 日時情報
# =========================

date_str = now.strftime("%Y-%m-%d")
weekday_str = now.strftime("%a")
collected_at = now.strftime("%H:%M:%S")

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

sheet = spreadsheet.worksheet("kouroData")

# =========================
# operating_bus取得
# =========================

print("operating_bus取得中...")

response = requests.get(
    "https://kitakyushu.busyohou.jp/api/v1/busstop/operating_bus",
    timeout=30
)

print("status:", response.status_code)
print("content-type:", response.headers.get("Content-Type"))
print(response.text[:500])

response.raise_for_status()
# =========================
# XML解析
# =========================

root = ET.fromstring(xml_text)

ns = {
    "ns": "http://schemas.datacontract.org/2004/07/Art.BusFcst.Web.Controllers"
}

new_rows = []

for item in root.findall("ns:OperationBuses", ns):

    route_id = item.find("ns:RouteId", ns)
    staffe_name = item.find("ns:StaffeName", ns)

    if route_id is None:
        continue

    if staffe_name is None:
        continue

    new_rows.append([
        date_str,
        weekday_str,
        collected_at,
        route_id.text,
        staffe_name.text
    ])

# =========================
# Sheetsへ保存
# =========================

if new_rows:

    print(f"{len(new_rows)}件追加")

    sheet.append_rows(
        new_rows,
        value_input_option="USER_ENTERED"
    )

else:

    print("追加データなし")

print("完了")
