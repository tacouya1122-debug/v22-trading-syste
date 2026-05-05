# ============================================================
# V22 Nolan 完整部署版
# 功能：台灣時間 / 08:50盤前 / 09:05確認 / 13:45盤後
# 適用：Nolan、Render、Railway、GitHub Actions、雲端主機、排程器
# ============================================================

import os
import time
import smtplib
import datetime
import traceback
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd
import yfinance as yf

try:
    from FinMind.data import DataLoader
    FINMIND_READY = True
except Exception:
    FINMIND_READY = False


# ============================================================
# 1. 環境變數設定
# ============================================================
# Nolan / Render / GitHub Actions 建議用環境變數，不要把密碼寫死在程式。
#
# 必填：
# EMAIL_FROM
# EMAIL_TO
# EMAIL_APP_PASSWORD
#
# 選填：
# FINMIND_TOKEN
# SAVE_DIR

EMAIL_FROM = "tacouya1122@gmail.com")
EMAIL_TO = "tacouya1122@gmail.com")
EMAIL_APP_PASSWORD = "niiuoflwpzqcbwok"

FINMIND_TOKEN = "yk5ONCi2zr_iL3pWpAqj8KNR7IkOwfSuyI")
SAVE_DIR = os.getenv("SAVE_DIR", "./V22_reports")

SEND_EMAIL = os.getenv("SEND_EMAIL", "true").lower() == "true"

MAX_PER_BLOCK = 7


# ============================================================
# 2. 股票池
# ============================================================

STOCK_LIST = {
    "2330.TW": "台積電",
    "2454.TW": "聯發科",
    "2308.TW": "台達電",
    "2383.TW": "台光電",
    "2368.TW": "金像電",
    "2313.TW": "華通",
    "3037.TW": "欣興",
    "8046.TW": "南電",
    "2408.TW": "南亞科",
    "2344.TW": "華邦電",
    "2337.TW": "旺宏",
    "3260.TW": "威剛",
    "8299.TWO": "群聯",
    "3081.TWO": "聯亞",
    "6442.TW": "光聖",
    "4979.TW": "華星光",
    "3711.TW": "日月光投控",
    "2449.TW": "京元電",
    "3231.TW": "緯創",
}


# ============================================================
# 3. 台灣時間
# ============================================================

TAIWAN_TZ = datetime.timezone(datetime.timedelta(hours=8))

def now_tw():
    return datetime.datetime.now(TAIWAN_TZ)

def now_tw_str():
    return now_tw().strftime("%Y/%m/%d %H:%M:%S")

def now_file_str():
    return now_tw().strftime("%Y%m%d_%H%M%S")

def today_str():
    return now_tw().strftime("%Y-%m-%d")

def phase_by_run_type(run_type: str):
    mapping = {
        "premarket_0850": "08:50盤前偵測",
        "open_confirm_0905": "09:05盤中確認",
        "aftermarket_1345": "13:45盤後復盤",
        "manual": "手動執行",
    }
    return mapping.get(run_type, "手動執行")

def is_905_phase(run_type: str):
    return run_type == "open_confirm_0905"


# ============================================================
# 4. 資料引擎：yfinance + FinMind
# ============================================================

def ticker_to_finmind_id(ticker):
    return ticker.replace(".TW", "").replace(".TWO", "")

def get_yfinance_data(ticker, period="120d", interval="1d", retry=3):
    for i in range(retry):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=False,
                threads=False
            )

            if df is not None and not df.empty:
                df = df.reset_index()

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

                df.columns = [str(c).replace(" ", "_") for c in df.columns]

                if "Date" in df.columns:
                    df["date"] = pd.to_datetime(df["Date"])
                elif "Datetime" in df.columns:
                    df["date"] = pd.to_datetime(df["Datetime"])
                else:
                    df["date"] = pd.to_datetime(df.index)

                df["source"] = "yfinance"
                return df

        except Exception as e:
            print(f"⚠️ yfinance 第 {i+1} 次失敗：{ticker} | {e}")
            time.sleep(1.5)

    return None

