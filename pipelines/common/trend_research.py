"""Autonomous trend research via Reddit, YouTube RSS, Google Trends."""
from __future__ import annotations
import urllib.request, json, xml.etree.ElementTree as ET, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import config, qwen_client, supervisor

def fetch_reddit_trends(subreddits=["videos", "YouTube", "trendingvideos"]) -> list[dict]:
    """Fetch hot posts from Reddit public subreddits (no auth needed)."""
    trends = []
    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
            req = urllib.request.Request(url, headers={"User-Agent": "MrBeast-AI-Team/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                for i, post in enumerate(data.get("data", {}).get("children", [])):
                    t = post["data"]
                    if t.get("selftext") or not t.get("url"):
                        continue
                    score = t.get("ups", 0)
                    trends.append({
                        "topic": t.get("title", "").strip(),
                        "raw_score": score / (i + 1),  # discount by position
                        "source": f"reddit/{sub}",
                    })
        except Exception as e:
            pass  # graceful: skip this subreddit
    return trends

def fetch_youtube_rss_trends() -> list[dict]:
    """Fetch YouTube trending RSS (public, no auth)."""
    trends = []
    try:
        url = "https://www.youtube.com/feeds/videos.xml?chart=mostpopular"
        with urllib.request.urlopen(url, timeout=5) as resp:
            tree = ET.parse(resp)
            root = tree.getroot()
            for i, entry in enumerate(root.findall("{http://www.w3.org/2005/Atom}entry")):
                title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
                if title_elem is not None and title_elem.text:
                    trends.append({
                        "topic": title_elem.text.strip(),
                        "raw_score": 100.0 / (i + 1),
                        "source": "youtube_rss",
                    })
    except Exception as e:
        pass
    return trends

def fetch_google_trends() -> list[dict]:
    """Fetch Google Trends RSS (public, no auth)."""
    trends = []
    try:
        url = "https://trends.google.com/trending/rss?geo=US"
        with urllib.request.urlopen(url, timeout=5) as resp:
            tree = ET.parse(resp)
            root = tree.getroot()
            ns = {"ht": "http://www.google.com/trends/csv"}
            for i, item in enumerate(root.findall(".//item")):
                title_elem = item.find("title")
                traffic_elem = item.find("ht:approx_traffic", ns)
                if title_elem is not None and title_elem.text:
                    traffic_str = traffic_elem.text if traffic_elem is not None else "0"
                    traffic = int(re.sub(r"[^0-9]", "", traffic_str) or 0)
                    trends.append({
                        "topic": title_elem.text.strip(),
                        "raw_score": traffic / max(i + 1, 1),
                        "source": "google_trends",
                    })
    except Exception as e:
        pass
    return trends

def score_and_rank(candidates: list[dict], db=None) -> list[dict]:
    """
    Score candidates using qwen_client.topic_to_mood() + supervisor.priors.
    Blend raw_score (40%) + prior_score (60%).
    """
    if not candidates:
        return []

    scored = []
    for cand in candidates:
        try:
            # Get category via mood classification
            mood = qwen_client.topic_to_mood(cand["topic"])
            category_map = {
                "epic": "history",
                "calm": "geography",
                "uplifting": "geography",
                "mysterious": "science",
                "documentary": "science",
            }
            category = category_map.get(mood, "default")

            # Score via priors
            prior_score = supervisor.priors.score({"category": category, "source": cand["source"]})

            # Blend
            final_score = cand["raw_score"] * 0.4 + prior_score * 0.6

            scored.append({
                **cand,
                "prior_score": prior_score,
                "final_score": final_score,
                "category": category,
            })
        except Exception:
            scored.append({**cand, "prior_score": 0.0, "final_score": cand["raw_score"], "category": "default"})

    return sorted(scored, key=lambda x: x["final_score"], reverse=True)

def fetch_all_trends() -> list[dict]:
    """Fetch from all sources in parallel."""
    results = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [
            ex.submit(fetch_reddit_trends),
            ex.submit(fetch_youtube_rss_trends),
            ex.submit(fetch_google_trends),
        ]
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                pass
    return results

def deduplicate_topics(candidates: list[dict]) -> list[dict]:
    """Merge near-duplicate topics (same words, different order/punctuation)."""
    seen = {}
    for cand in candidates:
        key = " ".join(sorted(cand["topic"].lower().replace("?!", "").split()))
        if key not in seen or cand["raw_score"] > seen[key]["raw_score"]:
            seen[key] = cand
    return list(seen.values())
