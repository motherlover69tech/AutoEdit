export function findClipAtTime(clips, tMs) {
  return clips.find((clip) => {
    const start = clip.timeline_in_ms;
    const end = clip.timeline_in_ms + clip.dur_ms;
    return tMs >= start && tMs < end;
  }) || null;
}

export function validateContiguousClips(clips) {
  if (!Array.isArray(clips) || clips.length === 0) {
    throw new Error("Player cut is empty; no authoritative timeline is available");
  }
  let expectedStart = 0;
  for (const [index, clip] of clips.entries()) {
    if (!clip || !Number.isInteger(clip.timeline_in_ms) || !Number.isInteger(clip.dur_ms)
      || !Number.isInteger(clip.src_in_ms) || clip.timeline_in_ms !== expectedStart
      || clip.dur_ms <= 0 || clip.src_in_ms < 0 || !clip.angle_id) {
      throw new Error(`Player cut contains malformed or non-contiguous clip ${index + 1}`);
    }
    expectedStart += clip.dur_ms;
  }
  return { totalDurationMs: expectedStart };
}

/** Validate the additive AI projection without repairing or clipping it. */
export function normalizeProjectedActivity(payload) {
  if (payload == null) return null;
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.timeline)) {
    throw new Error("Projected activity is malformed; timeline is required");
  }
  if (!Number.isInteger(payload.total_duration_ms) || payload.total_duration_ms <= 0) {
    throw new Error("Projected activity has an invalid total duration");
  }
  let expectedStart = 0;
  const timeline = payload.timeline.map((segment, index) => {
    if (!segment || !Number.isInteger(segment.start_ms) || !Number.isInteger(segment.end_ms)
      || segment.start_ms !== expectedStart || segment.end_ms <= segment.start_ms
      || segment.end_ms > payload.total_duration_ms || !Array.isArray(segment.active)
      || typeof segment.mapping_status !== "string" || typeof segment.authority_status !== "string") {
      throw new Error(`Projected activity contains malformed segment ${index + 1}`);
    }
    expectedStart = segment.end_ms;
    return Object.freeze({ ...segment, active: Object.freeze([...segment.active]) });
  });
  if (expectedStart !== payload.total_duration_ms) {
    throw new Error("Projected activity does not cover the accepted timeline");
  }
  return Object.freeze({ ...payload, timeline: Object.freeze(timeline) });
}

/** Small state seam: refresh may replace only the projected read model. */
export function createPlayerStateStore(initialState) {
  let state = initialState;
  let projectedError = null;
  return {
    get state() { return state; },
    get projectedError() { return projectedError; },
    replaceProjected(payload) {
      const projected = normalizeProjectedActivity(payload);
      state = { ...state, projected_activity: projected };
      projectedError = null;
      return state;
    },
    failProjected(error) {
      projectedError = error instanceof Error ? error.message : String(error);
      state = { ...state, projected_activity: null };
      return state;
    },
  };
}

export function analysisStatusDisplay(analysis = {}, clip = null) {
  const conditions = { ...(analysis.conditions || {}), ...(clip?.projection || {}) };
  const safety = conditions.missing_wide ? "Missing wide — playback blocked safely"
    : conditions.unresolved ? "Unresolved speaker — wide chosen to avoid a wrong close-up"
    : conditions.low_confidence ? "Low confidence — wide chosen until identity is confirmed"
    : conditions.off_camera ? "Off-camera or uncertain — wide chosen safely"
    : conditions.overlap ? "Overlap — wide chosen for simultaneous speech"
    : "Confirmed authority";
  const source = analysis.source === "whisperx" ? "WhisperX projected activity" : "VAD baseline activity";
  const mapping = {
    confirmed: "Mapping confirmed",
    needs_confirmation: "Mapping needs confirmation",
    unresolved: "Mapping unresolved",
    baseline: "Baseline mapping",
  }[analysis.mapping_status] || "Mapping status unavailable";
  return { source, mapping, safety, tone: conditions.unresolved || conditions.low_confidence || conditions.missing_wide || conditions.overlap || conditions.off_camera ? "uncertain" : "confirmed" };
}

const ACTIVITY_STATUS_LABELS = {
  confirmed: ["Confirmed authority", "confirmed"],
  unresolved: ["Unresolved", "unresolved"],
  low_confidence: ["Low confidence", "low-confidence"],
  overlap: ["Overlap", "overlap"],
  off_camera: ["Off-camera", "off-camera"],
  missing_wide: ["Missing wide", "missing-wide"],
};

export function activityStatusDisplay(segment = {}) {
  const status = segment.missing_wide ? "missing_wide"
    : segment.off_camera ? "off_camera"
    : segment.overlap ? "overlap"
    : segment.low_confidence ? "low_confidence"
    : segment.unresolved || segment.authority_status === "unresolved" ? "unresolved"
    : "confirmed";
  const [label, tone] = ACTIVITY_STATUS_LABELS[status];
  return { status, label, tone };
}

export function validateMasterTimeSpans(spans, totalMs) {
  if (!Array.isArray(spans) || !Number.isInteger(totalMs) || totalMs <= 0) {
    throw new Error("Timeline markers have an invalid master duration");
  }
  let expected = 0;
  for (const [index, span] of spans.entries()) {
    if (!span || !Number.isInteger(span.start_ms) || !Number.isInteger(span.end_ms)
      || span.start_ms !== expected || span.end_ms <= span.start_ms || span.end_ms > totalMs) {
      throw new Error(`Timeline markers contain an invalid master range ${index + 1}`);
    }
    expected = span.end_ms;
  }
  if (expected !== totalMs) throw new Error("Timeline markers do not cover the master timeline");
  return true;
}

export function findNextClip(clips, tMs) {
  return clips.find((clip) => clip.timeline_in_ms > tMs) || null;
}

const LEGACY_SHOT_REASONS = {
  "overlap:wide": ["Crosstalk", "Multiple speakers detected", "crosstalk"],
  "overlap:hold": ["Crosstalk · holding shot", "Wide cut disabled", "crosstalk"],
  "short_overlap:hold": ["Crosstalk · holding speaker", "Overlap shorter than the wide-shot threshold", "crosstalk"],
  "interjection:hold": ["Brief interjection · holding speaker", "Avoids a distracting reaction cut", "hold"],
  "exchange:wide": ["Rapid exchange", "Wide avoids ping-pong cuts", "crosstalk"],
  "silence:wide": ["Silence", "Wide shot during silence", "silence"],
  "silence:hold": ["Silence · holding shot", "No active speaker", "silence"],
  "periodic:wide": ["Variety shot", "Breaks up a long-held shot", "variety"],
  "unresolved:wide": ["Unresolved speaker", "Wide is safer than a wrong close-up", "uncertain"],
  "low_confidence:wide": ["Low confidence", "Wide is safer than a wrong close-up", "uncertain"],
};

export function shotReasonDisplay(clip, manualOverride = false) {
  if (manualOverride) {
    return { label: "Manual override", detail: "Automatic shot reason paused", tone: "manual" };
  }
  if (!clip) return { label: "No shot reason", detail: "", tone: "neutral" };
  if (clip.reason_label) {
    return {
      label: clip.reason_label,
      detail: clip.reason_detail || "",
      tone: clip.reason_code === "speaking" ? "speaking" :
        clip.reason_code === "variety_wide" ? "variety" :
        clip.reason_code?.includes("silence") ? "silence" :
        clip.reason_code?.includes("confidence") || clip.reason_code?.includes("unresolved") ? "uncertain" :
        clip.reason_code?.includes("crosstalk") || clip.reason_code === "rapid_exchange" ? "crosstalk" : "neutral",
    };
  }
  if (clip.reason?.startsWith("speaker:")) {
    return { label: "Speaking", detail: clip.reason.slice(8), tone: "speaking" };
  }
  const legacy = LEGACY_SHOT_REASONS[clip.reason];
  if (legacy) return { label: legacy[0], detail: legacy[1], tone: legacy[2] };
  return { label: "Editorial rule", detail: clip.reason || "Reason unavailable", tone: "neutral" };
}

export function timelineMsFromAudio(audioCurrentTime) {
  return Math.max(0, Math.round(Number(audioCurrentTime || 0) * 1000));
}

