import base64
import hashlib
import hmac
import html
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
import urllib.error
import urllib.parse
import urllib.request


X_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
X_USERS_BY_USERNAME_URL = "https://api.x.com/2/users/by/username"
X_POST_URL = "https://api.x.com/2/tweets"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5-mini"
POST_USER_NAME = "to_be_a_BILLAR"
MAX_POST_CHARS = 190
JST = timezone(timedelta(hours=9))
MORNING_START_HOUR = 6
MORNING_END_HOUR = 9


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def request_json(url, headers=None, data=None, method=None):
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method or ("POST" if body is not None else "GET"),
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {detail[:800]}") from e


def bearer_headers():
    return {"Authorization": f"Bearer {required_env('X_BEARER_TOKEN')}"}


def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 BloombergMorningBot/1.0",
            "Accept-Language": "ja,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as res:
        return res.read().decode("utf-8", errors="replace")


def expand_url(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        with opener.open(req, timeout=30) as res:
            return res.geturl()
    except Exception:
        return url


def normalize_article_url(url):
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def search_bloomberg_tweet():
    query = '(from:BloombergJapan "今朝の5本") OR (from:BloombergJapan "今朝の５本") -is:retweet'
    params = urllib.parse.urlencode(
        {
            "query": query,
            "max_results": "10",
            "tweet.fields": "created_at,entities",
            "expansions": "author_id",
        }
    )
    data = request_json(f"{X_SEARCH_URL}?{params}", headers=bearer_headers())
    tweets = data.get("data", [])
    if not tweets:
        raise RuntimeError("No recent BloombergJapan 今朝の5本 tweet was found.")

    tweet = sorted(tweets, key=lambda item: item.get("created_at", ""), reverse=True)[0]
    urls = tweet.get("entities", {}).get("urls", [])
    for item in urls:
        candidate = item.get("unwound_url") or item.get("expanded_url") or item.get("url")
        if candidate:
            return tweet, normalize_article_url(expand_url(candidate))
    raise RuntimeError("Bloomberg tweet was found, but it had no URL entity.")


def extract_article_text(url):
    urls_to_try = [url, "https://r.jina.ai/" + url]
    for candidate in urls_to_try:
        try:
            text = fetch_text(candidate)
            text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 500:
                return text[:8000]
        except Exception:
            continue
    return ""


def openai_text(prompt):
    data = request_json(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {required_env('OPENAI_API_KEY')}",
            "Content-Type": "application/json",
        },
        data={
            "model": os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            "input": prompt,
            "max_output_tokens": 500,
        },
    )
    if data.get("output_text"):
        return data["output_text"].strip()

    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(content.get("text", ""))
    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError("OpenAI returned no text.")
    return text


def make_post(tweet, article_url, article_text):
    prompt = f"""
Bloomberg日本語公式Xアカウントの投稿と記事情報をもとに、X投稿文を日本語で1つ作ってください。

必須条件:
- 先頭は必ず「【サラリーマン必見】」
- 5項目の短いニュース要約を番号付きで入れる
- 市場示唆、注目分野、↑↓行は入れない
- 断定しすぎない
- Bloomberg記事URLを最後に入れる
- 記事本文の長い引用はしない
- 余計な説明や引用符は出さず、投稿文だけ返す
- URLを含めて190文字以内

公式X投稿:
{tweet.get("text", "")}

記事URL:
{article_url}

記事テキスト抜粋:
{article_text}
""".strip()
    post = openai_text(prompt).strip().strip('"').strip("'")
    if article_url not in post:
        post = post.rstrip() + "\n" + article_url
    if not post.startswith("【サラリーマン必見】"):
        post = "【サラリーマン必見】" + post
    post = "\n".join(
        line for line in post.splitlines()
        if not line.startswith(("↑", "↓", "↑↑", "↓↓", "注目"))
    )
    if len(post) > MAX_POST_CHARS:
        shorten_prompt = f"""
次のX投稿文をURL込み190文字以内に圧縮してください。

必須条件:
- 先頭は必ず「【サラリーマン必見】」
- 番号付きニュース5項目を残す
- 市場示唆、注目分野、↑↓行は入れない
- 最後に記事URLを残す
- 投稿文だけ返す

記事URL:
{article_url}

元の投稿文:
{post}
""".strip()
        post = openai_text(shorten_prompt).strip().strip('"').strip("'")
        if article_url not in post:
            post = post.rstrip() + "\n" + article_url
        if not post.startswith("【サラリーマン必見】"):
            post = "【サラリーマン必見】" + post
    if len(post) > MAX_POST_CHARS:
        lines = post.splitlines()
        body_lines = [line for line in lines if "bloomberg.com" not in line]
        compact = []
        for line in body_lines:
            if line.startswith("【サラリーマン必見】"):
                compact.append("【サラリーマン必見】")
            elif re.match(r"^\d+\.", line):
                compact.append(line[:22])
        post = "\n".join(compact[:6] + [article_url])
    if len(post) > MAX_POST_CHARS:
        raise RuntimeError(f"Generated post is too long after shortening: {len(post)} characters\n{post}")
    return post


