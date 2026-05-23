import os
import json
import time
import re
import requests
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pypdf import PdfReader

# === 設定 ===
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
TARGET_NAMES = ["片山晃", "片山 晃"]
SEEN_FILE = "seen_tdnet_zenken.json"
TARGET_KEYWORDS = ["招集", "株主総会", "事業報告"]

MAJOR_SHAREHOLDERS_MARKERS = ["大株主の状況", "大株主の状況等"]
END_SECTION_MARKERS = [
    "議決権の状況", "従業員の状況", "ストックオプション",
    "新株予約権等", "コーポレート・ガバナンス", "監査の状況",
    "役員の状況", "会計監査人の状況",
]


def fetch_tdnet_today():
    """今日のTDnet全開示を取得"""
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y%m%d")
    url = f"https://webapi.yanoshin.jp/webapi/tdnet/list/{today}.json"
    params = {"limit": 1000}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"TDnet API error: {e}")
        return []


def is_shoshu_tsuchi(title):
    """招集通知系の書類か判定"""
    if not title:
        return False
    if "訂正" in title:
        return False
    return any(kw in title for kw in TARGET_KEYWORDS)


def download_pdf_text(url):
    """PDFをダウンロードしてテキスト抽出"""
    try:
        r = requests.get(url, timeout=60)
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
        print(f"PDF download/parse error: {e}")
        return ""


def extract_shareholders_section(text):
    """大株主の状況セクションを抽出"""
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
    """大株主セクション内に片山晃が居るか"""
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
    items = fetch_tdnet_today()
    seen = load_seen()
    
    candidates = []
    for item in items:
        tdnet = item.get("Tdnet", {})
        tdnet_id = tdnet.get("id")
        title = tdnet.get("title", "") or ""
        if not tdnet_id or tdnet_id in seen:
            continue
        if is_shoshu_tsuchi(title):
            candidates.append(tdnet)
    
    print(f"TDnet 招集通知 候補: {len(candidates)} 件")
    
    katayama_hits = 0
    for tdnet in candidates:
        tdnet_id = tdnet.get("id")
        title = tdnet.get("title", "")
        company_code = tdnet.get("company_code", "")
        company_name = tdnet.get("company_name", "")
        pdf_url = tdnet.get("document_url") or tdnet.get("url", "")
        
        seen.add(tdnet_id)
        
        if not pdf_url:
            continue
        
        print(f"処理中: {company_name}（{company_code}）")
        text = download_pdf_text(pdf_url)
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
                f"🎯 片山晃氏が大株主に発見！（TDnet 招集通知）\n"
                f"銘柄: {company_name}（{company_code}）\n"
                f"書類: {title}\n"
                f"PDF: {pdf_url}\n"
                f"\n抽出箇所:\n{context[:500]}"
            )
            print(msg)
            notify_discord(msg)
        
        time.sleep(2)
    
    save_seen(seen)
    print(f"完了: 候補 {len(candidates)} 件、片山氏ヒット {katayama_hits} 件")


if __name__ == "__main__":
    main()
