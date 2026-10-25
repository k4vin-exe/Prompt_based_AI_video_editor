/**
 * web/app.js
 * ----------
 * IncuBrix Studio — Minimalist Professional Dark Video Editor Client.
 * Connects with FastAPI /api/v1/ endpoints with full multi-clip support,
 * multi-track timeline, visual effects, and AI prompt copilot.
 */

// ── Application State ────────────────────────────────────────────────────────

const state = {
  projectId: null,
  videoDurationS: 10,
  currentHash: "",
  timeline: null,
  clips: [],
  effects: [],
  aspectRatio: "16:9",
  words: [],
  history: [],
  activeRailTab: "media",
  activeDrawerTab: "files",
  activeCopilotTab: "chat",
  isPlaying: false,
  zoomLevel: 1.0,
  lastRenderedVideoUrl: null,
};

// ── DOM References ───────────────────────────────────────────────────────────

const dom = {
  // Header
  projectSelect: document.getElementById("projectSelect"),
  uploadVideoBtn: document.getElementById("uploadVideoBtn"),
  videoFileInput: document.getElementById("videoFileInput"),
  undoBtn: document.getElementById("undoBtn"),
  redoBtn: document.getElementById("redoBtn"),
  renderBtn: document.getElementById("renderBtn"),
  quickDownloadBtn: document.getElementById("quickDownloadBtn"),

  // Tool Rail
  railBtns: document.querySelectorAll(".rail-btn"),
  drawerPanel: document.getElementById("drawerPanel"),
  drawerViews: {
    media: document.getElementById("drawerViewMedia"),
    captions: document.getElementById("drawerViewCaptions"),
    effects: document.getElementById("drawerViewEffects"),
    audio: document.getElementById("drawerViewAudio"),
    ai: document.getElementById("drawerViewAi"),
  },

  // Media Drawer
  mediaDropZone: document.getElementById("mediaDropZone"),
  browseFilesBtn: document.getElementById("browseFilesBtn"),
  importClipHeaderBtn: document.getElementById("importClipHeaderBtn"),
  mediaClipsList: document.getElementById("mediaClipsList"),

  // Captions & Effects Drawer
  autoCaptionAllBtn: document.getElementById("autoCaptionAllBtn"),
  styleCards: document.querySelectorAll(".style-card"),
  applyFxBtns: document.querySelectorAll(".apply-fx-btn"),
  quickToolBtns: document.querySelectorAll(".quick-tool-btn"),

  // Copilot Drawer Tabs
  copilotTabs: document.querySelectorAll(".copilot-tab"),
  copilotChatBox: document.getElementById("copilotChatBox"),
  copilotTranscriptBox: document.getElementById("copilotTranscriptBox"),
  copilotHistoryBox: document.getElementById("copilotHistoryBox"),
  chatStream: document.getElementById("chatStream"),
  transcriptWordCount: document.getElementById("transcriptWordCount"),
  transcriptWordsContainer: document.getElementById("transcriptWordsContainer"),
  historyCount: document.getElementById("historyCount"),
  historyList: document.getElementById("historyList"),

  // Center Stage (Player)
  ratioBtns: document.querySelectorAll(".ratio-btn"),
  videoContainer: document.getElementById("videoContainer"),
  videoPlayer: document.getElementById("videoPlayer"),
  captionOverlay: document.getElementById("captionOverlay"),
  previewStatusBadge: document.getElementById("previewStatusBadge"),
  timeDisplay: document.getElementById("timeDisplay"),
  playPauseBtn: document.getElementById("playPauseBtn"),
  playIcon: document.getElementById("playIcon"),
  pauseIcon: document.getElementById("pauseIcon"),
  stepBackBtn: document.getElementById("stepBackBtn"),
  stepForwardBtn: document.getElementById("stepForwardBtn"),
  muteToggleBtn: document.getElementById("muteToggleBtn"),
  volumeSlider: document.getElementById("volumeSlider"),
  fullscreenBtn: document.getElementById("fullscreenBtn"),

  // Timeline Toolbar
  splitClipBtn: document.getElementById("splitClipBtn"),
  deleteClipBtn: document.getElementById("deleteClipBtn"),
  speedRampBtn: document.getElementById("speedRampBtn"),
  quickCaptionBtn: document.getElementById("quickCaptionBtn"),
  quickFlashBtn: document.getElementById("quickFlashBtn"),
  timelineHashTag: document.getElementById("timelineHashTag"),
  tlDurationStat: document.getElementById("tlDurationStat"),
  zoomInBtn: document.getElementById("zoomInBtn"),
  zoomOutBtn: document.getElementById("zoomOutBtn"),

  // Multi-Track Timeline
  timelineRuler: document.getElementById("timelineRuler"),
  rulerTicks: document.getElementById("rulerTicks"),
  playhead: document.getElementById("playhead"),
  videoTrackBars: document.getElementById("videoTrackBars"),
  effectTrackBars: document.getElementById("effectTrackBars"),
  audioTrackBars: document.getElementById("audioTrackBars"),
  waveformCanvas: document.getElementById("waveformCanvas"),
  captionTrackBars: document.getElementById("captionTrackBars"),

  // Bottom AI Dock
  suggestionChips: document.getElementById("suggestionChips"),
  promptForm: document.getElementById("promptForm"),
  promptInput: document.getElementById("promptInput"),

  // Modals
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

// ── Application Initialization ───────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  init();
});

