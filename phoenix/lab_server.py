#!/usr/bin/env python3
"""Local browser lab for the Phoenix recommendation pipeline."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from handle_judge import SAMPLE_POSTS, TOKEN_ENV, fetch_user_posts, judge_posts, parse_post_input


ROOT = Path(__file__).resolve().parent
LAB_DIR = ROOT / "lab"
RUN_DIR = ROOT / "lab_runs"
ARTIFACTS_DIR = ROOT / "artifacts" / "oss-phoenix-artifacts"
EXAMPLE_SEQUENCE = ARTIFACTS_DIR / "example_sequence.json"

ROW_RE = re.compile(
    r"^\s*(?P<rank>\d+)\s+"
    r"(?P<score>[0-9.]+)\s+"
    r"(?P<retrieval>[0-9.]+)\s+"
    r"(?P<favorite>[0-9.]+)\s+"
    r"(?P<reply>[0-9.]+)\s+"
    r"(?P<repost>[0-9.]+)\s+"
    r"(?P<dwell>[0-9.]+)\s+"
    r"(?P<video>[0-9.]+)\s+"
    r"(?P<topics>.+?)\s+"
    r"(?P<url>https://x\.com/\S+)\s*$"
)


def read_json(path: Path) -> object:
    with path.open() as f:
        return json.load(f)


def parse_pipeline_output(text: str) -> dict:
    rows = []
    meta: dict[str, object] = {}
    for line in text.splitlines():
        if "posts, repr shape" in line:
            match = re.search(r"\s(\d+) posts, repr shape \((\d+),\s*(\d+)\)", line)
            if match:
                meta["corpus_posts"] = int(match.group(1))
                meta["embedding_dim"] = int(match.group(3))
        elif "Retrieved" in line and "score range" in line:
            match = re.search(r"Retrieved (\d+) \(score range: ([0-9.]+) - ([0-9.]+)\)", line)
            if match:
                meta["retrieved"] = int(match.group(1))
                meta["retrieval_score_min"] = float(match.group(2))
                meta["retrieval_score_max"] = float(match.group(3))
        elif line.startswith("Weighted score range:"):
            match = re.search(r"\[([0-9.]+),\s*([0-9.]+)\]", line)
            if match:
                meta["weighted_score_min"] = float(match.group(1))
                meta["weighted_score_max"] = float(match.group(2))

        row_match = ROW_RE.match(line)
        if row_match:
            row = row_match.groupdict()
            rows.append(
                {
                    "rank": int(row["rank"]),
                    "score": float(row["score"]),
                    "retrieval": float(row["retrieval"]),
                    "favorite": float(row["favorite"]),
                    "reply": float(row["reply"]),
                    "repost": float(row["repost"]),
                    "dwell": float(row["dwell"]),
                    "video": float(row["video"]),
                    "topics": row["topics"].strip(),
                    "url": row["url"],
                }
            )
    return {"meta": meta, "rows": rows}


def validate_sequence(sequence: object) -> tuple[bool, str]:
    if not isinstance(sequence, dict):
        return False, "Sequence must be a JSON object."
    if not isinstance(sequence.get("user_id"), int):
        return False, "`user_id` must be an integer."
    history = sequence.get("history")
    if not isinstance(history, list) or not history:
        return False, "`history` must be a non-empty list."
    for index, item in enumerate(history):
        if not isinstance(item, dict):
            return False, f"History item {index + 1} must be an object."
        if not isinstance(item.get("post_id"), int):
            return False, f"History item {index + 1} needs integer `post_id`."
        if not isinstance(item.get("author_id"), int):
            return False, f"History item {index + 1} needs integer `author_id`."
        actions = item.get("actions")
        if not isinstance(actions, dict) or not actions:
            return False, f"History item {index + 1} needs non-empty `actions`."
    return True, ""


def run_pipeline(payload: dict) -> dict:
    if not ARTIFACTS_DIR.exists():
        raise RuntimeError(f"Missing artifacts directory: {ARTIFACTS_DIR}")

    sequence = payload.get("sequence")
    ok, message = validate_sequence(sequence)
    if not ok:
        raise ValueError(message)

    top_k_retrieval = int(payload.get("top_k_retrieval", 200))
    top_k_display = int(payload.get("top_k_display", 30))
    if top_k_retrieval < 1 or top_k_retrieval > 1000:
        raise ValueError("Retrieval depth must be between 1 and 1000.")
    if top_k_display < 1 or top_k_display > 100:
        raise ValueError("Display count must be between 1 and 100.")

    RUN_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    sequence_path = RUN_DIR / f"sequence-{stamp}.json"
    log_path = RUN_DIR / f"pipeline-{stamp}.log"
    sequence_path.write_text(json.dumps(sequence, indent=2) + "\n")

    cmd = [
        sys.executable,
        "run_pipeline.py",
        "--artifacts_dir",
        str(ARTIFACTS_DIR),
        "--sequence_file",
        str(sequence_path),
        "--top_k_retrieval",
        str(top_k_retrieval),
        "--top_k_display",
        str(top_k_display),
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    raw = completed.stderr + completed.stdout
    log_path.write_text(raw)

    if completed.returncode != 0:
        raise RuntimeError(raw[-4000:] or f"Pipeline exited with {completed.returncode}")

    parsed = parse_pipeline_output(raw)
    parsed["elapsed_ms"] = elapsed_ms
    parsed["raw"] = raw
    parsed["sequence_path"] = str(sequence_path)
    parsed["log_path"] = str(log_path)
    return parsed


class LabHandler(BaseHTTPRequestHandler):
    server_version = "PhoenixLab/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_file(LAB_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/app.css":
            self.send_file(LAB_DIR / "app.css", "text/css; charset=utf-8")
        elif path == "/app.js":
            self.send_file(LAB_DIR / "app.js", "application/javascript; charset=utf-8")
        elif path == "/api/example":
            self.send_json({"sequence": read_json(EXAMPLE_SEQUENCE)})
        elif path == "/api/handle-sample":
            self.send_json({"handle": "sample", "posts": SAMPLE_POSTS})
        elif path == "/api/status":
            self.send_json(
                {
                    "artifacts_ready": ARTIFACTS_DIR.exists(),
                    "example_ready": EXAMPLE_SEQUENCE.exists(),
                    "artifacts_dir": str(ARTIFACTS_DIR),
                    "x_token_ready": bool(os.environ.get(TOKEN_ENV)),
                }
            )
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/run":
            try:
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self.send_json(run_pipeline(payload))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if path == "/api/judge":
            try:
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                handle = str(payload.get("handle") or "sample").strip().lstrip("@") or "sample"
                if payload.get("posts"):
                    posts = parse_post_input(payload["posts"])
                    source = "pasted"
                else:
                    fetched = fetch_user_posts(handle, int(payload.get("max_results", 10)))
                    posts = fetched["posts"]
                    source = fetched["source"]
                result = judge_posts(posts, handle=handle, phoenix=bool(payload.get("phoenix")))
                result["source"] = source
                self.send_json(result)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        else:
            self.send_error(404)

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), LabHandler)
    print(f"Phoenix Lab running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
