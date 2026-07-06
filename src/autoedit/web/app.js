const ROLES = [
  { key: 'cam_left', label: 'A · PRES', full: 'Presenter camera', colour: 'var(--presenter)' },
  { key: 'cam_right', label: 'B · INT', full: 'Interviewee camera', colour: 'var(--interviewee)' },
  { key: 'wide', label: 'C · WIDE', full: 'Wide camera', colour: 'var(--wide)' },
];
const CHUNK_SIZE = 8 * 1024 * 1024;

const state = {
  session: null,
  projects: [],
  activeProject: null,
  assets: { angles: [], channels: [] },
  probeByAngle: new Map(),
};

const qs = (id) => document.getElementById(id);
const fmtBytes = (bytes) => {
  if (!Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
};

function setStatus(message, kind = 'ok') {
  const el = qs('statusLine');
  el.hidden = !message;
  el.textContent = message || '';
  el.className = `status-line ${kind}`;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof Blob) ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new Error('authentication required');
  }
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body);
    } catch (_err) { /* ignore */ }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function routeName() {
  if (window.location.pathname.startsWith('/ingest')) return 'ingest';
  if (window.location.pathname.startsWith('/users/manage')) return 'users';
  return 'home';
}

function showRoute() {
  const route = routeName();
  qs('homeView').hidden = route !== 'home';
  qs('ingestView').hidden = route !== 'ingest';
  qs('usersView').hidden = route !== 'users';
  document.querySelectorAll('[data-route]').forEach((el) => el.classList.toggle('is-active', el.dataset.route === route));
  if (route === 'ingest') {
    qs('pageTitle').textContent = 'Create & ingest.';
    qs('pageLede').textContent = 'New project, three uploads, audio-channel mapping, and sync nudges in one screen.';
  } else if (route === 'users') {
    qs('pageTitle').textContent = 'Users & authorisation.';
    qs('pageLede').textContent = 'Add reviewer accounts and control who can create users.';
  } else {
    qs('pageTitle').textContent = 'The cut writes itself.';
    qs('pageLede').textContent = 'Create a project, upload three angles, map audio channels, then open the review player.';
  }
}

async function loadSession() {
  state.session = await api('/auth/session');
  qs('sessionInfo').textContent = `${state.session.display_name} · ${state.session.role || 'reviewer'} · ${state.session.username || 'operator'}`;
}

async function loadProjects() {
  const data = await api('/projects');
  state.projects = data.projects || [];
  renderProjects();
  renderProjectSelect();
}

function renderProjects() {
  const list = qs('projectList');
  list.replaceChildren();
  if (!state.projects.length) {
    const empty = document.createElement('article');
    empty.className = 'card';
    empty.innerHTML = '<h3>No projects yet.</h3><p class="body-copy">Create the first project and upload the three camera angles.</p>';
    list.appendChild(empty);
    return;
  }
  for (const project of state.projects) {
    const card = document.createElement('article');
    card.className = 'card tight';
    const playerHref = `/player/${encodeURIComponent(project.id)}`;
    card.innerHTML = `
      <p class="eyebrow">${escapeHtml(project.status || 'created')}</p>
      <h3>${escapeHtml(project.name)}</h3>
      <p class="mono-note">${escapeHtml(project.id)} · ${project.fps_num}/${project.fps_den}</p>
      <p style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <a class="btn btn-primary btn-sm" href="${playerHref}">Open player</a>
        <button class="btn btn-ghost btn-sm" type="button" data-select-project="${escapeHtml(project.id)}">Ingest</button>
        <button class="btn btn-quiet btn-sm" type="button" data-delete-project="${escapeHtml(project.id)}">Delete</button>
      </p>`;
    list.appendChild(card);
  }
  list.querySelectorAll('[data-select-project]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.activeProject = state.projects.find((p) => p.id === btn.dataset.selectProject);
      window.history.pushState({}, '', '/ingest');
      showRoute();
      renderProjectSelect();
      loadAssets().catch((err) => setStatus(err.message, ''));
    });
  });
  // Delete project buttons
  list.querySelectorAll('[data-delete-project]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const project = state.projects.find((p) => p.id === btn.dataset.deleteProject);
      if (!project) return;
      const typed = prompt(`Type DELETE to permanently remove "${project.name}" and all its data:`);
      if (typed !== 'DELETE') {
        setStatus('Deletion cancelled — you must type DELETE exactly.', '');
        return;
      }
      try {
        await api(`/projects/${project.id}?confirm=DELETE`, { method: 'DELETE' });
        setStatus(`Deleted "${project.name}".`, 'ok');
        await loadProjects();
      } catch (err) {
        setStatus(`Delete failed: ${err.message}`, '');
      }
    });
  });
}

