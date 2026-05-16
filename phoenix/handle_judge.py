"""Handle Judge 2.1 for recent X posts.

This module is deliberately not a narrative "algorithm thread" clone. It is a
runnable simulator and transparent judge:

1. Fast heuristic mode scores current or pasted posts with auditable signals.
2. Optional Phoenix simulation mode runs synthetic candidate IDs through the
   released Phoenix ranker artifacts when they are available locally.

The Phoenix path is intentionally framed as a simulation. The open release can
rank hashed post/author IDs, but it does not understand arbitrary live post text.
The heuristic path carries the creator-facing judgment and explains every score.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


X_API = "https://api.x.com/2"
TOKEN_ENV = "X_BEARER_TOKEN"
HASHTAG_RE = re.compile(r"#\w+")
URL_RE = re.compile(r"https?://\S+")
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9']+")
IDX_FAV = 1
IDX_REPLY = 4
IDX_RT = 6
IDX_DWELL = 11
IDX_VQV = 13

CLICKBAIT_PHRASES = (
    "breaking",
    "shocking",
    "you won't believe",
    "must watch",
    "viral",
    "big update",
    "latest update",
    "exclusive",
    "watch till end",
    "full details",
)
GENERIC_NEWS_WORDS = (
    "breaking",
    "latest",
    "update",
    "news",
    "today",
    "report",
    "announced",
    "official",
)
THREAD_MARKERS = ("thread", "1/", "part 1", "why", "how", "three ", "3 ", "explained")
POLL_MARKERS = ("poll", "vote", "choose", "which one", "what would you")
SIGNAL_LABELS = {
    "talk_signal": "Talk",
    "repost_velocity": "Repost velocity",
    "dwell_potential": "Dwell",
    "reply_depth": "Reply depth",
    "engagement": "Engagement",
    "slop_score": "Slop",
    "repetition_penalty": "Repetition",
}


SAMPLE_POSTS = [
    {
        "id": "2055371034010726771",
        "author_id": "19426551",
        "text": "NBA playoff thread: three possessions that changed the fourth quarter and why the matchup flipped after the timeout.",
        "created_at": "2026-05-16T09:15:00Z",
        "public_metrics": {
            "like_count": 1840,
            "reply_count": 96,
            "retweet_count": 221,
            "quote_count": 44,
        },
    },
    {
        "id": "2055363262837821760",
        "author_id": "19426551",
        "text": "Quick chart on sports clips: short highlights are carrying the feed today, but reply depth is still concentrated around analysis posts.",
        "created_at": "2026-05-16T08:20:00Z",
        "public_metrics": {
            "like_count": 920,
            "reply_count": 51,
            "retweet_count": 144,
            "quote_count": 18,
        },
    },
    {
        "id": "2055335444297011304",
        "author_id": "19426551",
        "text": "Final score. Big win.",
        "created_at": "2026-05-15T23:45:00Z",
        "public_metrics": {
            "like_count": 410,
            "reply_count": 12,
            "retweet_count": 28,
            "quote_count": 3,
        },
    },
    {
        "id": "2055324672833491097",
        "author_id": "19426551",
        "text": "What would you change about the Premier League table if goal difference was replaced by expected points?",
        "created_at": "2026-05-15T20:10:00Z",
        "public_metrics": {
            "like_count": 620,
            "reply_count": 148,
            "retweet_count": 73,
            "quote_count": 21,
        },
    },
    {
        "id": "2055311111111111111",
        "author_id": "19426551",
        "text": "BREAKING: Big update in the match today. Full details soon. #Sports #Breaking",
        "created_at": "2026-05-15T19:05:00Z",
        "public_metrics": {
            "like_count": 700,
            "reply_count": 9,
            "retweet_count": 31,
            "quote_count": 4,
        },
    },
]


def token_available() -> bool:
    return bool(os.environ.get(TOKEN_ENV))


def auth_headers() -> dict[str, str]:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise RuntimeError(f"Set {TOKEN_ENV} to fetch live X posts.")
    return {"Authorization": f"Bearer {token}"}


def x_get(path: str, params: dict[str, Any]) -> dict:
    url = f"{X_API}{path}?{urlencode(params)}"
    req = Request(url, headers=auth_headers())
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def fetch_user_posts(handle: str, max_results: int = 10) -> dict:
    username = handle.strip().lstrip("@")
    if not username:
        raise ValueError("Handle is required.")

    user = x_get(
        f"/users/by/username/{username}",
        {"user.fields": "public_metrics,verified,description"},
    ).get("data")
    if not user:
        raise RuntimeError(f"No X user found for @{username}.")

    posts = x_get(
        f"/users/{user['id']}/tweets",
        {
            "max_results": max(5, min(max_results, 100)),
            "tweet.fields": "created_at,public_metrics,entities,attachments",
            "exclude": "retweets,replies",
        },
    ).get("data", [])
    for post in posts:
        post["author_id"] = user["id"]
    return {"handle": username, "user": user, "posts": posts, "source": "live"}


def parse_post_input(value: Any) -> list[dict]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("data"), list):
            return value["data"]
        if isinstance(value.get("posts"), list):
            return value["posts"]
    if isinstance(value, str):
        parsed = json.loads(value)
        return parse_post_input(parsed)
    raise ValueError("Posts must be a JSON list, or an object with `data` or `posts`.")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def stable_u64(value: Any) -> int:
    if value is None or value == "":
        value = "0"
    try:
        return int(value)
    except (TypeError, ValueError):
        digest = hashlib.sha256(str(value).encode()).digest()
        return int.from_bytes(digest[:8], "big", signed=False)


def bounded(value: float, upper: float) -> float:
    if upper <= 0:
        return 0.0
    return max(0.0, min(value / upper, 1.0))


def calibrated_score(raw_score: float) -> float:
    """Map the auditable 0-1 raw score to a creator-friendly 0-100 display range."""
    raw_score = max(0.0, min(raw_score, 1.0))
    stretched = 30 + 65 / (1 + math.exp(-8 * (raw_score - 0.45)))
    return round(max(30.0, min(stretched, 95.0)), 1)


def words(text: str) -> list[str]:
    return [word.lower() for word in WORD_RE.findall(text)]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def text_similarity_penalties(posts: list[dict]) -> dict[str, float]:
    token_sets = {str(post.get("id") or index): set(words(str(post.get("text") or ""))) for index, post in enumerate(posts)}
    penalties: dict[str, float] = {}
    ids = list(token_sets)
    for post_id in ids:
        max_similarity = 0.0
        for other_id in ids:
            if other_id == post_id:
                continue
            max_similarity = max(max_similarity, jaccard(token_sets[post_id], token_sets[other_id]))
        penalties[post_id] = max(0.0, min((max_similarity - 0.38) / 0.42, 1.0))
    return penalties


def slop_score(text: str) -> float:
    lower = text.lower()
    post_words = words(text)
    if not post_words:
        return 0.7
    unique_ratio = len(set(post_words)) / max(len(post_words), 1)
    generic_hits = sum(1 for word in post_words if word in GENERIC_NEWS_WORDS)
    phrase_hits = sum(1 for phrase in CLICKBAIT_PHRASES if phrase in lower)
    headline_only = len(post_words) < 9 and not any(marker in lower for marker in THREAD_MARKERS)
    hashtag_load = len(HASHTAG_RE.findall(text))
    all_caps_words = sum(1 for word in text.split() if len(word) > 3 and word.isupper())

    raw = (
        phrase_hits * 0.18
        + generic_hits * 0.035
        + max(0.0, 0.62 - unique_ratio) * 0.65
        + (0.18 if headline_only else 0.0)
        + min(hashtag_load, 5) * 0.035
        + min(all_caps_words, 4) * 0.04
    )
    return round(max(0.0, min(raw, 1.0)), 4)


def dwell_potential(post: dict, text: str) -> float:
    lower = text.lower()
    length_bonus = 1.0 - min(abs(len(text) - 190) / 240, 0.75)
    has_media = bool(post.get("attachments"))
    media_bonus = 0.18 if has_media else 0.0
    thread_bonus = 0.18 if any(marker in lower for marker in THREAD_MARKERS) else 0.0
    question_bonus = 0.12 if "?" in text or any(marker in lower for marker in POLL_MARKERS) else 0.0
    explainer_bonus = 0.08 if ":" in text or "because" in lower or "why" in lower else 0.0
    return round(max(0.0, min(length_bonus * 0.62 + media_bonus + thread_bonus + question_bonus + explainer_bonus, 1.0)), 4)


def reply_quality_depth_proxy(replies: int, quotes: int, likes: int, text: str) -> float:
    talk_ratio = replies / max(likes, 1)
    quote_ratio = quotes / max(replies + quotes, 1)
    question_bonus = 0.16 if "?" in text else 0.0
    raw = bounded(talk_ratio, 0.18) * 0.5 + quote_ratio * 0.25 + bounded(replies, 160) * 0.25 + question_bonus
    return round(max(0.0, min(raw, 1.0)), 4)


def improvement_tips(row: dict) -> list[str]:
    tips = []
    signals = row["signals"]
    if signals["talk_ratio"] < 0.035:
        tips.append("Ask a real viewer question; this post is getting likes but little conversation.")
    if signals["slop_score"] > 0.35:
        tips.append("Replace generic headline language with one specific angle, number, or consequence.")
    if signals["dwell_potential"] < 0.45:
        tips.append("Add a short explanation, chart, clip, or thread structure so people have a reason to stay.")
    if signals["repetition_penalty"] > 0.25:
        tips.append("Vary the framing; this looks too similar to nearby posts in the batch.")
    if not tips:
        tips.append("Keep this shape: it has a clear angle and enough conversation signal to test again.")
    return tips[:3]


def clean_for_variation(text: str) -> str:
    cleaned = HASHTAG_RE.sub("", text)
    cleaned = re.sub(
        r"\b(BREAKING|Latest|Big update|Full details soon|VIRAL)\b[: !-]*",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"#\S*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([.,:;!?])", r"\1", cleaned)
    cleaned = re.sub(r"([.,:;!?]){2,}", r"\1", cleaned)
    cleaned = cleaned.strip(" .:-")
    if cleaned.lower().startswith("in "):
        cleaned = f"Match update: {cleaned[3:]}"
    return cleaned or text.strip()


def signal_reasons(signals: dict) -> list[str]:
    candidates = [
        ("Talk", signals["talk_signal"], f"Talk {signals['talk_ratio'] * 100:.1f}%"),
        ("Repost velocity", signals["repost_velocity"], f"Repost velocity {signals['repost_velocity']:.2f}"),
        ("Dwell", signals["dwell_potential"], f"Dwell {signals['dwell_potential']:.2f}"),
        ("Reply depth", signals["reply_depth"], f"Reply depth {signals['reply_depth']:.2f}"),
        ("Engagement", signals["engagement"], f"Engagement {signals['engagement']:.2f}"),
    ]
    positives = [label for _, value, label in sorted(candidates, key=lambda item: item[1], reverse=True) if value >= 0.45]
    penalties = []
    if signals["slop_score"] >= 0.32:
        penalties.append(f"Slop risk {signals['slop_score']:.2f}")
    if signals["repetition_penalty"] >= 0.25:
        penalties.append(f"Repetition {signals['repetition_penalty']:.2f}")
    if not positives:
        positives = [f"Baseline engagement {signals['engagement']:.2f}"]
    return (positives[:3] + penalties[:1])[:4]


def variation_improvements(base: dict, variant: dict) -> list[str]:
    improvements = []
    for key, label in [
        ("talk_signal", "Talk"),
        ("dwell_potential", "Dwell"),
        ("reply_depth", "Reply depth"),
        ("repost_velocity", "Repost velocity"),
    ]:
        diff = variant["signals"][key] - base["signals"][key]
        if diff >= 0.05:
            improvements.append(f"{label} +{diff:.2f}")
    slop_diff = base["signals"]["slop_score"] - variant["signals"]["slop_score"]
    if slop_diff >= 0.05:
        improvements.append(f"Slop -{slop_diff:.2f}")
    score_diff = variant["score"] - base["score"]
    if score_diff >= 2:
        improvements.append(f"Score +{score_diff:.1f}")
    return improvements[:4] or ["No major signal lift"]


def variation_explanation(base: dict, variant: dict) -> str:
    improvements = variation_improvements(base, variant)
    if improvements == ["No major signal lift"]:
        return "This variation does not materially improve the tested signals."
    return "Improves " + ", ".join(improvements[:3]) + "."


def score_post(
    post: dict,
    now: datetime | None = None,
    repetition_penalty: float = 0.0,
) -> dict:
    now = now or datetime.now(timezone.utc)
    metrics = post.get("public_metrics") or {}
    likes = int(metrics.get("like_count") or 0)
    replies = int(metrics.get("reply_count") or 0)
    reposts = int(metrics.get("retweet_count") or 0)
    quotes = int(metrics.get("quote_count") or 0)

    text = str(post.get("text") or "")
    created_at = parse_time(post.get("created_at"))
    age_hours = None
    if created_at:
        age_hours = max((now - created_at).total_seconds() / 3600, 0.0)

    engagement_raw = likes + replies * 3 + reposts * 4 + quotes * 5
    engagement = bounded(math.log1p(engagement_raw), math.log1p(5000))
    talk_ratio = replies / max(likes, 1)
    talk_signal = bounded(talk_ratio, 0.16)
    repost_velocity_raw = reposts / max(math.sqrt((age_hours or 24) + 1), 1.0)
    repost_velocity = bounded(repost_velocity_raw, 90)
    recency = 0.5 if age_hours is None else math.exp(-age_hours / 36)
    reply_depth = reply_quality_depth_proxy(replies, quotes, likes, text)
    dwell = dwell_potential(post, text)
    slop = slop_score(text)
    has_media = bool(post.get("attachments"))
    has_link = bool(URL_RE.search(text))
    media = 1.0 if has_media else 0.45 if has_link else 0.25

    raw_score = (
        engagement * 0.18
        + talk_signal * 0.22
        + repost_velocity * 0.13
        + dwell * 0.18
        + reply_depth * 0.13
        + recency * 0.08
        + media * 0.03
        - slop * 0.17
        - repetition_penalty * 0.12
    )
    raw_score = max(0.0, min(raw_score, 1.0))

    row = {
        "id": str(post.get("id") or ""),
        "author_id": str(post.get("author_id") or ""),
        "text": text,
        "url": f"https://x.com/i/web/status/{post.get('id')}" if post.get("id") else "",
        "created_at": post.get("created_at"),
        "metrics": {
            "likes": likes,
            "replies": replies,
            "reposts": reposts,
            "quotes": quotes,
            "engagement_raw": engagement_raw,
        },
        "signals": {
            "engagement": round(engagement, 4),
            "talk_ratio": round(talk_ratio, 4),
            "talk_signal": round(talk_signal, 4),
            "repost_velocity": round(repost_velocity, 4),
            "reply_depth": round(reply_depth, 4),
            "dwell_potential": dwell,
            "slop_score": slop,
            "repetition_penalty": round(repetition_penalty, 4),
            "recency": round(recency, 4),
            "media": round(media, 4),
        },
        "raw_score": round(raw_score, 4),
        "score": calibrated_score(raw_score),
        "phoenix_score": None,
        "phoenix_raw_score": None,
        "phoenix_delta": None,
        "phoenix_delta_pct": None,
        "phoenix_delta_label": "-",
        "reasons": [],
    }
    row["reasons"] = signal_reasons(row["signals"])
    row["tips"] = improvement_tips(row)
    return row


def make_variations(post: dict) -> list[dict]:
    text = str(post.get("text") or "").strip()
    cleaned = clean_for_variation(text)
    base = {**post, "id": f"{post.get('id', 'draft')}-base", "variant_label": "Original"}
    question = {
        **post,
        "id": f"{post.get('id', 'draft')}-question",
        "variant_label": "Question",
        "text": f"{text} What changed the outcome for you?",
    }
    poll = {
        **post,
        "id": f"{post.get('id', 'draft')}-poll",
        "variant_label": "Poll",
        "text": f"Poll: {cleaned} What should viewers watch next: impact, cause, or reaction?",
    }
    thread = {
        **post,
        "id": f"{post.get('id', 'draft')}-thread",
        "variant_label": "Thread Starter",
        "text": f"Thread: {text} Three things to watch next: the matchup, the decision point, and the fan reaction.",
    }
    specific = {
        **post,
        "id": f"{post.get('id', 'draft')}-specific",
        "variant_label": "Sharper",
        "text": f"{cleaned}. The part that matters: what changes for viewers in the next hour?",
    }
    contrarian = {
        **post,
        "id": f"{post.get('id', 'draft')}-contrarian",
        "variant_label": "Contrarian",
        "text": f"Unpopular read: {cleaned}. The obvious headline may not be the real story.",
    }
    personal = {
        **post,
        "id": f"{post.get('id', 'draft')}-personal",
        "variant_label": "Personal",
        "text": f"I'd watch this one closely: {cleaned}. What would you ask before sharing it?",
    }
    media = {
        **post,
        "id": f"{post.get('id', 'draft')}-media",
        "variant_label": "Media Prompt",
        "text": f"Visual explainer: {cleaned}. Add a 20-second clip or chart showing the key before/after.",
        "attachments": post.get("attachments") or {"media_keys": ["synthetic-chart"]},
    }
    return [base, question, poll, thread, specific, contrarian, personal, media]


def phoenix_simulate_posts(
    posts: list[dict],
    handle: str,
    artifacts_dir: str | Path | None = None,
) -> dict[str, dict]:
    """Run synthetic post IDs through the released Phoenix ranker.

    This uses the actual Phoenix ranking model and embedding tables. It does not
    claim text understanding; it only asks how Phoenix scores these hashed user,
    author, and post IDs under a synthetic history.
    """

    artifacts = Path(artifacts_dir or Path(__file__).resolve().parent / "artifacts" / "oss-phoenix-artifacts")
    if not (artifacts / "ranker" / "config.json").exists():
        return {}

    import haiku as hk
    import jax
    import jax.numpy as jnp
    import numpy as np

    from recsys_model import PhoenixModelConfig, RecsysBatch, RecsysEmbeddings
    from run_pipeline import build_hash_functions, build_model_config, build_unified_emb_table
    from runners import load_embedding_table, load_model_params

    with (artifacts / "ranker" / "config.json").open() as f:
        cfg = json.load(f)

    params = load_model_params(str(artifacts / "ranker" / "model_params.npz"))
    emb_table = build_unified_emb_table(load_embedding_table(str(artifacts / "ranker" / "embedding_tables.npz")), cfg)
    hash_user, hash_item, hash_author = build_hash_functions(cfg)
    model_config = build_model_config(cfg, PhoenixModelConfig)
    emb_size = cfg["emb_size"]
    hist_len = cfg["history_seq_len"]
    cand_len = cfg["candidate_seq_len"]
    num_actions = cfg["num_actions"]

    def rank_forward(batch, embeddings):
        return model_config.make()(batch, embeddings)

    rank_fn = hk.without_apply_rng(hk.transform(rank_forward))

    user_id = stable_u64(handle)
    candidate_posts = posts[:cand_len]
    history_posts = posts[: min(8, len(posts))]
    history_post_ids = np.zeros(hist_len, dtype=np.uint64)
    history_author_ids = np.zeros(hist_len, dtype=np.uint64)
    history_actions = np.zeros((hist_len, num_actions), dtype=np.float32)
    for index, post in enumerate(history_posts):
        history_post_ids[index] = stable_u64(post.get("id"))
        history_author_ids[index] = stable_u64(post.get("author_id") or handle)
        metrics = post.get("public_metrics") or {}
        history_actions[index, IDX_FAV] = 1.0 if int(metrics.get("like_count") or 0) > 0 else 0.0
        history_actions[index, IDX_REPLY] = min(int(metrics.get("reply_count") or 0) / 50, 1.0)
        history_actions[index, IDX_RT] = min(int(metrics.get("retweet_count") or 0) / 100, 1.0)
        history_actions[index, IDX_DWELL] = 1.0 if len(str(post.get("text") or "")) > 80 else 0.35

    user_h = hash_user(np.array([user_id], dtype=np.uint64))
    hist_post_h = hash_item(history_post_ids).reshape(1, hist_len, -1)
    hist_author_h = hash_author(history_author_ids).reshape(1, hist_len, -1)

    candidate_post_ids = np.zeros(cand_len, dtype=np.uint64)
    candidate_author_ids = np.zeros(cand_len, dtype=np.uint64)
    for index, post in enumerate(candidate_posts):
        candidate_post_ids[index] = stable_u64(post.get("id"))
        candidate_author_ids[index] = stable_u64(post.get("author_id") or handle)

    cph = hash_item(candidate_post_ids).reshape(1, cand_len, -1)
    cah = hash_author(candidate_author_ids).reshape(1, cand_len, -1)
    batch = RecsysBatch(
        user_hashes=jnp.asarray(user_h),
        history_post_hashes=jnp.asarray(hist_post_h),
        history_author_hashes=jnp.asarray(hist_author_h),
        history_actions=jnp.asarray(history_actions.reshape(1, hist_len, num_actions)),
        history_product_surface=jnp.zeros((1, hist_len), dtype=jnp.int32),
        candidate_post_hashes=jnp.asarray(cph),
        candidate_author_hashes=jnp.asarray(cah),
        candidate_product_surface=jnp.zeros((1, cand_len), dtype=jnp.int32),
    )
    embeddings = RecsysEmbeddings(
        user_embeddings=jnp.asarray(emb_table[user_h]),
        history_post_embeddings=jnp.asarray(emb_table[hist_post_h]),
        candidate_post_embeddings=jnp.asarray(emb_table[cph]),
        history_author_embeddings=jnp.asarray(emb_table[hist_author_h]),
        candidate_author_embeddings=jnp.asarray(emb_table[cah]),
    )

    output = rank_fn.apply(params, batch, embeddings)
    probs = np.asarray(jax.nn.sigmoid(output.logits))[0, : len(candidate_posts), :]
    result = {}
    for index, post in enumerate(candidate_posts):
        weighted = (
            probs[index, IDX_FAV] * 1.0
            + probs[index, IDX_REPLY] * 0.5
            + probs[index, IDX_RT] * 0.3
            + probs[index, IDX_DWELL] * 0.2
        )
        result[str(post.get("id") or "")] = {
            "phoenix_raw_score": round(float(weighted), 4),
            "phoenix_score": calibrated_score(float(weighted)),
            "phoenix_predicted_engagement": {
                "favorite": round(float(probs[index, IDX_FAV]), 4),
                "reply": round(float(probs[index, IDX_REPLY]), 4),
                "repost": round(float(probs[index, IDX_RT]), 4),
                "dwell": round(float(probs[index, IDX_DWELL]), 4),
                "video_quality_view": round(float(probs[index, IDX_VQV]), 4),
            },
        }
    return result


def attach_phoenix_scores(rows: list[dict], posts: list[dict], handle: str, enable: bool) -> str:
    if not enable:
        return "off"
    try:
        scores = phoenix_simulate_posts(posts, handle)
    except Exception as exc:
        for row in rows:
            row["phoenix_error"] = str(exc)
        return "error"
    if not scores:
        return "unavailable"
    for row in rows:
        phoenix = scores.get(row["id"])
        if not phoenix:
            continue
        row.update(phoenix)
        row["phoenix_delta"] = round(row["score"] - row["phoenix_score"], 1)
        row["phoenix_delta_pct"] = round(row["phoenix_delta"] / max(row["phoenix_score"], 1) * 100, 1)
        sign = "+" if row["phoenix_delta_pct"] >= 0 else ""
        row["phoenix_delta_label"] = f"{sign}{row['phoenix_delta_pct']:.1f}%"
    return "simulated"


def batch_patterns(rows: list[dict]) -> list[str]:
    patterns = []
    avg_slop = sum(row["signals"]["slop_score"] for row in rows) / len(rows)
    avg_repetition = sum(row["signals"]["repetition_penalty"] for row in rows) / len(rows)
    low_talk = sum(1 for row in rows if row["signals"]["talk_ratio"] < 0.025)
    if avg_slop > 0.28:
        patterns.append("The batch leans toward generic headline packaging.")
    if avg_repetition > 0.2:
        patterns.append("Several posts repeat the same framing; vary the angle or format.")
    if low_talk >= max(2, len(rows) // 2):
        patterns.append("Many posts earn likes without much conversation; add prompts that invite replies.")
    if not patterns:
        patterns.append("The batch has enough variety to run real A/B experiments.")
    return patterns[:3]


def broadcast_benchmark(rows: list[dict]) -> str:
    avg_talk = sum(row["signals"]["talk_ratio"] for row in rows) / len(rows)
    avg_slop = sum(row["signals"]["slop_score"] for row in rows) / len(rows)
    avg_dwell = sum(row["signals"]["dwell_potential"] for row in rows) / len(rows)
    if avg_talk >= 0.08:
        return "Compared with a typical news/broadcast account, this batch is unusually conversation-led rather than just headline-led."
    if avg_slop >= 0.35:
        return "Compared with a typical news/broadcast account, this batch risks blending into headline-only feed noise."
    if avg_dwell >= 0.65:
        return "Compared with a typical news/broadcast account, this batch has stronger dwell potential than plain headline posting."
    return "Compared with a typical news/broadcast account, this batch is solid but needs more reply hooks to become interactive."


def judge_posts(
    posts: list[dict],
    handle: str = "sample",
    now: datetime | None = None,
    phoenix: bool = False,
    include_experiments: bool = True,
) -> dict:
    if not posts:
        raise ValueError("No posts to judge.")
    penalties = text_similarity_penalties(posts)
    scored = [
        score_post(post, now=now, repetition_penalty=penalties.get(str(post.get("id") or index), 0.0))
        for index, post in enumerate(posts)
    ]
    phoenix_status = attach_phoenix_scores(scored, posts, handle, phoenix)
    rows = sorted(scored, key=lambda row: row["score"], reverse=True)
    top = rows[0]
    avg_score = round(sum(row["score"] for row in rows) / len(rows), 1)
    patterns = batch_patterns(rows)
    tips = []
    for row in rows:
        for tip in row["tips"]:
            if tip not in tips:
                tips.append(tip)
            if len(tips) == 3:
                break
        if len(tips) == 3:
            break
    summary = (
        f"@{handle.lstrip('@')} has {len(rows)} judged posts. "
        f"The strongest post scores {top['score']} because it shows {', '.join(top['reasons'][:3])}. "
        f"{broadcast_benchmark(rows)}"
    )
    technical = (
        "Handle Judge 2.1 blends talk ratio, early repost velocity, dwell potential, reply-depth proxy, "
        "slop detection, and repetition penalties. Phoenix Simulation optionally runs the actual released "
        "Phoenix ranker on synthetic hashed candidates, so treat Phoenix Delta as a signed simulation impact, not text understanding."
    )
    experiments = []
    if include_experiments:
        base_post = max(posts, key=lambda post: slop_score(str(post.get("text") or "")))
        experiment_rows = [score_post(post, now=now) for post in make_variations(base_post)]
        base_row = experiment_rows[0]
        for row in experiment_rows:
            row["variant_label"] = next((post.get("variant_label") for post in make_variations(base_post) if post.get("id") == row["id"]), "Variation")
            row["improved_signals"] = variation_improvements(base_row, row)
            row["why_won"] = variation_explanation(base_row, row)
        experiments = sorted(
            experiment_rows,
            key=lambda row: row["score"],
            reverse=True,
        )
        if experiments:
            experiments[0]["best_variation"] = True
    return {
        "version": "2.1",
        "handle": handle.lstrip("@"),
        "count": len(rows),
        "average_score": avg_score,
        "summary": summary,
        "technical_note": technical,
        "patterns": patterns,
        "tips": tips,
        "phoenix_status": phoenix_status,
        "rows": rows,
        "experiments": experiments,
    }
