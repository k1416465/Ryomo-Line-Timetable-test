from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    redirect,
    url_for,
    session
)

import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import re
from datetime import datetime, timezone, timedelta
import os
import secrets
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


# ==================================================
# Flask
# ==================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "ryomo-line-timetable-secret-key"
)


# ==================================================
# 日本時間
# ==================================================

# ZoneInfo("Asia/Tokyo") を使わず、
# UTC+9を直接指定することでRender等でも安定して動作させる
JST = timezone(
    timedelta(hours=9)
)


# ==================================================
# ファイル
# ==================================================

JSON_FILE = Path(__file__).with_name(
    "timetable.json"
)

NOTIFICATIONS_FILE = Path(__file__).with_name(
    "notifications.json"
)

# その他路線の運行情報キャッシュ
OPERATION_CACHE_FILE = Path(__file__).with_name(
    "operation_cache.json"
)


# ==================================================
# 管理者設定
# ==================================================

ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "admin1234"
)


# ==================================================
# Yahoo!運行情報
# ==================================================

YAHOO_RYOMO_URL = (
    "https://transit.yahoo.co.jp/diainfo/168/0"
)


OTHER_OPERATION_LINES = [

    {
        "name": "東北新幹線",
        "color": "#41934C",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/1/0"
        ]
    },

    {
        "name": "JR宇都宮線",
        "color": "#F68B1E",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/46/46",
            "https://transit.yahoo.co.jp/diainfo/46/47"
        ]
    },

    {
        "name": "JR高崎線",
        "color": "#F68B1E",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/48/0"
        ]
    },

    {
        "name": "上野東京ライン",
        "color": "#83186D",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/627/0"
        ]
    },

    {
        "name": "湘南新宿ライン",
        "color": "#E21F26",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/25/0"
        ]
    },

    {
        "name": "JR水戸線",
        "color": "#007AC0",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/167/0"
        ]
    },

    {
        "name": "JR上越線",
        "color": "#00ACD1",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/164/0"
        ]
    },

    {
        "name": "JR吾妻線",
        "color": "#008689",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/162/0"
        ]
    },

    {
        "name": "JR信越線",
        "color": "#73C11D",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/165/0"
        ]
    },

    {
        "name": "東武スカイツリーライン",
        "color": "#0071BB",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/77/0"
        ]
    },

    {
        "name": "東武日光線",
        "color": "#F58220",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/80/0"
        ]
    },

    {
        "name": "東武宇都宮線",
        "color": "#CFA348",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/169/0"
        ]
    },

    {
        "name": "東武伊勢崎線",
        "color": "#B10439",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/639/0"
        ]
    },

    {
        "name": "東武佐野線",
        "color": "#A065AA",
        "yahoo_urls": [
            "https://transit.yahoo.co.jp/diainfo/172/0"
        ]
    }

]


YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,"
        "image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language":
        "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
}


# ==================================================
# Yahoo!通信セッション
# ==================================================

YAHOO_SESSION = requests.Session()

YAHOO_SESSION.headers.update(
    YAHOO_HEADERS
)


# ==================================================
# 運行情報キャッシュ設定
# ==================================================

# 5分間キャッシュ
OPERATION_CACHE_SECONDS = 300


# キャッシュ更新中かどうか
operation_refresh_lock = threading.Lock()


# メモリ上のキャッシュ
operation_cache_data = None
operation_cache_time = 0


# ==================================================
# Yahoo!運行状態キーワード
# ==================================================

YAHOO_STATUS_WORDS = [

    "平常運転",

    "事故・遅延情報はありません",
    "事故･遅延情報はありません",

    "事故・遅延に関する情報はありません",
    "事故･遅延に関する情報はありません",

    "運転見合わせ",
    "運転を見合わせ",
    "運転を見合せ",

    "一部運休",
    "運休",

    "運転状況",
    "運転計画",

    "運転再開",

    "列車遅延",
    "遅延",
    "遅れ",

    "お知らせ",

    "その他"
]


# ==================================================
# Yahoo!つぶやき等
# ==================================================

YAHOO_TWEET_MARKERS = [

    "つぶやき",
    "みんなの運行情報",
    "ユーザー投稿",
    "路線情報を投稿",
    "この路線に関するつぶやき",
    "に関するつぶやき"

]


YAHOO_IGNORE_MARKERS = [

    "関連リンク",
    "Yahoo!乗換案内",
    "路線情報トップへ戻る",
    "運行情報トップへ戻る",
    "推奨環境",
    "Copyright ©"

]


# ==================================================
# 時刻表データ読み込み
# ==================================================

def load_timetable():

    if not JSON_FILE.exists():

        return {
            "line": "両毛線",
            "trains": []
        }

    try:

        with open(
            JSON_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print(
            "時刻表読み込みエラー:",
            e
        )

        return {
            "line": "両毛線",
            "trains": []
        }


# ==================================================
# 通知データ
# ==================================================

def load_notifications():

    if not NOTIFICATIONS_FILE.exists():

        return []

    try:

        with open(
            NOTIFICATIONS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)


        if isinstance(
            data,
            dict
        ):

            return data.get(
                "notifications",
                []
            )


        if isinstance(
            data,
            list
        ):

            return data


    except Exception as e:

        print(
            "通知読み込みエラー:",
            e
        )


    return []


def save_notifications(
    notifications
):

    with open(
        NOTIFICATIONS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "notifications": notifications
            },
            f,
            ensure_ascii=False,
            indent=2
        )


