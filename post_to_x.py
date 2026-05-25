import base64
import hashlib
import hmac
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request


TWEET_URL = "https://api.x.com/2/tweets"


def load_env(path=".env"):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def oauth_header(method, url, consumer_key, consumer_secret, token, token_secret):
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": hashlib.sha1(str(random.random()).encode()).hexdigest(),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    params = urllib.parse.urlencode(sorted(oauth.items()), quote_via=urllib.parse.quote)
    base = "&".join(urllib.parse.quote(x, safe="") for x in [method, url, params])
    key = "&".join(urllib.parse.quote(x, safe="") for x in [consumer_secret, token_secret])
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k)}="{urllib.parse.quote(v)}"'
        for k, v in sorted(oauth.items())
    )


def main():
    load_env()
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8-sig") as f:
            text = f.read().strip()
    else:
        text = sys.stdin.buffer.read().decode("utf-8-sig").strip()
    if not text:
        raise SystemExit("No post text was provided on stdin.")
    if len(text) > 280:
        raise SystemExit(f"Post is too long: {len(text)} characters.")

    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        TWEET_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": oauth_header(
                "POST",
                TWEET_URL,
                os.environ["X_API_KEY"],
                os.environ["X_API_KEY_SECRET"],
                os.environ["X_ACCESS_TOKEN"],
                os.environ["X_ACCESS_TOKEN_SECRET"],
            ),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        print(res.read().decode("utf-8"))


if __name__ == "__main__":
    main()