export function videoTimeForClip(clip, timelineMs) {
  if (!clip) return 0;
  return (timelineMs - clip.timeline_in_ms + clip.src_in_ms) / 1000;
}

export function videoTimeForAngle(angle, timelineMs) {
  if (!angle) return 0;
  return (Number(timelineMs || 0) + Number(angle.source_time_offset_ms || 0)) / 1000;
}

export function playbackVideoTimeForClip(clip, timelineMs, manualNudgeMs = 0) {
  if (!clip) return 0;
  // Keep all arithmetic in integer milliseconds and divide once, so seek
  // times land exactly on ms boundaries instead of accumulating IEEE754
  // error (1.15 - 0.1 === 1.0499999999999998).
  return (timelineMs - clip.timeline_in_ms + clip.src_in_ms - Number(manualNudgeMs || 0)) / 1000;
}

export function playbackVideoTimeForAngle(angle, timelineMs, manualNudgeMs = 0) {
  if (!angle) return 0;
  return (
    Number(timelineMs || 0)
    + Number(angle.source_time_offset_ms || 0)
    - Number(manualNudgeMs || 0)
  ) / 1000;
}

export function frameDurationSeconds(fpsNum, fpsDen) {
  return Number(fpsDen) / Number(fpsNum);
}

export function needsDriftCorrection(videoTime, desiredTime, frameDuration) {
  return Math.abs(Number(videoTime) - Number(desiredTime)) > Number(frameDuration);
}

export function chooseMediaUrl(angle, quality) {
  if (!angle) return null;
  if (quality === "proxy_low" && angle.proxy_low_url) return angle.proxy_low_url;
  return angle.proxy_url || angle.proxy_low_url || null;
}

export function createManualOverrideState(initialAngleId = null) {
  let manualAngleId = initialAngleId;
  return {
    get manualAngleId() {
      return manualAngleId;
    },
    force(angleId) {
      manualAngleId = angleId;
      return manualAngleId;
    },
    clear() {
      manualAngleId = null;
      return manualAngleId;
    },
    resolve(autoAngleId) {
      return manualAngleId || autoAngleId || null;
    },
  };
}

// ── .cube LUT parser ─────────────────────────────────────────

/**
 * Parse a .cube LUT file into a Float32Array suitable for WebGL 3D texture.
 * @param {string} text - the .cube file content
 * @returns {{size: number, title: string, data: Float32Array}}
 */
export function parseCubeLUT(text) {
  const lines = text.split(/\r?\n/);
  let title = "";
  let size = 0;
  const data = [];
  let inData = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    if (line.startsWith("TITLE") || line.startsWith("BMD_TITLE")) {
      const m = line.match(/"([^"]*)"/);
      title = m ? m[1] : line.split(/\s+/).slice(1).join(" ");
      continue;
    }

    if (line.startsWith("LUT_3D_SIZE")) {
      size = parseInt(line.split(/\s+/)[1], 10);
      continue;
    }

    if (line.startsWith("DOMAIN_MIN") || line.startsWith("DOMAIN_MAX")) {
      continue;
    }

    // First numeric line triggers data parsing
    const parts = line.split(/\s+/);
    if (parts.length >= 3) {
      const r = parseFloat(parts[0]);
      const g = parseFloat(parts[1]);
      const b = parseFloat(parts[2]);
      if (!isNaN(r) && !isNaN(g) && !isNaN(b)) {
        data.push(r, g, b);
        inData = true;
        continue;
      }
    }

    if (inData) break; // Stop at first non-data line after data started
  }

  if (!size) throw new Error("LUT_3D_SIZE not found in .cube file");

  return {
    size,
    title,
    data: new Float32Array(data),
  };
}

// ── WebGL 3D LUT pipeline ────────────────────────────────────

const LUT_VERTEX_SHADER = `#version 300 es
in vec2 a_position;
in vec2 a_texCoord;
out vec2 v_texCoord;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
  v_texCoord = a_texCoord;
}`;

const LUT_FRAGMENT_SHADER = `#version 300 es
precision highp float;
precision highp sampler3D;
in vec2 v_texCoord;
uniform sampler2D u_video;
uniform sampler3D u_lut;
uniform float u_lutSize;
uniform bool u_lutEnabled;
out vec4 outColor;

void main() {
  vec4 color = texture(u_video, v_texCoord);
  if (!u_lutEnabled) {
    outColor = color;
    return;
  }
  // Map to LUT coordinate space: (size-1)/size offset + 0.5/size
  float scale = (u_lutSize - 1.0) / u_lutSize;
  float offset = 0.5 / u_lutSize;
  vec3 lutCoord = clamp(color.rgb, 0.0, 1.0) * scale + offset;
  vec3 graded = texture(u_lut, lutCoord).rgb;
  outColor = vec4(graded, color.a);
}`;

/**
 * Create a WebGL LUT pipeline attached to a canvas.
 * @param {HTMLCanvasElement} canvas
 * @returns {{ gl: WebGL2RenderingContext, uniforms: object, setLUTEnabled: function, loadLUTData: function, render: function, dispose: function } | null}
 */
export function createLUTPipeline(canvas) {
  const gl = canvas.getContext("webgl2", { premultipliedAlpha: false, alpha: false });
  if (!gl) return null;

  // Shaders
  function compileShader(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const info = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error("Shader compile error: " + info);
    }
    return shader;
  }

  const vs = compileShader(gl.VERTEX_SHADER, LUT_VERTEX_SHADER);
  const fs = compileShader(gl.FRAGMENT_SHADER, LUT_FRAGMENT_SHADER);
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error("Shader link error: " + gl.getProgramInfoLog(program));
  }
  gl.useProgram(program);

  // Geometry (fullscreen quad)
  const positions = new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]);
  const texCoords = new Float32Array([0, 1, 1, 1, 0, 0, 1, 0]);

  function setupBuffer(name, data, components) {
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, name);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, components, gl.FLOAT, false, 0, 0);
  }
  setupBuffer("a_position", positions, 2);
  setupBuffer("a_texCoord", texCoords, 2);

  // Video texture
  const videoTexture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, videoTexture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

  // LUT 3D texture
  const lutTexture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_3D, lutTexture);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);

  const uniforms = {
    video: gl.getUniformLocation(program, "u_video"),
    lut: gl.getUniformLocation(program, "u_lut"),
    lutSize: gl.getUniformLocation(program, "u_lutSize"),
    lutEnabled: gl.getUniformLocation(program, "u_lutEnabled"),
  };

  gl.uniform1i(uniforms.video, 0);
  gl.uniform1i(uniforms.lut, 1);

  let lutEnabled = false;
  const state = { gl, uniforms, lutTexture, videoTexture, program };

  return {
    gl,
    uniforms,
    setLUTEnabled(enabled) {
      lutEnabled = enabled;
    },
    loadLUTData(cubeData) {
      // Convert RGB float data to RGBA unsigned byte for broad GPU support
      const size = cubeData.size;
      const rgbaData = new Uint8Array(size * size * size * 4);
      for (let i = 0; i < size * size * size; i++) {
        rgbaData[i * 4]     = Math.round(Math.max(0, Math.min(1, cubeData.data[i * 3])) * 255);
        rgbaData[i * 4 + 1] = Math.round(Math.max(0, Math.min(1, cubeData.data[i * 3 + 1])) * 255);
        rgbaData[i * 4 + 2] = Math.round(Math.max(0, Math.min(1, cubeData.data[i * 3 + 2])) * 255);
        rgbaData[i * 4 + 3] = 255;
      }
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_3D, lutTexture);
      gl.texImage3D(
        gl.TEXTURE_3D, 0, gl.RGBA8,
        cubeData.size, cubeData.size, cubeData.size,
        0, gl.RGBA, gl.UNSIGNED_BYTE,
        rgbaData,
      );
      gl.uniform1f(uniforms.lutSize, cubeData.size);
      gl.uniform1i(uniforms.lutEnabled, 1);
      lutEnabled = true;
    },
    render(videoEl) {
      // Wait for video to have dimensions before capturing frames
      if (!videoEl || !videoEl.videoWidth || !videoEl.videoHeight) return;
      if (canvas.width !== videoEl.videoWidth || canvas.height !== videoEl.videoHeight) {
        canvas.width = videoEl.videoWidth;
        canvas.height = videoEl.videoHeight;
      }

      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);

      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, videoTexture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, videoEl);

      gl.uniform1i(uniforms.lutEnabled, lutEnabled ? 1 : 0);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    },
    dispose() {
      gl.deleteProgram(program);
      gl.deleteTexture(videoTexture);
      gl.deleteTexture(lutTexture);
    },
  };
}

