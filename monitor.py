import os
import json
import requests
from datetime import datetime, timedelta, timezone

# === 設定 ===
EDINET_API_KEY = os.environ["EDINET_API_KEY"]
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")  # Discord使う場合
LINE_TOKEN = os.environ.get("LINE_TOKEN")            # LINE使う場合
LINE_USER_ID = os.environ.get("LINE_USER_ID")        # LINE使う場合

# 監視対象の人物名（部分一致）
TARGET_NAMES = ["片山晃", "片山 晃"]

# 監視対象の書類（docDescriptionに含まれる文字列）
TARGET_DOC_KEYWORDS = ["大量保有報告書", "変更報告書"]

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


def is_target_filing(doc):
    """片山氏の大量保有/変更報告書かを判定"""
    filer = doc.get("filerName", "") or ""
    desc = doc.get("docDescription", "") or ""

    name_match = any(name in filer for name in TARGET_NAMES)
    doc_match = any(kw in desc for kw in TARGET_DOC_KEYWORDS)
    return name_match and doc_match


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
        msg = (
            f"🚨 片山晃氏のEDINET開示\n"
            f"書類: {doc.get('docDescription')}\n"
            f"発行体: {doc.get('filerName')} / 証券コード: {doc.get('secCode')}\n"
            f"提出日時: {doc.get('submitDateTime')}\n"
            f"EDINET: https://disclosure2.edinet-fsa.go.jp/WEEK0040.aspx?"
            f"S100Dat=&S100SD={doc.get('docID')}"
        )
        print(msg)
        notify_discord(msg)
        notify_line(msg)

    save_seen(seen)
    print(f"Scanned {len(dates_to_check)} days, {len(new_hits)} new hits")


if __name__ == "__main__":
    main()