async function init() {
  setupEventListeners();
  drawAudioWaveform();
  await loadSelectedProject();
}

function setupEventListeners() {
  // 1. Tool Rail Tab Switching
  dom.railBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.railTab;
      if (tab === "ai") {
        // Focus dedicated right Copilot chat
        dom.copilotTabs.forEach(b => b.classList.toggle("active", b.dataset.view === "chat"));
        dom.copilotChatBox?.classList.remove("hidden");
        dom.copilotTranscriptBox?.classList.add("hidden");
        dom.copilotHistoryBox?.classList.add("hidden");
        dom.promptInput?.focus();
        return;
      }
      dom.railBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.activeRailTab = tab;

      // Switch drawer view
      Object.keys(dom.drawerViews).forEach(k => {
        if (dom.drawerViews[k]) {
          dom.drawerViews[k].classList.toggle("active", k === tab);
        }
      });
    });
  });

  // 2. Copilot Drawer Subtabs
  dom.copilotTabs.forEach(btn => {
    btn.addEventListener("click", () => {
      dom.copilotTabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const view = btn.dataset.view;
      state.activeCopilotTab = view;

      dom.copilotChatBox.classList.toggle("hidden", view !== "chat");
      dom.copilotTranscriptBox.classList.toggle("hidden", view !== "transcript");
      dom.copilotHistoryBox.classList.toggle("hidden", view !== "history");
    });
  });

  // 3. Project Selection & Import
  dom.projectSelect.addEventListener("change", () => loadSelectedProject());

  if (dom.uploadVideoBtn && dom.videoFileInput) {
    dom.uploadVideoBtn.addEventListener("click", () => dom.videoFileInput.click());
    if (dom.importClipHeaderBtn) {
      dom.importClipHeaderBtn.addEventListener("click", () => dom.videoFileInput.click());
    }
    if (dom.browseFilesBtn) {
      dom.browseFilesBtn.addEventListener("click", () => dom.videoFileInput.click());
    }
    if (dom.mediaDropZone) {
      dom.mediaDropZone.addEventListener("click", () => dom.videoFileInput.click());
      dom.mediaDropZone.addEventListener("dragover", e => { e.preventDefault(); e.stopPropagation(); });
      dom.mediaDropZone.addEventListener("drop", async e => {
        e.preventDefault();
        e.stopPropagation();
        const file = e.dataTransfer.files?.[0];
        if (file) await handleVideoUpload(file);
      });
    }

    dom.videoFileInput.addEventListener("change", async e => {
      const file = e.target.files?.[0];
      if (!file) return;
      await handleVideoUpload(file);
      dom.videoFileInput.value = "";
    });
  }

  // 4. Aspect Ratio Switcher
  dom.ratioBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      dom.ratioBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const ratio = btn.dataset.ratio;
      setAspectRatio(ratio);
    });
  });

  // 5. Playback & Transport Controls
  dom.playPauseBtn.addEventListener("click", togglePlayPause);
  dom.stepBackBtn.addEventListener("click", () => {
    dom.videoPlayer.currentTime = Math.max(0, dom.videoPlayer.currentTime - 1.0);
  });
  dom.stepForwardBtn.addEventListener("click", () => {
    dom.videoPlayer.currentTime = Math.min(state.videoDurationS, dom.videoPlayer.currentTime + 1.0);
  });
  dom.videoPlayer.addEventListener("timeupdate", onVideoTimeUpdate);

  // Volume & Fullscreen
  dom.volumeSlider.addEventListener("input", e => {
    dom.videoPlayer.volume = parseFloat(e.target.value);
  });
  dom.muteToggleBtn.addEventListener("click", () => {
    dom.videoPlayer.muted = !dom.videoPlayer.muted;
    dom.muteToggleBtn.style.opacity = dom.videoPlayer.muted ? "0.4" : "1";
  });
  dom.fullscreenBtn.addEventListener("click", () => {
    if (!document.fullscreenElement) {
      dom.videoContainer.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  });

  // 6. Interactive Playhead & Ruler Clicking
  dom.timelineRuler.addEventListener("click", onRulerClick);
  setupPlayheadDrag();

  // 7. Timeline Toolbar Tools
  dom.splitClipBtn.addEventListener("click", () => {
    const cur = dom.videoPlayer.currentTime.toFixed(2);
    sendInstruction(`Split clip at ${cur} seconds`);
  });
  dom.deleteClipBtn.addEventListener("click", () => {
    const cur = dom.videoPlayer.currentTime;
    const curEnd = (cur + 2.0).toFixed(2);
    sendInstruction(`Cut from ${cur.toFixed(2)} to ${curEnd}`);
  });
  dom.speedRampBtn.addEventListener("click", () => {
    sendInstruction("Speed up active clip by 2x");
  });
  dom.quickCaptionBtn.addEventListener("click", () => {
    sendInstruction("Add captions fully");
  });
  dom.quickFlashBtn.addEventListener("click", () => {
    sendInstruction("Add vibration flash effect");
  });

  // Zoom
  dom.zoomInBtn.addEventListener("click", () => {
    state.zoomLevel = Math.min(2.5, state.zoomLevel + 0.25);
    renderTimelineView();
  });
  dom.zoomOutBtn.addEventListener("click", () => {
    state.zoomLevel = Math.max(0.75, state.zoomLevel - 0.25);
    renderTimelineView();
  });

  // 8. Drawer 1-Click Action Buttons
  if (dom.autoCaptionAllBtn) {
    dom.autoCaptionAllBtn.addEventListener("click", () => sendInstruction("Add captions fully"));
  }
  dom.applyFxBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const fx = btn.dataset.fx;
      if (fx) sendInstruction(fx);
    });
  });
  dom.quickToolBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const cmd = btn.dataset.cmd;
      if (cmd) sendInstruction(cmd);
    });
  });
  dom.styleCards.forEach(card => {
    card.addEventListener("click", () => {
      dom.styleCards.forEach(c => c.classList.remove("active"));
      card.classList.add("active");
      const style = card.dataset.style;
      if (style === "mrbeast") {
        dom.captionOverlay.className = "caption-overlay";
      } else if (style === "boxed") {
        dom.captionOverlay.className = "caption-overlay style-boxed";
      } else {
        dom.captionOverlay.className = "caption-overlay";
      }
    });
  });

  // 9. Natural Language Prompt Form & Suggestion Chips
  dom.promptForm.addEventListener("submit", async e => {
    e.preventDefault();
    const text = dom.promptInput.value.trim();
    if (!text) return;
    dom.promptInput.value = "";
    await sendInstruction(text);
  });

  if (dom.suggestionChips) {
    dom.suggestionChips.addEventListener("click", e => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      const cmd = chip.dataset.cmd;
      if (cmd) {
        dom.promptInput.value = cmd;
        sendInstruction(cmd);
      }
    });
  }

  // 10. Undo, Redo, Render, and Export
  dom.undoBtn.addEventListener("click", () => sendInstruction("Undo"));
  dom.redoBtn.addEventListener("click", () => sendInstruction("Redo"));
  dom.renderBtn.addEventListener("click", () => triggerRenderModal());
  if (dom.quickDownloadBtn) {
    dom.quickDownloadBtn.addEventListener("click", async e => {
      e.preventDefault();
      await exportDirectMp4();
    });
  }

  // Keyboard Shortcuts: Space = Play/Pause, Ctrl+Z = Undo, Ctrl+Y = Redo
  window.addEventListener("keydown", e => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.code === "Space") {
      e.preventDefault();
      togglePlayPause();
    } else if (e.ctrlKey && e.code === "KeyZ") {
      e.preventDefault();
      sendInstruction("Undo");
    } else if (e.ctrlKey && e.code === "KeyY") {
      e.preventDefault();
      sendInstruction("Redo");
    }
  });

  // Render Modal close
  if (dom.closeRenderModalBtn) {
    dom.closeRenderModalBtn.addEventListener("click", () => {
      dom.renderModal.classList.add("hidden");
    });
  }
}

