#!/usr/bin/env python3
"""
================================================================================
 BUILD_DATA.PY
================================================================================
Generates the JSON data files consumed by the static web app in /docs.

Usage:
    python build_data.py --mode daily
    python build_data.py --mode weekly
    python build_data.py --mode sources     # regenerate docs/data/sources.json only

--------------------------------------------------------------------------
WHY "NOTEWORTHINESS" INSTEAD OF "POPULARITY"
--------------------------------------------------------------------------
Free, public RSS feeds do not expose click counts, view counts, or share
counts -- that data belongs to the publishers and isn't published. Rather
than fabricate numbers, this app ranks stories with a transparent composite
score built entirely from signals present in the feeds themselves:

  1. Cross-source corroboration (heaviest weight): how many distinct
     outlets are covering essentially the same story right now. This is
     the closest free proxy to "this is actually a big deal" -- when wire
     services and multiple newsrooms independently pick up a story, that
     IS a real signal of significance, not a guess.
  2. Source authority tier: a coarse, hand-maintained weighting of outlet
     editorial rigor (wire services / major broadsheets score higher).
  3. Salience language: presence of high-signal words in the headline
     ("breaking", "resigns", "record", "crisis", etc).
  4. Feed position: most outlets order their own RSS feed by editorial
     priority, so an item's position in its source feed carries signal
     beyond pure recency.
  5. Recency decay: freshness within the observation window.

The UI always shows "Reported by N outlets" next to the score so readers
can see the underlying evidence, not just trust an opaque number.
================================================================================
"""

import argparse
import json
import datetime as dt
from pathlib import Path

import news_engine as engine

DATA_DIR = Path(__file__).parent / "docs" / "data"

# --- Cadence configuration ---------------------------------------------------
DAILY_WINDOW_HOURS = 24
DAILY_MAX_PER_STACK = 4
DAILY_MIN_SCORE = 20        # a real threshold: quiet days can show fewer/zero

WEEKLY_WINDOW_HOURS = 24 * 7
WEEKLY_MAX_PER_STACK = 8
WEEKLY_MIN_SCORE = 8        # weekly digest is comprehensive, so threshold is lower


def article_to_json(article):
    """Slim an internal article dict down to what the frontend needs."""
    published = article["published_utc"]
    return {
        "title": article["title"],
        "link": article["link"],
        "snippet": article["snippet"],
        "source_domain": article["source_domain"],
        "outlet_name": article["outlet_name"],
        "published_utc": published.isoformat() if published else None,
        "stack": article["stack"],
        "stack_tag": engine.STACK_TAGS.get(article["stack"], ""),
        "score": article["score"],
        "corroboration_count": article.get("corroboration_count", 1),
        "corroborating_outlets": sorted({
            c["outlet_name"] for c in article.get("cluster_corroborators", [])
        }),
    }


def build_and_write(mode, now_utc):
    if mode == "daily":
        window_hours, max_per_stack, min_score = (
            DAILY_WINDOW_HOURS, DAILY_MAX_PER_STACK, DAILY_MIN_SCORE,
        )
    elif mode == "weekly":
        window_hours, max_per_stack, min_score = (
            WEEKLY_WINDOW_HOURS, WEEKLY_MAX_PER_STACK, WEEKLY_MIN_SCORE,
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")

    dataset = engine.build_dataset(now_utc, window_hours, max_per_stack, min_score)

    payload = {
        "generated_at": now_utc.isoformat(),
        "mode": mode,
        "window_hours": window_hours,
        "stacks": {
            stack: [article_to_json(a) for a in dataset[stack]]
            for stack in engine.STACK_ORDER
        },
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / f"{mode}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[INFO] Wrote {out_path} "
          f"({sum(len(v) for v in payload['stacks'].values())} total stories)")


def build_sources_file():
    """Write the human-readable list of every outlet the app pulls from."""
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stacks": {
            stack: [
                {"outlet_name": name, "feed_url": url, "stack_tag": engine.STACK_TAGS[stack]}
                for name, url in outlets
            ]
            for stack, outlets in engine.FEEDS.items()
        },
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "sources.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[INFO] Wrote {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Build news app JSON data files.")
    parser.add_argument("--mode", choices=["daily", "weekly", "sources"], required=True)
    args = parser.parse_args()

    now_utc = dt.datetime.now(dt.timezone.utc)
    print(f"[INFO] Build mode={args.mode} started at {now_utc.isoformat()}")

    if args.mode == "sources":
        build_sources_file()
    else:
        build_and_write(args.mode, now_utc)
        build_sources_file()  # keep the sources list fresh on every run too


if __name__ == "__main__":
    main()