def get_next_notification_id(
    notifications
):

    ids = []

    for item in notifications:

        try:

            ids.append(
                int(
                    item.get(
                        "id",
                        0
                    )
                )
            )

        except Exception:

            pass


    if not ids:

        return 1


    return max(ids) + 1


def sort_notifications(
    notifications
):

    return sorted(

        notifications,

        key=lambda item:
            item.get(
                "date",
                ""
            ),

        reverse=True

    )


# ==================================================
# 管理者ログイン
# ==================================================

def is_admin_logged_in():

    return bool(
        session.get(
            "admin_logged_in",
            False
        )
    )


# ==================================================
# 両毛線
# ==================================================

down_cars = {

    "421M": 6,
    "423M": 4,
    "425M": 6,
    "427M": 4,
    "429M": 4,
    "431M": 4,
    "433M": 6,
    "437M": 4,
    "439M": 4,
    "441M": 6,
    "443M": 4,
    "445M": 4,
    "447M": 4,
    "449M": 4,
    "451M": 4,
    "453M": 4,
    "455M": 6,
    "459M": 6,
    "461M": 4,
    "463M": 6,
    "465M": 6,
    "467M": 4,
    "469M": 4,
    "471M": 6,
    "475M": 4,
    "479M": 6

}


def get_train_number(
    train
):

    number = str(
        train.get(
            "train_number",
            ""
        )
    ).strip()


    if number in [
        "普通",
        "快速",
        "特急",
        ""
    ]:

        possible = str(
            train.get(
                "number",
                ""
            )
        ).strip()


        if possible:

            return possible


    return number


def normalize_train(
    train
):

    train = dict(train)


    train_number = get_train_number(
        train
    )


    train["train_number"] = (
        train_number
    )


    if train_number in down_cars:

        train["cars"] = down_cars[
            train_number
        ]


    if not train.get(
        "type"
    ):

        train["type"] = "普通"


    return train


# ==================================================
# ホーム
# ==================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# ==================================================
# 時刻表API
# ==================================================

@app.route("/api/timetable")
def api_timetable():

    data = load_timetable()


    trains = []

    for train in data.get(
        "trains",
        []
    ):

        trains.append(
            normalize_train(
                train
            )
        )


    return jsonify({

        "line": data.get(
            "line",
            "両毛線"
        ),

        "trains": trains

    })


# ==================================================
# 駅一覧
# ==================================================

STATION_MAP = {

    "tochigi": {
        "name": "栃木駅",
        "english": "Tochigi Station"
    },

    "sano": {
        "name": "佐野駅",
        "english": "Sano Station"
    },

    "ashikaga": {
        "name": "足利駅",
        "english": "Ashikaga Station"
    },

    "oyama": {
        "name": "小山駅",
        "english": "Oyama Station"
    },

    "omoigawa": {
        "name": "思川駅",
        "english": "Omoigawa Station"
    },

    "ohirashita": {
        "name": "大平下駅",
        "english": "Ōhirashita Station"
    },

    "iwafune": {
        "name": "岩舟駅",
        "english": "Iwafune Station"
    },

    "tomita": {
        "name": "富田駅",
        "english": "Tomita Station"
    },

    "ashikaga_flower_park": {
        "name": "あしかがフラワーパーク駅",
        "english": "Ashikaga Flower Park Station"
    },

    "yamamae": {
        "name": "山前駅",
        "english": "Yamamae Station"
    },

    "omata": {
        "name": "小俣駅",
        "english": "Omata Station"
    }

}


# ==================================================
# 電光掲示板
# ==================================================

@app.route(
    "/station/<station>"
)
def station_page(
    station
):

    if station not in STATION_MAP:

        return "駅が見つかりません", 404


    station_data = STATION_MAP[
        station
    ]


    return render_template(

        "timetable.html",

        station=station,

        station_id=station,

        station_name=station_data[
            "name"
        ],

        station_english=station_data[
            "english"
        ]

    )


# ==================================================
# リスト時刻表
# ==================================================

@app.route(
    "/station/<station>/timetable"
)
def station_timetable(
    station
):

    if station not in STATION_MAP:

        return "駅が見つかりません", 404


    station_data = STATION_MAP[
        station
    ]


    return render_template(

        "station_timetable.html",

        station=station,

        station_id=station,

        station_name=station_data[
            "name"
        ],

        station_english=station_data[
            "english"
        ]

    )


# ==================================================
# 列車詳細
# ==================================================