// ── Aspect Ratio Framing ─────────────────────────────────────────────────────

function setAspectRatio(ratio) {
  state.aspectRatio = ratio;
  dom.videoContainer.classList.remove("ratio-16-9", "ratio-9-16", "ratio-1-1");
  if (ratio === "9:16") {
    dom.videoContainer.classList.add("ratio-9-16");
  } else if (ratio === "1:1") {
    dom.videoContainer.classList.add("ratio-1-1");
  } else {
    dom.videoContainer.classList.add("ratio-1-16-9", "ratio-16-9");
  }
}

// ── Project Ingestion & Loading ──────────────────────────────────────────────

async function loadSelectedProject() {
  const choice = dom.projectSelect.value;
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

    // Fetch timeline and clips
    await refreshTimeline();
    await fetchProjectClips();

    appendSystemMessage(
      `Project initialized: ${choice.toUpperCase()} (${data.duration_s.toFixed(1)}s, ${data.transcript_word_count} words). Ask AI or click any tool to begin!`,
      "applied"
    );
  } catch (err) {
    appendSystemMessage(`Error loading project: ${err.message}`, "rejected");
  }
}

async function handleVideoUpload(file) {
  const formData = new FormData();
  formData.append("file", file);

  appendSystemMessage(`Uploading and analyzing "${file.name}" with Whisper STT & perception pipeline...`);

  try {
    const res = await fetch("/api/v1/projects/upload", {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      let errDetail = "Upload failed";
      try {
        const errData = await res.json();
        errDetail = errData.error?.message || errData.detail?.message || errDetail;
      } catch {}
      throw new Error(errDetail);
    }
    const data = await res.json();

    state.projectId = data.project_id;
    state.videoDurationS = data.duration_s;
    state.words = [];

    // Add to project select dropdown
    let opt = Array.from(dom.projectSelect.options).find(o => o.value === data.project_id);
    if (!opt) {
      opt = document.createElement("option");
      opt.value = data.project_id;
      opt.textContent = `${file.name} (${data.duration_s.toFixed(1)}s)`;
      dom.projectSelect.appendChild(opt);
    }
    dom.projectSelect.value = data.project_id;

    // Update player source
    const previewUrl = data.video_url || URL.createObjectURL(file);
    dom.videoPlayer.src = previewUrl;
    dom.videoPlayer.load();

    await refreshTimeline();
    await fetchProjectClips();

    appendSystemMessage(
      `✓ Video "${file.name}" analyzed successfully!\n• Duration: ${data.duration_s.toFixed(1)}s\n• Resolution: ${data.resolution ? data.resolution.join('×') : 'Auto'}\n• Words detected: ${data.transcript_word_count}\n\nAsk AI anything below (e.g., "Cut first 5s", "Add captions fully", "Make it 9:16", "Add vibration flash")!`,
      "applied"
    );
  } catch (err) {
    appendSystemMessage(`Upload error: ${err.message}`, "rejected");
  }
}

async function fetchProjectClips() {
  if (!state.projectId) return;
  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/clips`);
    if (!res.ok) return;
    const data = await res.json();
    state.clips = data.clips || [];
    renderMediaBin();
  } catch (err) {
    console.warn("Failed to fetch clips:", err);
  }
}

function renderMediaBin() {
  dom.mediaClipsList.innerHTML = "";
  if (!state.clips || state.clips.length === 0) {
    dom.mediaClipsList.innerHTML = `<div style="font-size:0.75rem; color:var(--text-dim); text-align:center; padding:1rem;">No supplementary clips added.</div>`;
    return;
  }

  state.clips.forEach(clip => {
    const card = document.createElement("div");
    card.className = "clip-bin-card";
    const durStr = (clip.duration_s || 10).toFixed(1) + "s";
    card.innerHTML = `
      <div class="clip-bin-thumb">
        <span>🎬</span>
        <span class="thumb-dur">${durStr}</span>
      </div>
      <div class="clip-bin-meta">
        <span class="clip-bin-name" title="${clip.name}">${clip.name}</span>
        <span class="clip-bin-desc">${clip.width || 1920}×${clip.height || 1080} • ${clip.primary ? "Main Timeline" : "Bin Asset"}</span>
      </div>
      <div class="clip-bin-actions">
        <button class="btn btn-secondary btn-xs add-to-tl-btn" data-clip-id="${clip.clip_id}">+ Timeline</button>
      </div>
    `;

    card.querySelector(".add-to-tl-btn")?.addEventListener("click", () => {
      sendInstruction(`Add clip '${clip.name}' to timeline`);
    });

    dom.mediaClipsList.appendChild(card);
  });
}

// ── Timeline Sync & Multi-Track Rendering ────────────────────────────────────

async function refreshTimeline() {
  if (!state.projectId) return;
  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/timeline`);
    if (!res.ok) throw new Error("Failed to fetch timeline");
    const data = await res.json();
    state.timeline = data.timeline;
    state.currentHash = data.timeline_hash;
    state.videoDurationS = data.duration_s || 10;

    renderTimelineView();
    updateTranscriptWords();
  } catch (err) {
    console.error("Timeline refresh failed:", err);
  }
}