def get_finmind_data(ticker, days=150, retry=3):
    if not FINMIND_READY:
        return None

    stock_id = ticker_to_finmind_id(ticker)
    end_date = now_tw().date()
    start_date = end_date - datetime.timedelta(days=days)

    for i in range(retry):
        try:
            api = DataLoader()

            if FINMIND_TOKEN:
                api.login_by_token(api_token=FINMIND_TOKEN)

            df = api.taiwan_stock_daily(
                stock_id=stock_id,
                start_date=str(start_date),
                end_date=str(end_date)
            )

            if df is not None and not df.empty:
                df = df.rename(columns={
                    "open": "Open",
                    "max": "High",
                    "min": "Low",
                    "close": "Close",
                    "Trading_Volume": "Volume",
                })
                df["date"] = pd.to_datetime(df["date"])
                df["source"] = "FinMind"
                return df

        except Exception as e:
            print(f"⚠️ FinMind 第 {i+1} 次失敗：{ticker} | {e}")
            time.sleep(1.5)

    return None

def get_stock_data_v22(ticker):
    print(f"📡 抓資料：{ticker}")

    df = get_yfinance_data(ticker)
    if df is not None and not df.empty:
        print(f"✅ {ticker} 使用 yfinance")
        return df

    print(f"🔁 {ticker} 改用 FinMind")
    df = get_finmind_data(ticker)
    if df is not None and not df.empty:
        print(f"✅ {ticker} 使用 FinMind")
        return df

    print(f"🚫 {ticker} 雙引擎失敗")
    return None


# ============================================================
# 5. V22 判斷核心
# ============================================================

def normalize_columns(df):
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in df.columns:
            for c in df.columns:
                if str(c).lower() == col.lower():
                    df[col] = df[c]
    return df

def analyze_one_stock(ticker, name, df, run_type):
    df = normalize_columns(df).copy()
    df = df.dropna(subset=["Close"]).sort_values("date")

    if len(df) < 20:
        return {
            "ticker": ticker,
            "name": name,
            "category": "觀察",
            "score": 50,
            "close": "資料不足",
            "reason": "K線資料不足20筆，列觀察。",
            "source": df["source"].iloc[-1] if "source" in df.columns else "unknown",
            "action": "等資料完整，不追。",
        }

    close = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2])
    ma5 = float(df["Close"].tail(5).mean())
    ma10 = float(df["Close"].tail(10).mean())
    ma20 = float(df["Close"].tail(20).mean())
    ma60 = float(df["Close"].tail(60).mean()) if len(df) >= 60 else None

    vol = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0
    vol5 = float(df["Volume"].tail(5).mean()) if "Volume" in df.columns else 0

    ret = (close - prev_close) / prev_close * 100 if prev_close else 0

    score = 50
    reasons = []

    if close > ma5 > ma10 > ma20:
        score += 25
        reasons.append("均線多頭")
    elif close > ma10:
        score += 10
        reasons.append("站上10MA")
    else:
        score -= 10
        reasons.append("結構未穩")

    if ma60 and close > ma60:
        score += 5
        reasons.append("站上60MA")
    elif ma60:
        score -= 5
        reasons.append("低於60MA")

    if vol5 > 0 and vol > vol5 * 1.3:
        score += 15
        reasons.append("量能放大")
    elif vol5 > 0 and vol < vol5 * 0.7:
        score -= 5
        reasons.append("量能不足")

    if ret > 3:
        score += 10
        reasons.append("短線強勢")
    elif ret < -3:
        score -= 15
        reasons.append("短線轉弱")

    if score >= 85:
        category = "主升"
    elif score >= 75:
        category = "起爆"
    elif score >= 65:
        category = "準備"
    elif score >= 50:
        category = "觀察"
    else:
        category = "假動作"

    if run_type == "premarket_0850":
        action = "盤前只分類，不下單；等9:05確認。"
    elif run_type == "open_confirm_0905":
        if score >= 80:
            action = "9:05確認後可列入下單候選；回檔接，不追高。"
        elif score >= 65:
            action = "9:05後觀察承接，不急追。"
        else:
            action = "9:05轉弱，不可下單。"
    elif run_type == "aftermarket_1345":
        action = "盤後復盤，列入明日觀察名單。"
    else:
        action = "手動執行，依目前時間與盤勢判斷。"

    buy_low = round(close * 0.985, 2)
    buy_high = round(close * 1.005, 2)
    stop = round(close * 0.955, 2)

    return {
        "ticker": ticker,
        "name": name,
        "category": category,
        "score": round(score, 1),
        "close": round(close, 2),
        "ret": round(ret, 2),
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2) if ma60 else "-",
        "buy_range": f"{buy_low} ~ {buy_high}",
        "stop": stop,
        "source": df["source"].iloc[-1] if "source" in df.columns else "unknown",
        "reason": "、".join(reasons),
        "action": action,
    }


