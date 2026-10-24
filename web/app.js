/**
 * web/app.js
 * ----------
 * IncuBrix Live Interactive Video Editing Demo client.
 * Connects with FastAPI /api/v1/ endpoints.
 */

// ── Application State ────────────────────────────────────────────────────────

const state = {
  projectId: null,
  videoDurationS: 0,
  currentHash: "",
  timeline: null,
  words: [],
  history: [],
  activeTab: "chat",
  isPlaying: false,
  lastRenderedVideoUrl: null,
};

// ── DOM References ───────────────────────────────────────────────────────────

const dom = {
  projectSelect: document.getElementById("projectSelect"),
  uploadVideoBtn: document.getElementById("uploadVideoBtn"),
  videoFileInput: document.getElementById("videoFileInput"),
  undoBtn: document.getElementById("undoBtn"),
  redoBtn: document.getElementById("redoBtn"),
  renderBtn: document.getElementById("renderBtn"),
  videoPlayer: document.getElementById("videoPlayer"),
  captionOverlay: document.getElementById("captionOverlay"),
  previewStatusBadge: document.getElementById("previewStatusBadge"),
  quickDownloadBtn: document.getElementById("quickDownloadBtn"),
  playPauseBtn: document.getElementById("playPauseBtn"),
  playIcon: document.getElementById("playIcon"),
  pauseIcon: document.getElementById("pauseIcon"),
  timeDisplay: document.getElementById("timeDisplay"),
  timeScrubber: document.getElementById("timeScrubber"),
  timePolicyBadge: document.getElementById("timePolicyBadge"),
  timelineHashTag: document.getElementById("timelineHashTag"),
  tlDurationStat: document.getElementById("tlDurationStat"),
  tlSegmentsStat: document.getElementById("tlSegmentsStat"),
  videoTrackBars: document.getElementById("videoTrackBars"),
  captionTrackBars: document.getElementById("captionTrackBars"),
  audioTrackBars: document.getElementById("audioTrackBars"),
  tabBtns: document.querySelectorAll(".tab-btn"),
  tabContents: document.querySelectorAll(".tab-content"),
  chatStream: document.getElementById("chatStream"),
  suggestionChips: document.getElementById("suggestionChips"),
  promptForm: document.getElementById("promptForm"),
  promptInput: document.getElementById("promptInput"),
  transcriptWordCount: document.getElementById("transcriptWordCount"),
  transcriptWordsContainer: document.getElementById("transcriptWordsContainer"),
  historyCount: document.getElementById("historyCount"),
  historyList: document.getElementById("historyList"),
  clarificationModal: document.getElementById("clarificationModal"),
  modalQuestionText: document.getElementById("modalQuestionText"),
  modalOptionsContainer: document.getElementById("modalOptionsContainer"),
  modalCustomInput: document.getElementById("modalCustomInput"),
  modalCustomSubmit: document.getElementById("modalCustomSubmit"),
  renderModal: document.getElementById("renderModal"),
  renderStatusLabel: document.getElementById("renderStatusLabel"),
  renderProgressBar: document.getElementById("renderProgressBar"),
  renderProgressText: document.getElementById("renderProgressText"),
  renderResultsBox: document.getElementById("renderResultsBox"),
  downloadVideoBtn: document.getElementById("downloadVideoBtn"),
  downloadTimelineBtn: document.getElementById("downloadTimelineBtn"),
  downloadOtioBtn: document.getElementById("downloadOtioBtn"),
  downloadManifestBtn: document.getElementById("downloadManifestBtn"),
  closeRenderModalBtn: document.getElementById("closeRenderModalBtn"),
};

// ── Initialization ───────────────────────────────────────────────────────────

async function init() {
  setupEventListeners();
  await loadSelectedProject();
}