@app.route("/train/<path:train_number>")
def train_detail(train_number):

    data = load_timetable()

    target = None

    # ------------------------------------------
    # 列車番号から列車を検索
    # ------------------------------------------

    for train in data.get("trains", []):

        current_number = get_train_number(train)

        if current_number == train_number:

            target = normalize_train(train)

            break

    # ------------------------------------------
    # 列車が見つからない場合
    # ------------------------------------------

    if target is None:

        return "列車が見つかりません", 404

    # ==================================================
    # 駅名 → 英語
    # ==================================================

    station_english_map = {

        "小山": "Oyama",
        "思川": "Omoigawa",
        "栃木": "Tochigi",
        "大平下": "Ōhirashita",
        "岩舟": "Iwafune",
        "佐野": "Sano",
        "富田": "Tomita",
        "足利": "Ashikaga",
        "あしかがフラワーパーク": "Ashikaga Flower Park",
        "山前": "Yamamae",
        "小俣": "Omata",

        "桐生": "Kiryū",
        "岩宿": "Iwajuku",
        "国定": "Kunisada",
        "伊勢崎": "Isesaki",
        "駒形": "Komagata",
        "前橋大島": "Maebashiōshima",
        "前橋": "Maebashi",
        "新前橋": "Shin-Maebashi",
        "井野": "Ino",
        "高崎問屋町": "Takasakitonyamachi",
        "高崎": "Takasaki",

        "大宮": "Ōmiya",
        "浦和": "Urawa",
        "上野": "Ueno",
        "東京": "Tōkyō",
        "品川": "Shinagawa",
        "横浜": "Yokohama",
        "大船": "Ōfuna",
        "池袋": "Ikebukuro",
        "新宿": "Shinjuku",
        "南浦和": "Minami-Urawa",
        "南越谷": "Minami-Koshigaya",
        "吉川美南": "Yoshikawaminami",
        "南流山": "Minami-Nagareyama",
        "新松戸": "Shim-Matsudo",
        "西船橋": "Nishi-Funabashi",
        "北朝霞": "Kita-Asaka",
        "新秋津": "Shin-Akitsu",
        "立川": "Tachikawa",
        "八王子": "Hachiōji",
        "高尾": "Takao"

    }

    # ==================================================
    # 種別 → 英語
    # ==================================================

    type_english_map = {

        "普通": "Local",
        "快速": "Rapid",
        "特急": "Limited Express",
        "臨時": "Extra",
        "団体": "Party",
        "回送": "Out of service",
        "試運転": "Test Run"

    }

    # ==================================================
    # 行先 → 英語
    # ==================================================

    destination_english_map = {

        "高崎": "Takasaki",
        "高崎問屋町": "Takasakitonyamachi",
        "井野": "Ino",
        "新前橋": "Shin-Maebashi",
        "前橋": "Maebashi",
        "前橋大島": "Maebashiōshima",
        "駒形": "Komagata",
        "伊勢崎": "Isesaki",
        "国定": "Kunisada",
        "岩宿": "Iwajuku",
        "桐生": "Kiryū",
        "小俣": "Omata",
        "山前": "Yamamae",
        "足利": "Ashikaga",
        "あしかがフラワーパーク": "Ashikaga Flower Park",
        "富田": "Tomita",
        "佐野": "Sano",
        "岩舟": "Iwafune",
        "大平下": "Ōhirashita",
        "栃木": "Tochigi",
        "思川": "Omoigawa",
        "小山": "Oyama",

        "大船": "Ōfuna",
        "新宿": "Shinjuku",
        "吉川美南": "Yoshikawaminami",
        "西船橋": "Nishi-Funabashi",
        "八王子": "Hachiōji",
        "高尾": "Takao"

    }

    # ==================================================
    # 基本情報を確定
    # ==================================================

    actual_train_number = get_train_number(target)

    train_type = target.get(
        "type",
        "普通"
    ) or "普通"

    cars = target.get(
        "cars",
        ""
    )

    destination = target.get(
        "destination",
        ""
    )

    type_english = type_english_map.get(
        train_type,
        train_type
    )

    destination_english = destination_english_map.get(
        destination,
        destination
    )

    # ==================================================
    # 停車駅データを作成
    # ==================================================

    stops = []

    raw_stops = target.get(
        "stops",
        {}
    )

    # ------------------------------------------
    # stops が辞書形式の場合
    #
    # {
    #   "小山": {
    #       "arrival": "",
    #       "departure": "6:10"
    #   },
    #   "思川": {
    #       "arrival": "6:17",
    #       "departure": "6:18"
    #   }
    # }
    # ------------------------------------------

    if isinstance(raw_stops, dict):

        for station_name, station_time in raw_stops.items():

            if not isinstance(
                station_time,
                dict
            ):
                station_time = {}

            stops.append({

                "name": station_name,

                "english": station_english_map.get(
                    station_name,
                    station_name
                ),

                "arrival": station_time.get(
                    "arrival",
                    ""
                ),

                "departure": station_time.get(
                    "departure",
                    ""
                )

            })

    # ------------------------------------------
    # stops がリスト形式の場合にも対応
    # ------------------------------------------

    elif isinstance(raw_stops, list):

        for item in raw_stops:

            if not isinstance(
                item,
                dict
            ):
                continue

            station_name = (
                item.get("name")
                or item.get("station")
                or ""
            )

            stops.append({

                "name": station_name,

                "english": (
                    item.get("english")
                    or station_english_map.get(
                        station_name,
                        station_name
                    )
                ),

                "arrival": item.get(
                    "arrival",
                    ""
                ),

                "departure": item.get(
                    "departure",
                    ""
                )

            })

    # ==================================================
    # テンプレートへ渡す
    # ==================================================

    return render_template(

        "train_detail.html",

        train=target,

        train_number=actual_train_number,

        cars=cars,

        type_english=type_english,

        destination_english=destination_english,

        stops=stops

    )