# ============================================================
# 6. HTML 戰鬥 UI
# ============================================================

CATEGORY_STYLE = {
    "主升": {"title": "🔥 主升股｜紅色核心攻擊區", "bg": "#ffecec", "border": "#ff4d4f"},
    "起爆": {"title": "🚀 起爆股｜橘色9:05確認區", "bg": "#fff4e6", "border": "#ff922b"},
    "準備": {"title": "🟡 準備股｜等待放量區", "bg": "#fffbe6", "border": "#fadb14"},
    "觀察": {"title": "👀 觀察股｜藍色等待區", "bg": "#eef6ff", "border": "#4096ff"},
    "假動作": {"title": "❌ 假動作｜灰色不追區", "bg": "#f5f5f5", "border": "#8c8c8c"},
}

def card_html(r):
    style = CATEGORY_STYLE.get(r["category"], CATEGORY_STYLE["觀察"])
    return f"""
    <div style="
        background:{style['bg']};
        border-left:8px solid {style['border']};
        padding:16px;
        border-radius:14px;
        margin:12px 0;
        box-shadow:0 2px 8px rgba(0,0,0,0.06);
    ">
        <div style="font-size:22px;font-weight:900;color:#111827;">
            {r['name']}（{r['ticker']}）｜{r['category']}
        </div>
        <div style="margin-top:8px;line-height:1.8;color:#374151;font-size:15px;">
            <b>收盤：</b>{r['close']}｜<b>漲跌：</b>{r['ret']}%｜<b>分數：</b>{r['score']}｜<b>資料源：</b>{r['source']}<br>
            <b>MA5：</b>{r['ma5']}｜<b>MA10：</b>{r['ma10']}｜<b>MA20：</b>{r['ma20']}｜<b>MA60：</b>{r['ma60']}<br>
            <b>買進觀察區：</b>{r['buy_range']}｜<b>停損：</b>{r['stop']}<br>
            <b>理由：</b>{r['reason']}<br>
            <b>V22動作：</b>{r['action']}
        </div>
    </div>
    """

def build_report(results, failed, run_type):
    phase = phase_by_run_type(run_type)
    now = now_tw_str()

    grouped = {c: [] for c in CATEGORY_STYLE.keys()}
    for r in results:
        grouped.get(r["category"], grouped["觀察"]).append(r)

    for c in grouped:
        grouped[c] = sorted(grouped[c], key=lambda x: x["score"], reverse=True)[:MAX_PER_BLOCK]

    html = f"""
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0;background:#f3f4f6;font-family:Arial,'Microsoft JhengHei',sans-serif;">
    <div style="max-width:940px;margin:auto;padding:20px;">

        <div style="
            background:linear-gradient(135deg,#0b1b3b,#123a73);
            color:white;
            padding:30px;
            border-radius:22px;
            margin-bottom:18px;
        ">
            <div style="font-size:32px;font-weight:900;">🔥 混血型戰鬥系統 V22｜Nolan部署版</div>
            <div style="font-size:18px;margin-top:14px;line-height:1.8;">
                執行階段：{phase}<br>
                台灣時間：{now}<br>
                成功：{len(results)} 檔｜失敗：{len(failed)} 檔
            </div>
        </div>

        <div style="background:white;padding:20px;border-radius:18px;margin-bottom:16px;">
            <div style="font-size:24px;font-weight:900;">✅ 今日操作總結</div>
            <div style="font-size:17px;line-height:1.9;margin-top:8px;color:#374151;">
                盤前：只分類，不下單。<br>
                9:05：只做承接確認，不追弱股。<br>
                盤後：復盤與明日觀察名單。<br>
                V22新增：Nolan外部排程，不怕Colab關閉。
            </div>
        </div>
    """

    for cat, style in CATEGORY_STYLE.items():
        items = grouped[cat]
        html += f"""
        <div style="background:white;padding:20px;border-radius:18px;margin-bottom:16px;">
            <div style="font-size:24px;font-weight:900;color:#111827;margin-bottom:10px;">
                {style['title']}（最多{MAX_PER_BLOCK}檔）
            </div>
        """
        if not items:
            html += """
            <div style="padding:16px;background:#f9fafb;border-radius:12px;color:#6b7280;">
                本區目前沒有標的。
            </div>
            """
        else:
            for r in items:
                html += card_html(r)
        html += "</div>"

    if failed:
        html += """
        <div style="background:white;padding:18px;border-radius:18px;margin-bottom:16px;">
        <div style="font-size:22px;font-weight:900;color:#991b1b;">⚠️ 資料失敗清單</div><ul>
        """
        for t, n in failed:
            html += f"<li>{n}（{t}）</li>"
        html += "</ul></div>"

    html += """
        <div style="text-align:center;color:#6b7280;font-size:12px;padding:20px;">
            V22 Nolan部署版｜資料來源：yfinance / FinMind｜非投資建議
        </div>
    </div>
    </body>
    </html>
    """
    return html