function setupEventListeners() {
  // Tabs
  dom.tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      dom.tabBtns.forEach((b) => b.classList.remove("active"));
      dom.tabContents.forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      const targetId = `${btn.dataset.tab}Tab`;
      document.getElementById(targetId)?.classList.add("active");
      state.activeTab = btn.dataset.tab;
    });
  });

  // Project selector
  dom.projectSelect.addEventListener("change", () => {
    loadSelectedProject();
  });

  // Video Upload
  if (dom.uploadVideoBtn && dom.videoFileInput) {
    dom.uploadVideoBtn.addEventListener("click", () => {
      dom.videoFileInput.click();
    });

    dom.videoFileInput.addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      await handleVideoUpload(file);
      dom.videoFileInput.value = "";
    });
  }

  // Prompt submission
  dom.promptForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = dom.promptInput.value.trim();
    if (!text) return;
    dom.promptInput.value = "";
    await sendInstruction(text);
  });

  // Suggestion chips
  dom.suggestionChips.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const cmd = chip.dataset.cmd;
    dom.promptInput.value = cmd;
    dom.promptInput.focus();
  });

  // Undo / Redo
  dom.undoBtn.addEventListener("click", () => sendInstruction("Undo"));
  dom.redoBtn.addEventListener("click", () => sendInstruction("Redo"));

  // Video Playback Controls
  dom.playPauseBtn.addEventListener("click", togglePlayPause);
  dom.videoPlayer.addEventListener("timeupdate", onVideoTimeUpdate);
  dom.timeScrubber.addEventListener("input", onScrubberInput);

  // Render modal
  dom.renderBtn.addEventListener("click", startRenderFlow);
  dom.closeRenderModalBtn.addEventListener("click", () => {
    dom.renderModal.classList.add("hidden");
  });

  // Export MP4 quick button
  if (dom.quickDownloadBtn) {
    dom.quickDownloadBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      await handleExportMP4();
    });
  }

  // Modal download button
  if (dom.downloadVideoBtn) {
    dom.downloadVideoBtn.addEventListener("click", (e) => {
      if (state.lastRenderedVideoUrl) {
        e.preventDefault();
        triggerFileDownload(state.lastRenderedVideoUrl, "final_video.mp4");
      }
    });
  }

  // Custom clarification reply
  dom.modalCustomSubmit.addEventListener("click", () => {
    const reply = dom.modalCustomInput.value.trim();
    if (reply) {
      dom.clarificationModal.classList.add("hidden");
      dom.modalCustomInput.value = "";
      sendInstruction(reply);
    }
  });
}

// ── Video Upload & AI Analysis Flow ──────────────────────────────────────────

async function handleVideoUpload(file) {
  appendSystemMessage(`Analyzing "${file.name}" with AI Perception Pipeline (speech-to-text transcription, silence detection, topic segmentation)...`);

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/v1/projects", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData?.error?.message || `HTTP ${res.status}`);
    }

    const data = await res.json();
    state.projectId = data.project_id;
    state.videoDurationS = data.duration_s;

    // Add new custom project to dropdown
    const opt = document.createElement("option");
    opt.value = data.project_id;
    opt.textContent = `${file.name} (${data.duration_s.toFixed(1)}s, Custom Upload)`;
    dom.projectSelect.appendChild(opt);
    dom.projectSelect.value = data.project_id;

    // Load preview in player
    const previewUrl = data.video_url || URL.createObjectURL(file);
    dom.videoPlayer.src = previewUrl;
    dom.videoPlayer.load();

    state.lastRenderedVideoUrl = null;
    if (dom.quickDownloadBtn) {
      dom.quickDownloadBtn.classList.remove("hidden");
    }

    await refreshTimeline();

    const summary = data.analysis_summary || {};
    const silencesCount = summary.silences_count || 0;
    const chaptersCount = summary.chapters_count || 0;
    const speakers = (summary.speakers || []).join(", ") || "Speaker 0";

    appendSystemMessage(
      `AI Perception Analysis complete for "${file.name}"!\n` +
      `• Words: ${data.transcript_word_count} words transcribed\n` +
      `• Duration: ${data.duration_s.toFixed(2)}s\n` +
      `• Silence gaps: ${silencesCount} detected\n` +
      `• Chapters: ${chaptersCount} topics\n` +
      `• Speakers: ${speakers}\n\n` +
      `Type any natural-language prompt below to edit (e.g. "Cut the first 5 seconds", "Remove filler words", "Speed up by 2x", "Add a caption 'Welcome!'", etc.)!`,
      "applied"
    );
  } catch (err) {
    appendSystemMessage(`Video analysis failed: ${err.message}`, "rejected");
  }
}

