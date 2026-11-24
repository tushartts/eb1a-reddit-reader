#!/usr/bin/env python3
"""Read-only, one-time reader for public posts in r/eb_1a.

Authenticates as the app itself (script app, client_credentials grant; no user
password), reads the subreddit's listing pages and the comments of each post,
and stores the text in a local SQLite file for personal research. It never
posts, votes, messages, or reads user profiles, private subreddits, or
messages. Usernames are not stored.

Usage:
    cp .env.example .env   # fill in REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME
    python3 reddit_eb1a_reader.py --subreddit eb_1a --out eb1a.db
    python3 reddit_eb1a_reader.py --export posts.csv
"""
import argparse, csv, os, sqlite3, sys, time
import requests

API = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
VERSION = "0.1"


def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def user_agent():
    user = os.environ.get("REDDIT_USERNAME", "unknown")
    return f"script:eb1a-reddit-reader:{VERSION} (by /u/{user})"


def get_token():
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env")
    r = requests.post(TOKEN_URL, auth=(cid, secret), data={"grant_type": "client_credentials"},
                      headers={"User-Agent": user_agent()}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


class Client:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"bearer {token}", "User-Agent": user_agent()})

    def get(self, path, **params):
        """GET with respect for Reddit's rate-limit headers."""
        while True:
            r = self.s.get(API + path, params=params, timeout=30)
            remaining = float(r.headers.get("X-Ratelimit-Remaining", "10") or 10)
            reset = float(r.headers.get("X-Ratelimit-Reset", "1") or 1)
            if r.status_code == 429 or remaining < 2:
                time.sleep(max(reset, 2))
                if r.status_code == 429:
                    continue
            r.raise_for_status()
            time.sleep(0.7)  # stay well under 100 requests per minute
            return r.json()


def init_db(path):
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS posts (
        id TEXT PRIMARY KEY, subreddit TEXT, title TEXT, body TEXT, created_utc REAL,
        score INTEGER, num_comments INTEGER, flair TEXT, permalink TEXT, fetched_at REAL);
    CREATE TABLE IF NOT EXISTS comments (
        id TEXT PRIMARY KEY, post_id TEXT, parent_id TEXT, body TEXT, created_utc REAL,
        score INTEGER, is_submitter INTEGER, depth INTEGER);
    """)
    return con


def read_listing(client, con, subreddit, sort, max_pages):
    after, pages, n = None, 0, 0
    while pages < max_pages:
        params = {"limit": 100, "raw_json": 1}
        if sort == "top":
            params["t"] = "all"
        if after:
            params["after"] = after
        data = client.get(f"/r/{subreddit}/{sort}", **params)["data"]
        for child in data["children"]:
            p = child["data"]
            con.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (p["id"], subreddit, p.get("title"), p.get("selftext"), p.get("created_utc"),
                         p.get("score"), p.get("num_comments"), p.get("link_flair_text"),
                         p.get("permalink"), time.time()))
            n += 1
        con.commit()
        after, pages = data.get("after"), pages + 1
        if not after:
            break
    return n


def walk(children, post_id, con, depth=0):
    for child in children:
        if child.get("kind") != "t1":
            continue
        c = child["data"]
        con.execute("INSERT OR REPLACE INTO comments VALUES (?,?,?,?,?,?,?,?)",
                    (c["id"], post_id, c.get("parent_id"), c.get("body"), c.get("created_utc"),
                     c.get("score"), 1 if c.get("is_submitter") else 0, depth))
        replies = c.get("replies")
        if isinstance(replies, dict):
            walk(replies["data"]["children"], post_id, con, depth + 1)


def read_comments(client, con, subreddit):
    ids = [r[0] for r in con.execute("SELECT id FROM posts WHERE subreddit=? AND num_comments>0", (subreddit,))]
    done = {r[0] for r in con.execute("SELECT DISTINCT post_id FROM comments")}
    todo = [i for i in ids if i not in done]
    for k, pid in enumerate(todo, 1):
        data = client.get(f"/r/{subreddit}/comments/{pid}", limit=500, depth=10, raw_json=1)
        walk(data[1]["data"]["children"], pid, con)
        con.commit()
        if k % 25 == 0:
            print(f"  comments: {k}/{len(todo)} posts", file=sys.stderr)
    return len(todo)


def export(con, path):
    rows = con.execute("SELECT id, title, body, created_utc, score, num_comments, flair, permalink FROM posts ORDER BY created_utc DESC")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "body", "created_utc", "score", "num_comments", "flair", "url"])
        for r in rows:
            w.writerow(list(r[:-1]) + ["https://www.reddit.com" + (r[-1] or "")])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subreddit", default="eb_1a")
    ap.add_argument("--out", default="eb1a.db")
    ap.add_argument("--max-pages", type=int, default=10, help="listing pages per sort (100 posts each)")
    ap.add_argument("--no-comments", action="store_true")
    ap.add_argument("--export", help="write posts to this CSV and exit")
    a = ap.parse_args()
    load_env()
    con = init_db(a.out)
    if a.export:
        export(con, a.export)
        print(f"wrote {a.export}")
        return
    client = Client(get_token())
    for sort in ("new", "top"):
        n = read_listing(client, con, a.subreddit, sort, a.max_pages)
        print(f"{sort}: {n} posts read", file=sys.stderr)
    if not a.no_comments:
        n = read_comments(client, con, a.subreddit)
        print(f"comments read for {n} posts", file=sys.stderr)
    print(f"done: {a.out}")


if __name__ == "__main__":
    main()