# ==================================================
# 設定
# ==================================================

@app.route(
    "/settings"
)
def settings():

    return render_template(
        "settings.html"
    )


# ==================================================
# Yahoo!運行情報取得
# ==================================================

def fetch_yahoo_route_page(
    url
):

    try:

        print(
            "[Yahoo] 個別路線取得:",
            url
        )


        response = YAHOO_SESSION.get(

            url,

            timeout=(4, 8)

        )


        response.raise_for_status()


        response.encoding = (
            response.apparent_encoding
            or "utf-8"
        )


        return response.text


    except Exception as e:

        print(
            "[Yahoo] 取得エラー:",
            url,
            e
        )

        return None


# ==================================================
# Yahoo!テキスト正規化
# ==================================================

def normalize_yahoo_text(
    text
):

    if not text:

        return ""


    text = str(text)


    text = text.replace(
        "\u3000",
        " "
    )


    text = text.replace(
        "\xa0",
        " "
    )


    text = re.sub(
        r"\s+",
        " ",
        text
    )


    return text.strip()


# ==================================================
# Yahoo!つぶやき部分削除
# ==================================================

def remove_yahoo_tweet_section(
    text
):

    if not text:

        return ""


    positions = []


    for marker in YAHOO_TWEET_MARKERS:

        position = text.find(
            marker
        )

        if position != -1:

            positions.append(
                position
            )


    if positions:

        text = text[
            :min(positions)
        ]


    return normalize_yahoo_text(
        text
    )


# ==================================================
# Yahoo!タグ属性
# ==================================================

def get_yahoo_tag_attributes(
    tag
):

    classes = " ".join(
        tag.get(
            "class",
            []
        )
    )

    element_id = tag.get(
        "id",
        ""
    )


    return (
        classes.lower(),
        str(element_id).lower()
    )


# ==================================================
# Yahoo!つぶやき要素判定
# ==================================================

def is_yahoo_tweet_element(
    tag
):

    classes, element_id = (
        get_yahoo_tag_attributes(
            tag
        )
    )


    value = (
        f"{classes} {element_id}"
    )


    tweet_words = [

        "tweet",
        "comment",
        "twitter",
        "userpost",
        "user-post",
        "sns"

    ]


    for word in tweet_words:

        if word in value:

            return True


    return False


# ==================================================
# Yahoo!運行情報テキスト抽出
# ==================================================

def extract_yahoo_operation_text(
    soup,
    yahoo_name=""
):

    working_soup = BeautifulSoup(

        str(soup),

        "html.parser"

    )


    for tag in working_soup.find_all(

        [
            "script",
            "style",
            "noscript",
            "template"
        ]

    ):

        try:

            tag.decompose()

        except Exception:

            pass


    body = (

        working_soup.body

        if working_soup.body is not None

        else working_soup

    )


    try:

        text = body.get_text(

            " ",

            strip=True

        )

    except Exception:

        text = ""


    text = normalize_yahoo_text(
        text
    )


    if not text:

        return ""


    tweet_positions = []


    for marker in YAHOO_TWEET_MARKERS:

        position = text.find(
            marker
        )

        if position != -1:

            tweet_positions.append(
                position
            )


    if tweet_positions:

        text = text[
            :min(tweet_positions)
        ]


    footer_markers = [

        "運行情報トップへ戻る",

        "路線情報トップへ戻る",

        "関東の運行情報へ戻る",

        "運行情報へ戻る",

        "Yahoo!乗換案内",

        "推奨環境",

        "Copyright ©"

    ]


    footer_positions = []


    for marker in footer_markers:

        position = text.find(
            marker
        )

        if position != -1:

            footer_positions.append(
                position
            )


    if footer_positions:

        text = text[
            :min(footer_positions)
        ]


    text = normalize_yahoo_text(
        text
    )


    return text[:6000]


# ==================================================
# Yahoo!更新時刻抽出
# ==================================================

def extract_yahoo_updated(
    text
):

    if not text:

        return ""


    patterns = [

        r"(\d{1,2}月\d{1,2}日\s*\d{1,2}時\d{1,2}分)\s*更新",

        r"(\d{1,2}月\d{1,2}日\s*\d{1,2}時\d{1,2}分)\s*現在",

        r"(\d{1,2}月\d{1,2}日\s*\d{1,2}時\d{1,2}分)"

    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )


        if match:

            return match.group(
                1
            )


    return ""


# ==================================================
# Yahoo!運行状態判定
# ==================================================

