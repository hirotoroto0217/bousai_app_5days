from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 気象庁の青森市区分コード（青森市）
AREA_CODE = "0220100"
LOCATION_LATITUDE = 40.8244
LOCATION_LONGITUDE = 140.7400

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')
DISASTER_REPORTS_FILE = os.path.join(APP_DIR, 'data', 'disaster_reports.json')
CITIZEN_REPORTS_FILE = os.path.join(APP_DIR, 'data', 'citizen_reports.json')
PUBLISHED_INFO_FILE = os.path.join(APP_DIR, 'data', 'published_info.json')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])
disaster_reports = load_json(DISASTER_REPORTS_FILE, [])
citizen_reports = load_json(CITIZEN_REPORTS_FILE, [])
published_info = load_json(PUBLISHED_INFO_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_shelters():
    """避難所データをファイルに保存する"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(shelters, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def save_disaster_reports():
    """災害報告をファイルに保存する"""
    try:
        with open(DISASTER_REPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(disaster_reports, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_board_data(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def board_id(data):
    return max((item.get('id', 0) for item in data), default=0) + 1


def admin_api_required():
    if not session.get('logged_in'):
        return jsonify({'error': '管理者権限が必要です'}), 403
    return None
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、なければ全件を返す"""
    return [s for s in shelters if not district or s.get('district') == district]


SHELTER_READINGS = {
    '青森県庁': 'あおもりけんちょう',
    '片瀬小学校': 'かたせしょうがっこう',
    '神戸大学': 'こうべだいがく',
    '鵠洋小学校': 'こうようしょうがっこう',
    '御所見小学校': 'ごしょみしょうがっこう',
    '鳥取西高校': 'とっとりにしこうこう'
}


def shelter_sort_key(shelter):
    """登録済みの読み仮名を優先して避難所をあいうえお順にする"""
    name = shelter.get('name', '')
    return shelter.get('reading') or SHELTER_READINGS.get(name) or name


def safe_float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def distance_km(latitude1, longitude1, latitude2, longitude2):
    radius = 6371
    lat1, lat2 = math.radians(latitude1), math.radians(latitude2)
    delta_lat = math.radians(latitude2 - latitude1)
    delta_lng = math.radians(longitude2 - longitude1)
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def search_shelters(disaster=None, capacity=None, elderly=None, children=None, conditions=None, user_lat=None, user_lng=None):
    results = []
    capacity_min = None
    if capacity:
        match = re.search(r'\d+', str(capacity).replace('０', '0').replace('１', '1').replace('２', '2').replace('３', '3').replace('４', '4').replace('５', '5').replace('６', '6').replace('７', '7').replace('８', '8').replace('９', '9'))
        capacity_min = int(match.group()) if match else None
    conditions = [item for item in (conditions or '').split(',') if item]
    for shelter in shelters:
        if disaster and disaster not in shelter.get('disasters', []):
            continue
        if capacity_min is not None and (not isinstance(shelter.get('capacity'), (int, float)) or shelter['capacity'] < capacity_min):
            continue
        if elderly == '1' and not shelter.get('elderly'):
            continue
        if elderly == '0' and shelter.get('elderly'):
            continue
        if children == '1' and not shelter.get('children'):
            continue
        if children == '0' and shelter.get('children'):
            continue
        if any(not shelter.get(condition) for condition in conditions):
            continue
        result = dict(shelter)
        latitude = safe_float(shelter.get('latitude'))
        longitude = safe_float(shelter.get('longitude'))
        if user_lat is not None and user_lng is not None and latitude is not None and longitude is not None:
            result['distance_km'] = round(distance_km(user_lat, user_lng, latitude, longitude), 2)
            result['distance_available'] = True
        elif user_lat is not None and user_lng is not None:
            result['distance_km'] = float('inf')
            result['distance_available'] = False
        results.append(result)
    if user_lat is not None and user_lng is not None:
        results.sort(key=lambda shelter: shelter.get('distance_km', float('inf')))
    return results


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            active_statuses = (
                "発表",
                "継続",
                "危険警報から警報",
                "警報から注意報",
                "危険警報から注意報"
            )
            if status not in active_statuses or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": "発表" if status not in ("発表", "継続") else status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)
        weather = get_weather_forecast()

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "weather": weather,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "weather": None,
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


def get_weather_forecast():
    """Open-Meteo から青森市の現在・当日予報を取得する"""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LOCATION_LATITUDE}&longitude={LOCATION_LONGITUDE}"
        "&current=temperature_2m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        "&forecast_days=1&timezone=Asia%2FTokyo"
    )
    try:
        with urllib.request.urlopen(url=url, timeout=10) as res:
            data = json.loads(res.read())
        current = data.get('current', {})
        daily = data.get('daily', {})
        return {
            'current_temperature': current.get('temperature_2m'),
            'weather_code': current.get('weather_code'),
            'maximum_temperature': (daily.get('temperature_2m_max') or [None])[0],
            'minimum_temperature': (daily.get('temperature_2m_min') or [None])[0],
            'precipitation_probability': (daily.get('precipitation_probability_max') or [None])[0],
            'unit': data.get('current_units', {}).get('temperature_2m', '°C')
        }
    except (OSError, ValueError, TypeError, KeyError):
        return None


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    latest_instructions = sorted(
        resident_notices,
        key=lambda item: item.get('updated_at') or item.get('created_at') or '',
        reverse=True
    )[:3]
    return render_template(
        'index.html',
        resident_notices=resident_notices,
        latest_instructions=latest_instructions,
        shelters=shelters,
        disaster_reports=disaster_reports
    )

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    form_data = {
        'name': '',
        'address': '',
        'capacity': '',
        'phone': '',
        'status': '',
        'pet_acceptance': '',
        'disasters': []
    }
    sorted_shelters = sorted(shelters, key=shelter_sort_key)

    if request.method == 'POST':
        form_data = {field: request.form.get(field, '').strip() for field in form_data}
        form_data['disasters'] = request.form.getlist('disasters')
        action = request.form.get('action', 'register')
        if action == 'delete':
            target = next((shelter for shelter in shelters if shelter.get('name') == form_data['name']), None)
            if not target:
                return render_template('shelter_register.html', error=True, message='削除対象の避難所が見つかりません。', form_data=form_data, shelters=sorted_shelters)
            return render_template('shelter_register.html', confirm_delete=True, form_data=form_data, shelters=sorted_shelters)

        if action == 'cancel_delete':
            return render_template('shelter_register.html', form_data=form_data, shelters=sorted_shelters)

        if action == 'confirm_delete':
            target_index = next((index for index, shelter in enumerate(shelters) if shelter.get('name') == form_data['name']), None)
            if target_index is None:
                return render_template('shelter_register.html', error=True, message='削除対象の避難所が見つかりません。', form_data=form_data, shelters=sorted_shelters)
            shelters.pop(target_index)
            if not save_shelters():
                return render_template('shelter_register.html', error=True, message='保存に失敗しました。', form_data=form_data, shelters=sorted_shelters)
            return render_template('shelter_register.html', success=True, message='データを削除しました。', form_data={field: '' for field in form_data}, shelters=sorted(shelters, key=shelter_sort_key))

        errors = {}
        name = form_data['name']
        address = form_data['address']
        if not name:
            errors['name'] = '避難所名を入力してください。'
        if re.fullmatch(r'[0-9０-９\-‐‑‒–—―ー()（）\s]+', address or ''):
            errors['address'] = '電話番号ではなく、番地まで入力してください。'
        elif not re.search(r'(\d|[０-９])(?:丁目|番地?|号|[-‐‑‒–—―ー])', address):
            errors['address'] = '番地まで入力してください。'
        try:
            capacity = int(form_data['capacity'])
            if capacity < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors['capacity'] = '1以上の整数を入力してください。'
        if not re.fullmatch(r'[0-9０-９\s()（）\-‐‑‒–—―ー]+', form_data['phone'] or '') or not re.search(r'\d|[０-９]', form_data['phone']):
            errors['phone'] = '正しい電話番号を入力してください。'
        if form_data['status'] not in ('開設', '未開設'):
            errors['status'] = '「開設」または「未開設」を選択してください。'
        if form_data['pet_acceptance'] not in ('可', '不可'):
            errors['pet_acceptance'] = '「可」または「不可」を選択してください。'
        if not form_data['disasters']:
            errors['disasters'] = '災害の種類を1つ以上選択してください。'
        if any(shelter.get('name') == name for shelter in shelters):
            errors['name'] = '過去に同じ避難所が登録されています。'

        if errors:
            return render_template('shelter_register.html', error=True, message='必須項目に不備があります。', errors=errors, form_data=form_data, shelters=sorted_shelters)

        new_id = max((s.get('id', 0) for s in shelters), default=0) + 1
        shelters.append({
            'id': new_id,
            'name': name,
            'address': address,
            'capacity': capacity,
            'phone': form_data['phone'],
            'status': form_data['status'],
            'pet_acceptance': form_data['pet_acceptance'],
            'disasters': form_data['disasters'],
            'opening_status': form_data['status'],
            'congestion_status': '不明'
        })
        if not save_shelters():
            shelters.pop()
            return render_template('shelter_register.html', error=True, message='保存に失敗しました。', form_data=form_data, shelters=sorted_shelters)
        return render_template('shelter_register.html', success=True, message='登録完了しました！', form_data={field: '' for field in form_data}, shelters=sorted(shelters, key=shelter_sort_key))

    return render_template('shelter_register.html', form_data=form_data, shelters=sorted_shelters)


