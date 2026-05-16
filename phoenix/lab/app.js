const statusEl = document.querySelector("#status");
const sequenceInput = document.querySelector("#sequenceInput");
const retrievalDepth = document.querySelector("#retrievalDepth");
const displayCount = document.querySelector("#displayCount");
const runButton = document.querySelector("#runButton");
const loadExample = document.querySelector("#loadExample");
const message = document.querySelector("#message");
const resultsBody = document.querySelector("#resultsBody");
const runMeta = document.querySelector("#runMeta");
const metrics = document.querySelector("#metrics");
const rawLog = document.querySelector("#rawLog");
const toggleLog = document.querySelector("#toggleLog");
const tabs = document.querySelectorAll(".tab");
const views = document.querySelectorAll(".view");
const handleInput = document.querySelector("#handleInput");
const postsInput = document.querySelector("#postsInput");
const maxPosts = document.querySelector("#maxPosts");
const loadSamplePosts = document.querySelector("#loadSamplePosts");
const runSampleJudge = document.querySelector("#runSampleJudge");
const judgePastedButton = document.querySelector("#judgePastedButton");
const judgeLiveButton = document.querySelector("#judgeLiveButton");
const judgeMessage = document.querySelector("#judgeMessage");
const judgeBody = document.querySelector("#judgeBody");
const judgeMeta = document.querySelector("#judgeMeta");
const judgeSummary = document.querySelector("#judgeSummary");
const judgeTechnical = document.querySelector("#judgeTechnical");
const judgeMetrics = document.querySelector("#judgeMetrics");
const tokenNote = document.querySelector("#tokenNote");
const phoenixSimToggle = document.querySelector("#phoenixSimToggle");
const judgeTips = document.querySelector("#judgeTips");
const patternSummary = document.querySelector("#patternSummary");
const experimentList = document.querySelector("#experimentList");

function setMessage(text, isError = false) {
  message.textContent = text;
  message.classList.toggle("error", isError);
}

function setJudgeMessage(text, isError = false) {
  judgeMessage.textContent = text;
  judgeMessage.classList.toggle("error", isError);
}

function fmt(value, digits = 4) {
  return Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function setMetric(index, value) {
  metrics.children[index].querySelector("strong").textContent = value;
}

function setJudgeMetric(index, value) {
  judgeMetrics.children[index].querySelector("strong").textContent = value;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed with ${response.status}`);
  }
  return data;
}

async function loadStatus() {
  try {
    const data = await fetchJson("/api/status");
    statusEl.textContent = data.artifacts_ready ? "Artifacts ready" : "Artifacts missing";
    statusEl.className = `status ${data.artifacts_ready ? "ready" : "error"}`;
    tokenNote.textContent = data.x_token_ready
      ? "Live mode is ready. The server has X_BEARER_TOKEN in its environment."
      : "Live mode needs X_BEARER_TOKEN. Sample and pasted-post judging work without it.";
    tokenNote.classList.toggle("ready", data.x_token_ready);
    judgeLiveButton.title = data.x_token_ready
      ? "Fetch recent posts with X_BEARER_TOKEN"
      : "Set X_BEARER_TOKEN before starting the server to fetch live posts";
  } catch (error) {
    statusEl.textContent = "Status failed";
    statusEl.className = "status error";
  }
}

async function loadSamplePostJson() {
  const data = await fetchJson("/api/handle-sample");
  handleInput.value = data.handle;
  postsInput.value = JSON.stringify(data.posts, null, 2);
  setJudgeMessage("Loaded sample posts.");
}

async function loadExampleSequence() {
  const data = await fetchJson("/api/example");
  sequenceInput.value = JSON.stringify(data.sequence, null, 2);
  setMessage("Loaded example sequence.");
}

function renderRows(rows) {
  if (!rows.length) {
    resultsBody.innerHTML = `<tr><td colspan="10" class="empty">No ranked rows were parsed from the pipeline output.</td></tr>`;
    return;
  }
  resultsBody.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td>${row.rank}</td>
          <td>${fmt(row.score)}</td>
          <td>${fmt(row.retrieval)}</td>
          <td>${fmt(row.favorite)}</td>
          <td>${fmt(row.reply)}</td>
          <td>${fmt(row.repost)}</td>
          <td>${fmt(row.dwell)}</td>
          <td>${fmt(row.video)}</td>
          <td>${row.topics}</td>
          <td><a href="${row.url}" target="_blank" rel="noreferrer">Open</a></td>
        </tr>
      `,
    )
    .join("");
}