// ── Project Loading ──────────────────────────────────────────────────────────

async function loadSelectedProject() {
  const choice = dom.projectSelect.value;

  // Custom project already uploaded
  if (choice && choice.startsWith("proj_")) {
    state.projectId = choice;
    await refreshTimeline();
    return;
  }

  let payload = { video_url: "tests/fixtures/sync_oracle_test.mp4" };

  if (choice === "interview") {
    payload = {
      video_url: "tests/fixtures/sync_oracle_test.mp4",
      transcript_path: "tests/fixtures/transcripts/interview_300s.json",
    };
  } else if (choice === "twospeakers") {
    payload = {
      video_url: "tests/fixtures/sync_oracle_test.mp4",
      transcript_path: "tests/fixtures/transcripts/two_speakers_120s.json",
    };
  }

  try {
    const res = await fetch("/api/v1/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("Failed to load project");
    const data = await res.json();
    state.projectId = data.project_id;
    state.videoDurationS = data.duration_s;

    // Load initial timeline
    await refreshTimeline();
    state.lastRenderedVideoUrl = null;
    if (dom.quickDownloadBtn) {
      dom.quickDownloadBtn.classList.remove("hidden");
    }
    appendSystemMessage(`Initialized project: ${choice.toUpperCase()} (${data.duration_s}s, ${data.transcript_word_count} words).`);
  } catch (err) {
    appendSystemMessage(`Error loading project: ${err.message}`, "rejected");
  }
}

async function refreshTimeline() {
  if (!state.projectId) return;
  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/timeline`);
    if (!res.ok) throw new Error("Failed to fetch timeline");
    const data = await res.json();
    state.timeline = data.timeline;
    state.currentHash = data.timeline_hash;
    state.videoDurationS = data.duration_s;

    updateTimelineView();
    updateTranscriptWords();
  } catch (err) {
    console.error("Timeline refresh failed:", err);
  }
}

// ── Instructions & 3-Way Answers ─────────────────────────────────────────────

async function sendInstruction(text) {
  if (!state.projectId) return;

  // Add user bubble
  appendUserMessage(text);

  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/instructions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": `ui_${Date.now()}_${Math.random().toString(36).substring(7)}`,
      },
      body: JSON.stringify({ say: text }),
    });

    const data = await res.json();
    if (data.error) {
      appendSystemMessage(data.error.message, "rejected", data.error.code);
      return;
    }

    handleInstructionAnswer(data, text);
    await refreshTimeline();
  } catch (err) {
    appendSystemMessage(`Network or engine error: ${err.message}`, "rejected");
  }
}

function handleInstructionAnswer(ans, originalText) {
  if (ans.status === "applied") {
    appendAppliedMessage(ans);
    state.history.push({
      text: originalText,
      summary: ans.summary,
      hash: ans.current_timeline_hash,
      dur: ans.current_duration_s,
    });
    updateHistoryList();
    // Automatically re-render the video so the player updates immediately
    autoRenderEditedPreview();

  } else if (ans.status === "needs_clarification") {
    appendClarificationMessage(ans);
    showClarificationModal(ans);

  } else if (ans.status === "rejected") {
    appendSystemMessage(ans.reason, "rejected", ans.error_code);
  }
}

let _autoRenderJobTimer = null;

async function autoRenderEditedPreview() {
  if (!state.projectId) return;

  if (dom.previewStatusBadge) {
    dom.previewStatusBadge.textContent = "🎬 Rendering edited video...";
    dom.previewStatusBadge.classList.add("updating");
    dom.previewStatusBadge.classList.remove("hidden");
  }

  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_url: null }),
    });
    if (res.status !== 202) return;
    const data = await res.json();
    const jobId = data.job_id;

    if (_autoRenderJobTimer) clearInterval(_autoRenderJobTimer);

    _autoRenderJobTimer = setInterval(async () => {
      try {
        const r = await fetch(`/api/v1/jobs/${jobId}`);
        if (!r.ok) return;
        const job = await r.json();

        if (job.status === "succeeded") {
          clearInterval(_autoRenderJobTimer);
          _autoRenderJobTimer = null;

          if (dom.previewStatusBadge) {
            dom.previewStatusBadge.textContent = "✓ Edited Video Active (MP4)";
            dom.previewStatusBadge.classList.remove("updating");
            dom.previewStatusBadge.classList.remove("hidden");
          }

          const streamUrl = job.results.stream_url || job.results.video_url;
          const wasPlaying = !dom.videoPlayer.paused;
          const prevTime = dom.videoPlayer.currentTime;

          dom.videoPlayer.src = streamUrl;
          dom.videoPlayer.load();
          dom.videoPlayer.currentTime = Math.min(prevTime, state.videoDurationS || 0);
          if (wasPlaying) dom.videoPlayer.play().catch(() => {});

          state.lastRenderedVideoUrl = job.results.video_url;

          if (dom.quickDownloadBtn) {
            dom.quickDownloadBtn.href = job.results.video_url;
            dom.quickDownloadBtn.setAttribute("download", "edited_video.mp4");
            dom.quickDownloadBtn.classList.remove("hidden");
          }

          dom.downloadVideoBtn.href = job.results.video_url;
          dom.downloadVideoBtn.setAttribute("download", "final_video.mp4");
          dom.downloadTimelineBtn.href = job.results.timeline_url;
          dom.downloadOtioBtn.href = job.results.otio_url;
          dom.downloadManifestBtn.href = job.results.manifest_url;

          appendRenderReadyMessage(job.results.video_url);

        } else if (job.status === "failed") {
          clearInterval(_autoRenderJobTimer);
          _autoRenderJobTimer = null;
          if (dom.previewStatusBadge) {
            dom.previewStatusBadge.classList.add("hidden");
          }
        }
      } catch {
        clearInterval(_autoRenderJobTimer);
        _autoRenderJobTimer = null;
      }
    }, 400);
  } catch (err) {
    console.warn("Auto render preview failed:", err);
  }
}

function appendRenderReadyMessage(videoUrl) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble system-bubble";
  bubble.style.borderLeft = "3px solid var(--accent-emerald)";
  bubble.innerHTML = `
    <div class="bubble-header"><span class="bubble-author" style="color: var(--accent-emerald);">🎬 Edited Video (MP4) Updated</span></div>
    <div class="bubble-body" style="display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
      <span>Video updated to ${state.videoDurationS.toFixed(2)}s. Preview playing above!</span>
      <button class="btn btn-primary btn-sm chat-dl-btn" style="text-decoration: none; cursor: pointer;">⬇ Download MP4</button>
    </div>
  `;
  const dlBtn = bubble.querySelector(".chat-dl-btn");
  if (dlBtn) {
    dlBtn.addEventListener("click", () => {
      triggerFileDownload(videoUrl, "edited_video.mp4");
    });
  }
  dom.chatStream.appendChild(bubble);
  dom.chatStream.scrollTop = dom.chatStream.scrollHeight;
}

// ── Chat Stream Rendering ────────────────────────────────────────────────────

function appendUserMessage(text) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble user-bubble";
  bubble.innerHTML = `
    <div class="bubble-header"><span class="bubble-author">You</span></div>
    <div class="bubble-body">${escapeHtml(text)}</div>
  `;
  dom.chatStream.appendChild(bubble);
  dom.chatStream.scrollTop = dom.chatStream.scrollHeight;
}

function appendAppliedMessage(ans) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble system-bubble applied-bubble";

  let deltaStr = "";
  if (ans.before_after) {
    const delta = ans.before_after.duration_delta_s;
    const sign = delta > 0 ? "+" : "";
    deltaStr = `<span style="color: ${delta < 0 ? 'var(--accent-rose)' : 'var(--accent-emerald)'}"> (${sign}${delta.toFixed(2)}s)</span>`;
  }

  let opsHtml = "";
  if (ans.operations && ans.operations.length > 0) {
    opsHtml = `<div class="bubble-ops">` +
      ans.operations.map(op => `<span class="op-badge">${escapeHtml(op.op_type)}: ${escapeHtml(op.description)}</span>`).join("") +
      `</div>`;
  }

  bubble.innerHTML = `
    <div class="bubble-header">
      <span class="bubble-author" style="color: var(--accent-emerald)">Applied</span>
      <span>${ans.current_duration_s.toFixed(2)}s${deltaStr}</span>
    </div>
    <div class="bubble-body">${escapeHtml(ans.summary || "Instruction applied successfully.")}</div>
    ${opsHtml}
  `;
  dom.chatStream.appendChild(bubble);
  dom.chatStream.scrollTop = dom.chatStream.scrollHeight;
}

function appendClarificationMessage(ans) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble system-bubble clarification-bubble";
  bubble.innerHTML = `
    <div class="bubble-header">
      <span class="bubble-author" style="color: var(--accent-amber)">Needs Clarification</span>
    </div>
    <div class="bubble-body">${escapeHtml(ans.question)}</div>
  `;
  dom.chatStream.appendChild(bubble);
  dom.chatStream.scrollTop = dom.chatStream.scrollHeight;
}

function appendSystemMessage(msg, type = "normal", code = null) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble system-bubble ${type === 'rejected' ? 'rejected-bubble' : ''}`;
  const codeBadge = code ? `<span class="op-badge" style="color: var(--accent-rose)">${code}</span>` : "";
  bubble.innerHTML = `
    <div class="bubble-header">
      <span class="bubble-author" style="color: ${type === 'rejected' ? 'var(--accent-rose)' : 'var(--text-dim)'}">
        ${type === 'rejected' ? 'Rejected' : 'IncuBrix'}
      </span>
      ${codeBadge}
    </div>
    <div class="bubble-body">${escapeHtml(msg)}</div>
  `;
  dom.chatStream.appendChild(bubble);
  dom.chatStream.scrollTop = dom.chatStream.scrollHeight;
}

// ── Clarification Modal ──────────────────────────────────────────────────────

function showClarificationModal(ans) {
  dom.modalQuestionText.textContent = ans.question;
  dom.modalOptionsContainer.innerHTML = "";

  (ans.options || []).forEach(opt => {
    const btn = document.createElement("button");
    btn.className = "modal-opt-btn";
    btn.textContent = opt;
    btn.addEventListener("click", () => {
      dom.clarificationModal.classList.add("hidden");
      sendInstruction(opt);
    });
    dom.modalOptionsContainer.appendChild(btn);
  });

  dom.clarificationModal.classList.remove("hidden");
}

// ── Visual Timeline Renderer ─────────────────────────────────────────────────

function updateTimelineView() {
  if (!state.timeline) return;

  dom.timelineHashTag.textContent = `Hash: ${state.currentHash.substring(0, 16)}...`;
  dom.tlDurationStat.textContent = `Duration: ${state.videoDurationS.toFixed(2)}s`;
  dom.tlSegmentsStat.textContent = `Segments: ${state.timeline.segments.length}`;

  const totalUs = state.timeline.duration_us || 1;

  // 1. Video Segments
  dom.videoTrackBars.innerHTML = "";
  state.timeline.segments.forEach((seg, i) => {
    const pct = (seg.output_duration_us / totalUs) * 100;
    const block = document.createElement("div");
    let speedClass = "normal";
    let speedLabel = "";
    if (seg.speed_factor > 1.05) {
      speedClass = "speed-up";
      speedLabel = `${seg.speed_factor.toFixed(1)}x`;
    } else if (seg.speed_factor < 0.95) {
      speedClass = "speed-down";
      speedLabel = `${seg.speed_factor.toFixed(1)}x`;
    }
    block.className = `segment-block ${speedClass}`;
    block.style.width = `${pct}%`;
    block.textContent = speedLabel;
    block.title = `Segment #${i+1}: ${seg.output_duration_us/1000000}s (Speed: ${seg.speed_factor}x)`;
    dom.videoTrackBars.appendChild(block);
  });

  // 2. Captions Track
  dom.captionTrackBars.innerHTML = "";
  (state.timeline.captions || []).forEach((cap) => {
    const startPct = (cap.output_start_us / totalUs) * 100;
    const widthPct = ((cap.output_end_us - cap.output_start_us) / totalUs) * 100;
    const block = document.createElement("div");
    block.className = "caption-block";
    block.style.left = `${startPct}%`;
    block.style.width = `${Math.max(widthPct, 1.5)}%`;
    block.textContent = cap.text;
    block.title = `Caption: "${cap.text}" (${(cap.output_end_us-cap.output_start_us)/1000000}s)`;
    if (cap.style?.color === "red" || cap.style?.color === "#ff0000") {
      block.style.background = "linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)";
    }
    dom.captionTrackBars.appendChild(block);
  });

  // 3. Audio Track
  dom.audioTrackBars.innerHTML = "";
  const audioBlock = document.createElement("div");
  audioBlock.className = "audio-block";
  audioBlock.style.left = "0%";
  audioBlock.style.width = "100%";
  dom.audioTrackBars.appendChild(audioBlock);
}

// ── Interactive Transcript ───────────────────────────────────────────────────

function updateTranscriptWords() {
  if (!state.timeline) return;
  dom.transcriptWordsContainer.innerHTML = "";

  // Collect surviving words or words from session
  const words = state.timeline.surviving_words || [];
  dom.transcriptWordCount.textContent = `${words.length} active words`;

  words.forEach(w => {
    const span = document.createElement("span");
    span.className = `word-span ${w.speaker?.includes("host") ? 'speaker-host' : 'speaker-guest'}`;
    span.textContent = w.text;
    span.dataset.startS = w.timeline_start_s || (w.start_us / 1000000);
    span.title = `${w.text} (${(w.start_us/1000000).toFixed(2)}s)`;

    span.addEventListener("click", () => {
      const seekS = parseFloat(span.dataset.startS);
      if (!isNaN(seekS)) {
        dom.videoPlayer.currentTime = seekS;
      }
    });

    dom.transcriptWordsContainer.appendChild(span);
  });
}

// ── Video Playback & Synchronisation ─────────────────────────────────────────

function togglePlayPause() {
  if (dom.videoPlayer.paused) {
    dom.videoPlayer.play();
    dom.playIcon.classList.add("hidden");
    dom.pauseIcon.classList.remove("hidden");
    state.isPlaying = true;
  } else {
    dom.videoPlayer.pause();
    dom.playIcon.classList.remove("hidden");
    dom.pauseIcon.classList.add("hidden");
    state.isPlaying = false;
  }
}

function onVideoTimeUpdate() {
  const current = dom.videoPlayer.currentTime;
  const isRendered = dom.videoPlayer.src.includes("/stream/") || dom.videoPlayer.src.includes("/download/");

  // Seamless Virtual Timeline Jumping for unrendered preview playback
  if (!isRendered && state.timeline && state.timeline.segments && state.timeline.segments.length > 0) {
    const segments = state.timeline.segments;
    const firstStart = segments[0].src_start_us / 1000000;
    const lastEnd = segments[segments.length - 1].src_end_us / 1000000;

    if (current < firstStart - 0.05) {
      dom.videoPlayer.currentTime = firstStart;
      return;
    }

    if (current >= lastEnd) {
      dom.videoPlayer.pause();
      dom.videoPlayer.currentTime = firstStart;
      dom.playIcon.classList.remove("hidden");
      dom.pauseIcon.classList.add("hidden");
      state.isPlaying = false;
      return;
    }

    for (let i = 0; i < segments.length - 1; i++) {
      const segEnd = segments[i].src_end_us / 1000000;
      const nextStart = segments[i + 1].src_start_us / 1000000;
      if (current >= segEnd && current < nextStart) {
        dom.videoPlayer.currentTime = nextStart;
        return;
      }
    }
  }

  const dur = state.videoDurationS || dom.videoPlayer.duration || 1;
  const pct = Math.min((current / dur) * 100, 100);

  dom.timeScrubber.value = pct;
  dom.timeDisplay.textContent = `${formatTime(current)} / ${formatTime(dur)}`;

  // Live Caption Display
  checkActiveCaptions(current);

  // Live Transcript Highlighting
  highlightActiveWord(current);
}

function onScrubberInput() {
  const pct = parseFloat(dom.timeScrubber.value);
  const dur = state.videoDurationS || dom.videoPlayer.duration || 1;
  dom.videoPlayer.currentTime = (pct / 100) * dur;
}

function checkActiveCaptions(timeS) {
  if (!state.timeline || !state.timeline.captions) return;
  const timeUs = timeS * 1000000;
  const activeCap = state.timeline.captions.find(c => timeUs >= c.output_start_us && timeUs <= c.output_end_us);

  if (activeCap) {
    dom.captionOverlay.textContent = activeCap.text;
    dom.captionOverlay.classList.remove("hidden");
    if (activeCap.style?.color === "red" || activeCap.style?.color === "#ff0000") {
      dom.captionOverlay.classList.add("style-red");
    } else {
      dom.captionOverlay.classList.remove("style-red");
    }
  } else {
    dom.captionOverlay.classList.add("hidden");
  }
}

function highlightActiveWord(timeS) {
  const spans = dom.transcriptWordsContainer.querySelectorAll(".word-span");
  spans.forEach(span => {
    const startS = parseFloat(span.dataset.startS);
    if (Math.abs(timeS - startS) < 0.4) {
      span.classList.add("active");
    } else {
      span.classList.remove("active");
    }
  });
}

function formatTime(s) {
  const m = Math.floor(s / 60);
  const rem = (s % 60).toFixed(2);
  return `${m.toString().padStart(2, '0')}:${rem.padStart(5, '0')}`;
}

// ── History Log ──────────────────────────────────────────────────────────────

function updateHistoryList() {
  dom.historyCount.textContent = state.history.length;
  if (state.history.length === 0) {
    dom.historyList.innerHTML = '<div class="empty-state">No edits applied yet.</div>';
    return;
  }
  dom.historyList.innerHTML = "";
  state.history.slice().reverse().forEach((item, idx) => {
    const div = document.createElement("div");
    div.className = "history-item";
    div.innerHTML = `
      <div class="history-item-top">
        <span>#${state.history.length - idx}</span>
        <span>${item.dur.toFixed(2)}s</span>
      </div>
      <strong>"${escapeHtml(item.text)}"</strong>
      <span style="color: var(--text-muted); font-size: 0.78rem;">${escapeHtml(item.summary)}</span>
    `;
    dom.historyList.appendChild(div);
  });
}

// ── Rendering Background Job Flow (Integration Standard 3) ───────────────────

async function startRenderFlow() {
  if (!state.projectId) return;

  dom.renderModal.classList.remove("hidden");
  dom.renderResultsBox.classList.add("hidden");
  dom.renderProgressBar.style.width = "5%";
  dom.renderProgressText.textContent = "5%";
  dom.renderStatusLabel.textContent = "Submitting render job (202 Accepted)...";

  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_url: null }),
    });

    if (res.status !== 202) throw new Error("Expected 202 Accepted");
    const jobData = await res.json();
    const jobId = jobData.job_id;

    pollRenderJob(jobId);
  } catch (err) {
    dom.renderStatusLabel.textContent = `Render initiation failed: ${err.message}`;
  }
}

