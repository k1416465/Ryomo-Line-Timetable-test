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
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import secrets


app = Flask(__name__)


# ==================================================
# Flask セッション設定
# ==================================================

# 本番公開時は環境変数 FLASK_SECRET_KEY を設定してください。
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "ryomo-line-timetable-secret-key"
)


# ==================================================
# ファイル設定
# ==================================================

JSON_FILE = Path(__file__).with_name(
    "timetable.json"
)

NOTIFICATIONS_FILE = Path(__file__).with_name(
    "notifications.json"
)


# ==================================================
# 管理画面設定
# ==================================================

# 本番公開時は環境変数 ADMIN_PASSWORD を設定してください。
#
# ローカル開発時の初期パスワード:
# admin1234
#
# Windows コマンドプロンプト:
#
# set ADMIN_PASSWORD=好きなパスワード
#
# PowerShell:
#
# $env:ADMIN_PASSWORD="好きなパスワード"
#

ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "admin1234"
)


# ==================================================
# 時刻表データ読み込み
# ==================================================

def load_timetable():

    with open(
        JSON_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# ==================================================
# お知らせデータ読み込み
# ==================================================

def load_notifications():

    # ファイルが存在しない場合
    if not NOTIFICATIONS_FILE.exists():

        return []


    try:

        with open(
            NOTIFICATIONS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)


        # ------------------------------------------
        # 旧形式
        #
        # [
        #   {...},
        #   {...}
        # ]
        # ------------------------------------------

        if isinstance(
            data,
            list
        ):

            return data


        # ------------------------------------------
        # 現在の形式
        #
        # {
        #     "notifications": [...]
        # }
        # ------------------------------------------

        if isinstance(
            data,
            dict
        ):

            notifications = data.get(
                "notifications",
                []
            )

            if isinstance(
                notifications,
                list
            ):

                return notifications


        return []


    except (
        json.JSONDecodeError,
        OSError
    ):

        return []


# ==================================================
# お知らせデータ保存
# ==================================================

def save_notifications(
    notifications
):

    data = {

        "notifications":
            notifications

    }


    with open(
        NOTIFICATIONS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(

            data,

            f,

            ensure_ascii=False,

            indent=2
        )


# ==================================================
# お知らせID生成
# ==================================================

def get_next_notification_id(
    notifications
):

    max_id = 0


    for notification in notifications:

        if not isinstance(
            notification,
            dict
        ):

            continue


        try:

            notification_id = int(
                notification.get(
                    "id",
                    0
                )
            )


            if notification_id > max_id:

                max_id = notification_id


        except (
            TypeError,
            ValueError
        ):

            continue


    return max_id + 1


# ==================================================
# お知らせ並び替え
# ==================================================

def sort_notifications(
    notifications
):

    def sort_key(item):

        if not isinstance(
            item,
            dict
        ):

            return 0


        try:

            return int(
                item.get(
                    "id",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            return 0


    return sorted(
        notifications,
        key=sort_key,
        reverse=True
    )


# ==================================================
# 管理者ログイン確認
# ==================================================

def is_admin_logged_in():

    return bool(
        session.get(
            "admin_logged_in",
            False
        )
    )


# ==================================================
# 下り列車の両数
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


# ==================================================
# 列車番号を正常化
# ==================================================

def get_train_number(train):

    if not isinstance(
        train,
        dict
    ):

        return ""


    train_number = str(
        train.get(
            "train_number",
            ""
        )
    ).strip()


    cars = str(
        train.get(
            "cars",
            ""
        )
    ).strip()


    # 正常な列車番号
    if re.fullmatch(
        r"\d+M",
        train_number
    ):

        return train_number


    # cars に列車番号が入っている場合
    if re.fullmatch(
        r"\d+M",
        cars
    ):

        return cars


    return train_number


# ==================================================
# 列車データを正常化
# ==================================================

def normalize_train(train):

    if not isinstance(
        train,
        dict
    ):

        return train


    normalized = dict(
        train
    )


    # ----------------------------------------------
    # 列車番号
    # ----------------------------------------------

    train_number = get_train_number(
        train
    )


    if train_number:

        normalized[
            "train_number"
        ] = train_number


    # ----------------------------------------------
    # 種別
    # ----------------------------------------------

    if not normalized.get(
        "type"
    ):

        normalized[
            "type"
        ] = "普通"


    # ----------------------------------------------
    # 両数
    # ----------------------------------------------

    cars = normalized.get(
        "cars",
        ""
    )


    if isinstance(
        cars,
        str
    ):

        cars_text = cars.strip()


        if re.fullmatch(
            r"\d+M",
            cars_text
        ):

            if train_number in down_cars:

                normalized[
                    "cars"
                ] = down_cars[
                    train_number
                ]

            else:

                normalized[
                    "cars"
                ] = ""


    # 下り列車の両数
    if (

        normalized.get(
            "direction"
        ) == "下り"

        and

        train_number in down_cars

    ):

        current_cars = normalized.get(
            "cars"
        )


        if (

            current_cars is None

            or

            current_cars == ""

            or

            (
                isinstance(
                    current_cars,
                    str
                )

                and

                re.fullmatch(
                    r"\d+M",
                    current_cars.strip()
                )
            )

        ):

            normalized[
                "cars"
            ] = down_cars[
                train_number
            ]


    return normalized


# ==================================================
# ホーム
# ==================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# ==================================================
# 時刻表 API
# ==================================================

@app.route("/api/timetable")
def api_timetable():

    data = load_timetable()


    trains = data.get(
        "trains",
        []
    )


    normalized_trains = []


    for train in trains:

        normalized_trains.append(
            normalize_train(
                train
            )
        )


    result = dict(
        data
    )


    result[
        "trains"
    ] = normalized_trains


    return jsonify(
        result
    )


# ==================================================
# 駅ページ
# ==================================================

@app.route(
    "/station/<station>"
)
def station(station):

    station_map = {

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
            "name":
                "あしかがフラワーパーク駅",
            "english":
                "Ashikaga Flower Park Station"
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


    if station not in station_map:

        return (
            "駅が見つかりません",
            404
        )


    station_info = station_map[
        station
    ]


    return render_template(

        "timetable.html",

        station_id=station,

        station_name=
            station_info["name"],

        station_english=
            station_info["english"]

    )


# ==================================================
# 駅の時刻表リスト
# ==================================================

@app.route(
    "/station/<station>/timetable"
)
def station_timetable_list(
    station
):

    station_map = {

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
            "name":
                "あしかがフラワーパーク駅",
            "english":
                "Ashikaga Flower Park Station"
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


    if station not in station_map:

        return (
            "駅が見つかりません",
            404
        )


    station_info = station_map[
        station
    ]


    return render_template(

        "station_timetable.html",

        station_id=station,

        station_name=
            station_info["name"],

        station_english=
            station_info["english"]

    )


# ==================================================
# 列車詳細
# ==================================================

@app.route(
    "/train/<path:train_number>"
)
def train_detail(
    train_number
):

    data = load_timetable()


    trains = data.get(
        "trains",
        []
    )


    train_number = str(
        train_number
    ).strip()


    train = None


    for item in trains:

        normalized = normalize_train(
            item
        )


        current_number = get_train_number(
            normalized
        )


        if current_number == train_number:

            train = normalized

            break


    if train is None:

        return (
            "列車が見つかりません",
            404
        )


    # ==================================================
    # 駅名 英語
    # ==================================================

    station_map = {

        "小山": "Oyama",
        "思川": "Omoigawa",
        "栃木": "Tochigi",
        "大平下": "Ōhirashita",
        "岩舟": "Iwafune",
        "佐野": "Sano",
        "富田": "Tomita",
        "足利": "Ashikaga",

        "あしかがフラワーパーク":
            "Ashikaga Flower Park",

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
       "新松戸": "Shim-Maatsudo",
       "西船橋": "Nishi-Funabashi",

       "北朝霞": "Kita-Asaka",
       "新秋津": "Shin-Akitsu",
       "立川": "Tachikawa",
       "八王子": "Hachiōji",
       "高尾": "Takao"

    }


    # ==================================================
    # 停車駅
    # ==================================================

    stops = []


    for station_name, station_data in (
        train.get(
            "stops",
            {}
        ) or {}
    ).items():

        if not isinstance(
            station_data,
            dict
        ):

            continue


        arrival = station_data.get(
            "arrival"
        )


        departure = station_data.get(
            "departure"
        )


        stops.append({

            "name":
                station_name,

            "english":
                station_map.get(
                    station_name,
                    station_name
                ),

            "arrival":
                arrival or "",

            "departure":
                departure or ""

        })


    # ==================================================
    # 種別
    # ==================================================

    type_name = (
        train.get(
            "type"
        )
        or
        "普通"
    )


    type_english_map = {

        "普通":
            "Local",

        "快速":
            "Rapid",

        "特急":
            "Limited Express",

        "臨時":
            "Extra",

        "団体":
            "Party",

        "回送":
            "Out of service",

        "試運転":
            "Test Run"

    }


    # ==================================================
    # 行先
    # ==================================================

    destination = (
        train.get(
            "destination"
        )
        or
        ""
    )


    destination_english_map = {

        "高崎":
            "Takasaki",

        "新前橋":
            "Shin-Maebashi",

        "前橋":
            "Maebashi",

        "伊勢崎":
            "Isesaki",

        "桐生":
            "Kiryū",

        "足利":
            "Ashikaga",

        "佐野":
            "Sano",
       
        "岩舟":
            "Iwafune",

        "栃木":
            "Tochigi",

        "小山":
            "Oyama",

        "大船":
            "Ōfuna",

        "新宿":
            "Shinjuku",

        "吉川美南":
            "Yoshikawaminami",

        "西船橋":
            "Nishi-Funabashi",

        "八王子":
            "Hachiōji",

        "高尾":
            "Takao"


    }


    return render_template(

        "train_detail.html",

        train=train,

        train_number=
            get_train_number(
                train
            ),

        station_id="sano",

        stops=stops,

        type_english=
            type_english_map.get(
                type_name,
                type_name
            ),

        destination_english=
            destination_english_map.get(
                destination,
                destination
            )

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
# 運行情報
# ==================================================

@app.route(
    "/api/operation"
)
def api_operation():

    url = (
        "https://transit.yahoo.co.jp/diainfo/168/0"
    )


    headers = {

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


    try:

        response = requests.get(

            url,

            headers=headers,

            timeout=20

        )


        print(
            "Yahoo!路線情報 HTTP status:",
            response.status_code
        )


        print(
            "Yahoo! response length:",
            len(response.text)
        )


        response.raise_for_status()


        soup = BeautifulSoup(

            response.text,

            "html.parser"

        )


        text = soup.get_text(

            " ",

            strip=True

        )


        print(
            "Yahoo!路線情報ページ取得成功"
        )


        updated = ""


        update_patterns = [

            re.compile(
                r"\d{1,2}月\d{1,2}日"
                r"\s*\d{1,2}時\d{2}分"
                r"\s*更新"
            ),

            re.compile(
                r"\d{1,2}月\d{1,2}日"
                r"\s*\d{1,2}時\d{2}分"
                r"\s*現在"
            )

        ]


        for pattern in update_patterns:

            match = pattern.search(
                text
            )


            if match:

                updated = match.group(0)

                break


        ryomo_index = text.find(
            "両毛線"
        )


        if ryomo_index == -1:

            return jsonify({

                "line":
                    "両毛線",

                "status":
                    "情報取得中",

                "message":
                    "両毛線の運行情報を確認しています。",

                "updated":
                    updated,

                "source":
                    "Yahoo!路線情報"

            })


        ryomo_text = text[

            ryomo_index:

            ryomo_index + 500

        ]


        status = "情報取得中"


        message = (
            "現在、両毛線の運行情報を確認しています。"
        )


        if (

            "平常運転" in ryomo_text

            or

            "事故・遅延に関する情報はありません"
            in ryomo_text

        ):

            status = "平常運転"

            message = (
                "両毛線は平常通り運転しています。"
            )


        elif (

            "運転見合わせ" in ryomo_text

            or

            "運転を見合わせ" in ryomo_text

        ):

            status = "運転見合わせ"

            message = ryomo_text[:300]


        elif "運休" in ryomo_text:

            status = "運休"

            message = ryomo_text[:300]


        elif (

            "遅延" in ryomo_text

            or

            "遅れ" in ryomo_text

            or

            "運転状況" in ryomo_text

        ):

            status = "遅延"

            message = ryomo_text[:300]


        return jsonify({

            "line":
                "両毛線",

            "status":
                status,

            "message":
                message,

            "updated":
                updated,

            "source":
                "Yahoo!路線情報"

        })


    except requests.exceptions.RequestException as e:

        return jsonify({

            "line":
                "両毛線",

            "status":
                "情報取得中",

            "message":
                "運行情報を取得できません。",

            "updated":
                "",

            "source":
                "Yahoo!路線情報",

            "error":
                str(e)

        })


    except Exception as e:

        return jsonify({

            "line":
                "両毛線",

            "status":
                "情報取得中",

            "message":
                "運行情報の取得中にエラーが発生しました。",

            "updated":
                "",

            "source":
                "Yahoo!路線情報",

            "error":
                str(e)

        })


# ==================================================
# お知らせページ
# ==================================================

@app.route(
    "/notifications"
)
def notifications():

    return render_template(
        "notifications.html"
    )


# ==================================================
# お知らせ API
# ==================================================

@app.route(
    "/api/notifications"
)
def api_notifications():

    notifications = load_notifications()


    notifications = sort_notifications(
        notifications
    )


    response = jsonify({

        "notifications":
            notifications,

        "count":
            len(notifications)

    })


    # ブラウザやプロキシに古い通知を
    # キャッシュさせない
    response.headers[
        "Cache-Control"
    ] = "no-store, no-cache, must-revalidate, max-age=0"


    response.headers[
        "Pragma"
    ] = "no-cache"


    return response


# ==================================================
# 管理者 お知らせ管理画面
# ==================================================

@app.route(
    "/admin/notifications",
    methods=[
        "GET",
        "POST"
    ]
)
def admin_notifications():

    # ==================================================
    # ログイン済み
    # ==================================================

    if is_admin_logged_in():

        # ----------------------------------------------
        # POST処理
        # ----------------------------------------------

        if request.method == "POST":

            action = request.form.get(
                "action",
                ""
            ).strip()


            # ==========================================
            # お知らせ投稿
            # ==========================================

            if action == "create":

                title = request.form.get(
                    "title",
                    ""
                ).strip()


                message = request.form.get(
                    "message",
                    ""
                ).strip()


                # タイトル・本文の両方がある場合だけ投稿
                if title and message:

                    notifications = (
                        load_notifications()
                    )


                    new_id = (
                        get_next_notification_id(
                            notifications
                        )
                    )


                    # ==================================
                    # 日本時間で現在時刻を取得
                    # ==================================

                    now = datetime.now(
                        ZoneInfo("Asia/Tokyo")
                    )


                    notification = {

                        "id":
                            new_id,

                        "title":
                            title,

                        "message":
                            message,

                        "date":
                            now.strftime(
                                "%Y-%m-%d"
                            ),

                        "time":
                            now.strftime(
                                "%H:%M"
                            )

                    }


                    notifications.append(
                        notification
                    )


                    save_notifications(
                        notifications
                    )


                    return redirect(
                        url_for(
                            "admin_notifications"
                        )
                    )


            # ==========================================
            # お知らせ削除
            # ==========================================

            elif action == "delete":

                notification_id = request.form.get(
                    "notification_id",
                    ""
                ).strip()


                new_notifications = []


                for item in load_notifications():

                    try:

                        current_id = int(
                            item.get(
                                "id",
                                -1
                            )
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        current_id = -1


                    if str(
                        current_id
                    ) != str(
                        notification_id
                    ):

                        new_notifications.append(
                            item
                        )


                save_notifications(
                    new_notifications
                )


                return redirect(
                    url_for(
                        "admin_notifications"
                    )
                )


        # ----------------------------------------------
        # 管理画面表示
        # ----------------------------------------------

        notifications = sort_notifications(
            load_notifications()
        )


        return render_template(

            "admin_notifications.html",

            logged_in=True,

            notifications=notifications,

            error=""

        )


    # ==================================================
    # 未ログイン
    # ==================================================

    if request.method == "POST":

        password = request.form.get(
            "password",
            ""
        )


        # パスワード比較
        if secrets.compare_digest(
            str(password),
            str(ADMIN_PASSWORD)
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

            notifications=[],

            error=
                "パスワードが正しくありません。"

        )


    return render_template(

        "admin_notifications.html",

        logged_in=False,

        notifications=[],

        error=""

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

    app.run(

        debug=True,

        host="127.0.0.1",

        port=5000

    )