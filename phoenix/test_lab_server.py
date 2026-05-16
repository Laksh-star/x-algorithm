import json
from datetime import datetime, timezone

import pytest

from handle_judge import SAMPLE_POSTS, judge_posts, parse_post_input, slop_score
from lab_server import parse_pipeline_output, validate_sequence


SAMPLE_PIPELINE_OUTPUT = """
2026-05-16 16:16:52,202   84564 posts, repr shape (84564, 128)
2026-05-16 16:16:53,909   Retrieved 50 (score range: 0.8965 - 0.9382)
Rank  Score    Ret     Fav     Reply   RT      Dwell   VQV     Topics                         Post URL
1     0.3922   0.8980  0.2930  0.0003  0.0114  0.4785  0.0781  Sports,NBA                     https://x.com/a/status/2055371034010726771
2     0.3511   0.9382  0.2402  0.0009  0.0061  0.5430  0.1128  Sports,NBA                     https://x.com/a/status/2055335444297011304
Weighted score range: [0.0022, 0.3922]
"""


def test_parse_pipeline_output_returns_metrics_and_rows():
    parsed = parse_pipeline_output(SAMPLE_PIPELINE_OUTPUT)

    assert parsed["meta"]["corpus_posts"] == 84564
    assert parsed["meta"]["embedding_dim"] == 128
    assert parsed["meta"]["retrieved"] == 50
    assert parsed["rows"][0]["score"] == 0.3922
    assert parsed["rows"][0]["topics"] == "Sports,NBA"
    assert parsed["rows"][0]["url"].endswith("2055371034010726771")


def test_validate_sequence_rejects_missing_history():
    ok, message = validate_sequence({"user_id": 123, "history": []})

    assert ok is False
    assert "history" in message


def test_validate_sequence_accepts_example_shape():
    ok, message = validate_sequence(
        {
            "user_id": 123,
            "history": [
                {
                    "post_id": 2055082803453378718,
                    "author_id": 19426551,
                    "actions": {"1": 1, "11": 1},
                }
            ],
        }
    )

    assert ok is True
    assert message == ""


def test_parse_post_input_accepts_x_api_shape():
    posts = parse_post_input(json.dumps({"data": SAMPLE_POSTS[:2]}))

    assert len(posts) == 2
    assert posts[0]["id"] == SAMPLE_POSTS[0]["id"]


def test_judge_posts_orders_scores_and_explains_result():
    judged = judge_posts(
        SAMPLE_POSTS,
        handle="sample",
        now=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    scores = [row["score"] for row in judged["rows"]]
    assert scores == sorted(scores, reverse=True)
    assert judged["count"] == len(SAMPLE_POSTS)
    assert judged["summary"].startswith("@sample")
    assert judged["version"] == "2.0"
    assert "Phoenix Simulation" in judged["technical_note"]
    assert judged["tips"]
    assert judged["patterns"]
    assert "talk_ratio" in judged["rows"][0]["signals"]
    assert "slop_score" in judged["rows"][0]["signals"]
    assert "dwell_potential" in judged["rows"][0]["signals"]


def test_judge_posts_rejects_empty_list():
    with pytest.raises(ValueError, match="No posts"):
        judge_posts([])


def test_slop_score_flags_generic_headline_style():
    generic = "BREAKING: Big update today. Full details soon. #News #Breaking"
    specific = "Three possessions changed the fourth quarter because the matchup forced a different switch."

    assert slop_score(generic) > slop_score(specific)


def test_judge_posts_can_run_without_phoenix_simulation():
    judged = judge_posts(SAMPLE_POSTS, handle="sample", phoenix=False)

    assert judged["phoenix_status"] == "off"
    assert all(row["phoenix_score"] is None for row in judged["rows"])