async function pollRenderJob(jobId) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/v1/jobs/${jobId}`);
      if (!res.ok) return;
      const job = await res.json();

      dom.renderProgressBar.style.width = `${job.progress}%`;
      dom.renderProgressText.textContent = `${job.progress}%`;

      if (job.status === "running") {
        dom.renderStatusLabel.textContent = `FFmpeg pipeline rendering (${job.progress}%)...`;
      } else if (job.status === "succeeded") {
        clearInterval(interval);
        state.lastRenderedVideoUrl = job.results.video_url;
        dom.renderStatusLabel.textContent = `Render completed in ${job.latency_ms} ms!`;
        dom.downloadVideoBtn.href = job.results.video_url;
        dom.downloadVideoBtn.setAttribute("download", "final_video.mp4");
        dom.downloadTimelineBtn.href = job.results.timeline_url;
        dom.downloadOtioBtn.href = job.results.otio_url;
        dom.downloadManifestBtn.href = job.results.manifest_url;
        dom.renderResultsBox.classList.remove("hidden");

        if (dom.quickDownloadBtn) {
          dom.quickDownloadBtn.href = job.results.video_url;
          dom.quickDownloadBtn.setAttribute("download", "final_video.mp4");
          dom.quickDownloadBtn.classList.remove("hidden");
        }

        if (dom.previewStatusBadge) {
          dom.previewStatusBadge.textContent = "✓ Rendered MP4 Active";
          dom.previewStatusBadge.classList.remove("updating");
          dom.previewStatusBadge.classList.remove("hidden");
        }

        // Set video player to streamed rendered video
        dom.videoPlayer.src = job.results.stream_url || job.results.video_url;
        dom.videoPlayer.load();

      } else if (job.status === "failed") {
        clearInterval(interval);
        dom.renderStatusLabel.textContent = `Render failed: ${job.error?.message || 'Unknown error'}`;
      }
    } catch (err) {
      clearInterval(interval);
      dom.renderStatusLabel.textContent = `Polling error: ${err.message}`;
    }
  }, 400);
}

// ── Export & Download Helpers ───────────────────────────────────────────────

function triggerFileDownload(url, filename = "edited_video.mp4") {
  const saveFilename = filename.endsWith(".mp4") ? filename : `${filename}.mp4`;
  let downloadUrl = url || (state.projectId ? `/api/v1/projects/${state.projectId}/download` : "");
  if (!downloadUrl) return;

  if (downloadUrl.startsWith("http") && (downloadUrl.includes("127.0.0.1:8000") || downloadUrl.includes("localhost:8000"))) {
    try {
      const u = new URL(downloadUrl);
      downloadUrl = u.pathname;
    } catch {}
  }

  // Ensure download route is used rather than stream
  downloadUrl = downloadUrl.replace("/api/v1/stream/", "/api/v1/download/");

  appendSystemMessage(`⬇ Downloading MP4: "${saveFilename}"...`, "applied");

  // Direct native anchor download:
  // Using direct HTTP attachment ensures Chrome/Edge reads the Content-Disposition header
  // and saves the file with the proper .mp4 extension instead of a blob UUID.
  const a = document.createElement("a");
  a.style.display = "none";
  a.href = downloadUrl;
  a.setAttribute("download", saveFilename);
  a.target = "_self";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    if (a.parentNode) a.parentNode.removeChild(a);
  }, 1000);
}

async function handleExportMP4() {
  if (!state.projectId) {
    appendSystemMessage("Please load or upload a video first.", "rejected");
    return;
  }

  if (state.lastRenderedVideoUrl) {
    await triggerFileDownload(state.lastRenderedVideoUrl, "edited_video.mp4");
    return;
  }

  // If no rendered video yet, trigger background render flow or direct export
  appendSystemMessage("Exporting MP4: rendering edited video with FFmpeg...", "applied");
  await triggerFileDownload(`/api/v1/projects/${state.projectId}/download`, "edited_video.mp4");
}

function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// Boot
window.addEventListener("DOMContentLoaded", init);