function renderProjectSelect() {
  const select = qs('projectSelect');
  select.replaceChildren();
  const empty = document.createElement('option');
  empty.value = '';
  empty.textContent = 'Select project…';
  select.appendChild(empty);
  for (const project of state.projects) {
    const opt = document.createElement('option');
    opt.value = project.id;
    opt.textContent = `${project.name} · ${project.id}`;
    select.appendChild(opt);
  }
  if (state.activeProject) select.value = state.activeProject.id;
  qs('activeProjectText').textContent = state.activeProject
    ? `${state.activeProject.name} · ${state.activeProject.id}`
    : 'No project selected.';
}

function renderUploadGrid() {
  const grid = qs('uploadGrid');
  grid.replaceChildren();
  for (const role of ROLES) {
    const angle = state.assets.angles.find((a) => a.role === role.key);
    const zone = document.createElement('article');
    zone.className = 'dropzone';
    zone.innerHTML = `
      <span class="pill"><span class="led" style="background:${role.colour}"></span>${role.label}</span>
      <h3 style="margin-top:14px">${role.full}</h3>
      <p class="mono-note">${angle ? escapeHtml(angle.source_path || angle.label) : 'Drop or choose a source video.'}</p>
      <div class="field"><label>Label</label><input data-label="${role.key}" value="${role.key === 'cam_left' ? 'Presenter' : role.key === 'cam_right' ? 'Interviewee' : 'Wide'}"></div>
      <input type="file" data-file="${role.key}" accept="video/*,.mov,.mp4,.m4v,.mxf">
      <div class="progress"><span data-progress="${role.key}" style="width:${angle ? 100 : 0}%"></span></div>
      <p class="mono-note" data-upload-status="${role.key}">${angle ? 'uploaded' : 'waiting'}</p>
      ${angle ? `<button type="button" class="btn btn-ghost btn-sm" data-probe="${angle.id}">Probe source</button>` : ''}`;
    grid.appendChild(zone);
  }
  grid.querySelectorAll('[data-file]').forEach((input) => input.addEventListener('change', () => uploadForRole(input.dataset.file, input.files[0])));
  grid.querySelectorAll('[data-probe]').forEach((btn) => btn.addEventListener('click', () => probeAngle(btn.dataset.probe)));
}

async function uploadForRole(role, file) {
  if (!state.activeProject || !file) {
    setStatus('Select or create a project before uploading.', '');
    return;
  }
  const labelInput = document.querySelector(`[data-label="${role}"]`);
  const progress = document.querySelector(`[data-progress="${role}"]`);
  const status = document.querySelector(`[data-upload-status="${role}"]`);
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE) || 1;
  status.textContent = `Creating upload session for ${fmtBytes(file.size)}…`;
  const created = await api(`/projects/${state.activeProject.id}/uploads`, {
    method: 'POST',
    body: JSON.stringify({
      filename: file.name,
      label: labelInput.value.trim() || role,
      role,
      total_bytes: file.size,
      total_chunks: totalChunks,
      chunk_bytes: CHUNK_SIZE,
    }),
  });
  for (let index = 0; index < totalChunks; index++) {
    const chunk = file.slice(index * CHUNK_SIZE, Math.min(file.size, (index + 1) * CHUNK_SIZE));
    await api(`/upload/${created.upload_id}/chunk/${index}`, { method: 'POST', body: chunk, headers: { 'Content-Type': 'application/octet-stream' } });
    const pct = Math.round(((index + 1) / totalChunks) * 100);
    progress.style.width = `${pct}%`;
    status.textContent = `Uploaded chunk ${index + 1}/${totalChunks} · ${pct}%`;
  }
  status.textContent = `Finalizing ${fmtBytes(file.size)} upload…`;
  const angle = await api(`/upload/${created.upload_id}/complete`, {
    method: 'POST',
    body: JSON.stringify({ total_bytes: file.size }),
  });
  status.textContent = `Uploaded ${angle.label}. Probing…`;
  await loadAssets();
  await probeAngle(angle.id);
}