function renderTimelineView() {
  if (!state.timeline) return;

  dom.timelineHashTag.textContent = `Hash: ${state.currentHash.substring(0, 16)}...`;
  dom.tlDurationStat.textContent = `${state.videoDurationS.toFixed(2)}s`;

  renderRulerTicks();

  const totalUs = state.timeline.duration_us || (state.videoDurationS * 1_000_000) || 1;

  // 1. Video Track (V1)
  dom.videoTrackBars.innerHTML = "";
  (state.timeline.segments || []).forEach((seg, i) => {
    const segSpeed = seg.speed != null ? seg.speed : (seg.speed_factor || 1.0);
    const startUs = seg.edited_start_us != null ? seg.edited_start_us : (seg.output_start_us || 0);
    const endUs = seg.edited_end_us != null ? seg.edited_end_us : (startUs + (seg.src_end_us - seg.src_start_us));
    const segDurUs = (endUs - startUs) || 1000000;
    const leftPct = (startUs / totalUs) * 100;
    const widthPct = (segDurUs / totalUs) * 100;

    const block = document.createElement("div");
    let speedClass = "normal";
    let speedLabel = "";
    if (segSpeed > 1.05) {
      speedClass = "speed-up";
      speedLabel = `⚡ ${segSpeed.toFixed(1)}x`;
    } else if (segSpeed < 0.95) {
      speedClass = "speed-down";
      speedLabel = `🐢 ${segSpeed.toFixed(1)}x`;
    }

    block.className = `video-block ${speedClass}`;
    block.style.left = `${leftPct}%`;
    block.style.width = `calc(${Math.max(widthPct, 1.5)}% - 2px)`;
    block.innerHTML = `<span class="block-label">Segment #${i + 1} ${speedLabel}</span>`;
    block.title = `Segment #${i + 1}: ${(segDurUs / 1_000_000).toFixed(2)}s`;

    block.addEventListener("click", () => {
      dom.videoPlayer.currentTime = startUs / 1_000_000;
    });

    dom.videoTrackBars.appendChild(block);
  });

  // 2. Effects Track (FX)
  dom.effectTrackBars.innerHTML = "";
  if (state.effects && state.effects.length > 0) {
    state.effects.forEach(fx => {
      const pill = document.createElement("div");
      pill.className = "effect-block";
      pill.style.left = "5%";
      pill.style.width = "40%";
      pill.innerHTML = `<span>✨ ${fx.type.replace('_', ' ').toUpperCase()}</span>`;
      dom.effectTrackBars.appendChild(pill);
    });
  } else {
    // Show placeholder subtle track block if none
    const fxPill = document.createElement("div");
    fxPill.className = "effect-block";
    fxPill.style.left = "0%";
    fxPill.style.width = "100%";
    fxPill.style.opacity = "0.2";
    fxPill.innerHTML = `<span>[FX Lane: Flash / Grades]</span>`;
    dom.effectTrackBars.appendChild(fxPill);
  }

  // 3. Captions Track (T1)
  dom.captionTrackBars.innerHTML = "";
  (state.timeline.captions || []).forEach(cap => {
    if (cap.hidden) return;
    const startUs = cap.edited_start_us != null ? cap.edited_start_us : (cap.output_start_us || 0);
    const endUs = cap.edited_end_us != null ? cap.edited_end_us : (startUs + 1_000_000);
    const capDurUs = (endUs - startUs) || 1_000_000;
    const startPct = (startUs / totalUs) * 100;
    const widthPct = (capDurUs / totalUs) * 100;

    const block = document.createElement("div");
    block.className = "caption-block";
    block.style.left = `${startPct}%`;
    block.style.width = `${Math.max(widthPct, 2)}%`;
    block.textContent = `"${cap.text}"`;
    block.title = `Caption: "${cap.text}"`;

    block.addEventListener("click", () => {
      dom.videoPlayer.currentTime = startUs / 1_000_000;
    });

    dom.captionTrackBars.appendChild(block);
  });

  // Re-draw waveform
  drawAudioWaveform();
}

