# Phoenix Lab

Phoenix Lab is a local browser UI for the open Phoenix recommendation demo. It wraps
`phoenix/run_pipeline.py` so you can edit a user engagement sequence, run retrieval
and ranking, inspect the ranked feed, and compare that model path with a transparent
current-post judge.

This lab is local-only code added on top of the upstream release. It does not change
the model, checkpoints, corpus, or original example sequence.

## Files

- `../lab_server.py` serves the UI and exposes the local API.
- `../handle_judge.py` scores pasted or live recent posts with explainable signals.
- `index.html`, `app.css`, and `app.js` make up the browser UI.
- `../lab_runs/` is created at runtime for generated sequence files and pipeline logs.

## Prerequisites

From the `phoenix/` directory:

```shell
uv sync
```

The model artifacts must also be available at:

```text
phoenix/artifacts/oss-phoenix-artifacts/
```

If you only have the Git LFS pointer or zip, fetch and extract the artifact first:

```shell
git lfs pull
cd phoenix
unzip artifacts/oss-phoenix-artifacts.zip -d artifacts/
```

## Start The Lab

```shell
cd "/Users/ln-mini/Downloads/x algorithm/x-algorithm/phoenix"
uv run python lab_server.py 8765
```

Then open:

```text
http://127.0.0.1:8765/
```

The UI loads the shipped `example_sequence.json` by default. Use `Reset` to restore
that example after editing.

## Phoenix Pipeline

1. Edit the JSON in the User Sequence editor.
2. Set `Retrieval` to control how many posts are retrieved before ranking.
3. Set `Display` to control how many ranked rows appear in the table.
4. Click `Run Pipeline`.

Each history item must include:

```json
{
  "post_id": 2055082803453378718,
  "author_id": 19426551,
  "actions": {
    "1": 1,
    "11": 1,
    "13": 1
  },
  "label": "NFL"
}
```

Common action IDs used by the example:

| ID | Meaning |
| --- | --- |
| `1` | favorite |
| `4` | reply |
| `5` | quote |
| `6` | repost |
| `11` | dwell |
| `13` | video quality view |

## Handle Judge 2.1

The Handle Judge tab is deliberately separate from Phoenix:

- Phoenix ranks hashed post IDs against the released local sports corpus.
- Handle Judge scores current or pasted posts using observable creator/news signals so the result is easy to explain.
- Phoenix Simulation Mode optionally runs the released Phoenix ranker on synthetic hashed candidates and compares that output with the heuristic score.

Use it in two modes:

1. Click `Run Sample` to load and score built-in sample posts without any API token.
2. Click `Load Sample`, edit the JSON, then click `Judge Pasted` to test your own post set.
3. Set `X_BEARER_TOKEN`, restart the server, enter a handle, then click `Fetch Live`.

Live mode reads the bearer token from the server process environment. It uses X API v2 user lookup and user timeline endpoints. Start the server with:

```shell
cd "/Users/ln-mini/Downloads/x algorithm/x-algorithm/phoenix"
X_BEARER_TOKEN="..." uv run python lab_server.py 8765
```

If the token is present, the Handle Judge tab shows that live mode is ready. If it
is missing, sample and pasted-post judging still work.

Positioning:

```text
Runnable Phoenix simulator + creator judge.
Not another algorithm thread: edit posts, run tests, compare signals, and see what changed.
```

The scorecard shows both views:

- **Plain English**: a short read on what is working.
- **Technical**: calibrated score, talk ratio, repost velocity, dwell potential, reply-depth proxy, slop detection, repetition penalty, and optional Phoenix simulation.
- **Signal columns**: `Talk Ratio`, `Slop`, `Dwell`, and signed Phoenix simulation impact.

## Manual Test Checklist

Use this checklist after starting the server.

### 1. Basic UI Load

1. Open `http://127.0.0.1:8765/`.
2. Confirm the top-right status says `Artifacts ready`.
3. Confirm both tabs are visible: `Phoenix Pipeline` and `Handle Judge`.

### 2. Phoenix Pipeline

1. Stay on `Phoenix Pipeline`.
2. Click `Run Pipeline`.
3. Expected result:
   - `Ranked Feed` table fills with rows.
   - Metrics show `Corpus`, `Retrieved`, `Best Score`, and `Runtime`.
   - `Log` reveals the raw `run_pipeline.py` output.

### 3. Handle Judge Sample

1. Open `Handle Judge`.
2. Click `Run Sample`.
3. Expected result:
   - Message says `Scored 5 posts.`
   - `Plain English` summary explains the strongest post.
   - Tips appear under the summary.
   - Table includes `Talk Ratio`, `Slop`, `Dwell`, and `Phoenix Delta`.
   - `Phoenix Delta` is `-` because simulation is off.
   - `Experiment Ideas` appears below the table.