def user_timeline(username):
    user = request_json(f"{X_USERS_BY_USERNAME_URL}/{username}", headers=bearer_headers())
    user_id = user.get("data", {}).get("id")
    if not user_id:
        return []
    params = urllib.parse.urlencode(
        {
            "max_results": "20",
            "tweet.fields": "created_at,entities",
            "exclude": "retweets,replies",
        }
    )
    data = request_json(f"https://api.x.com/2/users/{user_id}/tweets?{params}", headers=bearer_headers())
    return data.get("data", []) or []


def already_posted(article_url):
    target = normalize_article_url(article_url)
    try:
        for tweet in user_timeline(POST_USER_NAME):
            for item in tweet.get("entities", {}).get("urls", []) or []:
                candidate = item.get("unwound_url") or item.get("expanded_url") or item.get("url") or ""
                if normalize_article_url(candidate) == target:
                    print(f"Already posted article URL in tweet {tweet.get('id')}; skipping.")
                    return True
    except Exception as exc:
        print(f"Duplicate check failed; continuing: {exc}")
    return False


def percent(value):
    return urllib.parse.quote(str(value), safe="")


def oauth_header(method, url, consumer_key, consumer_secret, token, token_secret, params=None):
    params = params or {}
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": hashlib.sha1(str(random.random()).encode()).hexdigest(),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    signing_params = {**params, **oauth}
    param_string = "&".join(f"{percent(k)}={percent(v)}" for k, v in sorted(signing_params.items()))
    base = "&".join(percent(x) for x in [method, url, param_string])
    key = "&".join(percent(x) for x in [consumer_secret, token_secret])
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    return "OAuth " + ", ".join(
        f'{percent(k)}="{percent(v)}"'
        for k, v in sorted(oauth.items())
    )


def post_to_x(text):
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        X_POST_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": oauth_header(
                "POST",
                X_POST_URL,
                required_env("X_API_KEY"),
                required_env("X_API_KEY_SECRET"),
                required_env("X_ACCESS_TOKEN"),
                required_env("X_ACCESS_TOKEN_SECRET"),
            ),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as res:
            print(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"X post failed: HTTP {e.code}: {detail[:800]}") from e


def is_scheduled_event():
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def in_morning_window():
    now = datetime.now(JST)
    return MORNING_START_HOUR <= now.hour < MORNING_END_HOUR


def should_skip_for_time_window():
    if os.environ.get("FORCE_POST") == "1":
        return False
    return is_scheduled_event() and not in_morning_window()


def main():
    if should_skip_for_time_window():
        now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"Outside JST morning post window ({now}); skipping.")
        return

    try:
        tweet, article_url = search_bloomberg_tweet()
    except RuntimeError as exc:
        if is_scheduled_event() and "No recent BloombergJapan" in str(exc):
            print(f"Bloomberg morning tweet is not available yet; skipping: {exc}")
            return
        raise

    if already_posted(article_url):
        return
    article_text = extract_article_text(article_url)
    if not article_text:
        article_text = tweet.get("text", "")
    post = make_post(tweet, article_url, article_text)
    print("Generated post:")
    print(post)
    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN=1, so the post was not sent.")
        return
    post_to_x(post)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
