import os
import json
import requests
from datetime import datetime, timedelta, timezone

# === 設定 ===
EDINET_API_KEY = os.environ["EDINET_API_KEY"]
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")  # Discord使う場合
LINE_TOKEN = os.environ.get("LINE_TOKEN")            # LINE使う場合
LINE_USER_ID = os.environ.get("LINE_USER_ID")        # LINE使う場合

# === 片山氏監視 ===
TARGET_NAMES = ["片山晃", "片山 晃"]
TARGET_DOC_KEYWORDS = ["大量保有報告書", "変更報告書"]

# === ウォッチリスト銘柄監視 ===
WATCHLIST_SEC_CODES = {
    "40220": "ラサ工業",
    "44610": "第一工業製薬",
    "59890": "エイチワン",
    "62270": "AIメカテック",
    "378A0": "ヒット",
}
WATCHLIST_DOC_KEYWORDS = ["有価証券報告書", "半期報告書"]

# 既通知docIDのキャッシュ（GitHub Actionsならアーティファクトに保存）
SEEN_FILE = "seen_docs.json"


def fetch_edinet_documents(date_str):
    """指定日のEDINET書類一覧を取得"""
    url = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
    params = {
        "date": date_str,
        "type": 2,  # 提出書類一覧及びメタデータ
        "Subscription-Key": EDINET_API_KEY,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])


def is_katayama_filing(doc):
    """片山氏の大量保有/変更報告書か"""
    filer = doc.get("filerName", "") or ""
    desc = doc.get("docDescription", "") or ""
    if "訂正" in desc:
        return False
    name_match = any(name in filer for name in TARGET_NAMES)
    doc_match = any(kw in desc for kw in TARGET_DOC_KEYWORDS)
    return name_match and doc_match


def is_watchlist_filing(doc):
    """ウォッチリスト銘柄の有報・半期報告書か"""
    sec_code = doc.get("secCode", "") or ""
    desc = doc.get("docDescription", "") or ""
    if "訂正" in desc:
        return False
    code_match = sec_code in WATCHLIST_SEC_CODES
    doc_match = any(kw in desc for kw in WATCHLIST_DOC_KEYWORDS)
    return code_match and doc_match


def is_target_filing(doc):
    return is_katayama_filing(doc) or is_watchlist_filing(doc)


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def notify_discord(message):
    if not DISCORD_WEBHOOK:
        return
    requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)


def notify_line(message):
    if not (LINE_TOKEN and LINE_USER_ID):
        return
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {LINE_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "to": LINE_USER_ID,
            "messages": [{"type": "text", "text": message}],
        },
        timeout=10,
    )


def main():
    # 今日と昨日をスキャン(土日の取りこぼし防止)
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).date()
    dates_to_check = [today, today - timedelta(days=1)]

    seen = load_seen()
    new_hits = []

    for d in dates_to_check:
        try:
            docs = fetch_edinet_documents(d.strftime("%Y-%m-%d"))
        except Exception as e:
            print(f"API error on {d}: {e}")
            continue

        for doc in docs:
            doc_id = doc.get("docID")
            if not doc_id or doc_id in seen:
                continue
            if is_target_filing(doc):
                new_hits.append(doc)
                seen.add(doc_id)

    for doc in new_hits:
        doc_id = doc.get('docID')
        sec_code = doc.get('secCode') or ''
        company_label = WATCHLIST_SEC_CODES.get(sec_code, '')

        if is_katayama_filing(doc):
            header = "🚨 片山晃氏のEDINET開示"
        else:
            header = f"📊 ウォッチリスト銘柄の開示: {company_label}（{sec_code[:4]}）"

        msg = (
            f"{header}\n"
            f"書類: {doc.get('docDescription')}\n"
            f"提出者: {doc.get('filerName')}\n"
            f"証券コード: {sec_code or '（記載なし）'}\n"
            f"提出日時: {doc.get('submitDateTime')}\n"
            f"docID: {doc_id}\n"
            f"EDINETで検索: https://disclosure2.edinet-fsa.go.jp/"
        )
        print(msg)
        notify_discord(msg)
        notify_line(msg)

    save_seen(seen)
    print(f"Scanned {len(dates_to_check)} days, {len(new_hits)} new hits")


if __name__ == "__main__":
    main()