function renderRulerTicks() {
  dom.rulerTicks.innerHTML = "";
  const totalS = Math.max(state.videoDurationS, 1);
  const step = totalS > 60 ? 10 : (totalS > 20 ? 5 : 1);

  for (let s = 0; s <= totalS; s += step) {
    const pct = (s / totalS) * 100;
    const tick = document.createElement("div");
    tick.className = `ruler-tick ${s % (step * 2) === 0 ? "major" : ""}`;
    tick.style.left = `${pct}%`;
    if (s % (step * 2) === 0 || s === 0 || s === Math.floor(totalS)) {
      const lbl = document.createElement("span");
      lbl.className = "ruler-tick-label";
      lbl.textContent = formatTime(s);
      tick.appendChild(lbl);
    }
    dom.rulerTicks.appendChild(tick);
  }
}

// ── Audio Waveform Visualizer ────────────────────────────────────────────────

function drawAudioWaveform() {
  const canvas = dom.waveformCanvas;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width || 600;
  canvas.height = rect.height || 40;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const numBars = Math.floor(canvas.width / 4);
  const midY = canvas.height / 2;

  // Render glowing gradient waveform peaks
  const grad = ctx.createLinearGradient(0, 0, 0, canvas.height);
  grad.addColorStop(0, "#a855f7");
  grad.addColorStop(0.5, "#06b6d4");
  grad.addColorStop(1, "#3b82f6");
  ctx.fillStyle = grad;

  for (let i = 0; i < numBars; i++) {
    // Generate organic pseudo-amplitude
    const seed = Math.sin(i * 0.15) * Math.cos(i * 0.08);
    const height = Math.max(3, Math.abs(seed) * (canvas.height * 0.78));
    const x = i * 4;
    const y = midY - height / 2;
    ctx.fillRect(x, y, 2.5, height);
  }
}

// ── Playhead & Scrubber Dragging ─────────────────────────────────────────────