// ── Timeline helpers ──────────────────────────────────────────

export function formatTimelineMs(tMs) {
  const totalSeconds = Math.floor(tMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function msToPercent(tMs, totalDurationMs) {
  if (!totalDurationMs) return 0;
  return (tMs / totalDurationMs) * 100;
}

export function percentToMs(percent, totalDurationMs) {
  return Math.max(0, (percent * totalDurationMs) / 100);
}

/**
 * Render a lane with colour blocks from time spans.
 * @param {HTMLElement} track - the .lane-track container
 * @param {Array} spans - [{start_ms, end_ms, colour, label, topicId?}]
 * @param {number} totalMs - total timeline duration
 */
export function renderLaneBlocks(track, spans, totalMs) {
  track.replaceChildren();
  if (!totalMs) return;
  for (const span of spans) {
    const block = document.createElement("div");
    block.className = "lane-block";
    block.style.left = msToPercent(span.start_ms, totalMs) + "%";
    block.style.width = msToPercent(span.end_ms - span.start_ms, totalMs) + "%";
    block.style.background = span.colour || "#808080";
    block.dataset.startMs = span.start_ms;
    block.dataset.endMs = span.end_ms;
    if (span.label) block.title = span.label;
    if (span.topicId) block.dataset.topicId = span.topicId;
    track.appendChild(block);
  }
}

/**
 * Render waveform bars from loudness data (downsampled to fit).
 */
export function renderWaveformBars(track, loudness, totalMs) {
  track.replaceChildren();
  if (!loudness || !totalMs) return;

  const hopMs = loudness.hop_ms || 20;
  const channels = loudness.channels || {};
  const trackWidth = track.clientWidth || 400;
  const maxBars = Math.min(trackWidth / 4, 500);

  // Merge all channels into max dB per hop for a combined waveform
  const dbPerHop = [];
  for (const chId of Object.keys(channels)) {
    const rms = channels[chId].rms_db || [];
    for (let i = 0; i < rms.length; i++) {
      if (i >= dbPerHop.length) dbPerHop.push(rms[i]);
      else dbPerHop[i] = Math.max(dbPerHop[i], rms[i]);
    }
  }

  if (!dbPerHop.length) return;

  // Downsample
  const step = Math.max(1, Math.floor(dbPerHop.length / maxBars));
  const noiseFloor = -60;

  for (let i = 0; i < dbPerHop.length; i += step) {
    let peak = -Infinity;
    for (let j = i; j < Math.min(i + step, dbPerHop.length); j++) {
      peak = Math.max(peak, dbPerHop[j]);
    }
    const normalized = Math.max(0, (peak - noiseFloor) / Math.abs(noiseFloor));
    const height = Math.round(normalized * 100);

    const bar = document.createElement("div");
    bar.className = "waveform-bar";
    const leftPct = (i * hopMs / totalMs) * 100;
    bar.style.left = leftPct + "%";
    bar.style.top = (100 - height) + "%";
    bar.style.height = height + "%";
    bar.style.width = Math.max(1, (step * hopMs / totalMs) * 100) + "%";
    track.appendChild(bar);
  }
}

function projectIdFromLocation(locationObj = window.location) {
  const params = new URLSearchParams(locationObj.search);
  const fromQuery = params.get("project_id");
  if (fromQuery) return fromQuery;
  const match = locationObj.pathname.match(/\/player\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function setStatus(elements, text) {
  if (elements.statusText) elements.statusText.textContent = text;
}

function setVideoSource(video, src, desiredTime) {
  if (!src) return;
  if (video.dataset.src !== src) {
    video.src = src;
    video.dataset.src = src;
  }
  if (Number.isFinite(desiredTime)) {
    try {
      video.currentTime = Math.max(0, desiredTime);
    } catch (_err) {
      // Browser may reject seeks before metadata is ready; the tick loop retries.
    }
  }
}

function makeAngleButton(angle, state, elements, render, angleLuts, angleById) {
  const button = document.createElement("button");
  button.type = "button";
  // LUT status dot
  const dot = document.createElement("span");
  dot.className = "angle-lut-dot";
  dot.style.display = "none";
  if (angleLuts && angleLuts[angle.id]) {
    dot.style.display = "inline-block";
    dot.style.background = "#8cc7ff";
    dot.title = `LUT: ${angleLuts[angle.id].title || angleLuts[angle.id].filename}`;
  }
  const label = angle.label || angle.role || angle.id;
  button.appendChild(dot);
  button.appendChild(document.createTextNode(" " + label));
  button.dataset.angleId = angle.id;
  button.addEventListener("click", () => {
    state.force(angle.id);
    setStatus(elements, `Manual override: ${label}`);
    render(true);
  });
  return button;
}

// ── Player processing interstitial ──────────────────────────

const PLAYER_STAGE_BADGES = {
  done: 'ok',
  running: 'warn',
  queued: 'neutral',
  error: 'err',
};

function showPlayerProcessing(doc, projectId, progress) {
  // Hide the main player shell, show the processing interstitial
  const shell = doc.getElementById('playerShell');
  if (shell) shell.style.display = 'none';

  const procView = doc.getElementById('playerProcessing');
  if (!procView) return;
  procView.hidden = false;

  function render(progress) {
    const summary = doc.getElementById('playerProcessingSummary');
    if (progress.ready || progress.status === 'ready') {
      summary.textContent = 'Your project is ready. Reloading player…';
      // Reload to show the player
      window.location.reload();
      return;
    }
    if (progress.status === 'error') {
      summary.textContent = 'Processing stopped with an error.';
    } else {
      const doneCount = progress.stages.filter((s) => s.status === 'done').length;
      const total = progress.stages.length;
      summary.textContent = `Processing in progress — ${doneCount} of ${total} stages complete.`;
    }

    const tableDiv = doc.getElementById('playerPipelineTable');
    const table = doc.createElement('table');
    table.className = 'table pipeline-status';
    table.innerHTML = '<thead><tr><th>Stage</th><th>State</th><th>Detail</th></tr></thead><tbody></tbody>';
    const tbody = table.querySelector('tbody');
    for (const stage of progress.stages) {
      const tr = doc.createElement('tr');
      const badge = PLAYER_STAGE_BADGES[stage.status] || 'neutral';
      const statusText = stage.status.charAt(0).toUpperCase() + stage.status.slice(1);
      const label = doc.createElement('td');
      label.innerHTML = `<b>${escapeHtml(stage.label)}</b>`;
      const stateTd = doc.createElement('td');
      stateTd.innerHTML = `<span class="badge ${badge}">${statusText}</span>`;
      const detail = doc.createElement('td');
      detail.className = 'stage-detail';
      if (stage.error) {
        detail.innerHTML = `<span class="processing-error" style="display:inline-block;margin:0;padding:4px 8px;font-size:11px">${escapeHtml(stage.error)}</span>`;
      } else {
        detail.textContent = stage.description || '';
      }
      tr.appendChild(label);
      tr.appendChild(stateTd);
      tr.appendChild(detail);
      tbody.appendChild(tr);
    }
    tableDiv.replaceChildren(table);

    const actions = doc.getElementById('playerProcessingActions');
    if (progress.status === 'error') {
      actions.innerHTML = '<a class="btn btn-ghost" href="/">Back to projects</a>';
    } else {
      actions.innerHTML = '';
    }
  }

  // Initial render
  render(progress);

  // Poll for updates
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/projects/${projectId}/progress`, { credentials: 'same-origin' });
      if (res.ok) {
        const updated = await res.json();
        render(updated);
        if (updated.ready || updated.status === 'ready') {
          clearInterval(interval);
        }
        if (updated.status === 'error') {
          clearInterval(interval);
        }
      }
    } catch (_err) { /* continue polling */ }
  }, 2000);
}

function escapeHtml(value) {
  return String(value ?? '').replace(
    /[&<>'"]/g,
    (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]),
  );
}

export async function bootPlayer(doc = document, locationObj = window.location) {
  const projectId = projectIdFromLocation(locationObj);
  if (!projectId) return;

  // ── Check project readiness ───────────────────────────────
  // If the project isn't ready, show the processing interstitial
  // and poll progress until it is.
  try {
    const progressRes = await fetch(
      `/projects/${projectId}/progress`,
      { credentials: "same-origin" },
    );
    if (progressRes.ok) {
      const progress = await progressRes.json();
      if (!progress.ready && progress.status !== "ready") {
        // Show processing interstitial
        showPlayerProcessing(doc, projectId, progress);
        return;  // Don't initialize the player
      }
    }
    // If progress check fails (404/401), continue to boot player
    // — player-state will give a more specific error.
  } catch (_err) {
    // Network error; continue to boot (player-state handles it)
  }

  const elements = {
    audio: doc.getElementById("programAudio"),
    videoA: doc.getElementById("videoA"),
    videoB: doc.getElementById("videoB"),
    angleButtons: doc.getElementById("angleButtons"),
    qualitySelect: doc.getElementById("qualitySelect"),
    backToAutoButton: doc.getElementById("backToAutoButton"),
    statusText: doc.getElementById("statusText"),
    shotReason: doc.getElementById("shotReason"),
    shotReasonLabel: doc.getElementById("shotReasonLabel"),
    shotReasonDetail: doc.getElementById("shotReasonDetail"),
    analysisSource: doc.getElementById("analysisSource"),
    analysisMapping: doc.getElementById("analysisMapping"),
    analysisSafety: doc.getElementById("analysisSafety"),
    // Timeline
    cdlLane: doc.getElementById("cdlLane"),
    projectedLane: doc.getElementById("projectedLane"),
    topicLane: doc.getElementById("topicLane"),
    waveformTrack: doc.getElementById("waveformTrack"),
    loudnessLane: doc.getElementById("loudnessLane"),
    scrubber: doc.getElementById("timelineScrubber"),
    scrubberPlayhead: doc.getElementById("scrubberPlayhead"),
    timelineTime: doc.getElementById("timelineTime"),
    angleDot: doc.getElementById("angleDot"),
    angleLabel: doc.getElementById("angleLabel"),
    // LUT
    lutCanvas: doc.getElementById("lutCanvas"),
    lutSelect: doc.getElementById("lutSelect"),
    lutToggle: doc.getElementById("lutToggle"),
    // Notes
    notesLane: doc.getElementById("notesLane"),
    noteForm: doc.getElementById("noteForm"),
    noteBody: doc.getElementById("noteBody"),
    noteKind: doc.getElementById("noteKind"),
    noteSubmit: doc.getElementById("noteSubmit"),
    noteList: doc.getElementById("noteList"),
  };

  // ── Load player-state ────────────────────────────────────
  const response = await fetch(`/projects/${projectId}/player-state`, { credentials: "same-origin" });
  if (!response.ok) {
    setStatus(elements, `Player state failed: ${response.status}`);
    return;
  }

  const statePayload = await response.json();
  try {
    validateContiguousClips(statePayload.cut?.clips || []);
  } catch (error) {
    setStatus(elements, `Timeline error: ${error.message}`);
    return;
  }
  try {
    statePayload.projected_activity = normalizeProjectedActivity(statePayload.projected_activity);
  } catch (error) {
    setStatus(elements, `Timeline error: ${error.message}`);
    if (elements.projectedLane) elements.projectedLane.replaceChildren();
    return;
  }
  const angleById = new Map(statePayload.angles.map((angle) => [angle.id, angle]));
  const clips = statePayload.cut.clips || [];
  const override = createManualOverrideState();
  const frameSeconds = frameDurationSeconds(
    statePayload.project.fps_num,
    statePayload.project.fps_den,
  );
  let visible = elements.videoA;
  let hidden = elements.videoB;
  let currentAngleId = null;

  const initialAnalysis = analysisStatusDisplay(statePayload.analysis);
  if (elements.analysisSource) elements.analysisSource.textContent = initialAnalysis.source;
  if (elements.analysisMapping) elements.analysisMapping.textContent = initialAnalysis.mapping;
  if (elements.analysisSafety) {
    elements.analysisSafety.textContent = initialAnalysis.safety;
    elements.analysisSafety.dataset.tone = initialAnalysis.tone;
  }

  elements.audio.src = statePayload.audio.program_url;
  elements.audio.dataset.projectId = projectId;
  elements.qualitySelect.value = statePayload.quality_default || "proxy";

  // ── LUT pipeline with per-angle binding ──────────────────
  let lutPipeline = null;
  /** @type {Map<string, {title: string, data: Float32Array, size: number}>} */
  const lutForAngle = new Map();
  let defaultLutData = null;
  let hasAnyLut = false;

  if (elements.lutCanvas) {
    try {
      lutPipeline = createLUTPipeline(elements.lutCanvas);
    } catch (err) {
      console.warn("LUT pipeline unavailable:", err.message);
      lutPipeline = null;
      // Hide LUT elements gracefully
      if (elements.lutCanvas) elements.lutCanvas.style.display = "none";
      if (elements.lutToggle) elements.lutToggle.style.display = "none";
    }

    // Preload per-angle LUTs from state
    if (lutPipeline && statePayload.angle_luts) {
      for (const [angleId, lutInfo] of Object.entries(statePayload.angle_luts)) {
        try {
          const lutRes = await fetch(lutInfo.url, { credentials: "same-origin" });
          if (lutRes.ok) {
            const cubeData = parseCubeLUT(await lutRes.text());
            lutForAngle.set(angleId, cubeData);
            hasAnyLut = true;
          }
        } catch (_err) { /* skip unavailable */ }
      }
    }

    // Load default LUT as fallback
    if (lutPipeline && statePayload.active_lut) {
      try {
        const lutRes = await fetch(statePayload.active_lut.url, { credentials: "same-origin" });
        if (lutRes.ok) {
          defaultLutData = parseCubeLUT(await lutRes.text());
          hasAnyLut = true;
        }
      } catch (_err) { /* skip */ }
    }
  }

  /** Bind the LUT for a specific angle, or default, or none */
  function bindAngleLUT(angleId) {
    if (!lutPipeline) return;
    const cubeData = lutForAngle.get(angleId) || defaultLutData;
    if (cubeData) {
      lutPipeline.loadLUTData(cubeData);
      lutPipeline.setLUTEnabled(true);
      // Show LUT canvas on top — don't hide videos (decoders need them visible)
      if (elements.lutCanvas) elements.lutCanvas.classList.add("is-visible");
      if (elements.lutToggle) elements.lutToggle.textContent = "LUT ON";
    } else {
      lutPipeline.setLUTEnabled(false);
      // Hide canvas, LUT off
      if (elements.lutCanvas) elements.lutCanvas.classList.remove("is-visible");
      if (elements.lutToggle) elements.lutToggle.textContent = "LUT OFF";
    }
  }

  // ── LUT toggle button ────────────────────────────────────
  if (elements.lutToggle && lutPipeline) {
    elements.lutToggle.addEventListener("click", () => {
      const wasEnabled = elements.lutToggle.textContent === "LUT ON";
      if (wasEnabled) {
        lutPipeline.setLUTEnabled(false);
        elements.lutToggle.textContent = "LUT OFF";
        if (elements.lutCanvas) elements.lutCanvas.classList.remove("is-visible");
      } else {
        lutPipeline.setLUTEnabled(true);
        elements.lutToggle.textContent = "LUT ON";
        if (elements.lutCanvas) elements.lutCanvas.classList.add("is-visible");
        // Re-bind current angle's LUT
        bindAngleLUT(currentAngleId);
      }
    });
    if (hasAnyLut) {
      elements.lutToggle.style.display = "";
    }
  }

  // ── Load timeline-state ──────────────────────────────────
  let timelineState = null;
  renderProjectedActivity(elements, statePayload.projected_activity);
  try {
    const tlRes = await fetch(`/projects/${projectId}/timeline-state`, { credentials: "same-origin" });
    if (tlRes.ok) {
      timelineState = await tlRes.json();
      renderTimeline(elements, timelineState, clips, angleById);
      // Render notes from timeline state
      if (timelineState.notes) {
        renderNotes(elements, timelineState, clips);
      }
    }
  } catch (_err) {
    // Timeline is optional; player still works without it.
  }

  // Also reload notes via dedicated endpoint for fresh data
  loadNotesList(elements, projectId);

  // Load LUTs
  loadLuts(projectId, elements, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId);

  // LUT file upload handler
  const lutFileInput = document.getElementById("lutFile");
  const lutUploadStatus = document.getElementById("lutUploadStatus");
  if (lutFileInput) {
    lutFileInput.addEventListener("change", async () => {
      const file = lutFileInput.files[0];
      if (!file) return;
      lutUploadStatus.textContent = "Uploading…";
      const formData = new FormData();
      formData.append("file", file);
      try {
        const res = await fetch(`/projects/${projectId}/luts`, {
          method: "POST",
          credentials: "same-origin",
          body: formData,
        });
        if (res.ok) {
          lutUploadStatus.textContent = `Uploaded: ${file.name}`;
          lutFileInput.value = "";
          await loadLuts(projectId, elements, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId);
          if (lutPipeline && statePayload.active_lut) {
            bindAngleLUT(currentAngleId);
          }
        } else {
          const err = await res.json();
          lutUploadStatus.textContent = `Failed: ${err.detail || res.status}`;
        }
      } catch (_err) {
        lutUploadStatus.textContent = "Upload failed";
      }
    });
  }

  // Load cut parameters
  loadCutParams(projectId, elements, statePayload, clips, angleById, override, render, frameSeconds, () => {
    if (timelineState) renderTimeline(elements, timelineState, clips, angleById);
  });

  // ── Note form submission ─────────────────────────────────
  if (elements.noteForm) {
    elements.noteForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = elements.noteBody.value.trim();
      if (!body) return;
      const kind = elements.noteKind.value;
      const tMs = timelineMsFromAudio(elements.audio.currentTime);

      try {
        const res = await fetch(`/projects/${projectId}/notes`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ t_ms: tMs, body, kind }),
        });
        if (res.ok) {
          elements.noteBody.value = "";
          loadNotesList(elements, projectId);
        }
      } catch (_err) { /* ignore */ }
    });
  }

  function updateAngleButtons() {
    for (const button of elements.angleButtons.querySelectorAll("button")) {
      button.classList.toggle("is-active", button.dataset.angleId === override.manualAngleId);
    }
  }

  function swapVideos() {
    visible.classList.remove("is-visible");
    hidden.classList.add("is-visible");
    const oldVisible = visible;
    visible = hidden;
    hidden = oldVisible;
  }

  // LUT frame render loop
  let lutFrameId = null;
  function startLUTFrames() {
    if (!lutPipeline) return;
    function frame() {
      if (lutPipeline && elements.lutCanvas.classList.contains("is-visible")) {
        lutPipeline.render(visible);
      }
      lutFrameId = requestAnimationFrame(frame);
    }
    lutFrameId = requestAnimationFrame(frame);
  }
  if (lutPipeline) startLUTFrames();

  // ── Manual sync nudge controls ────────────────────────────────
  let baseSyncOffsets = {};
  let syncOffsets = {};
  for (const angle of statePayload.angles) {
    baseSyncOffsets[angle.id] = angle.sync_offset_ms || 0;
    syncOffsets[angle.id] = 0;
  }

  const syncNudge = doc.getElementById("syncNudge");
  const syncMinus = doc.getElementById("syncMinus");
  const syncPlus = doc.getElementById("syncPlus");
  const syncSave = doc.getElementById("syncSave");
  const syncDisplay = doc.getElementById("syncOffsetDisplay");

  function updateSyncDisplay() {
    const currentAngle = override.resolve(currentAngleId);
    if (!currentAngle) return;
    const offset = syncOffsets[currentAngle] || 0;
    if (syncDisplay) syncDisplay.textContent = `${offset > 0 ? "+" : ""}${offset}ms`;
  }

  if (syncNudge) syncNudge.style.display = "flex";

  if (syncMinus) {
    syncMinus.addEventListener("click", () => {
      const currentAngle = override.resolve(currentAngleId);
      if (!currentAngle) return;
      syncOffsets[currentAngle] = (syncOffsets[currentAngle] || 0) - 100;
      updateSyncDisplay();
      render(true);
    });
  }

  if (syncPlus) {
    syncPlus.addEventListener("click", () => {
      const currentAngle = override.resolve(currentAngleId);
      if (!currentAngle) return;
      syncOffsets[currentAngle] = (syncOffsets[currentAngle] || 0) + 100;
      updateSyncDisplay();
      render(true);
    });
  }

  if (syncSave) {
    syncSave.addEventListener("click", async () => {
      syncSave.disabled = true;
      syncSave.textContent = "Saving…";
      try {
        const mappings = Object.entries(syncOffsets).map(([aid, ms]) => ({
          source_angle_id: aid,
          offset_ms: (baseSyncOffsets[aid] || 0) + (ms || 0),
        }));
        await fetch(`/projects/${projectId}/sync-nudge`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ nudges: mappings }),
        });
        syncSave.textContent = "Saved";
        setTimeout(() => { syncSave.textContent = "Save"; syncSave.disabled = false; }, 1500);
      } catch (_err) {
        syncSave.textContent = "Failed";
        syncSave.disabled = false;
      }
    });
  }

  let pendingSwap = false;
  let pendingAngleId = null;

  // Event-driven swap: when hidden video has loaded enough data, perform the swap
  function onHiddenReady() {
    if (!pendingSwap) return;
    if (hidden.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
    hidden.removeEventListener("loadeddata", onHiddenReady);
    hidden.removeEventListener("canplay", onHiddenReady);
    swapVideos();
    currentAngleId = pendingAngleId;
    bindAngleLUT(pendingAngleId);
    updateSyncDisplay();
    pendingSwap = false;
    pendingAngleId = null;
    const angle = angleById.get(currentAngleId);
    setStatus(elements, "Playing " + (angle?.label || currentAngleId));
  }

  function render(forceSwap = false) {
    const tMs = timelineMsFromAudio(elements.audio.currentTime);
    const autoClip = findClipAtTime(clips, tMs);
    const manualAngleId = override.manualAngleId;
    const angleId = override.resolve(autoClip?.angle_id);
    const angle = angleById.get(angleId);
    const reasonDisplay = shotReasonDisplay(autoClip, Boolean(manualAngleId));
    const analysisDisplay = analysisStatusDisplay(statePayload.analysis, autoClip);
    if (elements.analysisSafety) {
      elements.analysisSafety.textContent = analysisDisplay.safety;
      elements.analysisSafety.dataset.tone = analysisDisplay.tone;
    }
    if (elements.shotReason) elements.shotReason.dataset.tone = reasonDisplay.tone;
    if (elements.shotReasonLabel) elements.shotReasonLabel.textContent = reasonDisplay.label;
    if (elements.shotReasonDetail) elements.shotReasonDetail.textContent = reasonDisplay.detail;
    const manualNudgeMs = syncOffsets[angleId] || 0;
    let desired = manualAngleId
      ? playbackVideoTimeForAngle(angle, tMs, manualNudgeMs)
      : playbackVideoTimeForClip(autoClip, tMs, manualNudgeMs);
    const mediaUrl = chooseMediaUrl(angle, elements.qualitySelect.value);

    if (!angle || !mediaUrl) {
      setStatus(elements, "No playable angle for current cut");
      return;
    }

    const switched = currentAngleId !== angleId;
    const urlChanged = visible.dataset.src !== mediaUrl && !pendingSwap;

    // On first load, put the source on the visible video so it shows immediately
    if (currentAngleId === null) {
      setVideoSource(visible, mediaUrl, desired);
      currentAngleId = angleId;
    } else if (urlChanged && !switched) {
      // Quality change or source URL update for same angle — reload visible
      setVideoSource(visible, mediaUrl, desired);
    } else if (switched) {
      // Angle changed — load into hidden, wait for loadeddata event, then swap
      // Clean up any stale listeners from a previous pending swap
      hidden.removeEventListener("loadeddata", onHiddenReady);
      hidden.removeEventListener("canplay", onHiddenReady);
      setVideoSource(hidden, mediaUrl, desired);
      pendingSwap = true;
      pendingAngleId = angleId;
      hidden.addEventListener("loadeddata", onHiddenReady);
      hidden.addEventListener("canplay", onHiddenReady);
      setStatus(elements, "Switching angle\u2026");
    } else if (pendingSwap) {
      // Still waiting for hidden to buffer — onHiddenReady will handle it
    } else if (needsDriftCorrection(visible.currentTime, desired, frameSeconds)) {
      setVideoSource(visible, mediaUrl, desired);
    }

    // Pre-load next clip into hidden only when stable (no switch pending)
    if (!pendingSwap && !manualAngleId) {
      const nextClip = findNextClip(clips, tMs);
      if (nextClip) {
        const nextAngle = angleById.get(nextClip.angle_id);
        const nextUrl = chooseMediaUrl(nextAngle, elements.qualitySelect.value);
        if (nextUrl) setVideoSource(hidden, nextUrl, playbackVideoTimeForClip(nextClip, nextClip.timeline_in_ms, syncOffsets[nextClip.angle_id] || 0));
      }
    }

    if (!elements.audio.paused && visible.paused) {
      visible.play().catch(() => undefined);
    }
    updateAngleButtons();
    updateCurrentAngleLabel(elements, angle, timelineState);
    updateTimelinePlayhead(elements, tMs, timelineState);
    updateSyncDisplay();
    setStatus(elements, override.manualAngleId ? "Manual override active" : "Auto cut playback");
  }

  elements.angleButtons.replaceChildren(
    ...statePayload.angles.map((angle) => makeAngleButton(angle, override, elements, render, statePayload.angle_luts)),
  );
  elements.backToAutoButton.addEventListener("click", () => {
    override.clear();
    render(true);
  });
  elements.qualitySelect.addEventListener("change", () => render(true));
  elements.audio.addEventListener("play", () => visible.play().catch(() => undefined));
  elements.audio.addEventListener("pause", () => visible.pause());
  elements.audio.addEventListener("seeking", () => render(true));
  elements.audio.addEventListener("timeupdate", () => render(false));

  // ── Timeline seek handlers ───────────────────────────────
  if (timelineState && elements.scrubber) {
    setupTimelineSeek(elements, timelineState);
  }

  render(true);
}

// ── Timeline rendering ──────────────────────────────────────

function renderTimeline(elements, timelineState, clips, angleById) {
  const totalMs = timelineState.total_duration_ms;
  if (!totalMs) return;

  // CDL lane — colour blocks per clip
  if (elements.cdlLane) {
    const cdlSpans = clips.map((clip) => ({
      start_ms: clip.timeline_in_ms,
      end_ms: clip.timeline_in_ms + clip.dur_ms,
      colour: timelineState.angles?.[clip.angle_id]?.colour || "#808080",
      label: `${timelineState.angles?.[clip.angle_id]?.label || clip.angle_id} · ${shotReasonDisplay(clip).label}`,
    }));
    renderLaneBlocks(elements.cdlLane, cdlSpans, totalMs);
  }

  // Topic lane — colour blocks from summary topics
  if (elements.topicLane && timelineState.summary?.topics) {
    const topicSpans = [];
    for (const topic of timelineState.summary.topics) {
      for (const span of topic.spans || []) {
        topicSpans.push({
          start_ms: span.start_ms,
          end_ms: span.end_ms,
          colour: topic.colour,
          label: topic.label,
          topicId: topic.label,
        });
      }
    }
    topicSpans.sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms || String(a.label).localeCompare(String(b.label)));
    renderLaneBlocks(elements.topicLane, topicSpans, totalMs);
  }

  // Loudness lane
  if (timelineState.loudness && elements.loudnessLane && elements.waveformTrack) {
    elements.loudnessLane.classList.add("is-visible");
    renderWaveformBars(elements.waveformTrack, timelineState.loudness, totalMs);
  }

  // Time display
  if (elements.timelineTime) {
    elements.timelineTime.textContent = `0:00 / ${formatTimelineMs(totalMs)}`;
  }
}

function renderProjectedActivity(elements, projected) {
  if (!elements.projectedLane) return;
  elements.projectedLane.replaceChildren();
  if (!projected) return;
  try {
    validateMasterTimeSpans(projected.timeline, projected.total_duration_ms);
  } catch (error) {
    setStatus(elements, `Timeline error: ${error.message}`);
    return;
  }
  const spans = projected.timeline.map((segment) => {
    const display = activityStatusDisplay(segment);
    return {
      start_ms: segment.start_ms,
      end_ms: segment.end_ms,
      colour: `var(--activity-${display.tone})`,
      label: `${display.label} · ${segment.start_ms}–${segment.end_ms} ms master time`,
      status: display.status,
    };
  });
  renderLaneBlocks(elements.projectedLane, spans, projected.total_duration_ms);
  for (const [index, block] of [...elements.projectedLane.children].entries()) {
    const span = spans[index];
    block.dataset.status = span.status;
    block.setAttribute("aria-label", span.label);
    block.setAttribute("role", "img");
  }
}

function updateCurrentAngleLabel(elements, angle, timelineState) {
  const colour = timelineState?.angles?.[angle?.id]?.colour || angle?.colour || "#808080";
  const label = angle?.label || angle?.role || "—";
  if (elements.angleDot) elements.angleDot.style.background = colour;
  if (elements.angleLabel) elements.angleLabel.textContent = label;
}

function updateTimelinePlayhead(elements, tMs, timelineState) {
  if (!elements.scrubberPlayhead || !timelineState?.total_duration_ms) return;
  const pct = msToPercent(tMs, timelineState.total_duration_ms);
  elements.scrubberPlayhead.style.left = Math.min(100, Math.max(0, pct)) + "%";
}

// ── Timeline seek ──────────────────────────────────────────

function setupTimelineSeek(elements, timelineState) {
  const totalMs = timelineState.total_duration_ms;
  if (!totalMs || !elements.scrubber) return;

  function seekFromEvent(e) {
    const rect = elements.scrubber.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    const seekMs = percentToMs(pct, totalMs);
    elements.audio.currentTime = seekMs / 1000;
    elements.scrubber.setAttribute("aria-valuenow", String(Math.round(pct * 100)));
  }

  elements.scrubber.addEventListener("click", seekFromEvent);
  elements.scrubber.addEventListener("mousedown", (e) => {
    seekFromEvent(e);
    const onMove = (ev) => seekFromEvent(ev);
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });

  // Click on lane tracks also seeks
  for (const track of [elements.cdlLane, elements.topicLane, elements.notesLane]) {
    if (!track) continue;
    track.addEventListener("click", (e) => {
      // If clicking a note marker, seek to that specific time
      if (e.target.classList.contains("note-marker")) {
        const tMs = parseInt(e.target.dataset.tMs, 10);
        if (!isNaN(tMs)) {
          elements.audio.currentTime = tMs / 1000;
          return;
        }
      }
      const rect = track.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      const seekMs = percentToMs(pct, totalMs);
      elements.audio.currentTime = seekMs / 1000;
    });
  }
}

// ── Notes rendering ────────────────────────────────────────

function renderNotes(elements, timelineState, clips) {
  const totalMs = timelineState.total_duration_ms;
  if (!totalMs || !elements.notesLane) return;

  const notes = timelineState.notes || [];
  elements.notesLane.replaceChildren();

  for (const note of notes) {
    const marker = document.createElement("div");
    marker.className = "note-marker";
    marker.dataset.kind = note.kind;
    marker.dataset.tMs = note.t_ms;
    marker.style.left = msToPercent(note.t_ms, totalMs) + "%";
    marker.title = `${note.author}: ${note.body}`;
    elements.notesLane.appendChild(marker);
  }
}

async function loadNotesList(elements, projectId) {
  if (!elements.noteList) return;
  try {
    const res = await fetch(`/projects/${projectId}/notes`, { credentials: "same-origin" });
    if (!res.ok) return;
    const data = await res.json();
    renderNoteList(elements, data.notes || []);
  } catch (_err) { /* ignore */ }
}

function renderNoteList(elements, notes) {
  elements.noteList.replaceChildren();
  for (const note of notes) {
    const li = document.createElement("li");
    li.className = "note-item";
    li.dataset.kind = note.kind;

    const header = document.createElement("div");
    header.className = "note-item-header";

    const author = document.createElement("span");
    author.className = "note-item-author";
    author.textContent = note.author;
    header.appendChild(author);

    const kind = document.createElement("span");
    kind.className = "note-item-kind";
    kind.textContent = note.kind === "cut_suggestion" ? "cut" : "note";
    header.appendChild(kind);

    const time = document.createElement("span");
    time.className = "note-item-time";
    time.textContent = formatTimelineMs(note.t_ms);
    time.addEventListener("click", () => {
      elements.audio.currentTime = note.t_ms / 1000;
    });
    header.appendChild(time);

    const del = document.createElement("button");
    del.className = "note-item-delete";
    del.textContent = "×";
    del.addEventListener("click", async () => {
      try {
        const res = await fetch(`/projects/${elements.audio.dataset.projectId || ""}/notes/${note.id}`,
          { method: "DELETE", credentials: "same-origin" });
        if (res.ok) {
          loadNotesList(elements, elements.audio.dataset.projectId);
        }
      } catch (_err) { /* ignore */ }
    });
    header.appendChild(del);

    li.appendChild(header);

    const body = document.createElement("div");
    body.className = "note-item-body";
    body.textContent = note.body;  // textContent = XSS-safe
    li.appendChild(body);

    elements.noteList.appendChild(li);
  }
}

// ── LUT Management ────────────────────────────────────────

async function loadLuts(projectId, elements, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId) {
  try {
    const res = await fetch(`/projects/${projectId}/luts`, { credentials: "same-origin" });
    if (!res.ok) return;
    const data = await res.json();
    renderLutList(elements, data);
    renderDefaultLut(elements, data, projectId, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId);
    renderAngleLutAssignments(elements, data, projectId, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId);
  } catch (_err) { /* ignore */ }
}

function renderLutList(elements, data) {
  const list = document.getElementById("lutList");
  if (!list) return;
  list.replaceChildren();
  for (const lut of data.luts || []) {
    const item = document.createElement("div");
    item.className = "lut-item";
    item.dataset.filename = lut.filename;
    item.innerHTML = `<span class="lut-title">${escapeHtml(lut.title || lut.filename)}</span><span class="lut-filename">${escapeHtml(lut.filename)}</span>`;
    list.appendChild(item);
  }
  updateDefaultLutSelect(elements, data);
}

function updateDefaultLutSelect(elements, data) {
  const select = document.getElementById("defaultLutSelect");
  const activateBtn = document.getElementById("activateDefaultLut");
  const deactivateBtn = document.getElementById("deactivateDefaultLut");
  if (!select) return;
  
  const currentValue = select.value;
  select.replaceChildren();
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "— Select a LUT —";
  select.appendChild(empty);
  
  for (const lut of data.luts || []) {
    const opt = document.createElement("option");
    opt.value = lut.filename;
    opt.textContent = lut.title || lut.filename;
    select.appendChild(opt);
  }
  
  select.value = currentValue;
  
  const hasLuts = (data.luts || []).length > 0;
  select.disabled = !hasLuts;
  if (activateBtn) activateBtn.disabled = !hasLuts;
  if (deactivateBtn) deactivateBtn.disabled = !data.default;
  
  const display = document.getElementById("defaultLutDisplay");
  if (display) {
    display.textContent = data.default || "None";
  }
}

function renderDefaultLut(elements, data, projectId, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId) {
  const display = document.getElementById("defaultLutDisplay");
  const select = document.getElementById("defaultLutSelect");
  const activateBtn = document.getElementById("activateDefaultLut");
  const deactivateBtn = document.getElementById("deactivateDefaultLut");
  
  if (display) display.textContent = data.default || "None";
  updateDefaultLutSelect(elements, data);
  
  if (activateBtn) {
    activateBtn.onclick = async () => {
      const filename = select.value;
      if (!filename) return;
      activateBtn.disabled = true;
      activateBtn.textContent = "Activating…";
      try {
        await fetch(`/projects/${projectId}/luts/activate`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename }),
        });
        // Load the new default LUT data
        const lutRes = await fetch(`/projects/${projectId}/media/lut/${filename}`, { credentials: "same-origin" });
        if (lutRes.ok && lutPipeline) {
          const text = await lutRes.text();
          const cubeData = parseCubeLUT(text);
          lutPipeline.loadLUTData(cubeData);
          lutPipeline.setLUTEnabled(true);
          // Show LUT canvas on top of video
          if (elements.lutCanvas) elements.lutCanvas.classList.add("is-visible");
          if (elements.lutToggle) {
            elements.lutToggle.textContent = "LUT ON";
            elements.lutToggle.style.display = "";
          }
        }
        await loadLuts(projectId, elements, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId);
      } catch (err) {
        activateBtn.textContent = "Activate (error)";
        console.error("LUT activate failed:", err);
      } finally {
        activateBtn.disabled = false;
        if (activateBtn.textContent === "Activating…") {
          activateBtn.textContent = "Activate";
        }
      }
    };
  }
  
  if (deactivateBtn) {
    deactivateBtn.onclick = async () => {
      deactivateBtn.disabled = true;
      deactivateBtn.textContent = "Deactivating…";
      try {
        await fetch(`/projects/${projectId}/luts/deactivate`, {
          method: "POST",
          credentials: "same-origin",
        });
        await loadLuts(projectId, elements, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId);
        if (lutPipeline) {
          bindAngleLUT(currentAngleId);
        }
      } catch (_err) { /* ignore */ }
    };
  }
}

function renderAngleLutAssignments(elements, data, projectId, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId) {
  const container = document.getElementById("angleLutAssignments");
  if (!container) return;
  container.replaceChildren();
  
  const angleLuts = data.angle_luts || {};
  
  for (const angle of statePayload.angles) {
    const div = document.createElement("div");
    div.className = "angle-lut-assignment";
    
    const assignedFilename = angleLuts[angle.id];
    const assignedLut = (data.luts || []).find(l => l.filename === assignedFilename);
    
    const nameSpan = document.createElement("span");
    nameSpan.className = "angle-name";
    nameSpan.textContent = angle.label || angle.role || angle.id;
    nameSpan.style.color = angle.colour || "#808080";
    
    const badge = document.createElement("span");
    badge.className = "lut-badge";
    if (assignedLut) {
      badge.style.background = "#8cc7ff";
      badge.title = `Assigned: ${assignedLut.title || assignedLut.filename}`;
    } else {
      badge.style.background = "var(--line)";
      badge.title = "No LUT assigned";
    }
    
    const select = document.createElement("select");
    select.dataset.angleId = angle.id;
    const emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = "— No LUT —";
    select.appendChild(emptyOpt);
    
    for (const lut of data.luts || []) {
      const opt = document.createElement("option");
      opt.value = lut.filename;
      opt.textContent = lut.title || lut.filename;
      if (lut.filename === assignedFilename) opt.selected = true;
      select.appendChild(opt);
    }
    
    const assignBtn = document.createElement("button");
    assignBtn.className = "assign-btn primary btn-sm";
    assignBtn.textContent = assignedFilename ? "Update" : "Assign";
    assignBtn.addEventListener("click", async () => {
      const filename = select.value;
      assignBtn.disabled = true;
      assignBtn.textContent = "Saving…";
      try {
        if (filename) {
          await fetch(`/projects/${projectId}/luts/assign`, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ angle_id: angle.id, filename }),
          });
        } else {
          await fetch(`/projects/${projectId}/luts/unassign`, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ angle_id: angle.id }),
          });
        }
        // Reload LUT for this angle
        if (filename) {
          const lutRes = await fetch(`/projects/${projectId}/media/lut/${filename}`, { credentials: "same-origin" });
          if (lutRes.ok) {
            const cubeData = parseCubeLUT(await lutRes.text());
            lutForAngle.set(angle.id, cubeData);
          }
        } else {
          lutForAngle.delete(angle.id);
        }
        await loadLuts(projectId, elements, statePayload, angleById, lutPipeline, lutForAngle, defaultLutData, hasAnyLut, currentAngleId);
        if (lutPipeline) bindAngleLUT(currentAngleId);
      } catch (_err) { /* ignore */ }
    });
    
    div.appendChild(nameSpan);
    div.appendChild(badge);
    div.appendChild(select);
    div.appendChild(assignBtn);
    container.appendChild(div);
  }
}

// ── Cut Parameters ────────────────────────────────────────

function loadCutParams(projectId, elements, statePayload, clips, angleById, override, render, frameSeconds, refreshTimeline = null) {
  const overlapSelect = document.getElementById("cutOverlapToWide");
  const minShotInput = document.getElementById("cutMinShotMs");
  const leadInInput = document.getElementById("cutLeadInMs");
  const tailInput = document.getElementById("cutTailMs");
  const silenceSelect = document.getElementById("cutSilenceBehaviour");
  const wideIntervalInput = document.getElementById("cutWideIntervalMs");
  const overlapMinInput = document.getElementById("cutOverlapMinMs");
  const interjectInput = document.getElementById("cutInterjectMaxMs");
  const directPresetBtn = document.getElementById("cutPresetDirect");
  const steadyPresetBtn = document.getElementById("cutPresetSteady");
  const looserPresetBtn = document.getElementById("cutPresetLooser");
  const regenBtn = document.getElementById("regenerateCutBtn");
  const statusEl = document.getElementById("cutRegenStatus");

  function applyPreset(params) {
    if (overlapSelect) overlapSelect.value = params.overlap_to_wide !== false ? "true" : "false";
    if (minShotInput) minShotInput.value = params.min_shot_ms ?? 250;
    if (leadInInput) leadInInput.value = params.lead_in_ms ?? 0;
    if (tailInput) tailInput.value = params.tail_ms ?? 0;
    if (silenceSelect) silenceSelect.value = params.silence_behaviour || "wide";
    if (wideIntervalInput) wideIntervalInput.value = params.wide_interval_ms ?? 0;
    if (overlapMinInput) overlapMinInput.value = params.overlap_min_ms ?? 900;
    if (interjectInput) interjectInput.value = params.interject_max_ms ?? 1200;
  }

  // Load current params from player-state; do not regenerate just to populate controls.
  applyPreset(statePayload.cut?.params || {});

  if (directPresetBtn) {
    directPresetBtn.addEventListener("click", () => applyPreset({
      overlap_to_wide: true,
      min_shot_ms: 250,
      lead_in_ms: 0,
      tail_ms: 0,
      silence_behaviour: "wide",
      wide_interval_ms: 0,
      overlap_min_ms: 0,
      interject_max_ms: 0,
      dominance_db: 0,
      exchange_min_turns: 0,
    }));
  }

  if (looserPresetBtn) {
    looserPresetBtn.addEventListener("click", () => applyPreset({
      overlap_to_wide: true,
      min_shot_ms: 800,
      lead_in_ms: 80,
      tail_ms: 150,
      silence_behaviour: "wide",
      wide_interval_ms: 45000,
      overlap_min_ms: 1200,
      interject_max_ms: 1500,
    }));
  }

  if (steadyPresetBtn) {
    steadyPresetBtn.addEventListener("click", () => applyPreset({
      overlap_to_wide: true,
      min_shot_ms: 250,
      lead_in_ms: 0,
      tail_ms: 0,
      silence_behaviour: "wide",
      wide_interval_ms: 0,
      overlap_min_ms: 900,
      interject_max_ms: 1200,
    }));
  }

  if (regenBtn) {
    regenBtn.addEventListener("click", async () => {
      regenBtn.disabled = true;
      regenBtn.textContent = "Regenerating…";
      statusEl.textContent = "";
      try {
        const params = {
          overlap_to_wide: overlapSelect.value === "true",
          min_shot_ms: parseInt(minShotInput.value, 10) || 250,
          lead_in_ms: parseInt(leadInInput.value, 10) || 0,
          tail_ms: parseInt(tailInput.value, 10) || 0,
          silence_behaviour: silenceSelect.value || "wide",
          wide_interval_ms: parseInt(wideIntervalInput.value, 10) || 0,
          overlap_min_ms: overlapMinInput ? (parseInt(overlapMinInput.value, 10) || 0) : 900,
          interject_max_ms: interjectInput ? (parseInt(interjectInput.value, 10) || 0) : 1200,
        };
        const res = await fetch(`/projects/${projectId}/cut`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ params }),
        });
        if (res.ok) {
          const newCut = await res.json();
          // Do not replace the displayed/persisted selection with a malformed
          // or gapped candidate. The authoritative current cut remains visible
          // and the failure is explicit in the controls below.
          validateContiguousClips(newCut.clips);
          // Replace clips with new ones
          clips.length = 0;
          clips.push(...newCut.clips);
          if (statePayload.cut) statePayload.cut.params = params;
          if (refreshTimeline) refreshTimeline();
          render(true);
          statusEl.textContent = "Cut regenerated";
          statusEl.style.color = "var(--ok)";
        } else {
          const err = await res.json();
          statusEl.textContent = `Failed: ${err.detail || res.status}`;
          statusEl.style.color = "var(--err)";
        }
      } catch (_err) {
        statusEl.textContent = "Regeneration failed";
        statusEl.style.color = "var(--err)";
      } finally {
        regenBtn.disabled = false;
        regenBtn.textContent = "Regenerate Cut";
      }
    });
  }

  // ── Export controls ────────────────────────────────────────
  const exportStatusEl = document.getElementById("exportStatus");

  function wireExport(buttonId, format, idleLabel) {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Exporting…";
      if (exportStatusEl) exportStatusEl.textContent = "";
      try {
        const res = await fetch(`/projects/${projectId}/export`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ export_format: format }),
        });
        const data = await res.json();
        if (res.ok && data.url) {
          if (exportStatusEl) {
            exportStatusEl.textContent = `Exported ${format.toUpperCase()}`;
            exportStatusEl.style.color = "var(--ok)";
          }
          // Trigger the browser download from the media URL the API returned.
          const link = document.createElement("a");
          link.href = data.url;
          link.download = data.url.split("/").pop() || `export.${format}`;
          document.body.appendChild(link);
          link.click();
          link.remove();
        } else {
          if (exportStatusEl) {
            exportStatusEl.textContent = `Failed: ${data.detail || res.status}`;
            exportStatusEl.style.color = "var(--err)";
          }
        }
      } catch (_err) {
        if (exportStatusEl) {
          exportStatusEl.textContent = "Export failed";
          exportStatusEl.style.color = "var(--err)";
        }
      } finally {
        btn.disabled = false;
        btn.textContent = idleLabel;
      }
    });
  }

  wireExport("exportFcpxmlBtn", "fcpxml", "Export FCPXML");
  wireExport("exportEdlBtn", "edl", "Export EDL");
}

// ── Window bootstrap ────────────────────────────────────────

if (typeof window !== "undefined") {
  window.AUTOEDIT_PLAYER = {
    findClipAtTime,
    findNextClip,
    timelineMsFromAudio,
    videoTimeForClip,
    frameDurationSeconds,
    needsDriftCorrection,
    chooseMediaUrl,
    createManualOverrideState,
    validateContiguousClips,
    normalizeProjectedActivity,
    createPlayerStateStore,
    analysisStatusDisplay,
    // Timeline helpers
    formatTimelineMs,
    msToPercent,
    percentToMs,
    renderLaneBlocks,
    renderWaveformBars,
    // LUT helpers
    parseCubeLUT,
    createLUTPipeline,
    bootPlayer,
  };

  window.addEventListener("DOMContentLoaded", () => {
    bootPlayer().catch((err) => {
      const statusText = document.getElementById("statusText");
      if (statusText) statusText.textContent = `Player failed: ${err.message}`;
    });
  });
}