def classify_operation_status(
    status_text,
    detail_text=""
):

    text = normalize_yahoo_text(
        f"{status_text} {detail_text}"
    )


    # ==================================================
    # 運転再開後に遅れが発生している場合
    # → 遅延として扱う
    # ==================================================

    if (
        (
            "運転再開" in text
            or "運転を再開" in text
        )
        and
        (
            "列車遅延" in text
            or "遅延" in text
            or "遅れ" in text
        )
    ):

        return "遅延"


    # ==================================================
    # 一部運休
    # ==================================================

    if (
        "一部運休" in text
        or "一部列車に運休" in text
        or "一部列車が運休" in text
        or "一部列車は運休" in text
        or "一部の列車に運休" in text
        or "一部の列車が運休" in text
    ):

        return "一部運休"


    # ==================================================
    # 運転見合わせ
    # ==================================================

    if (
        "運転見合わせ" in text
        or "運転を見合わせ" in text
        or "運転を見合せ" in text
    ):

        return "運転見合わせ"


    # ==================================================
    # 運休
    # ==================================================

    if "運休" in text:

        return "運休"


    # ==================================================
    # 平常運転
    # ==================================================

    if (
        "平常運転" in text
        or "通常運転" in text
        or "事故・遅延情報はありません" in text
        or "事故･遅延情報はありません" in text
        or "事故・遅延に関する情報はありません" in text
        or "事故･遅延に関する情報はありません" in text
    ):

        return "平常運転"


    # ==================================================
    # 運転状況
    # ==================================================

    if "運転状況" in text:

        return "運転状況"


    # ==================================================
    # 運転計画
    # ==================================================

    if "運転計画" in text:

        return "運転計画"


    # ==================================================
    # 運転再開
    # ==================================================

    if (
        "運転再開" in text
        or "運転を再開" in text
    ):

        return "運転再開"


    # ==================================================
    # 遅延
    # ==================================================

    if (
        "列車遅延" in text
        or "遅延" in text
        or "遅れ" in text
    ):

        return "遅延"


    # ==================================================
    # お知らせ
    # ==================================================

    if "お知らせ" in text:

        return "お知らせ"


    if "その他" in text:

        return "その他"


    return "情報取得中"


# ==================================================
# Yahoo!詳細情報抽出
# ==================================================

def extract_yahoo_detail(
    text,
    yahoo_name=""
):

    if not text:
        return ""


    text = normalize_yahoo_text(text)


    if (
        "平常運転" in text
        and (
            "事故・遅延情報はありません" in text
            or "事故･遅延情報はありません" in text
            or "事故・遅延に関する情報はありません" in text
            or "事故･遅延に関する情報はありません" in text
        )
    ):
        return ""


    # ステータス語が実際の詳細文の中に含まれている場合があります。
    # そのため、文中の最初の「運休」などを直接切り出すのではなく、
    # 更新時刻や路線名より後にあるステータス見出しを探します。
    status_patterns = [
        "運転見合わせ",
        "運転を見合わせ",
        "運転を見合せ",
        "一部運休",
        "運転状況",
        "運転計画",
        "運転再開",
        "列車遅延",
        "運休",
        "遅延",
        "遅れ",
        "お知らせ"
    ]


    start_positions = []


    updated = extract_yahoo_updated(text)

    if updated:
        position = text.find(updated)
        if position != -1:
            start_positions.append(
                position + len(updated)
            )


    if yahoo_name:
        position = text.find(yahoo_name)
        if position != -1:
            start_positions.append(
                position + len(yahoo_name)
            )


    start_position = (
        max(start_positions)
        if start_positions
        else 0
    )


    candidates = []

    for status_word in status_patterns:
        position = text.find(
            status_word,
            start_position
        )

        if position != -1:
            candidates.append(
                (position, status_word)
            )


    if not candidates:
        return ""


    status_position, status_word = min(
        candidates,
        key=lambda item: (
            item[0],
            -len(item[1])
        )
    )


    after = text[
        status_position + len(status_word):
    ].strip()


    after = re.sub(
        r"^[:：\s]+",
        "",
        after
    )


    cut_words = [
        "迂回ルート検索",
        "路線を登録すると",
        "路線を登録",
        "運行情報トップへ戻る",
        "路線情報トップへ戻る",
        "関東の運行情報へ戻る",
        "Yahoo!乗換案内",
        "推奨環境",
        "Copyright ©"
    ]


    cut_positions = []

    for word in cut_words:
        position = after.find(word)
        if position != -1:
            cut_positions.append(position)


    if cut_positions:
        after = after[:min(cut_positions)]


    after = normalize_yahoo_text(after)


    after = re.sub(
        r"\s*（\s*\d{1,2}月\d{1,2}日.*?掲載\s*）",
        "",
        after
    )


    after = normalize_yahoo_text(after)


    if after:
        return after[:1000]


    return ""


# ==================================================
# Yahoo!個別路線解析
# ==================================================

