"""大口受注開示の監視 + order_events.json 書き出し。

kessan-surprise(決算サプライズ発掘システム)の S2c シグナル(SPEC_v2 §4.3, §9)の
入力となるイベントログを蓄積する。連携は data/order_events.json の参照のみ
(API・DB共有はしない疎結合)。

- キーワード: 大口受注 / 受注のお知らせ / 受注に関するお知らせ(訂正は除外)
- 通知: 招集通知系とは別チャンネル(DISCORD_WEBHOOK_ORDERS、prefix [受注])
- ログ: data/order_events.json に {code(4桁), title, disclosed_at, url} を追記
"""
import os
import sys
import json
import requests
from datetime import datetime, timedelta, timezone

DISCORD_WEBHOOK_ORDERS = os.environ.get("DISCORD_WEBHOOK_ORDERS")
SEEN_FILE = "seen_order_docs.json"
EVENTS_FILE = "data/order_events.json"

ORDER_KEYWORDS = ["大口受注", "受注のお知らせ", "受注に関するお知らせ"]


def fetch_tdnet_recent():
    """過去2日分のTDnet全開示を取得(既存tdnet_scan.pyと同じyanoshin API)"""
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).date()
    yesterday = today - timedelta(days=1)
    start = yesterday.strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    url = f"https://webapi.yanoshin.jp/webapi/tdnet/list/{start}-{end}.json"
    params = {"limit": 5000}
    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"TDnet API error: {e}")
        return []


def is_order_disclosure(title):
    """大口受注系の開示か判定(訂正・株主優待等のノイズは除外)"""
    if not title:
        return False
    if "訂正" in title:
        return False
    return any(kw in title for kw in ORDER_KEYWORDS)


def to_4digit(code):
    """TDnetの5桁コード(末尾0)を4桁に正規化"""
    code = str(code or "").strip()
    if len(code) == 5 and code.endswith("0"):
        return code[:4]
    return code


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def load_events():
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE) as f:
            return json.load(f)
    return []


def save_events(events):
    os.makedirs(os.path.dirname(EVENTS_FILE), exist_ok=True)
    with open(EVENTS_FILE, "w") as f:
        json.dump(events, f, ensure_ascii=False, indent=1)


def notify_discord(message):
    """DISCORD_WEBHOOK_ORDERS へ送信。戻り値で成否を返す(疎通確認用に呼び出し元でログ出力する)。"""
    if not DISCORD_WEBHOOK_ORDERS:
        print("DISCORD_WEBHOOK_ORDERS が未設定です。")
        return False
    try:
        r = requests.post(DISCORD_WEBHOOK_ORDERS, json={"content": message}, timeout=10)
        if r.status_code >= 300:
            print(f"Discord error: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"Discord error: {e}")
        return False


def run_test_notification():
    """DISCORD_WEBHOOK_ORDERS の疎通確認のみ行う(TDnetスキャンは実行しない)。

    workflow_dispatch の test 入力から呼ばれる。実際の検知処理を経由せず、
    Webhookの登録有無・宛先チャンネルの疎通を素早く確認できるようにする。
    """
    msg = (
        "[受注] テスト通知: DISCORD_WEBHOOK_ORDERS の疎通確認です。"
        "この通知が見えていれば設定は正しく機能しています。"
        "(order_scan.py --test より送信、実際の受注検知ではありません)"
    )
    print(msg)
    ok = notify_discord(msg)
    print(f"Discord送信結果: {'成功' if ok else '失敗またはWebhook未設定'}")
    return 0 if ok else 1


def main():
    if "--test" in sys.argv:
        return run_test_notification()

    items = fetch_tdnet_recent()
    seen = load_seen()
    events = load_events()
    known_urls = {ev.get("url") for ev in events}

    new_count = 0
    for item in items:
        tdnet = item.get("Tdnet", {})
        tdnet_id = tdnet.get("id")
        title = tdnet.get("title", "") or ""
        if not tdnet_id or tdnet_id in seen:
            continue
        if not is_order_disclosure(title):
            continue
        seen.add(tdnet_id)

        code = to_4digit(tdnet.get("company_code", ""))
        name = tdnet.get("company_name", "")
        url = tdnet.get("document_url") or tdnet.get("url", "")
        pubdate = (tdnet.get("pubdate", "") or "")[:10]  # YYYY-MM-DD

        if url in known_urls:
            continue
        events.append({
            "code": code,
            "title": title,
            "disclosed_at": pubdate,
            "url": url,
        })
        new_count += 1

        msg = (
            f"[受注] {name}（{code}） {pubdate}\n"
            f"{title}\n{url}"
        )
        print(msg)
        notify_discord(msg)

    if new_count:
        save_events(events)
    save_seen(seen)
    print(f"完了: 新規受注イベント {new_count} 件（累計 {len(events)} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