@app.route('/shelter/<int:shelter_id>')
def shelter_detail(shelter_id):
    shelter = next((item for item in shelters if item.get('id') == shelter_id), None)
    if shelter is None:
        return '避難所が見つかりません。', 404
    return render_template('shelter_detail.html', shelter=shelter)

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html')

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=sorted(shelters, key=shelter_sort_key))


# 指示・発信ボード：未ログインは公開掲示板、ログイン済みは管理者版
@app.route('/board')
def board():
    return render_template('board.html', is_admin=bool(session.get('logged_in')))


@app.route('/citizen_board')
def citizen_board_compatibility():
    return redirect(url_for('board'))


@app.route('/api/published_info')
def api_published_info():
    return jsonify([item for item in published_info if item.get('published', True)])


@app.route('/api/add_citizen_report', methods=['POST'])
def api_add_citizen_report():
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data.get('title') or not data.get('type') or not data.get('location') or not data.get('content'):
        return jsonify({'error': 'title, type, location, content are required'}), 400
    item = {
        'id': board_id(citizen_reports), 'title': data['title'].strip(),
        'type': data['type'].strip(), 'location': data['location'].strip(),
        'name': data.get('name', '').strip() or '匿名', 'content': data['content'].strip(),
        'read': False, 'status': '報告済み', 'created_at': get_japan_time()
    }
    citizen_reports.append(item)
    if not save_board_data(CITIZEN_REPORTS_FILE, citizen_reports):
        citizen_reports.pop()
        return jsonify({'error': '保存に失敗しました'}), 500
    return jsonify(item), 201