def parse_yahoo_individual_route(
    html,
    yahoo_name,
    url
):

    try:

        soup = BeautifulSoup(

            html,

            "html.parser"

        )


        operation_text = (
            extract_yahoo_operation_text(
                soup,
                yahoo_name
            )
        )


        print(

            "[Yahoo] 解析テキスト:",

            yahoo_name,

            "=>",

            operation_text[:1000]

        )


        updated = extract_yahoo_updated(
            operation_text
        )


        detail_text = extract_yahoo_detail(

            operation_text,

            yahoo_name

        )


        status = classify_operation_status(

            operation_text,

            detail_text

        )


        print(

            "[Yahoo] 判定結果:",

            yahoo_name,

            "| status =",

            status,

            "| updated =",

            updated,

            "| detail =",

            detail_text[:300]

        )


        if status == "平常運転":

            message = (

                f"{yahoo_name}は"

                "平常通り運転しています。"

            )


        elif status == "情報取得中":

            message = (

                f"{yahoo_name}の"

                "運行情報を確認しています。"

            )


        else:

            if detail_text:

                message = detail_text

            else:

                message = (

                    f"{yahoo_name}で"

                    f"{status}の情報があります。"

                )


        return {

            "name": yahoo_name,

            "status": status,

            "message": message,

            "detail": detail_text,

            "updated": updated,

            "url": url

        }


    except Exception as e:

        print(

            "[Yahoo] 個別路線解析エラー:",

            yahoo_name,

            e

        )


        return {

            "name": yahoo_name,

            "status": "情報取得中",

            "message": (

                f"{yahoo_name}の"

                "運行情報を確認しています。"

            ),

            "detail": "",

            "updated": "",

            "url": url

        }


# ==================================================
# 複数URLを1路線へ統合
# ==================================================

def combine_other_operation_results(
    line_name,
    line_color,
    route_results
):

    if not route_results:

        return {

            "name": line_name,

            "color": line_color,

            "status": "情報取得中",

            "message": (

                f"{line_name}の"

                "運行情報を確認しています。"

            ),

            "detail": "",

            "updated": "",

            "routes": []

        }


    priority = {

        "運転見合わせ": 100,

        "一部運休": 90,

        "運休": 80,

        "運転状況": 70,

        "遅延": 60,

        "運転計画": 50,

        "運転再開": 40,

        "お知らせ": 30,

        "その他": 20,

        "平常運転": 10,

        "情報取得中": 0

    }


    valid_results = [

        result

        for result in route_results

        if isinstance(
            result,
            dict
        )

    ]


    if not valid_results:

        return {

            "name": line_name,

            "color": line_color,

            "status": "情報取得中",

            "message": (

                f"{line_name}の"

                "運行情報を確認しています。"

            ),

            "detail": "",

            "updated": "",

            "routes": []

        }


    best_result = max(

        valid_results,

        key=lambda result:

            priority.get(

                result.get(

                    "status",

                    "情報取得中"

                ),

                0

            )

    )


    status = best_result.get(

        "status",

        "情報取得中"

    )


    if status == "情報取得中":

        normal_results = [

            result

            for result in valid_results

            if result.get(
                "status"
            ) == "平常運転"

        ]


        if normal_results:

            status = "平常運転"

            best_result = normal_results[0]

        else:

            return {

                "name": line_name,

                "color": line_color,

                "status": "情報取得中",

                "message": (

                    f"{line_name}の"

                    "運行情報を確認しています。"

                ),

                "detail": "",

                "updated": best_result.get(

                    "updated",

                    ""

                ),

                "routes": valid_results

            }


    if status == "平常運転":

        message = (

            f"{line_name}は"

            "平常通り運転しています。"

        )

        detail = ""

    else:

        detail = best_result.get(

            "detail",

            ""

        )


        message = (

            detail

            if detail

            else best_result.get(

                "message",

                f"{line_name}で"

                f"{status}の情報があります。"

            )

        )


    updated_values = [

        result.get(

            "updated",

            ""

        )

        for result in valid_results

        if result.get(

            "updated",

            ""

        )

    ]


    updated = (

        updated_values[0]

        if updated_values

        else ""

    )


    return {

        "name": line_name,

        "color": line_color,

        "status": status,

        "message": message,

        "detail": detail,

        "updated": updated,

        "routes": valid_results

    }


# ==================================================
# 個別Yahoo! URLを取得・解析
# ==================================================

def fetch_and_parse_other_route(
    line_name,
    url
):

    html = fetch_yahoo_route_page(
        url
    )


    if not html:

        return {

            "name": line_name,

            "status": "情報取得中",

            "message": (

                f"{line_name}の"

                "運行情報を確認しています。"

            ),

            "detail": "",

            "updated": "",

            "url": url,

            "_fetch_failed": True

        }


    result = parse_yahoo_individual_route(

        html,

        line_name,

        url

    )


    result["_fetch_failed"] = False


    return result


# ==================================================
# その他路線運行情報取得
#
# ★ここを並列化
# ==================================================

