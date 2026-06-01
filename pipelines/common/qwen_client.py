"""qwen orchestration via a LOCAL OpenAI-compatible endpoint (Ollama / vLLM).

All creative generation goes through here: topic -> script, image prompts,
category tag, music mood, and fresh topic propositions for the reject loop.
If the local endpoint is unreachable, a deterministic offline fallback keeps
the pipeline runnable for testing.
"""
from __future__ import annotations
import json, re, logging
from . import config

log = logging.getLogger("qwen")

try:
    from openai import OpenAI
    _client = OpenAI(base_url=config.QWEN_BASE_URL, api_key=config.QWEN_API_KEY)
except Exception:  # pragma: no cover
    _client = None


def _chat(system: str, user: str, want_json: bool = True) -> str:
    if _client is None:
        raise RuntimeError("openai client unavailable")
    kwargs = {}
    if want_json:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _client.chat.completions.create(
        model=config.QWEN_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.8,
        **kwargs,
    )
    return resp.choices[0].message.content


def _json(system: str, user: str, fallback: dict) -> dict:
    try:
        raw = _chat(system, user, want_json=True)
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0) if m else raw)
    except Exception as e:
        log.warning("qwen offline/parse-fail (%s); using fallback", e)
        return fallback


# ---------------------------------------------------------------- Pipeline A
def script_for_topic(topic: str) -> dict:
    """Return {title, category, mood, beats:[{text, image_prompt}], full_script}."""
    sys = ("You are a viral short-form scriptwriter. Output JSON only. "
           "Write a punchy 30-60s vertical-reel voiceover script. Hook in the "
           "first line. 4-7 beats. Each beat: spoken 'text' and a vivid 'image_prompt'.")
    user = (f'Topic: "{topic}". Return JSON: '
            '{"title": str, "category": one of [history,geography,science,default], '
            '"mood": one of [epic,calm,uplifting,mysterious,documentary], '
            '"beats": [{"text": str, "image_prompt": str}]}')
    fb = {
        "title": topic.strip().title(),
        "category": "default",
        "mood": "documentary",
        "beats": [
            {"text": f"Here's something surprising about {topic}.",
             "image_prompt": f"cinematic establishing shot about {topic}, dramatic lighting"},
            {"text": "Most people have no idea this is even true.",
             "image_prompt": f"close detail related to {topic}, shallow depth of field"},
            {"text": "But the story goes much deeper than that.",
             "image_prompt": f"wide atmospheric scene of {topic}, golden hour"},
            {"text": "And that changes how you see everything.",
             "image_prompt": f"symbolic abstract representation of {topic}"},
        ],
    }
    data = _json(sys, user, fb)
    data["full_script"] = " ".join(b["text"] for b in data.get("beats", []))
    return data


# ---------------------------------------------------------------- Pipeline B
def anecdote_script(seed_hint: str = "") -> dict:
    """Pull a historical/geographic anecdote and script it.
    Return {title, category, mood, full_script, keywords:[...]}."""
    sys = ("You are a documentary narrator. Output JSON only. Pull ONE true "
           "historical or geographic anecdote and write a 35-55s narration. "
           "Provide 4-6 footage search 'keywords' (concrete, filmable nouns).")
    user = (f'Seed/angle (optional): "{seed_hint}". Return JSON: '
            '{"title": str, "category": one of [history,geography,science], '
            '"mood": one of [epic,calm,mysterious,documentary], '
            '"narration": str, "keywords": [str]}')
    fb = {
        "title": "The Forgotten Library of Timbuktu",
        "category": "history",
        "mood": "mysterious",
        "narration": ("In the deserts of Mali, a city once held thousands of "
                      "manuscripts on astronomy, law, and medicine. Scholars "
                      "traveled for months to reach its libraries. When danger "
                      "came, families hid the books in the sand to save them."),
        "keywords": ["desert sand dunes", "ancient manuscript", "old library",
                     "african city aerial", "candle writing"],
    }
    data = _json(sys, user, fb)
    data["full_script"] = data.get("narration", "")
    return data


# ---------------------------------------------------------------- Shared
def topic_to_mood(topic: str) -> str:
    sys = "Output JSON only. Map the topic to one music mood."
    user = (f'Topic: "{topic}". Return {{"mood": one of '
            '[epic,calm,uplifting,mysterious,documentary]}}.')
    return _json(sys, user, {"mood": "documentary"}).get("mood", "documentary")


def new_proposition(pipeline: str, rejected_topic: str) -> str:
    """Reject loop: generate a fresh topic proposition different from the rejected one."""
    sys = "Output JSON only. Propose ONE fresh, engaging reel topic."
    flavor = ("a surprising fact, list, or 'did you know' angle" if pipeline == "A"
              else "a vivid historical or geographic anecdote")
    user = (f'Avoid anything like: "{rejected_topic}". Propose {flavor}. '
            'Return {"topic": str}.')
    return _json(sys, user, {"topic": f"An alternative angle on {rejected_topic}"}).get(
        "topic", rejected_topic)


def seed_topics(pipeline: str, n: int, profile: dict | None = None) -> list[str]:
    """Generate N starter topics for a weekly batch.

    `profile` (e.g. {'category':'history','mood':'mysterious'}) biases generation
    toward what has performed best, supplied by topic_engine.preferred_profile().
    """
    sys = "Output JSON only. Generate a diverse list of reel topics."
    flavor = ("surprising facts / 'did you know' hooks" if pipeline == "A"
              else "historical or geographic anecdotes")
    bias = ""
    if profile:
        bias = (" Favor topics that fit this best-performing profile: "
                + ", ".join(f"{k}={v}" for k, v in profile.items()) + ".")
    user = f'Return {{"topics": [{n} distinct {flavor} as strings]}}.{bias}'
    fb = {"topics": [f"{flavor.split('/')[0].strip()} #{i+1}" for i in range(n)]}
    out = _json(sys, user, fb).get("topics", [])
    # pad/truncate to exactly n
    while len(out) < n:
        out.append(f"Backup topic {len(out)+1}")
    return out[:n]


def thumbnail_titles(topic: str, title: str, n: int = 4) -> list[dict]:
    """MrBeast-style packaging variants: one-object, one-question, big number/stake.
    Return [{title, big_number, object}]."""
    sys = ("Output JSON only. You write high-CTR YouTube titles + thumbnail text "
           "using the formula: one clear question or claim, one concrete object, "
           "and one bold NUMBER/stake. Keep titles under 60 characters.")
    user = (f'Topic: "{topic}". Base title: "{title}". Return '
            f'{{"variants": [{n} items of {{"title": str, "big_number": str (e.g. "$1M", "100", "24h"), '
            '"object": str}}]}}.')
    fb = {"variants": [
        {"title": f"The TRUTH about {title}", "big_number": "#1", "object": title},
        {"title": f"Why {title}? (you won't believe)", "big_number": "99%", "object": title},
        {"title": f"{title} in 60 seconds", "big_number": "60s", "object": title},
        {"title": f"I tested {title}", "big_number": "10x", "object": title},
    ]}
    out = _json(sys, user, fb).get("variants", [])
    while len(out) < n:
        out.append(fb["variants"][len(out) % len(fb["variants"])])
    return out[:n]