function onRulerClick(e) {
  const rect = dom.timelineRuler.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const pct = Math.max(0, Math.min(1, clickX / rect.width));
  const newTime = pct * state.videoDurationS;
  dom.videoPlayer.currentTime = newTime;
  updatePlayheadPosition(pct * 100);
}

function setupPlayheadDrag() {
  let isDragging = false;

  dom.playhead.addEventListener("mousedown", e => {
    isDragging = true;
    e.preventDefault();
  });

  window.addEventListener("mousemove", e => {
    if (!isDragging) return;
    const rect = dom.timelineRuler.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    dom.videoPlayer.currentTime = pct * state.videoDurationS;
    updatePlayheadPosition(pct * 100);
  });

  window.addEventListener("mouseup", () => {
    if (isDragging) isDragging = false;
  });
}

function updatePlayheadPosition(pct) {
  dom.playhead.style.left = `${pct}%`;
}

// ── Video Playback Synchronisation ───────────────────────────────────────────

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
  const cur = dom.videoPlayer.currentTime;
  const dur = state.videoDurationS || dom.videoPlayer.duration || 10;
  const pct = Math.min((cur / dur) * 100, 100);

  updatePlayheadPosition(pct);
  dom.timeDisplay.textContent = `${formatTime(cur)} / ${formatTime(dur)}`;

  // Dynamic Captions Check
  checkActiveCaptions(cur);

  // Transcript Highlighting
  highlightActiveWord(cur);
}

function checkActiveCaptions(timeS) {
  if (!state.timeline || !state.timeline.captions) return;
  const timeUs = timeS * 1_000_000;
  const cap = state.timeline.captions.find(c => {
    if (c.hidden) return false;
    const s = c.edited_start_us != null ? c.edited_start_us : (c.output_start_us || 0);
    const e = c.edited_end_us != null ? c.edited_end_us : (s + 1_000_000);
    return timeUs >= s && timeUs <= e;
  });

  if (cap) {
    const styleClass = cap.style?.preset ? `style-${cap.style.preset}` : "";
    dom.captionOverlay.innerHTML = `<span class="caption-text-styled ${styleClass}">${escapeHtml(cap.text)}</span>`;
    dom.captionOverlay.classList.remove("hidden");
  } else {
    dom.captionOverlay.classList.add("hidden");
  }
}

function highlightActiveWord(timeS) {
  if (!dom.transcriptWordsContainer) return;
  const spans = dom.transcriptWordsContainer.querySelectorAll(".word-span");
  spans.forEach(span => {
    const startS = parseFloat(span.dataset.startS);
    if (Math.abs(timeS - startS) < 0.35) {
      span.classList.add("active");
    } else {
      span.classList.remove("active");
    }
  });
}

async function updateTranscriptWords() {
  if (!state.projectId) return;
  try {
    if (!state.words || state.words.length === 0) {
      const res = await fetch(`/api/v1/projects/${state.projectId}/transcript`);
      if (res.ok) {
        const data = await res.json();
        state.words = data.transcript?.words || [];
      }
    }

    if (!dom.transcriptWordsContainer) return;
    dom.transcriptWordsContainer.innerHTML = "";

    const segments = state.timeline?.segments || [];
    const survivingWords = (state.words || []).filter(w => {
      if (segments.length === 0) return true;
      return segments.some(seg => w.start_us >= seg.src_start_us && w.end_us <= seg.src_end_us);
    });

    if (dom.transcriptWordCount) {
      dom.transcriptWordCount.textContent = `${survivingWords.length}`;
    }

    if (survivingWords.length === 0) {
      dom.transcriptWordsContainer.innerHTML = `<div style="color:var(--text-dim); font-size:0.75rem; padding:0.5rem;">No active words in current cut.</div>`;
      return;
    }

    survivingWords.forEach(w => {
      const span = document.createElement("span");
      span.className = "word-span";
      span.textContent = w.text;
      span.dataset.startS = (w.start_us / 1_000_000).toFixed(2);
      span.title = `[${w.id || ""}] ${w.text} (${(w.start_us / 1_000_000).toFixed(2)}s)`;

      span.addEventListener("click", () => {
        const seek = parseFloat(span.dataset.startS);
        if (!isNaN(seek)) dom.videoPlayer.currentTime = seek;
      });

      dom.transcriptWordsContainer.appendChild(span);
    });
  } catch (err) {
    console.warn("Failed to update transcript words:", err);
  }
}

function formatTime(s) {
  const m = Math.floor(s / 60);
  const rem = (s % 60).toFixed(2);
  return `${m.toString().padStart(2, "0")}:${rem.padStart(5, "0")}`;
}

// ── Natural Language Instruction Dispatcher ──────────────────────────────────