def parse_other_operation_lines():

    results = []


    # ------------------------------------------
    # 全URLを最初に集める
    # ------------------------------------------

    jobs = []


    for line in OTHER_OPERATION_LINES:

        line_name = line[
            "name"
        ]


        for url in line.get(
            "yahoo_urls",
            []
        ):

            jobs.append({

                "line_name":
                    line_name,

                "url":
                    url

            })


    # ------------------------------------------
    # Yahoo!へのアクセスを並列実行
    # ------------------------------------------

    route_results_by_url = {}


    max_workers = min(
        8,
        max(
            1,
            len(jobs)
        )
    )


    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        future_map = {

            executor.submit(

                fetch_and_parse_other_route,

                job["line_name"],

                job["url"]

            ):
                job

            for job in jobs

        }


        for future in as_completed(
            future_map
        ):

            job = future_map[
                future
            ]


            try:

                result = future.result()

            except Exception as e:

                print(

                    "[Yahoo] 並列取得エラー:",

                    job["url"],

                    e

                )


                result = {

                    "name":
                        job["line_name"],

                    "status":
                        "情報取得中",

                    "message": (

                        f"{job['line_name']}の"

                        "運行情報を確認しています。"

                    ),

                    "detail": "",

                    "updated": "",

                    "url":
                        job["url"],

                    "_fetch_failed":
                        True

                }


            route_results_by_url[
                job["url"]
            ] = result


    # ------------------------------------------
    # 路線ごとに元の順番へ戻して統合
    # ------------------------------------------

    for line in OTHER_OPERATION_LINES:

        line_name = line[
            "name"
        ]

        line_color = line[
            "color"
        ]


        route_results = []


        for url in line.get(
            "yahoo_urls",
            []
        ):

            result = route_results_by_url.get(
                url
            )


            if result is not None:

                # 内部用フラグは削除
                result = dict(
                    result
                )

                result.pop(
                    "_fetch_failed",
                    None
                )

                route_results.append(
                    result
                )


        combined = combine_other_operation_results(

            line_name,

            line_color,

            route_results

        )


        results.append(
            combined
        )


    return results


# ==================================================
# キャッシュ読み込み
# ==================================================

def load_operation_cache():

    global operation_cache_data
    global operation_cache_time


    # ------------------------------------------
    # すでにメモリにある場合
    # ------------------------------------------

    if operation_cache_data is not None:

        return operation_cache_data


    # ------------------------------------------
    # ファイルから読み込み
    # ------------------------------------------

    if not OPERATION_CACHE_FILE.exists():

        return None


    try:

        with open(

            OPERATION_CACHE_FILE,

            "r",

            encoding="utf-8"

        ) as f:

            data = json.load(f)


        if not isinstance(
            data,
            dict
        ):

            return None


        if "lines" not in data:

            return None


        operation_cache_data = data


        try:

            operation_cache_time = float(
                data.get(
                    "_cache_time",
                    0
                )
            )

        except Exception:

            operation_cache_time = 0


        return data


    except Exception as e:

        print(
            "[Cache] 読み込みエラー:",
            e
        )

        return None


# ==================================================
# キャッシュ保存
# ==================================================