@app.route('/api/instructions')
def api_instructions():
    denied = admin_api_required()
    return denied or jsonify(instructions)


@app.route('/api/add_instruction', methods=['POST'])
@login_required
def api_add_instruction():
    data = request.get_json(silent=True) or {}
    required = ('title', 'target', 'type', 'location', 'content')
    if any(not str(data.get(key, '')).strip() for key in required):
        return jsonify({'error': '必須項目が不足しています'}), 400
    item = {'id': board_id(instructions), **{key: str(data[key]).strip() for key in required}, 'status': data.get('status', '指示中'), 'created_at': get_japan_time()}
    instructions.append(item)
    if not save_board_data(INSTRUCTIONS_FILE, instructions):
        instructions.pop()
        return jsonify({'error': '保存に失敗しました'}), 500
    return jsonify(item), 201


@app.route('/api/update_instruction_status', methods=['POST'])
@login_required
def api_update_instruction_status():
    data = request.get_json(silent=True) or {}
    item = next((x for x in instructions if x.get('id') == data.get('id')), None)
    if not item or data.get('status') not in ('指示中', '対応中', '完了', '解除'):
        return jsonify({'error': '対象または状態が不正です'}), 400
    item['status'] = data['status']
    save_board_data(INSTRUCTIONS_FILE, instructions)
    return jsonify(item)