function renderJudgeRows(rows) {
  if (!rows.length) {
    judgeBody.innerHTML = `<tr><td colspan="10" class="empty">No posts were scored.</td></tr>`;
    return;
  }
  judgeBody.innerHTML = rows
    .map(
      (row, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${fmt(row.score, 1)}</td>
          <td>${row.metrics.likes.toLocaleString()}</td>
          <td>${row.metrics.replies.toLocaleString()}</td>
          <td>${row.metrics.reposts.toLocaleString()}</td>
          <td>${fmt(row.signals.talk_ratio, 3)}</td>
          <td>${fmt(row.signals.slop_score, 2)}</td>
          <td>${fmt(row.signals.dwell_potential, 2)}</td>
          <td>${row.phoenix_delta_label || "-"}</td>
          <td class="reason-cell">${row.reasons.join(", ")}</td>
          <td>${row.url ? `<a href="${row.url}" target="_blank" rel="noreferrer">Open</a>` : "-"}</td>
        </tr>
        <tr class="post-text-row">
          <td></td>
          <td colspan="9">${row.text}</td>
        </tr>
      `,
    )
    .join("");
}

function renderTips(tips = []) {
  judgeTips.innerHTML = tips.map((tip) => `<li>${tip}</li>`).join("");
}

function renderExperiments(experiments = []) {
  if (!experiments.length) {
    experimentList.innerHTML = `<div class="empty-mini">No experiments generated.</div>`;
    return;
  }
  experimentList.innerHTML = experiments
    .map(
      (item) => `
        <article class="${item.best_variation ? "best-variation" : ""}">
          <div class="experiment-head">
            <strong>${fmt(item.score, 1)}</strong>
            <span>${item.variant_label || "Variation"}${item.best_variation ? " | Best" : ""}</span>
          </div>
          <p>${item.text}</p>
          <span>Talk ${fmt(item.signals.talk_ratio, 3)} | Slop ${fmt(item.signals.slop_score, 2)} | Dwell ${fmt(item.signals.dwell_potential, 2)}</span>
          <span>${(item.improved_signals || []).join(" | ")}</span>
          <em>${item.why_won || ""}</em>
        </article>
      `,
    )
    .join("");
}

async function judgePosts(useLive = false) {
  let posts;
  if (!useLive) {
    try {
      posts = JSON.parse(postsInput.value);
    } catch (error) {
      setJudgeMessage("Post JSON is invalid.", true);
      return;
    }
  }

  const button = useLive ? judgeLiveButton : judgePastedButton;
  button.disabled = true;
  button.textContent = useLive ? "Fetching..." : "Judging...";
  setJudgeMessage(useLive ? "Fetching recent posts from X." : "Scoring pasted posts.");

  try {
    const payload = {
      handle: handleInput.value,
      max_results: Number(maxPosts.value),
      phoenix: phoenixSimToggle.checked,
    };
    if (!useLive) {
      payload.posts = posts;
    }
    const data = await fetchJson("/api/judge", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderJudgeRows(data.rows);
    judgeSummary.textContent = data.summary;
    judgeTechnical.textContent = data.technical_note;
    judgeMeta.textContent = `@${data.handle} judged from ${data.source} data. Phoenix simulation: ${data.phoenix_status}.`;
    renderTips(data.tips || []);
    patternSummary.textContent = (data.patterns || []).join(" ");
    renderExperiments(data.experiments || []);
    setJudgeMetric(0, data.count.toLocaleString());
    setJudgeMetric(1, fmt(data.average_score, 1));
    setJudgeMetric(2, data.rows.length ? fmt(data.rows[0].score, 1) : "-");
    setJudgeMetric(3, data.source);
    setJudgeMessage(`Scored ${data.count} posts.`);
  } catch (error) {
    setJudgeMessage(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = useLive ? "Fetch Live" : "Judge Pasted";
  }
}

async function runPipeline() {
  let sequence;
  try {
    sequence = JSON.parse(sequenceInput.value);
  } catch (error) {
    setMessage("Sequence JSON is invalid.", true);
    return;
  }

  runButton.disabled = true;
  runButton.classList.add("running");
  runButton.textContent = "Running...";
  setMessage("Running Phoenix retrieval and ranking.");

  try {
    const data = await fetchJson("/api/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        sequence,
        top_k_retrieval: Number(retrievalDepth.value),
        top_k_display: Number(displayCount.value),
      }),
    });
    renderRows(data.rows);
    rawLog.textContent = data.raw;
    const meta = data.meta || {};
    const best = data.rows[0]?.score;
    setMetric(0, meta.corpus_posts ? meta.corpus_posts.toLocaleString() : "-");
    setMetric(1, meta.retrieved ? meta.retrieved.toLocaleString() : "-");
    setMetric(2, Number.isFinite(best) ? best.toFixed(4) : "-");
    setMetric(3, `${(data.elapsed_ms / 1000).toFixed(1)}s`);
    runMeta.textContent = `Saved log to ${data.log_path}`;
    setMessage(`Ranked ${data.rows.length} posts.`);
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    runButton.disabled = false;
    runButton.classList.remove("running");
    runButton.textContent = "Run Pipeline";
  }
}

toggleLog.addEventListener("click", () => {
  rawLog.hidden = !rawLog.hidden;
});

loadExample.addEventListener("click", () => {
  loadExampleSequence().catch((error) => setMessage(error.message, true));
});

runButton.addEventListener("click", runPipeline);
loadSamplePosts.addEventListener("click", () => {
  loadSamplePostJson().catch((error) => setJudgeMessage(error.message, true));
});
runSampleJudge.addEventListener("click", async () => {
  try {
    await loadSamplePostJson();
    await judgePosts(false);
  } catch (error) {
    setJudgeMessage(error.message, true);
  }
});
judgePastedButton.addEventListener("click", () => judgePosts(false));
judgeLiveButton.addEventListener("click", () => judgePosts(true));
tabs.forEach((tabButton) => {
  tabButton.addEventListener("click", () => {
    tabs.forEach((item) => item.classList.remove("active"));
    views.forEach((view) => view.classList.remove("active-view"));
    tabButton.classList.add("active");
    document.querySelector(`#${tabButton.dataset.view}`).classList.add("active-view");
  });
});

loadStatus();
loadExampleSequence().catch((error) => setMessage(error.message, true));
loadSamplePostJson().catch((error) => setJudgeMessage(error.message, true));