async function sendInstruction(text) {
  if (!state.projectId) {
    await loadSelectedProject();
    if (!state.projectId) {
      appendSystemMessage("Please select or import a video project first.", "rejected");
      return;
    }
  }

  // Add user speech bubble
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

    if (!res.ok) {
      let errMsg = `Server returned status ${res.status}`;
      try {
        const errJson = await res.json();
        errMsg = errJson.error?.message || errJson.detail?.message || errJson.message || errMsg;
      } catch {}
      appendSystemMessage(errMsg, "rejected");
      return;
    }

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

    // Check if aspect ratio was modified
    if (ans.summary && ans.summary.toLowerCase().includes("aspect ratio")) {
      if (ans.summary.includes("9:16")) setAspectRatio("9:16");
      else if (ans.summary.includes("1:1")) setAspectRatio("1:1");
      else setAspectRatio("16:9");
    }

    // Check if an effect was applied
    if (ans.summary && ans.summary.toLowerCase().includes("effect")) {
      state.effects.push({ type: "vibration_flash", text: originalText });
      renderTimelineView();
    }

    // Auto-render updated preview MP4 in background
    autoRenderEditedPreview();

  } else if (ans.status === "needs_clarification") {
    appendClarificationMessage(ans);
    showClarificationModal(ans);

  } else if (ans.status === "rejected") {
    appendSystemMessage(ans.reason, "rejected", ans.error_code);
  }
}

// ── Background Auto-Render Preview ───────────────────────────────────────────

let _autoRenderTimer = null;
let _isAutoRendering = false;

async function autoRenderEditedPreview() {
  if (!state.projectId || _isAutoRendering) return;
  _isAutoRendering = true;

  dom.previewStatusBadge.textContent = "🎬 Rendering preview...";
  dom.previewStatusBadge.classList.add("updating");
  dom.previewStatusBadge.classList.remove("hidden");

  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_url: null }),
    });
    if (res.status !== 202) {
      _isAutoRendering = false;
      return;
    }
    const data = await res.json();
    const jobId = data.job_id;

    if (_autoRenderTimer) clearInterval(_autoRenderTimer);

    _autoRenderTimer = setInterval(async () => {
      try {
        const r = await fetch(`/api/v1/jobs/${jobId}`);
        if (!r.ok) return;
        const job = await r.json();

        if (job.status === "succeeded") {
          clearInterval(_autoRenderTimer);
          _autoRenderTimer = null;
          _isAutoRendering = false;

          dom.previewStatusBadge.textContent = "✓ Edited Video Active (MP4)";
          dom.previewStatusBadge.classList.remove("updating");

          const streamUrl = job.results.stream_url || job.results.video_url;
          const wasPlaying = !dom.videoPlayer.paused;
          const prevTime = dom.videoPlayer.currentTime;

          dom.videoPlayer.src = streamUrl;
          dom.videoPlayer.load();
          dom.videoPlayer.currentTime = Math.min(prevTime, state.videoDurationS);
          if (wasPlaying) dom.videoPlayer.play().catch(() => {});

          state.lastRenderedVideoUrl = job.results.video_url;

        } else if (job.status === "failed") {
          clearInterval(_autoRenderTimer);
          _autoRenderTimer = null;
          _isAutoRendering = false;
          dom.previewStatusBadge.classList.add("hidden");
        }
      } catch {
        clearInterval(_autoRenderTimer);
        _autoRenderTimer = null;
        _isAutoRendering = false;
      }
    }, 500);
  } catch (err) {
    _isAutoRendering = false;
    console.warn("Auto render preview failed:", err);
  }
}

// ── Direct 100% Reliable MP4 Export ──────────────────────────────────────────

async function exportDirectMp4() {
  if (!state.projectId) {
    alert("Please select or import a project first.");
    return;
  }

  const exportBtn = dom.quickDownloadBtn;
  const originalText = exportBtn.innerHTML;
  exportBtn.innerHTML = `<span>⏳ Saving MP4...</span>`;
  exportBtn.style.opacity = "0.7";

  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/export-direct`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ open_folder: true }),
    });

    if (!res.ok) throw new Error("Export failed on server");
    const data = await res.json();

    // Trigger browser MP4 download
    const dlLink = document.createElement("a");
    dlLink.href = `/api/v1/projects/${state.projectId}/download/video`;
    dlLink.download = "edited_video.mp4";
    document.body.appendChild(dlLink);
    dlLink.click();
    document.body.removeChild(dlLink);

    appendSystemMessage(
      `🎉 MP4 Video successfully exported!\n` +
      `• File: ${data.filename} (${data.size_mb} MB)\n` +
      `• Saved directly to: ${data.saved_path}\n` +
      `• Highlighted in Windows File Explorer!`,
      "applied"
    );

  } catch (err) {
    appendSystemMessage(`Export error: ${err.message}`, "rejected");
  } finally {
    exportBtn.innerHTML = originalText;
    exportBtn.style.opacity = "1";
  }
}

// ── Render Progress Modal ────────────────────────────────────────────────────

async function triggerRenderModal() {
  if (!state.projectId) return;

  dom.renderModal.classList.remove("hidden");
  dom.renderResultsBox.classList.add("hidden");
  dom.renderStatusLabel.textContent = "Queueing FFmpeg render pipeline...";
  dom.renderProgressBar.style.width = "10%";
  dom.renderProgressText.textContent = "10%";

  try {
    const res = await fetch(`/api/v1/projects/${state.projectId}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_url: null }),
    });
    const data = await res.json();
    const jobId = data.job_id;

    const timer = setInterval(async () => {
      try {
        const r = await fetch(`/api/v1/jobs/${jobId}`);
        const job = await r.json();

        dom.renderProgressBar.style.width = `${job.progress}%`;
        dom.renderProgressText.textContent = `${job.progress}%`;
        dom.renderStatusLabel.textContent = `Status: ${job.status.toUpperCase()} (${job.progress}%)`;

        if (job.status === "succeeded") {
          clearInterval(timer);
          dom.renderResultsBox.classList.remove("hidden");
          dom.downloadVideoBtn.href = job.results.video_url;
          dom.downloadTimelineBtn.href = job.results.timeline_url;
          dom.downloadOtioBtn.href = job.results.otio_url;
          dom.downloadManifestBtn.href = job.results.manifest_url;
        } else if (job.status === "failed") {
          clearInterval(timer);
          dom.renderStatusLabel.textContent = `Render failed: ${job.error?.message || "Unknown error"}`;
        }
      } catch {
        clearInterval(timer);
      }
    }, 400);
  } catch (err) {
    dom.renderStatusLabel.textContent = `Error: ${err.message}`;
  }
}