def save_operation_cache(
    lines
):

    global operation_cache_data
    global operation_cache_time


    now = time.time()


    data = {

        "lines": lines,

        "updated": datetime.now(
            JST
        ).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "_cache_time":
            now

    }


    try:

        # 一時ファイルへ書き込んでから置き換え
        temp_file = OPERATION_CACHE_FILE.with_suffix(
            ".tmp"
        )


        with open(

            temp_file,

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(

                data,

                f,

                ensure_ascii=False,

                indent=2

            )


        temp_file.replace(
            OPERATION_CACHE_FILE
        )


        operation_cache_data = data

        operation_cache_time = now


        print(
            "[Cache] その他路線運行情報を保存しました"
        )


    except Exception as e:

        print(
            "[Cache] 保存エラー:",
            e
        )


        # ファイル保存に失敗しても
        # メモリには保持する
        operation_cache_data = data
        operation_cache_time = now


# ==================================================
# キャッシュの新鮮さ
# ==================================================

def is_operation_cache_fresh():

    global operation_cache_time


    if operation_cache_time <= 0:

        return False


    return (
        time.time()
        - operation_cache_time
        < OPERATION_CACHE_SECONDS
    )


# ==================================================
# その他路線キャッシュ更新
# ==================================================

def refresh_operation_cache():

    # ------------------------------------------
    # 同時に複数回更新しない
    # ------------------------------------------

    if not operation_refresh_lock.acquire(
        blocking=False
    ):

        print(
            "[Cache] すでに更新中です"
        )

        return


    try:

        print(
            "[Cache] その他路線運行情報を更新します"
        )


        start_time = time.time()


        new_results = (
            parse_other_operation_lines()
        )


        elapsed = (
            time.time()
            - start_time
        )


        print(

            "[Cache] 更新完了:",

            f"{elapsed:.2f}秒"

        )


        # --------------------------------------
        # 全路線が取得失敗した場合
        # --------------------------------------

        useful_results = [

            item

            for item in new_results

            if item.get(
                "status"
            ) != "情報取得中"

        ]


        old_cache = (
            load_operation_cache()
        )


        if (
            not useful_results
            and old_cache
            and old_cache.get("lines")
        ):

            print(
                "[Cache] 新しいデータを取得できなかったため"
                "前回のデータを保持します"
            )

            return


        save_operation_cache(
            new_results
        )


    except Exception as e:

        print(
            "[Cache] 更新エラー:",
            e
        )


    finally:

        operation_refresh_lock.release()


# ==================================================
# バックグラウンド更新開始
# ==================================================

def start_background_operation_refresh():

    thread = threading.Thread(

        target=refresh_operation_cache,

        daemon=True

    )

    thread.start()


# ==================================================
# その他の路線 運行情報ページ
# ==================================================

@app.route(
    "/other-operation"
)
def other_operation():

    # ページ自体はYahoo!へアクセスしない
    return render_template(
        "other_operation.html"
    )


# ==================================================
# その他の路線 運行情報API
# ==================================================

@app.route(
    "/api/other-operation"
)
def api_other_operation():

    try:

        cache = load_operation_cache()


        # --------------------------------------
        # キャッシュがあれば即返す
        # --------------------------------------

        if cache and cache.get(
            "lines"
        ):

            response = jsonify({

                "lines":
                    cache.get(
                        "lines",
                        []
                    ),

                "updated":
                    cache.get(
                        "updated",
                        ""
                    )

            })


            # ブラウザ側では
            # 古いHTTPレスポンスを使わない
            response.headers[
                "Cache-Control"
            ] = "no-store"


            # ----------------------------------
            # キャッシュが古ければ
            # 裏で更新
            # ----------------------------------

            if not is_operation_cache_fresh():

                start_background_operation_refresh()


            return response


        # --------------------------------------
        # 初回だけキャッシュがない場合
        # --------------------------------------

        # この場合もページを止めず、
        # バックグラウンドで取得する

        start_background_operation_refresh()


        return jsonify({

            "lines": [],

            "updated": ""

        })


    except Exception as e:

        print(

            "その他路線運行情報APIエラー:",

            e

        )


        return jsonify({

            "lines": [],

            "updated": ""

        })


# ==================================================
# 両毛線運行情報
# ==================================================

@app.route(
    "/api/operation"
)
def api_operation():

    try:

        html = fetch_yahoo_route_page(
            YAHOO_RYOMO_URL
        )


        if not html:

            return jsonify({

                "status": "情報取得中",

                "message": (
                    "両毛線の運行情報を"
                    "確認しています。"
                ),

                "updated": ""

            })


        result = parse_yahoo_individual_route(

            html,

            "両毛線",

            YAHOO_RYOMO_URL

        )


        return jsonify(result)


    except Exception as e:

        print(
            "両毛線運行情報エラー:",
            e
        )


        return jsonify({

            "status": "情報取得中",

            "message": (
                "両毛線の運行情報を"
                "確認しています。"
            ),

            "updated": ""

        })


# ==================================================
# 通知
# ==================================================

@app.route(
    "/notifications"
)
def notifications():

    notifications_data = sort_notifications(

        load_notifications()

    )


    return render_template(

        "notifications.html",

        notifications=notifications_data

    )


# ==================================================
# 通知API
# ==================================================

@app.route(
    "/api/notifications"
)
def api_notifications():

    notifications_data = sort_notifications(

        load_notifications()

    )


    return jsonify({

        "notifications":
            notifications_data

    })


# ==================================================
# 管理者通知ページ
# ==================================================

@app.route(
    "/admin/notifications",
    methods=[
        "GET",
        "POST"
    ]
)
def admin_notifications():

    if not is_admin_logged_in():

        if request.method == "POST":

            password = request.form.get(
                "password",
                ""
            )


            if secrets.compare_digest(

                password,

                ADMIN_PASSWORD

            ):

                session[
                    "admin_logged_in"
                ] = True


                return redirect(
                    url_for(
                        "admin_notifications"
                    )
                )


        return render_template(

            "admin_notifications.html",

            logged_in=False,

            notifications=[]

        )


    notifications_data = load_notifications()


    # ------------------------------------------
    # 新規通知
    # ------------------------------------------

    if request.method == "POST":

        action = request.form.get(
            "action",
            ""
        )


        if action == "add":

            title = request.form.get(
                "title",
                ""
            ).strip()


            message = request.form.get(
                "message",
                ""
            ).strip()


            notification_type = request.form.get(
                "type",
                "info"
            ).strip()


            if title and message:

                # 日本時間で保存
                now = datetime.now(
                    JST
                )


                notifications_data.append({

                    "id":
                        get_next_notification_id(
                            notifications_data
                        ),

                    "title":
                        title,

                    "message":
                        message,

                    "type":
                        notification_type,

                    "date":
                        now.strftime(
                            "%Y-%m-%d %H:%M"
                        )

                })


                save_notifications(
                    notifications_data
                )


            return redirect(

                url_for(
                    "admin_notifications"
                )

            )


        # --------------------------------------
        # 削除
        # --------------------------------------

        if action == "delete":

            notification_id = request.form.get(
                "id",
                ""
            )


            notifications_data = [

                item

                for item in notifications_data

                if str(
                    item.get(
                        "id",
                        ""
                    )
                ) != str(
                    notification_id
                )

            ]


            save_notifications(
                notifications_data
            )


            return redirect(

                url_for(
                    "admin_notifications"
                )

            )


    return render_template(

        "admin_notifications.html",

        logged_in=True,

        notifications=
            sort_notifications(
                notifications_data
            )

    )


# ==================================================
# 管理者ログアウト
# ==================================================

@app.route(
    "/admin/notifications/logout"
)
def admin_notifications_logout():

    session.pop(
        "admin_logged_in",
        None
    )


    return redirect(

        url_for(
            "admin_notifications"
        )

    )


# ==================================================
# 起動
# ==================================================

if __name__ == "__main__":

    # ----------------------------------------------
    # 起動時に運行情報キャッシュを
    # バックグラウンドで作成
    # ----------------------------------------------

    start_background_operation_refresh()


    app.run(

        host="127.0.0.1",

        port=5000,

        debug=True

    )