# ============================================================
# 7. 儲存與寄信
# ============================================================

def save_report(html, run_type):
    base = Path(SAVE_DIR)
    day_dir = base / today_str()
    day_dir.mkdir(parents=True, exist_ok=True)

    filename = f"V22_{run_type}_{now_file_str()}.html"
    path = day_dir / filename
    latest = base / "latest_report.html"

    path.write_text(html, encoding="utf-8")
    latest.write_text(html, encoding="utf-8")

    print(f"💾 報告已儲存：{path}")
    print(f"📌 最新報告：{latest}")
    return str(path)

def send_email(subject, html):
    if not SEND_EMAIL:
        print("📩 SEND_EMAIL=false，不寄信。")
        return False

    if not EMAIL_APP_PASSWORD:
        print("❌ EMAIL_APP_PASSWORD 未設定，不能寄信。")
        return False

    for i in range(3):
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = EMAIL_FROM
            msg["To"] = EMAIL_TO
            msg.attach(MIMEText(html, "html", "utf-8"))

            server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
            server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
            server.quit()

            print("✅ 信件寄送成功")
            return True
        except Exception as e:
            print(f"⚠️ 寄信第 {i+1} 次失敗：{e}")
            time.sleep(3)

    print("❌ 寄信失敗，但報告已儲存。")
    return False


# ============================================================
# 8. 主流程
# ============================================================

def run_v22(run_type="manual"):
    print("=" * 70)
    print(f"🔥 V22 Nolan部署版開始執行：{phase_by_run_type(run_type)}")
    print(f"🇹🇼 台灣時間：{now_tw_str()}")
    print("=" * 70)

    results = []
    failed = []

    for ticker, name in STOCK_LIST.items():
        try:
            df = get_stock_data_v22(ticker)
            if df is None or df.empty:
                failed.append((ticker, name))
                continue

            result = analyze_one_stock(ticker, name, df, run_type)
            results.append(result)

        except Exception as e:
            print(f"❌ {ticker} 分析失敗：{e}")
            traceback.print_exc()
            failed.append((ticker, name))

    html = build_report(results, failed, run_type)
    path = save_report(html, run_type)

    subject = f"🔥 V22戰鬥報告｜{phase_by_run_type(run_type)}｜{now_tw_str()}"
    send_email(subject, html)

    print("=" * 70)
    print("✅ V22 Nolan部署版執行完成")
    print(f"成功：{len(results)}｜失敗：{len(failed)}")
    print(f"報告：{path}")
    print("=" * 70)

    return {
        "results": results,
        "failed": failed,
        "path": path,
        "html": html,
    }


# ============================================================
# 9. 命令列入口
# ============================================================
# 用法：
# python v22_nolan_deploy.py premarket_0850
# python v22_nolan_deploy.py open_confirm_0905
# python v22_nolan_deploy.py aftermarket_1345

if __name__ == "__main__":
    import sys
    run_type = sys.argv[1] if len(sys.argv) > 1 else "manual"
    run_v22(run_type)
# 🔥 防止 Railway 判定為 crash
import time
while True:
    time.sleep(60)