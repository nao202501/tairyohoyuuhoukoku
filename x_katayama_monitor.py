import os
import json
import requests

# === 設定 ===
BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
SEEN_FILE = "seen_x_tweets.json"

# 検索クエリ: 指定2アカウントからの片山関連投稿
QUERY = '(from:riorio1412 OR from:stock_unknown) ("片山晃" OR "五月さん")'


def search_tweets():
    from urllib.parse import urlencode, quote
    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    params = {
        "query": QUERY,
        "max_results": "10",
        "tweet.fields": "created_at,author_id,text",
        "expansions": "author_id",
        "user.fields": "username,name",
    }
    # 日本語を正しくURLエンコードするために手動でクエリ文字列を構築
    query_string = urlencode(params, quote_via=quote)
    full_url = f"{url}?{query_string}"
    try:
        r = requests.get(full_url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        print(f"X API HTTP error: {e}")
        print(f"Response: {r.text}")
        return {}
    except Exception as e:
        print(f"X API error: {e}")
        return {}



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
        print("DISCORD_WEBHOOK not set")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"Discord error: {e}")


def main():
    data = search_tweets()
    tweets = data.get("data", [])
    users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    
    seen = load_seen()
    new_hits = 0
    
    for tweet in tweets:
        tweet_id = tweet["id"]
        if tweet_id in seen:
            continue
        
        author_id = tweet["author_id"]
        author = users.get(author_id, {})
        username = author.get("username", "unknown")
        text = tweet.get("text", "")
        created_at = tweet.get("created_at", "")
        
        msg = (
            f"🎯 片山氏言及検知（X）\n"
            f"アカウント: @{username}\n"
            f"投稿日時: {created_at}\n"
            f"URL: https://twitter.com/{username}/status/{tweet_id}\n"
            f"\n本文:\n{text[:500]}"
        )
        print(msg)
        notify_discord(msg)
        seen.add(tweet_id)
        new_hits += 1
    
    save_seen(seen)
    print(f"検索結果: {len(tweets)} 件、新規通知: {new_hits} 件")


if __name__ == "__main__":
    main()