### 4. Phoenix Simulation Mode

1. In `Handle Judge`, check `Phoenix Simulation Mode`.
2. Click `Run Sample` again.
3. Expected result:
   - Metadata says `Phoenix simulation: simulated`.
   - `Phoenix Delta` values populate as signed percent-style impact, such as `+13.4%`.
   - This mode can take a few seconds because it loads the actual ranker artifact.

### 5. Pasted Post Experiment

1. Click `Load Sample`.
2. Edit one post in the JSON, for example add a question to the text.
3. Click `Judge Pasted`.
4. Expected result:
   - Scores and tips update.
   - Changes in `Talk Ratio`, `Slop`, and `Dwell` make the experiment auditable.

### 6. Live Handle Mode

Start the server with a token:

```shell
cd "/Users/ln-mini/Downloads/x algorithm/x-algorithm/phoenix"
X_BEARER_TOKEN="..." uv run python lab_server.py 8765
```

Then:

1. Open `Handle Judge`.
2. Enter a handle, for example `@xdevelopers`.
3. Click `Fetch Live`.
4. Expected result:
   - The token note says live mode is ready.
   - The table fills with recent posts fetched from X API v2.

Example sample output:

```text
@sample has 5 judged posts. The strongest post scores 85.5 because it shows Talk 23.9%, Reply depth 0.92, Engagement 0.86. Compared with a typical news/broadcast account, this batch is solid but needs more reply hooks to become interactive.

Tips:
- Keep this shape: it has a clear angle and enough conversation signal to test again.
- Ask a real viewer question; this post is getting likes but little conversation.
- Add a short explanation, chart, clip, or thread structure so people have a reason to stay.

Phoenix simulation example:
Heuristic 85.5 | Phoenix 75.4 | Simulation impact +13.4%

Best experiment example:
Media Prompt | Score 57.2 | Improves Dwell +0.45, Slop -0.72, Score +20.3
```

## Smoke Tests

Run the Phoenix model tests:

```shell
cd "/Users/ln-mini/Downloads/x algorithm/x-algorithm/phoenix"
uv run pytest test_recsys_model.py test_recsys_retrieval_model.py
```

Run the lab unit tests:

```shell
uv run pytest test_lab_server.py
```

Check the lab server health:

```shell
curl -s http://127.0.0.1:8765/api/status
```

Run the original command-line pipeline:

```shell
uv run run_pipeline.py --artifacts_dir artifacts/oss-phoenix-artifacts --top_k_retrieval 200 --top_k_display 30
```

Run the lab API directly:

```shell
uv run python -c 'import json, urllib.request; seq=json.load(open("artifacts/oss-phoenix-artifacts/example_sequence.json")); data=json.dumps({"sequence":seq,"top_k_retrieval":50,"top_k_display":5}).encode(); req=urllib.request.Request("http://127.0.0.1:8765/api/run", data=data, headers={"content-type":"application/json"}); print(urllib.request.urlopen(req, timeout=60).read().decode()[:1000])'
```

Run the handle judge API directly with sample posts:

```shell
uv run python -c 'import json, urllib.request; sample=json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/handle-sample")); data=json.dumps({"handle":sample["handle"],"posts":sample["posts"]}).encode(); req=urllib.request.Request("http://127.0.0.1:8765/api/judge", data=data, headers={"content-type":"application/json"}); print(urllib.request.urlopen(req, timeout=60).read().decode()[:1000])'
```

Run the handle judge API with Phoenix Simulation Mode:

```shell
uv run python -c 'import json, urllib.request; sample=json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/handle-sample")); data=json.dumps({"handle":sample["handle"],"posts":sample["posts"],"phoenix":True}).encode(); req=urllib.request.Request("http://127.0.0.1:8765/api/judge", data=data, headers={"content-type":"application/json"}); out=json.load(urllib.request.urlopen(req, timeout=120)); print(out["phoenix_status"]); print([(row["score"], row["phoenix_score"], row["phoenix_delta"]) for row in out["rows"]])'
```

## Generated Files

The lab writes generated inputs and logs to:

```text
phoenix/lab_runs/
```

Those files are ignored by Git. The extracted artifact directory and local Python
environment are also ignored:

```text
phoenix/artifacts/oss-phoenix-artifacts/
phoenix/.venv/
phoenix/.pytest_cache/
```

Keep the source files committed, but leave the generated artifacts and run logs local.