@app.route('/api/citizen_reports')
@login_required
def api_citizen_reports():
    return jsonify(citizen_reports)


@app.route('/api/mark_citizen_report_read', methods=['POST'])
@login_required
def api_mark_citizen_report_read():
    data = request.get_json(silent=True) or {}
    item = next((x for x in citizen_reports if x.get('id') == data.get('id')), None)
    if not item:
        return jsonify({'error': '対象が見つかりません'}), 404
    item['read'] = True
    save_board_data(CITIZEN_REPORTS_FILE, citizen_reports)
    return jsonify(item)


@app.route('/api/update_report_status', methods=['POST'])
@login_required
def api_update_report_status():
    data = request.get_json(silent=True) or {}
    item = next((x for x in citizen_reports if x.get('id') == data.get('id')), None)
    allowed = ('報告済み', '確認済み', '対応中', '対応完了', '掲示済み')
    if not item or data.get('status') not in allowed:
        return jsonify({'error': '対象または状態が不正です'}), 400
    item['status'] = data['status']
    save_board_data(CITIZEN_REPORTS_FILE, citizen_reports)
    return jsonify(item)


@app.route('/api/publish_info', methods=['POST'])
@login_required
def api_publish_info():
    data = request.get_json(silent=True) or {}
    required = ('title', 'type', 'location', 'content', 'urgency')
    if any(not str(data.get(key, '')).strip() for key in required):
        return jsonify({'error': '必須項目が不足しています'}), 400
    item = {'id': board_id(published_info), **{key: str(data[key]).strip() for key in required}, 'published': True, 'created_at': get_japan_time()}
    published_info.append(item)
    save_board_data(PUBLISHED_INFO_FILE, published_info)
    return jsonify(item), 201


@app.route('/api/unpublish_info', methods=['POST'])
@login_required
def api_unpublish_info():
    data = request.get_json(silent=True) or {}
    item = next((x for x in published_info if x.get('id') == data.get('id')), None)
    if not item:
        return jsonify({'error': '対象が見つかりません'}), 404
    item['published'] = False
    save_board_data(PUBLISHED_INFO_FILE, published_info)
    return jsonify(item)

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    user_lat = safe_float(request.args.get('lat'))
    user_lng = safe_float(request.args.get('lng'))
    results = search_shelters(
        request.args.get('disasters'),
        request.args.get('capacity'),
        request.args.get('elderly'),
        request.args.get('children'),
        request.args.get('conditions'),
        user_lat,
        user_lng
    )
    return render_template('search_results.html', results=results, search_params=request.args)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())


@app.route('/api/disaster_reports', methods=['GET', 'POST'])
def api_disaster_reports():
    """別アプリからの災害報告を取得・登録する API"""
    if request.method == 'POST':
        report = request.get_json(silent=True) or {}
        required = ('type', 'title', 'description', 'address', 'latitude', 'longitude')
        if any(report.get(field) in (None, '') for field in required):
            return jsonify({'error': 'type, title, description, address, latitude, longitude are required'}), 400

        new_report = {
            'id': max((item.get('id', 0) for item in disaster_reports), default=0) + 1,
            'type': str(report['type']),
            'title': str(report['title']),
            'description': str(report['description']),
            'address': str(report['address']),
            'latitude': float(report['latitude']),
            'longitude': float(report['longitude']),
            'reported_at': report.get('reported_at') or get_japan_time()
        }
        disaster_reports.append(new_report)
        save_disaster_reports()
        return jsonify(new_report), 201

    return jsonify(disaster_reports)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
