# eb1a-reddit-reader

A read-only, one-time reader for public posts in r/eb_1a, for personal
research into how self-petitioners documented their EB-1A cases.

## What it does

- Authenticates as the app itself with Reddit's app-only OAuth
  (`client_credentials` grant). No user password is involved.
- Reads the subreddit's `new` and `top` listing pages (up to 100 posts per
  request, paginated) and then the comments of each post.
- Stores title, body, date, score, flair, and comment text in a local SQLite
  file. Usernames are not stored.
- Paces requests under Reddit's rate limit using the `X-Ratelimit-*` headers.

## What it does not do

- It never posts, comments, votes, or sends messages.
- It does not read user profiles, private subreddits, or messages.
- It is not scheduled; it runs once, by hand, on the researcher's own machine.
- It publishes nothing back to Reddit or anywhere else.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env     # add REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME
python3 reddit_eb1a_reader.py --subreddit eb_1a --out eb1a.db
python3 reddit_eb1a_reader.py --out eb1a.db --export posts.csv
```

`REDDIT_USERNAME` is used only to build the User-Agent string Reddit asks
for (`script:eb1a-reddit-reader:0.1 (by /u/<username>)`).

## Request volume

Roughly 30 to 50 listing requests plus one request per post with comments,
on the order of a few hundred to two thousand requests in total, at under
100 per minute.

## License

MIT. Not affiliated with Reddit or USCIS. Not legal advice.
