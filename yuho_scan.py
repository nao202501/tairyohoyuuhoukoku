import os
import json
import time
import re
import requests
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pypdf import PdfReader

# === 設定 ===
EDINET_API_KEY = os.environ["EDINET_API_KEY"]
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
TARGET_NAMES = ["片山晃", "片山 晃"]
SEEN_FILE = "seen_hanki_zenken.json"
TARGET_DOC_KEYWORD = "半期報告書"
MAJOR_SHAREHOLDERS_MARKERS = ["大株主の状況", "大株主の状況等"]
END_SECTION_MARKERS = [
    "議決権の状況", "従業員の状況", "ストックオプション",
    "新株予約権等", "コーポレート・ガバナンス", "監査の状況",
    "役員の状況", "会計監査人の状況",
]


def fetch_edinet_today():
    """今日のEDINET全書類一覧を取得"""
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y-%m-%d")
    url = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
    params = {"date": today, "type": 2, "Subscription-Key": EDINET_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as e:
        print(f"EDINET API error: {e}")
        return []


def is_hanki_houkokusho(doc):
    """半期報告書か判定（訂正・投資信託は除外、上場会社のみ）"""
    desc = doc.get("docDescription", "") or ""
    sec_code = doc.get("secCode", "") or ""
    
    if "訂正" in desc:
        return False
    # 上場会社（証券コードあり）のみを対象にする
    if not sec_code:
        return False
    # 念のため投資信託キーワードも除外
    if "投資信託" in desc or "ファンド" in desc:
        return False
    return TARGET_DOC_KEYWORD in desc


def download_edinet_pdf_text(doc_id):
    """EDINET PDFをダウンロードしてテキスト化"""
    url = f"https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"
    params = {"type": 2, "Subscription-Key": EDINET_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        reader = PdfReader(BytesIO(r.content))
        text = ""
        for page in reader.pages:
            try:
                text += page.extract_text() + "\n"
            except Exception:
                continue
        return text
    except Exception as e:
        print(f"PDF error ({doc_id}): {e}")
        return ""


def extract_shareholders_section(text):
    start_idx = -1
    for marker in MAJOR_SHAREHOLDERS_MARKERS:
        idx = text.find(marker)
        if idx != -1 and (start_idx == -1 or idx < start_idx):
            start_idx = idx
    if start_idx == -1:
        return ""
    section = text[start_idx:start_idx + 8000]
    for marker in END_SECTION_MARKERS:
        end_idx = section.find(marker, 100)
        if end_idx != -1:
            section = section[:end_idx]
            break
    return section


def find_katayama(section):
    for name in TARGET_NAMES:
        idx = section.find(name)
        if idx != -1:
            context = section[max(0, idx-100):min(len(section), idx+400)]
            context_clean = re.sub(r"\s+", " ", context).strip()
            return True, context_clean
    return False, ""


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
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"Discord error: {e}")


def main():
    docs = fetch_edinet_today()
    seen = load_seen()
    
    candidates = []
    for doc in docs:
        doc_id = doc.get("docID")
        if not doc_id or doc_id in seen:
            continue
        if is_hanki_houkokusho(doc):
            candidates.append(doc)
    
    print(f"EDINET 半期報告書 候補: {len(candidates)} 件")
    
    katayama_hits = 0
    for doc in candidates:
        doc_id = doc.get("docID")
        filer_name = doc.get("filerName", "")
        sec_code = doc.get("secCode", "") or ""
        desc = doc.get("docDescription", "")
        
        seen.add(doc_id)
        
        print(f"処理中: {filer_name}（{sec_code}）")
        text = download_edinet_pdf_text(doc_id)
        if not text:
            continue
        
        section = extract_shareholders_section(text)
        if not section:
            print(f"  → 大株主セクション未検出")
            continue
        
        found, context = find_katayama(section)
        if found:
            katayama_hits += 1
            msg = (
                f"🎯 片山晃氏が大株主に発見！（EDINET 半期報告書）\n"
                f"銘柄: {filer_name}（{sec_code[:4]}）\n"
                f"書類: {desc}\n"
                f"docID: {doc_id}\n"
                f"EDINETで検索: https://disclosure2.edinet-fsa.go.jp/\n"
                f"\n抽出箇所:\n{context[:500]}"
            )
            print(msg)
            notify_discord(msg)
        
        time.sleep(3)
    
    save_seen(seen)
    print(f"完了: 候補 {len(candidates)} 件、片山氏ヒット {katayama_hits} 件")


if __name__ == "__main__":
    main()
