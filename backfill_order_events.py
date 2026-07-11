"""order_events.json の初期バックフィル(一回限りの実行)。

order_scan.py の稼働開始前に、過去の大口受注開示を遡って蓄積する。
kessan-surprise のキャリブレーション(SPEC_v2 §8: 直近8四半期の遡及適用)で
S2c判定を実データで行えるようにするのが目的(S2cのコールドスタート対策)。

使い方: python backfill_order_events.py 2024-01-01 [end]
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import requests

from order_scan import EVENTS_FILE, is_order_disclosure, to_4digit, load_events, save_events


def fetch_range(start, end):
    url = f"https://webapi.yanoshin.jp/webapi/tdnet/list/{start}-{end}.json"
    r = requests.get(url, params={"limit": 5000}, timeout=60,
                     headers={"User-Agent": "tairyohoyuuhoukoku-backfill/0.1"})
    r.raise_for_status()
    return r.json().get("items", [])


def main():
    start = date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2024-01-01")
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()

    events = load_events()
    known = {(ev.get("url"), ev.get("disclosed_at")) for ev in events}
    added = 0

    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=6), end)
        s, e = cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")
        try:
            items = fetch_range(s, e)
        except Exception as ex:
            print(f"  {s}-{e}: 取得失敗 {ex}(スキップ)")
            cur = chunk_end + timedelta(days=1)
            continue
        hit = 0
        for item in items:
            td = item.get("Tdnet", {})
            title = td.get("title", "") or ""
            if not is_order_disclosure(title):
                continue
            url = td.get("document_url") or td.get("url", "")
            pubdate = (td.get("pubdate", "") or "")[:10]
            if (url, pubdate) in known:
                continue
            known.add((url, pubdate))
            events.append({
                "code": to_4digit(td.get("company_code", "")),
                "title": title,
                "disclosed_at": pubdate,
                "url": url,
            })
            hit += 1
            added += 1
        print(f"  {s}-{e}: 開示{len(items)}件中 受注{hit}件")
        if len(items) >= 5000:
            print(f"  ⚠ {s}-{e}: limit=5000に到達(取りこぼしの可能性)")
        cur = chunk_end + timedelta(days=1)
        time.sleep(1.5)

    events.sort(key=lambda ev: ev.get("disclosed_at") or "")
    save_events(events)
    print(f"完了: 追加 {added} 件(累計 {len(events)} 件)→ {EVENTS_FILE}")


if __name__ == "__main__":
    main()