// ── Chat & Instruction Messages ──────────────────────────────────────────────

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
  bubble.className = "chat-bubble system-bubble";
  bubble.style.borderLeft = "3px solid var(--accent-emerald)";
  bubble.innerHTML = `
    <div class="bubble-header"><span class="bubble-author" style="color:var(--accent-emerald);">✓ Applied</span></div>
    <div class="bubble-body" style="white-space: pre-wrap;">${escapeHtml(ans.summary)}</div>
  `;
  dom.chatStream.appendChild(bubble);
  dom.chatStream.scrollTop = dom.chatStream.scrollHeight;
}

function appendClarificationMessage(ans) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble system-bubble";
  bubble.style.borderLeft = "3px solid var(--accent-amber)";
  bubble.innerHTML = `
    <div class="bubble-header"><span class="bubble-author" style="color:var(--accent-amber);">? Clarification</span></div>
    <div class="bubble-body">${escapeHtml(ans.question)}</div>
  `;
  dom.chatStream.appendChild(bubble);
  dom.chatStream.scrollTop = dom.chatStream.scrollHeight;
}

function appendSystemMessage(text, type = "normal", code = "") {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble system-bubble";
  if (type === "rejected") {
    bubble.style.borderLeft = "3px solid var(--accent-rose)";
    bubble.innerHTML = `
      <div class="bubble-header"><span class="bubble-author" style="color:var(--accent-rose);">Rejected ${code ? `(${code})` : ""}</span></div>
      <div class="bubble-body">${escapeHtml(text)}</div>
    `;
  } else {
    bubble.innerHTML = `
      <div class="bubble-header"><span class="bubble-author">IncuBrix Copilot</span></div>
      <div class="bubble-body" style="white-space: pre-wrap;">${escapeHtml(text)}</div>
    `;
  }
  dom.chatStream.appendChild(bubble);
  dom.chatStream.scrollTop = dom.chatStream.scrollHeight;
}

function updateHistoryList() {
  dom.historyCount.textContent = `${state.history.length}`;
  dom.historyList.innerHTML = "";
  if (state.history.length === 0) {
    dom.historyList.innerHTML = `<div style="font-size:0.75rem; color:var(--text-dim); padding:0.5rem;">No edits yet.</div>`;
    return;
  }
  state.history.forEach((h, i) => {
    const item = document.createElement("div");
    item.style.padding = "0.45rem 0.6rem";
    item.style.marginBottom = "0.35rem";
    item.style.background = "var(--bg-panel-sub)";
    item.style.borderRadius = "var(--radius-sm)";
    item.style.fontSize = "0.72rem";
    item.innerHTML = `
      <div style="font-weight:700; color:var(--text-main);">#${i + 1} "${escapeHtml(h.text)}"</div>
      <div style="color:var(--text-muted); font-size:0.65rem;">${escapeHtml(h.summary)}</div>
    `;
    dom.historyList.appendChild(item);
  });
}

function showClarificationModal(ans) {
  dom.modalQuestionText.textContent = ans.question;
  dom.modalOptionsContainer.innerHTML = "";

  (ans.options || []).forEach(opt => {
    const btn = document.createElement("button");
    btn.className = "modal-option-btn";
    btn.textContent = opt.label;
    btn.addEventListener("click", () => {
      dom.clarificationModal.classList.add("hidden");
      sendInstruction(opt.label);
    });
    dom.modalOptionsContainer.appendChild(btn);
  });

  dom.clarificationModal.classList.remove("hidden");
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