async function probeAngle(angleId) {
  if (!state.activeProject) return;
  try {
    const result = await api(`/projects/${state.activeProject.id}/angles/${angleId}/probe`, { method: 'POST' });
    state.probeByAngle.set(angleId, result);
    setStatus(`${result.angle_id} probed · ${result.width}x${result.height} · ${result.vcodec}`, result.warnings?.length ? '' : 'ok');
    await loadAssets(false);
  } catch (err) {
    setStatus(`Probe failed: ${err.message}. You can still map channel indices manually.`, '');
  }
  renderChannelMapping();
}

async function loadAssets(rerender = true) {
  if (!state.activeProject) return;
  state.assets = await api(`/projects/${state.activeProject.id}/assets`);
  if (rerender) {
    renderProjectSelect();
    renderUploadGrid();
    renderChannelMapping();
  } else {
    renderUploadGrid();
  }
}

function renderChannelMapping() {
  const target = qs('channelMapping');
  target.replaceChildren();
  const angles = state.assets.angles || [];
  if (!state.activeProject || !angles.length) {
    target.innerHTML = '<p class="mono-note">Upload and probe at least one angle to map audio channels.</p>';
    qs('saveChannelsBtn').disabled = true;
    return;
  }
  const rows = document.createElement('div');
  rows.innerHTML = `
    <table class="table">
      <thead><tr><th>Use</th><th>Source</th><th>Channel</th><th>Speaker</th><th>Sync nudge</th><th>Status</th></tr></thead>
      <tbody></tbody>
    </table>`;
  const tbody = rows.querySelector('tbody');
  const existing = state.assets.channels || [];
  angles.forEach((angle) => {
    const probe = state.probeByAngle.get(angle.id) || {};
    const channelCount = Math.max(2, ...(probe.audio_streams || []).map((s) => s.channels || 0));
    for (let ch = 0; ch < channelCount; ch++) {
      const mapped = existing.find((item) => item.source_angle_id === angle.id && item.channel_index === ch);
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><input type="checkbox" data-map-use="${angle.id}:${ch}" ${mapped || (angle.role === 'cam_left' && ch < 2) ? 'checked' : ''}></td>
        <td><b>${escapeHtml(angle.label)}</b><br><span class="mono-note">${escapeHtml(angle.role)} · ${escapeHtml(angle.id)}</span></td>
        <td class="mono">${ch}</td>
        <td><input data-speaker="${angle.id}:${ch}" value="${escapeHtml(mapped?.speaker_label || (ch === 0 ? 'presenter' : 'interviewee'))}"></td>
        <td><input data-nudge="${angle.id}" type="number" value="${Number(angle.sync_offset_ms || 0)}"></td>
        <td>${mapped ? '<span class="badge ok">mapped</span>' : '<span class="badge neutral">available</span>'}</td>`;
      tbody.appendChild(tr);
    }
  });
  target.appendChild(rows);
  qs('saveChannelsBtn').disabled = false;
}

async function saveChannelMapping() {
  if (!state.activeProject) return;
  const mappings = [];
  document.querySelectorAll('[data-map-use]').forEach((box) => {
    if (!box.checked) return;
    const [source_angle_id, chStr] = box.dataset.mapUse.split(':');
    const speaker = document.querySelector(`[data-speaker="${source_angle_id}:${chStr}"]`)?.value.trim();
    if (speaker) mappings.push({ source_angle_id, channel_index: Number(chStr), speaker_label: speaker });
  });
  const syncByAngle = new Map();
  document.querySelectorAll('[data-nudge]').forEach((input) => syncByAngle.set(input.dataset.nudge, Number(input.value || 0)));
  const sync_nudges = Array.from(syncByAngle, ([source_angle_id, offset_ms]) => ({ source_angle_id, offset_ms }));
  if (mappings.length < 2) {
    setStatus('Select at least two speaker channels before saving.', '');
    return;
  }
  await api(`/projects/${state.activeProject.id}/channels`, {
    method: 'POST',
    body: JSON.stringify({ mappings, sync_nudges }),
  });
  setStatus('Channel mapping saved.', 'ok');
  await loadAssets();
  // Show Start Processing button
  const startBtn = qs('startProcessBtn');
  if (startBtn) startBtn.style.display = 'inline-block';
}

// ── Processing pipeline ──────────────────────────────────────────

let progressInterval = null;
const STAGE_BADGES = {
  done: 'ok',
  running: 'warn',
  queued: 'neutral',
  error: 'err',
};

async function startProcess() {
  if (!state.activeProject) return;
  const startBtn = qs('startProcessBtn');
  startBtn.disabled = true;
  startBtn.textContent = 'Starting…';
  setStatus('', 'ok');
  try {
    const result = await api(`/projects/${state.activeProject.id}/process`, { method: 'POST' });
    setStatus(result.message, 'ok');
    // Show processing view
    qs('processView').hidden = false;
    startBtn.style.display = 'none';
    // Start polling
    pollProgress();
    progressInterval = setInterval(pollProgress, 2000);
  } catch (err) {
    setStatus(err.message, '');
    startBtn.disabled = false;
    startBtn.textContent = 'Start processing';
  }
}

async function pollProgress() {
  if (!state.activeProject) return;
  try {
    const progress = await api(`/projects/${state.activeProject.id}/progress`);
    renderProcessingView(progress);
    // If ready, stop polling
    if (progress.ready) {
      clearInterval(progressInterval);
      progressInterval = null;
    }
    if (progress.status === 'error') {
      clearInterval(progressInterval);
      progressInterval = null;
    }
  } catch (err) {
    setStatus(`Progress check failed: ${err.message}`, '');
  }
}

function renderProcessingView(progress) {
  const view = qs('processView');
  view.hidden = false;

  // Summary
  const summary = qs('processingSummary');
  const ready = progress.ready;
  const isError = progress.status === 'error';
  const isProcessing = progress.status === 'processing' || progress.status === 'ingesting';

  if (isError) {
    summary.innerHTML = 'Processing stopped with an error. Check the failed stage below.';
  } else if (ready) {
    summary.innerHTML = '<b>All processing stages complete.</b> Your project is ready for review.';
  } else if (isProcessing) {
    const doneCount = progress.stages.filter((s) => s.status === 'done').length;
    const total = progress.stages.length;
    summary.textContent = `Processing in progress — ${doneCount} of ${total} stages complete.`;
  } else {
    summary.textContent = 'Processing not started. Save channel mapping and click Start processing.';
  }

  // Pipeline table
  const tableDiv = qs('pipelineTable');
  const table = document.createElement('table');
  table.className = 'table pipeline-status';
  table.innerHTML = '<thead><tr><th>Stage</th><th>State</th><th>Detail</th></tr></thead><tbody></tbody>';
  const tbody = table.querySelector('tbody');
  for (const stage of progress.stages) {
    const tr = document.createElement('tr');
    const badge = STAGE_BADGES[stage.status] || 'neutral';
    const statusText = stage.status.charAt(0).toUpperCase() + stage.status.slice(1);
    let detail = escapeHtml(stage.description);
    if (stage.error) {
      detail = `<span class="processing-error" style="display:inline-block;margin:0;padding:4px 8px;font-size:11px">${escapeHtml(stage.error)}</span>`;
    }
    tr.innerHTML = `<td><b>${escapeHtml(stage.label)}</b></td>
      <td><span class="badge ${badge}">${statusText}</span></td>
      <td class="stage-detail">${detail}</td>`;
    tbody.appendChild(tr);
  }
  tableDiv.replaceChildren(table);

  // Actions
  const actions = qs('processActions');
  if (ready) {
    const playerHref = `/player/${encodeURIComponent(progress.project_id)}`;
    actions.innerHTML = `<a class="btn btn-primary" href="${playerHref}">Open in player</a>`;
  } else if (isError) {
    actions.innerHTML = '<button id="retryProcessBtn" type="button" class="btn btn-ghost">Retry processing</button>';
    // Wire up retry
    const retryBtn = qs('retryProcessBtn');
    if (retryBtn) {
      retryBtn.addEventListener('click', async () => {
        setStatus('', 'ok');
        await startProcess();
      });
    }
  } else {
    actions.innerHTML = '';
  }
}

function checkProjectStatusOnIngest() {
  // If we're on the ingest page with an active project, check status
  // and auto-show processing view if already processing
  if (state.activeProject && routeName() === 'ingest') {
    api(`/projects/${state.activeProject.id}/progress`)
      .then((progress) => {
        if (progress.status === 'processing' || progress.status === 'ready' || progress.status === 'error') {
          renderProcessingView(progress);
          qs('startProcessBtn').style.display = 'none';
          if (progress.status === 'processing') {
            progressInterval = setInterval(pollProgress, 2000);
          }
        }
      })
      .catch(() => { /* not started yet */ });
  }
}

async function loadUsers() {
  const target = qs('userList');
  try {
    const data = await api('/users');
    if (!data.users.length) {
      target.textContent = 'No per-user accounts yet. The shared operator password can add the first admin/reviewer.';
      return;
    }
    const table = document.createElement('table');
    table.className = 'table';
    table.innerHTML = '<thead><tr><th>Username</th><th>Name</th><th>Role</th></tr></thead><tbody></tbody>';
    data.users.forEach((user) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${escapeHtml(user.username)}</td><td>${escapeHtml(user.display_name)}</td><td><span class="badge ${user.role === 'admin' ? 'warn' : 'neutral'}">${escapeHtml(user.role)}</span></td>`;
      table.querySelector('tbody').appendChild(tr);
    });
    target.replaceChildren(table);
  } catch (err) {
    target.textContent = `Users are admin-only: ${err.message}`;
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
}

function bindEvents() {
  qs('logoutBtn').addEventListener('click', async () => {
    await api('/auth/logout', { method: 'POST' });
    window.location.href = '/login';
  });
  qs('projectForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const project = await api('/projects', {
      method: 'POST',
      body: JSON.stringify({
        name: qs('projectName').value.trim(),
        fps_num: Number(qs('fpsNum').value),
        fps_den: Number(qs('fpsDen').value),
      }),
    });
    state.activeProject = project;
    setStatus('Project created. Drop three angles to begin.', 'ok');
    // Clear form fields after creation
    qs('projectName').value = '';
    qs('fpsNum').value = '24000';
    qs('fpsDen').value = '1001';
    await loadProjects();
    renderProjectSelect();
    renderUploadGrid();
    renderChannelMapping();
  });
  qs('projectSelect').addEventListener('change', async (e) => {
    state.activeProject = state.projects.find((p) => p.id === e.target.value) || null;
    // Clear form fields and state when switching projects
    qs('projectName').value = '';
    qs('fpsNum').value = '24000';
    qs('fpsDen').value = '1001';
    state.assets = { angles: [], channels: [] };
    state.probeByAngle.clear();
    renderProjectSelect();
    renderUploadGrid();
    renderChannelMapping();
    await loadAssets();
  });
  qs('saveChannelsBtn').addEventListener('click', () => saveChannelMapping().catch((err) => setStatus(err.message, '')));
  qs('startProcessBtn').addEventListener('click', () => startProcess().catch((err) => setStatus(err.message, '')));
  qs('userForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    await api('/users', {
      method: 'POST',
      body: JSON.stringify({
        username: qs('newUsername').value.trim(),
        display_name: qs('newDisplayName').value.trim(),
        password: qs('newPassword').value,
        role: qs('newRole').value,
      }),
    });
    e.target.reset();
    setStatus('User added.', 'ok');
    await loadUsers();
  });
}

async function boot() {
  showRoute();
  bindEvents();
  renderUploadGrid();
  renderChannelMapping();
  await loadSession();
  await loadProjects();
  if (state.projects.length && !state.activeProject) state.activeProject = state.projects[0];
  if (routeName() === 'ingest' && state.activeProject) {
    await loadAssets();
    checkProjectStatusOnIngest();
  }
  if (routeName() === 'users') await loadUsers();
}

window.addEventListener('DOMContentLoaded', () => {
  boot().catch((err) => setStatus(err.message, ''));
});
