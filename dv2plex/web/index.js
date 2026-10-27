'use strict';
/*
 * DV2Plex interface. One page, eight tabs; everything talks to the local API and listens
 * on the WebSocket for progress, log lines and preview frames.
 *
 * Text is set with textContent only (titles and file names come from users and disks).
 * Every visible string goes through t(); the texts are in i18n.json (English and German).
 */

// ------------------------------------------------------------------ texts

const I18N = JSON.parse(document.getElementById('i18n').textContent);
let lang = 'en';

function pickLanguage(setting) {
    if (setting === 'en' || setting === 'de') return setting;
    const browser = (navigator.languages && navigator.languages[0]) || navigator.language || 'en';
    return browser.toLowerCase().startsWith('de') ? 'de' : 'en';
}

function t(key, vars) {
    let text = (I18N[lang] && I18N[lang][key]) ?? I18N.en[key] ?? key;
    if (vars) text = text.replace(/\{(\w+)\}/g, (match, name) => (vars[name] ?? match));
    return text;
}

function applyTranslations(root = document) {
    root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    root.querySelectorAll('[data-i18n-aria-label]').forEach(el => { el.setAttribute('aria-label', t(el.dataset.i18nAriaLabel)); });
    root.querySelectorAll('[data-i18n-alt]').forEach(el => { el.alt = t(el.dataset.i18nAlt); });
    document.documentElement.lang = lang;
}

function setLanguage(next) {
    lang = next;
    try { localStorage.setItem('dv2plex_language', next); } catch (_) { /* private mode */ }
    applyTranslations();
    renderEverything();
}

// ------------------------------------------------------------------ small helpers

const $ = (id) => document.getElementById(id);

function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') el.className = value;
        else if (key === 'text') el.textContent = value;
        else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
        else if (key === 'checked' || key === 'disabled') el[key] = Boolean(value);
        else el.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
}

function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#i-${name}`);
    svg.append(use);
    return svg;
}

function emptyState(iconName, title, hint, action) {
    return h('div', {class: 'empty'},
        icon(iconName === 'tape' ? 'tape' : iconName),
        h('p', {class: 'empty-title', text: title}),
        hint ? h('p', {class: 'empty-hint', text: hint}) : null,
        action || null);
}

function formatBytes(bytes) {
    if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = Number(bytes);
    let i = 0;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
    return `${value.toLocaleString(lang, {maximumFractionDigits: i === 0 ? 0 : 1})} ${units[i]}`;
}

function formatClock(date) {
    return date.toLocaleTimeString(lang === 'de' ? 'de-DE' : 'en-GB', {hour12: false});
}

function formatElapsed(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)}`;
}

function setStatus(el, text, kind = '') {
    if (typeof el === 'string') el = $(el);
    if (!el) return;
    el.textContent = text || '';
    el.className = `status ${kind}`.trim();
}

function setProgress(prefix, value, name) {
    const box = $(`${prefix}-progress`);
    if (!box) return;
    const pct = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
    box.hidden = false;
    box.querySelector('.bar > span').style.width = `${pct}%`;
    box.querySelector('.bar').setAttribute('aria-valuenow', String(pct));
    $(`${prefix}-progress-value`).textContent = `${pct} %`;
    if (name !== undefined) $(`${prefix}-progress-name`).textContent = name;
}

function hideProgress(prefix) {
    const box = $(`${prefix}-progress`);
    if (box) box.hidden = true;
}

function appendLog(id, message) {
    const log = $(id);
    if (!log) return;
    const time = formatClock(new Date());
    log.textContent += `[${time}] ${message}\n`;
    if (log.textContent.length > 60000) log.textContent = log.textContent.slice(-50000);
    log.scrollTop = log.scrollHeight;
}

function toast(text, kind = 'info', ms = 6000) {
    const box = $('toasts');
    const item = h('div', {class: `toast ${kind}`}, h('span', {text}));
    box.append(item);
    setTimeout(() => item.remove(), ms);
}

function validYear(text) {
    return /^\d{4}$/.test(text) && Number(text) >= 1900 && Number(text) <= 2100;
}

// ------------------------------------------------------------------ API token and requests

const TOKEN_KEY = 'dv2plex_api_token';
let apiToken = '';

(function initToken() {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get('token') || '';
    let stored = '';
    try {
        if (fromUrl) localStorage.setItem(TOKEN_KEY, fromUrl);
        stored = localStorage.getItem(TOKEN_KEY) || '';
    } catch (_) { /* no storage: keep it in the URL */ }
    apiToken = fromUrl || stored;
    if (fromUrl && stored === fromUrl) {
        params.delete('token');
        const query = params.toString();
        history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : '') + window.location.hash);
    }
})();

function withToken(url) {
    if (!apiToken) return url;
    return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(apiToken)}`;
}

class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
}

function detailText(data) {
    if (!data) return '';
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map(d => d.msg || '').filter(Boolean).join('; ');
    return data.message || '';
}

async function api(path, {method = 'GET', body} = {}) {
    const headers = {};
    if (apiToken) headers['X-DV2Plex-Token'] = apiToken;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let response;
    try {
        response = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
    } catch (_) {
        throw new ApiError(t('error.network'), 0);
    }
    let data = null;
    try { data = await response.json(); } catch (_) { /* empty body */ }
    if (response.status === 401) {
        askForToken();
        throw new ApiError(t('error.token'), 401);
    }
    if (!response.ok) throw new ApiError(detailText(data) || t('error.http', {status: response.status}), response.status);
    return data;
}

let tokenDialogShown = false;
function askForToken() {
    if (tokenDialogShown) return;
    tokenDialogShown = true;
    $('token-input').value = '';
    $('token-dialog').showModal();
}

// ------------------------------------------------------------------ dialogs

function confirmDialog({title, text, ok, danger = false}) {
    const dialog = $('confirm-dialog');
    $('confirm-heading').textContent = title;
    $('confirm-text').textContent = text;
    const okButton = $('confirm-ok');
    okButton.textContent = ok || t('common.ok');
    okButton.className = `btn ${danger ? 'danger' : 'primary'}`;
    return new Promise(resolve => {
        dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), {once: true});
        dialog.returnValue = '';
        dialog.showModal();
        okButton.focus();
    });
}

document.querySelectorAll('dialog [data-close]').forEach(button => {
    button.addEventListener('click', () => button.closest('dialog').close());
});

// ------------------------------------------------------------------ state

const state = {
    info: null,
    settings: null,
    status: null,
    capture: {running: false, stopping: false, startedAt: null},
    postprocess: {movies: [], selected: null, running: false, logTarget: false},
    cover: {videos: [], selected: new Set()},
    movie: {videos: [], storage: null, selected: new Set(), busy: false},
    queue: null,
    player: {projects: [], selected: null, playing: null},
    logs: [],
    profiles: {names: [], default: null},
    settingsDirty: false,
    activeTab: 'capture',
};

// ------------------------------------------------------------------ theme

function applyTheme(theme) {
    const value = theme === 'light' || theme === 'dark' ? theme : 'auto';
    if (value === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', value);
    try { localStorage.setItem('dv2plex_theme', value); } catch (_) { /* ignore */ }
}

// ------------------------------------------------------------------ tabs

const TABS = ['capture', 'postprocess', 'cover', 'movie', 'queue', 'player', 'logs', 'settings'];

function tabButtons() { return TABS.map(name => $(`tab-${name}`)).filter(b => b && !b.hidden); }

function activateTab(name, focus = false) {
    if (!TABS.includes(name) || $(`tab-${name}`).hidden) name = 'capture';
    state.activeTab = name;
    for (const tab of TABS) {
        const button = $(`tab-${tab}`);
        const panel = $(`panel-${tab}`);
        const active = tab === name;
        button.setAttribute('aria-selected', String(active));
        button.tabIndex = active ? 0 : -1;
        panel.hidden = !active;
    }
    if (focus) $(`tab-${name}`).focus();
    // On narrow screens the tab strip scrolls; keep the active tab in sight
    $(`tab-${name}`).scrollIntoView({block: 'nearest', inline: 'nearest'});
    history.replaceState(null, '', `${window.location.pathname}${window.location.search}#${name}`);
    loadTab(name);
}

function loadTab(name) {
    if (name === 'postprocess') loadPostprocessList();
    else if (name === 'cover') loadCoverList();
    else if (name === 'movie') loadMovieList();
    else if (name === 'queue') loadMergeQueue();
    else if (name === 'player') loadPlayerProjects();
    else if (name === 'logs') loadLogs();
    else if (name === 'settings') loadSettings();
}

$('tab-capture').parentElement.addEventListener('click', (event) => {
    const button = event.target.closest('[role="tab"]');
    if (button) activateTab(button.dataset.tab);
});

$('tab-capture').parentElement.addEventListener('keydown', (event) => {
    const buttons = tabButtons();
    const index = buttons.indexOf(document.activeElement);
    if (index < 0) return;
    let next = null;
    if (event.key === 'ArrowRight') next = buttons[(index + 1) % buttons.length];
    else if (event.key === 'ArrowLeft') next = buttons[(index - 1 + buttons.length) % buttons.length];
    else if (event.key === 'Home') next = buttons[0];
    else if (event.key === 'End') next = buttons[buttons.length - 1];
    if (next) {
        event.preventDefault();
        activateTab(next.dataset.tab, true);
    }
});

function setCoverTabVisible(show) {
    $('tab-cover').hidden = !show;
    if (!show && state.activeTab === 'cover') activateTab('capture');
}

// ------------------------------------------------------------------ live connection

let socket = null;
let reconnectDelay = 1000;

const chipKeys = {'chip-camera': 'chip.camera_unknown', 'chip-connection': 'chip.connecting'};

function setChip(id, stateName, key) {
    chipKeys[id] = key;
    $(id).dataset.state = stateName;
    $(`${id}-text`).textContent = t(key);
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(withToken(`${protocol}//${window.location.host}/ws`));
    socket.onopen = () => {
        reconnectDelay = 1000;
        setChip('chip-connection', 'ok', 'chip.connected');
    };
    socket.onmessage = (event) => {
        try { handleMessage(JSON.parse(event.data)); } catch (e) { console.error(e); }
    };
    socket.onclose = () => {
        setChip('chip-connection', 'bad', 'chip.disconnected');
        setTimeout(connectWebSocket, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    };
}

function handleMessage(data) {
    switch (data.type) {
        case 'preview_frame': showPreviewFrame(data.data); break;
        case 'progress': handleProgress(data); break;
        case 'status': handleStatus(data); break;
        case 'log': handleLogLine(data.message); break;
        case 'postprocessing_finished': handlePostprocessFinished(data); break;
        case 'poster_generation_finished': handlePosterFinished(data); break;
        case 'cover_generation_finished': handlePosterFinished(data); break;
        case 'merge_progress': handleMergeProgress(data.job); break;
        default: break;
    }
}

function handleLogLine(message) {
    if (!message) return;
    state.logs.push({timestamp: new Date().toISOString(), message, category: 'live'});
    if (state.logs.length > 800) state.logs.splice(0, state.logs.length - 800);
    if (state.activeTab === 'logs' && !$('log-filter').value) appendLogEntry(state.logs[state.logs.length - 1]);
    if (state.postprocess.logTarget) appendLog('postprocess-log', message);
    if (state.movie.busy) appendLog('movie-log', message);
    if (state.cover.busy) appendLog('cover-log', message);
}

function handleProgress(data) {
    const op = data.operation;
    if (op === 'postprocessing') {
        state.postprocess.running = true;
        setProgress('postprocess', data.value, data.project || $('postprocess-progress-name').textContent);
    } else if (op === 'poster_generation' || op === 'poster_generation_batch' || op === 'cover_generation') {
        setProgress('cover', data.value);
    } else if (op === 'movie_export_all' || op === 'movie_export_single' || op === 'movie_merge') {
        setProgress('movie', data.value);
    }
}

function handleStatus(data) {
    const status = data.status;
    if (status === 'capture_started') {
        setCaptureRunning(true, data.data);
    } else if (status === 'capture_stopped') {
        setCaptureRunning(false);
    } else if (data.operation === 'postprocessing') {
        setStatus('postprocess-status', status, 'busy');
    } else if (data.operation === 'poster_generation' || data.operation === 'poster_generation_batch') {
        setStatus('cover-status', status, 'busy');
    } else if (data.operation && data.operation.startsWith('movie_')) {
        handleMovieStatus(status, data.data || {});
    }
}

// ------------------------------------------------------------------ status and info

async function loadInfo() {
    try {
        state.info = await api('/api/info');
    } catch (e) {
        return;
    }
    const info = state.info;
    $('foot-version').textContent = `DV2Plex ${info.version}`;
    $('chip-demo').hidden = !info.demo;
    $('demo-banner').hidden = !info.demo;
    const unsupported = !info.capture.supported;
    $('capture-unsupported').hidden = !unsupported;
    for (const id of ['capture-start-btn', 'cam-rewind', 'cam-play', 'cam-pause']) $(id).disabled = unsupported;
    document.querySelectorAll('.posix-only').forEach(el => { el.hidden = info.platform === 'win32'; });
    renderSystemFacts();
}

async function loadStatus() {
    try {
        state.status = await api('/api/status');
    } catch (_) {
        return;
    }
    const s = state.status;
    if (state.info && !state.info.capture.supported) setChip('chip-camera', 'unknown', 'chip.no_capture');
    else if (s.device_available) setChip('chip-camera', 'ok', 'chip.camera_ready');
    else setChip('chip-camera', 'bad', 'chip.camera_missing');
    if (s.capture_running && !state.capture.running) setCaptureRunning(true, s.active_capture);
    if (!s.capture_running && state.capture.running && !state.capture.stopping) setCaptureRunning(false);
    if (state.capture.stopping && !s.capture_running) setCaptureRunning(false);
}

// ------------------------------------------------------------------ capture

function setCaptureRunning(running, data) {
    state.capture.running = running;
    $('capture-rec').hidden = !running;
    if (running) {
        state.capture.stopping = false;
        state.capture.startedAt = (data && data.started_at) || state.capture.startedAt || new Date().toISOString();
        if (data && data.title) $('capture-title').value = data.title;
        if (data && data.year) $('capture-year').value = data.year;
        setStatus('capture-status', t('capture.running'), 'busy');
    } else {
        const wasStopping = state.capture.stopping || state.capture.startedAt;
        state.capture.stopping = false;
        state.capture.startedAt = null;
        if (wasStopping) setStatus('capture-status', t('capture.finished'), 'ok');
        $('preview-img').hidden = true;
        $('preview-empty').hidden = false;
        loadMergeQueue();
    }
    const supported = !state.info || state.info.capture.supported;
    $('capture-start-btn').disabled = running || !supported;
    $('capture-stop-btn').disabled = !running || state.capture.stopping;
    $('capture-title').disabled = running;
    $('capture-year').disabled = running;
}

function fieldError(inputId, errorId, message) {
    const input = $(inputId);
    const error = $(errorId);
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
    error.textContent = message || '';
    error.hidden = !message;
    return !message;
}

$('capture-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const title = $('capture-title').value.trim();
    const year = $('capture-year').value.trim();
    const titleOk = fieldError('capture-title', 'capture-title-error', title ? '' : t('validation.title'));
    const yearOk = fieldError('capture-year', 'capture-year-error', validYear(year) ? '' : t('validation.year'));
    if (!titleOk) { $('capture-title').focus(); return; }
    if (!yearOk) { $('capture-year').focus(); return; }

    $('capture-start-btn').disabled = true;
    setStatus('capture-status', t('capture.starting'), 'busy');
    try {
        await api('/api/capture/start', {method: 'POST', body: {title, year, auto_rewind_play: $('auto-rewind').checked}});
        setCaptureRunning(true, {title, year, started_at: new Date().toISOString()});
    } catch (e) {
        setStatus('capture-status', e.message, 'bad');
        $('capture-start-btn').disabled = false;
    }
});

$('capture-stop-btn').addEventListener('click', async () => {
    $('capture-stop-btn').disabled = true;
    state.capture.stopping = true;
    setStatus('capture-status', t('capture.stopping'), 'busy');
    try {
        await api('/api/capture/stop', {method: 'POST'});
    } catch (e) {
        state.capture.stopping = false;
        $('capture-stop-btn').disabled = false;
        setStatus('capture-status', e.message, 'bad');
    }
});

for (const action of ['rewind', 'play', 'pause']) {
    $(`cam-${action}`).addEventListener('click', async () => {
        try {
            await api(`/api/capture/${action}`, {method: 'POST'});
            setStatus('capture-status', t(`capture.sent_${action}`));
        } catch (e) {
            toast(e.message, 'bad');
        }
    });
}

function showPreviewFrame(dataUrl) {
    const img = $('preview-img');
    img.src = dataUrl;
    img.hidden = false;
    $('preview-empty').hidden = true;
}

function tickClock() {
    $('capture-clock').textContent = formatClock(new Date());
    const started = state.capture.startedAt ? new Date(state.capture.startedAt) : null;
    $('capture-elapsed').textContent = started && !Number.isNaN(started.getTime())
        ? formatElapsed(Date.now() - started.getTime()) : '--:--:--';
}

// ------------------------------------------------------------------ merge queue

function jobBadge(status) {
    const kind = {completed: 'ok', failed: 'bad', running: 'busy'}[status] || '';
    return h('span', {class: `badge ${kind}`, text: t(`job.${status}`)});
}

function jobView(job, withBar) {
    return h('div', {class: 'job'},
        h('div', {class: 'job-head'},
            h('span', {class: 'job-title', text: job.year ? `${job.title} (${job.year})` : job.title}),
            jobBadge(job.status)),
        job.message ? h('p', {class: 'job-msg', text: job.message}) : null,
        withBar ? h('div', {class: 'bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100',
            'aria-valuenow': String(job.progress || 0), 'aria-label': t('queue.progress')},
        h('span', {style: `width:${job.progress || 0}%`})) : null);
}

function handleMergeProgress(job) {
    if (!job) return;
    if (!state.queue) state.queue = {jobs: [], pending_count: 0, current_job: null};
    if (job.status === 'running') state.queue.current_job = job;
    else if (state.queue.current_job && state.queue.current_job.title === job.title) state.queue.current_job = null;
    const known = state.queue.jobs.find(j => j.title === job.title && j.year === job.year);
    if (known) Object.assign(known, job); else state.queue.jobs.push(job);
    renderMergeQueue();
    if (job.status === 'completed') toast(t('queue.merged', {name: `${job.title} (${job.year})`}), 'ok');
    if (job.status === 'failed') toast(t('queue.failed', {name: `${job.title} (${job.year})`}), 'bad');
}

async function loadMergeQueue() {
    try {
        state.queue = await api('/api/merge/queue');
    } catch (_) {
        return;
    }
    renderMergeQueue();
}

function renderMergeQueue() {
    const q = state.queue;
    if (!q) return;
    const current = q.current_job;
    const mini = $('merge-mini');
    mini.hidden = !current && !q.pending_count;
    $('merge-mini-job').replaceChildren(current ? jobView(current, true) : '');
    $('merge-mini-pending').textContent = q.pending_count ? t('queue.waiting', {count: q.pending_count}) : '';

    const box = $('queue-current');
    box.hidden = !current;
    box.replaceChildren(current ? jobView(current, true) : '');
    const list = $('queue-list');
    const jobs = (q.jobs || []).slice().reverse().filter(j => !current || j !== current);
    if (!jobs.length && !current) {
        list.replaceChildren(h('li', {}, emptyState('queue', t('queue.empty'), t('queue.empty_hint'))));
        return;
    }
    list.replaceChildren(...jobs.map(job => h('li', {}, h('div', {class: 'row static'}, jobView(job, false)))));
}

// ------------------------------------------------------------------ upscaling

const PROFILE_HINTS = ['realesrgan_4x_hq', 'realesrgan_4x_balanced', 'realesrgan_4x_fast', 'realesrgan_2x', 'ffmpeg_hd', 'ffmpeg_fast'];

function profileLabel(name) {
    return PROFILE_HINTS.includes(name) ? `${name} · ${t(`profile.${name}`)}` : name;
}

async function loadProfiles() {
    try {
        const data = await api('/api/upscaling/profiles');
        state.profiles = {names: data.profiles || [], default: data.default_profile};
    } catch (_) { /* keep the old list */ }
    renderProfiles();
}

function profileAvailable(name) {
    const entry = state.info && state.info.upscaling.profiles.find(p => p.name === name);
    return !entry || entry.available;
}

function renderProfiles() {
    for (const id of ['profile-select', 'settings-default-profile']) {
        const select = $(id);
        const previous = select.value;
        select.replaceChildren(...state.profiles.names.map(name => h('option', {
            value: name,
            disabled: !profileAvailable(name),
            text: profileAvailable(name) ? profileLabel(name) : `${profileLabel(name)} · ${t('profile.unavailable')}`,
        })));
        const wanted = id === 'settings-default-profile' && state.settings ? state.settings.default_profile : previous;
        select.value = state.profiles.names.includes(wanted) ? wanted : (state.profiles.default || '');
        if (!profileAvailable(select.value)) {
            const first = state.profiles.names.find(profileAvailable);
            if (first) select.value = first;
        }
    }
    updateProfileHint();
}

function updateProfileHint() {
    const name = $('profile-select').value;
    const reason = state.info && state.info.upscaling.realesrgan_reason;
    $('profile-hint').textContent = !profileAvailable(name) && reason ? reason : (name ? t(`profile.${name}.detail`) : '');
    if ($('profile-hint').textContent.startsWith('profile.')) $('profile-hint').textContent = '';
}
$('profile-select').addEventListener('change', updateProfileHint);

async function loadPostprocessList() {
    const list = $('postprocess-list');
    if (!state.postprocess.movies.length) list.replaceChildren(h('li', {}, h('p', {class: 'empty', text: t('common.loading')})));
    try {
        const data = await api('/api/postprocess/list');
        state.postprocess.movies = data.movies || [];
    } catch (e) {
        list.replaceChildren(h('li', {}, emptyState('upscale', t('error.load'), e.message,
            h('button', {class: 'btn', type: 'button', onclick: loadPostprocessList, text: t('common.retry')}))));
        return;
    }
    renderPostprocessList();
}

function renderPostprocessList() {
    const list = $('postprocess-list');
    const movies = state.postprocess.movies;
    if (!movies.some(m => m.path === state.postprocess.selected)) state.postprocess.selected = null;
    if (!movies.length) {
        list.replaceChildren(h('li', {}, emptyState('upscale', t('post.empty'), t('post.empty_hint'),
            h('button', {class: 'btn', type: 'button', onclick: () => activateTab('capture', true), text: t('post.to_capture')}))));
    } else {
        list.replaceChildren(...movies.map(movie => {
            const id = `pp-${btoa(unescape(encodeURIComponent(movie.path))).replace(/[^a-zA-Z0-9]/g, '')}`;
            const badges = [];
            if (movie.merging) badges.push(h('span', {class: 'badge busy', text: t('post.merging')}));
            else if (movie.needs_merge) badges.push(h('span', {class: 'badge', text: t('post.needs_merge')}));
            return h('li', {},
                h('label', {class: 'row', for: id},
                    h('input', {type: 'radio', name: 'postprocess-movie', id, value: movie.path,
                        checked: movie.path === state.postprocess.selected,
                        onchange: () => { state.postprocess.selected = movie.path; updatePostprocessButtons(); }}),
                    h('span', {class: 'name', text: movie.display}),
                    ...badges));
        }));
    }
    updatePostprocessButtons();
}

function updatePostprocessButtons() {
    const selected = state.postprocess.movies.find(m => m.path === state.postprocess.selected);
    $('postprocess-run').disabled = !selected || Boolean(selected.merging);
    $('postprocess-delete').disabled = !selected;
    $('postprocess-run-all').disabled = !state.postprocess.movies.length;
}

async function startUpscale(movie) {
    const profile = $('profile-select').value;
    await api('/api/postprocess/process', {method: 'POST', body: {movie_dir: movie.path, profile_name: profile}});
}

$('postprocess-run').addEventListener('click', async () => {
    const movie = state.postprocess.movies.find(m => m.path === state.postprocess.selected);
    if (!movie) return;
    try {
        state.postprocess.logTarget = true;
        await startUpscale(movie);
        setStatus('postprocess-status', t('post.queued', {name: movie.display}), 'busy');
        setProgress('postprocess', 0, movie.display);
    } catch (e) {
        setStatus('postprocess-status', e.message, 'bad');
    }
});

$('postprocess-run-all').addEventListener('click', async () => {
    const movies = state.postprocess.movies.filter(m => !m.merging);
    if (!movies.length) return;
    const ok = await confirmDialog({title: t('post.all_title'), text: t('post.all_text', {count: movies.length}), ok: t('post.process_all')});
    if (!ok) return;
    state.postprocess.logTarget = true;
    let queued = 0;
    for (const movie of movies) {
        try { await startUpscale(movie); queued += 1; } catch (e) { appendLog('postprocess-log', `${movie.display}: ${e.message}`); }
    }
    setStatus('postprocess-status', t('post.queued_many', {count: queued}), 'busy');
});

$('postprocess-delete').addEventListener('click', async () => {
    const movie = state.postprocess.movies.find(m => m.path === state.postprocess.selected);
    if (movie) await deleteProjects([movie.path], [movie.display]);
});

$('postprocess-refresh').addEventListener('click', loadPostprocessList);

function handlePostprocessFinished(data) {
    setStatus('postprocess-status', data.message || '', data.success ? 'ok' : 'bad');
    toast(data.message || (data.success ? t('post.done') : t('post.failed')), data.success ? 'ok' : 'bad');
    if (!(state.status && state.status.postprocessing_queued)) hideProgress('postprocess');
    loadPostprocessList();
    if (state.activeTab === 'movie') loadMovieList();
}

// ------------------------------------------------------------------ deleting projects

async function deleteProjects(paths, names) {
    const ok = await confirmDialog({
        title: t('delete.title'),
        text: t('delete.text', {names: names.join(', ')}),
        ok: t('delete.confirm'),
        danger: true,
    });
    if (!ok) return;
    try {
        await api('/api/project/delete', {method: 'POST', body: {paths}});
        toast(t('delete.done', {count: paths.length}), 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
    loadPostprocessList();
    if (state.activeTab === 'movie') loadMovieList();
}

// ------------------------------------------------------------------ covers

async function loadCoverList() {
    const list = $('cover-video-list');
    try {
        const data = await api('/api/cover/videos');
        state.cover.videos = data.videos || [];
    } catch (e) {
        list.replaceChildren(h('li', {}, emptyState('cover', t('error.load'), e.message)));
        return;
    }
    const paths = new Set(state.cover.videos.map(v => v.path));
    state.cover.selected = new Set([...state.cover.selected].filter(p => paths.has(p)));
    renderCoverList();
}

function renderCoverList() {
    const list = $('cover-video-list');
    if (!state.cover.videos.length) {
        list.replaceChildren(h('li', {}, emptyState('cover', t('cover.empty'), t('cover.empty_hint'))));
    } else {
        list.replaceChildren(...state.cover.videos.map((video, index) => {
            const id = `cv-${index}`;
            const thumb = video.has_poster && video.poster_path
                ? h('img', {src: withToken(`/api/player/poster?path=${encodeURIComponent(video.poster_path)}`), alt: '', width: '30', height: '45', class: 'thumb', loading: 'lazy'})
                : null;
            return h('li', {},
                h('label', {class: 'row', for: id},
                    h('input', {type: 'checkbox', id, checked: state.cover.selected.has(video.path),
                        onchange: (event) => {
                            if (event.target.checked) state.cover.selected.add(video.path);
                            else state.cover.selected.delete(video.path);
                            updateCoverButtons();
                        }}),
                    thumb,
                    h('span', {class: 'name', text: video.display}),
                    h('span', {class: `badge ${video.has_poster ? 'ok' : ''}`, text: video.has_poster ? t('cover.has_poster') : t('cover.no_poster')})));
        }));
    }
    updateCoverButtons();
}

function updateCoverButtons() {
    $('generate-poster-selected-btn').disabled = state.cover.selected.size === 0;
    $('generate-poster-all-btn').disabled = !state.cover.videos.some(v => !v.has_poster);
}

async function generatePosters(paths) {
    if (!paths.length) return;
    state.cover.busy = true;
    state.cover.pending = paths.length;
    setProgress('cover', 0, t('cover.working_count', {count: paths.length}));
    try {
        const data = await api('/api/poster/generate-batch', {method: 'POST', body: {video_paths: paths}});
        setStatus('cover-status', t('cover.queued', {count: data.count}), 'busy');
    } catch (e) {
        state.cover.busy = false;
        hideProgress('cover');
        setStatus('cover-status', e.message, 'bad');
    }
}

$('generate-poster-selected-btn').addEventListener('click', () => generatePosters([...state.cover.selected]));
$('generate-poster-all-btn').addEventListener('click', async () => {
    const missing = state.cover.videos.filter(v => !v.has_poster).map(v => v.path);
    const ok = await confirmDialog({title: t('cover.all_title'), text: t('cover.all_text', {count: missing.length}), ok: t('cover.generate_missing')});
    if (ok) generatePosters(missing);
});
$('cover-refresh').addEventListener('click', loadCoverList);

function handlePosterFinished(data) {
    state.cover.pending = Math.max(0, (state.cover.pending || 1) - 1);
    if (!data.success) toast(data.message || t('cover.failed'), 'bad');
    if (!state.cover.pending) {
        state.cover.busy = false;
        hideProgress('cover');
        setStatus('cover-status', data.success ? t('cover.done') : (data.message || t('cover.failed')), data.success ? 'ok' : 'bad');
        if (data.success) toast(t('cover.done'), 'ok');
    }
    loadCoverList();
    if (state.activeTab === 'player') loadPlayerProjects();
}

// ------------------------------------------------------------------ Plex export

async function loadMovieList() {
    const list = $('movie-list');
    try {
        const data = await api('/api/movie/list');
        state.movie.videos = data.videos || [];
        state.movie.storage = data.storage || null;
    } catch (e) {
        list.replaceChildren(h('li', {}, emptyState('export', t('error.load'), e.message)));
        return;
    }
    const paths = new Set(state.movie.videos.map(v => v.path));
    state.movie.selected = new Set([...state.movie.selected].filter(p => paths.has(p)));
    renderMovieList();
}

function renderStorage() {
    const s = state.movie.storage;
    const box = $('movie-storage');
    if (!s) { box.hidden = true; return; }
    box.hidden = false;
    $('storage-root').textContent = s.plex_root;
    $('storage-root').title = s.plex_root;
    $('storage-free').textContent = formatBytes(s.free_bytes);
    $('storage-needed').textContent = s.required_count
        ? t('movie.needed_value', {size: formatBytes(s.required_bytes), count: s.required_count}) : t('movie.nothing_new');
    box.classList.toggle('short', !s.fits_all);
    const used = s.total_bytes ? Math.min(100, ((s.used_bytes || 0) + (s.required_bytes || 0)) / s.total_bytes * 100) : 0;
    $('storage-meter').style.width = `${used}%`;
}

function renderMovieList() {
    renderStorage();
    const list = $('movie-list');
    if (!state.movie.videos.length) {
        list.replaceChildren(h('li', {}, emptyState('export', t('movie.empty'), t('movie.empty_hint'),
            h('button', {class: 'btn', type: 'button', onclick: () => activateTab('postprocess', true), text: t('movie.to_upscaling')}))));
    } else {
        list.replaceChildren(...state.movie.videos.map((video, index) => {
            const id = `mv-${index}`;
            const fits = video.exported || video.fits_now !== false;
            return h('li', {},
                h('label', {class: 'row', for: id, 'data-path': video.path},
                    h('input', {type: 'checkbox', id, checked: state.movie.selected.has(video.path),
                        onchange: (event) => {
                            if (event.target.checked) state.movie.selected.add(video.path);
                            else state.movie.selected.delete(video.path);
                            updateMovieButtons();
                        }}),
                    h('span', {class: 'name', text: video.display, title: video.expected_target}),
                    h('span', {class: 'meta', text: formatBytes(video.size_bytes)}),
                    !fits ? h('span', {class: 'badge bad', text: t('movie.no_space')}) : null,
                    h('span', {class: `badge ${video.exported ? 'ok' : ''}`, 'data-badge': '1',
                        text: video.exported ? t('movie.in_library') : t('movie.not_exported')})));
        }));
    }
    updateMovieButtons();
}

function updateMovieButtons() {
    const count = state.movie.selected.size;
    const busy = state.movie.busy;
    $('export-btn').disabled = count !== 1 || busy;
    $('export-btn').title = count > 1 ? t('movie.one_at_a_time') : '';
    $('merge-btn').disabled = count < 2 || busy;
    $('movie-delete-btn').disabled = count < 1 || busy;
    $('export-all-btn').disabled = busy || !state.movie.videos.some(v => !v.exported);
}

function markMovie(path, kind, text) {
    const row = document.querySelector(`#movie-list label[data-path="${CSS.escape(path || '')}"]`);
    const badge = row && row.querySelector('[data-badge]');
    if (!badge) return;
    badge.className = `badge ${kind}`;
    badge.textContent = text;
}

$('export-btn').addEventListener('click', async () => {
    const path = [...state.movie.selected][0];
    const video = state.movie.videos.find(v => v.path === path);
    if (!video) return;
    if (video.exported) {
        const ok = await confirmDialog({title: t('movie.overwrite_title'), text: t('movie.overwrite_text', {name: video.display}), ok: t('movie.overwrite')});
        if (!ok) return;
    }
    try {
        state.movie.busy = true;
        updateMovieButtons();
        await api('/api/movie/export', {method: 'POST', body: {video_path: path}});
    } catch (e) {
        state.movie.busy = false;
        updateMovieButtons();
        setStatus('movie-status', e.message, 'bad');
    }
});

$('export-all-btn').addEventListener('click', async () => {
    const count = state.movie.videos.filter(v => !v.exported).length;
    const ok = await confirmDialog({title: t('movie.all_title'), text: t('movie.all_text', {count}), ok: t('movie.export_all')});
    if (!ok) return;
    try {
        state.movie.busy = true;
        updateMovieButtons();
        await api('/api/movie/export-all', {method: 'POST', body: {skip_existing: true}});
    } catch (e) {
        state.movie.busy = false;
        updateMovieButtons();
        setStatus('movie-status', e.message, 'bad');
    }
});

$('merge-btn').addEventListener('click', async () => {
    const title = $('movie-title').value.trim();
    const year = $('movie-year').value.trim();
    if (!title) { toast(t('validation.title'), 'bad'); $('movie-title').focus(); return; }
    if (!validYear(year)) { toast(t('validation.year'), 'bad'); $('movie-year').focus(); return; }
    const paths = [...state.movie.selected];
    const ok = await confirmDialog({title: t('movie.merge_title'), text: t('movie.merge_text', {count: paths.length, name: `${title} (${year})`}), ok: t('movie.merge')});
    if (!ok) return;
    try {
        state.movie.busy = true;
        updateMovieButtons();
        await api('/api/movie/merge', {method: 'POST', body: {video_paths: paths, title, year}});
    } catch (e) {
        state.movie.busy = false;
        updateMovieButtons();
        setStatus('movie-status', e.message, 'bad');
    }
});

$('movie-delete-btn').addEventListener('click', async () => {
    const videos = state.movie.videos.filter(v => state.movie.selected.has(v.path));
    if (videos.length) await deleteProjects(videos.map(v => v.path), videos.map(v => v.display));
    state.movie.selected.clear();
});

$('movie-refresh').addEventListener('click', loadMovieList);

function handleMovieStatus(status, payload) {
    const finished = ['movie_export_all_finished', 'movie_export_all_failed', 'movie_export_single_done',
        'movie_export_single_failed', 'movie_merge_finished', 'movie_merge_failed'];
    switch (status) {
        case 'movie_export_all_started':
            setStatus('movie-status', t('movie.all_started', {count: payload.total ?? '?'}), 'busy');
            setProgress('movie', 0, t('movie.exporting'));
            break;
        case 'movie_export_single_started':
            setStatus('movie-status', t('movie.single_started'), 'busy');
            setProgress('movie', 0, t('movie.exporting'));
            markMovie(payload.video_path, 'busy', t('movie.exporting'));
            break;
        case 'movie_merge_started':
            setStatus('movie-status', t('movie.merge_started', {count: payload.count ?? '?'}), 'busy');
            setProgress('movie', 0, t('movie.merging'));
            break;
        case 'movie_export_item_started': markMovie(payload.video_path, 'busy', t('movie.exporting')); break;
        case 'movie_export_item_done':
        case 'movie_export_item_skipped': markMovie(payload.video_path, 'ok', t('movie.in_library')); break;
        case 'movie_export_item_failed': markMovie(payload.video_path, 'bad', t('movie.failed_short')); break;
        case 'movie_export_all_finished':
            setStatus('movie-status', t('movie.all_done', {skipped: payload.skipped ?? 0, failed: payload.failed ?? 0}), payload.failed ? 'bad' : 'ok');
            break;
        case 'movie_export_single_done': setStatus('movie-status', t('movie.single_done'), 'ok'); toast(t('movie.single_done'), 'ok'); break;
        case 'movie_merge_finished': setStatus('movie-status', t('movie.merge_done'), 'ok'); toast(t('movie.merge_done'), 'ok'); break;
        case 'movie_export_all_failed':
        case 'movie_export_single_failed':
        case 'movie_merge_failed':
            setStatus('movie-status', `${t('movie.failed')}: ${payload.error || ''}`, 'bad');
            if (payload.video_path) markMovie(payload.video_path, 'bad', t('movie.failed_short'));
            break;
        default: break;
    }
    if (finished.includes(status)) {
        state.movie.busy = false;
        hideProgress('movie');
        loadMovieList();
    }
}

// ------------------------------------------------------------------ video player

async function loadPlayerProjects() {
    const box = $('player-project-list');
    try {
        const data = await api('/api/player/projects');
        state.player.projects = data.projects || [];
    } catch (e) {
        box.replaceChildren(emptyState('player', t('error.load'), e.message));
        return;
    }
    renderPlayerProjects();
}

function renderPlayerProjects() {
    const box = $('player-project-list');
    const projects = state.player.projects;
    if (!projects.length) {
        box.replaceChildren(emptyState('player', t('player.empty'), t('player.empty_hint')));
        showViewer(null);
        return;
    }
    if (state.player.selected && !projects.some(p => p.path === state.player.selected.path)) state.player.selected = null;
    box.replaceChildren(...projects.map(project => {
        const selected = state.player.selected && state.player.selected.path === project.path;
        const files = (label, items) => h('div', {class: 'files'},
            h('span', {class: 'label', text: label}),
            items.length
                ? h('div', {class: 'file-chips'}, ...items.map(file => h('button', {
                    type: 'button', class: 'file-chip',
                    'aria-pressed': String(state.player.playing === file.path),
                    onclick: () => playVideo(project, file),
                }, icon('play'), h('span', {text: file.name}))))
                : h('span', {class: 'muted small', text: t('player.no_files')}));
        return h('div', {class: `project${selected ? ' selected' : ''}`},
            h('div', {class: 'project-head'},
                h('button', {type: 'button', 'aria-pressed': String(Boolean(selected)), text: project.title,
                    onclick: () => { state.player.selected = project; state.player.playing = null; renderPlayerProjects(); showViewer(project); }}),
                project.has_poster ? h('span', {class: 'badge ok', text: t('cover.has_poster')}) : null),
            files(t('player.lowres'), project.lowres || []),
            files(t('player.highres'), project.highres || []));
    }));
    if (!state.player.playing) showViewer(state.player.selected || projects.find(p => p.has_poster) || null);
    $('player-rename-btn').hidden = !state.player.selected;
}

function showViewer(project) {
    const video = $('player-video');
    const poster = $('player-poster');
    video.pause();
    video.removeAttribute('src');
    video.hidden = true;
    if (project && project.has_poster && project.poster_path) {
        poster.src = withToken(`/api/player/poster?path=${encodeURIComponent(project.poster_path)}`);
        poster.alt = t('player.poster_alt', {name: project.title});
        poster.hidden = false;
        $('player-placeholder').hidden = true;
        $('player-now-playing').textContent = project.title;
    } else {
        poster.hidden = true;
        $('player-placeholder').hidden = false;
        $('player-now-playing').textContent = project ? project.title : '';
    }
}

function playVideo(project, file) {
    state.player.selected = project;
    state.player.playing = file.path;
    const video = $('player-video');
    $('player-poster').hidden = true;
    $('player-placeholder').hidden = true;
    video.hidden = false;
    video.src = withToken(`/api/player/stream?path=${encodeURIComponent(file.path)}`);
    video.play().catch(() => { /* the user starts it */ });
    $('player-now-playing').textContent = t('player.playing', {name: `${project.title} · ${file.name}`});
    video.onended = () => { state.player.playing = null; showViewer(project); renderPlayerProjects(); };
    renderPlayerProjects();
}

$('player-refresh').addEventListener('click', loadPlayerProjects);

$('player-rename-btn').addEventListener('click', () => {
    const project = state.player.selected;
    if (!project) return;
    const match = project.title.match(/^(.+?)\s*\((\d{4})\)$/);
    $('rename-title').value = match ? match[1].trim() : project.title;
    $('rename-year').value = match ? match[2] : '';
    $('rename-error').hidden = true;
    $('rename-dialog').showModal();
    $('rename-title').focus();
});

$('rename-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const project = state.player.selected;
    const title = $('rename-title').value.trim();
    const year = $('rename-year').value.trim();
    const showError = (text) => { $('rename-error').textContent = text; $('rename-error').hidden = false; };
    if (!title) return showError(t('validation.title'));
    if (year && !validYear(year)) return showError(t('validation.year'));
    try {
        const data = await api('/api/player/rename', {method: 'POST', body: {project_path: project.path, new_title: title, new_year: year || null}});
        $('rename-dialog').close();
        toast(t('player.renamed', {name: data.new_name}), 'ok');
        state.player.selected = {path: data.new_path};
        await loadPlayerProjects();
        state.player.selected = state.player.projects.find(p => p.path === data.new_path) || null;
        renderPlayerProjects();
    } catch (e) {
        showError(e.message);
    }
});

// ------------------------------------------------------------------ logs

const LOG_CATEGORIES = ['capture', 'merge', 'postprocessing', 'poster_generation', 'update', 'player', 'movie', 'general', 'live'];

function appendLogEntry(entry, list = $('system-logs')) {
    const time = new Date(entry.timestamp);
    const failed = /fehl|error|failed|fehler/i.test(entry.message);
    const cat = LOG_CATEGORIES.includes(entry.category) ? t(`logcat.${entry.category}`) : entry.category;
    const item = h('li', {'data-cat': entry.category, class: failed ? 'bad' : ''},
        h('time', {datetime: entry.timestamp, text: Number.isNaN(time.getTime()) ? '' : formatClock(time)}),
        h('span', {class: 'cat', text: cat}),
        h('span', {class: 'msg', text: entry.message}));
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
    const empty = list.querySelector('.empty');
    if (empty) empty.remove();
    list.append(item);
    if (nearBottom) list.scrollTop = list.scrollHeight;
}

async function loadLogs() {
    const list = $('system-logs');
    const category = $('log-filter').value;
    let entries = [];
    try {
        const data = await api(`/api/logs?limit=500${category ? `&category=${encodeURIComponent(category)}` : ''}`);
        entries = data.logs || [];
    } catch (e) {
        list.replaceChildren(h('li', {class: 'empty'}, emptyState('logs', t('error.load'), e.message)));
        return;
    }
    list.replaceChildren();
    if (!entries.length) {
        list.append(h('li', {class: 'empty'}, emptyState('logs', t('logs.empty'), t('logs.empty_hint'))));
    } else {
        entries.forEach(entry => appendLogEntry(entry, list));
        list.scrollTop = list.scrollHeight;
    }
    if (state.info) $('logs-file').textContent = t('logs.file', {path: state.info.paths.logs});
}

$('log-filter').addEventListener('change', loadLogs);
$('logs-refresh').addEventListener('click', loadLogs);
$('logs-clear').addEventListener('click', async () => {
    const ok = await confirmDialog({title: t('logs.clear_title'), text: t('logs.clear_text'), ok: t('logs.clear')});
    if (!ok) return;
    try { await api('/api/logs/clear', {method: 'POST'}); } catch (e) { toast(e.message, 'bad'); }
    loadLogs();
});

// ------------------------------------------------------------------ settings

const SETTING_FIELDS = {
    'settings-plex-root': 'plex_movies_root',
    'settings-dv-root': 'dv_import_root',
    'settings-ffmpeg': 'ffmpeg_path',
};
const SETTING_CHECKS = {
    'settings-timestamp-overlay': 'timestamp_overlay',
    'settings-auto-postprocess': 'auto_postprocess',
    'settings-auto-upscale': 'auto_upscale',
    'settings-auto-export': 'auto_export',
    'settings-show-cover': 'show_cover_tab',
    'settings-update-enabled': 'update_enabled',
};

async function loadSettings(force = false) {
    if (state.settingsDirty && !force) return;
    try {
        state.settings = await api('/api/settings');
    } catch (e) {
        setStatus('settings-status', e.message, 'bad');
        return;
    }
    fillSettings();
    loadUpdateStatus();
}

function fillSettings() {
    const s = state.settings;
    if (!s) return;
    for (const [id, key] of Object.entries(SETTING_FIELDS)) $(id).value = s[key] || '';
    for (const [id, key] of Object.entries(SETTING_CHECKS)) $(id).checked = Boolean(s[key]);
    $('settings-language').value = ['en', 'de'].includes(s.ui_language) ? s.ui_language : '';
    $('settings-theme').value = ['light', 'dark'].includes(s.ui_theme) ? s.ui_theme : 'auto';
    renderProfiles();
    updateSubChecks();
    state.settingsDirty = false;
    setStatus('settings-status', '');
}

function updateSubChecks() {
    const on = $('settings-auto-postprocess').checked;
    $('settings-auto-upscale').disabled = !on;
    $('settings-auto-export').disabled = !on;
}

$('settings-form').addEventListener('input', () => {
    state.settingsDirty = true;
    setStatus('settings-status', t('settings.unsaved'));
});
$('settings-form').addEventListener('change', (event) => {
    state.settingsDirty = true;
    setStatus('settings-status', t('settings.unsaved'));
    if (event.target.id === 'settings-auto-postprocess') updateSubChecks();
    if (event.target.id === 'settings-language') setLanguage(pickLanguage(event.target.value));
    if (event.target.id === 'settings-theme') applyTheme(event.target.value);
    if (event.target.id === 'settings-show-cover') setCoverTabVisible(event.target.checked);
});

$('settings-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const body = {};
    for (const [id, key] of Object.entries(SETTING_FIELDS)) body[key] = $(id).value.trim();
    for (const [id, key] of Object.entries(SETTING_CHECKS)) body[key] = $(id).checked;
    body.ui_language = $('settings-language').value;
    body.ui_theme = $('settings-theme').value;
    body.default_profile = $('settings-default-profile').value || undefined;
    if (!body.plex_movies_root || !body.dv_import_root) {
        setStatus('settings-status', t('settings.folders_required'), 'bad');
        return;
    }
    try {
        await api('/api/settings', {method: 'POST', body});
        state.settingsDirty = false;
        setStatus('settings-status', t('settings.saved'), 'ok');
        toast(t('settings.saved'), 'ok');
        await loadInfo();
        await loadSettings(true);
        loadProfiles();
    } catch (e) {
        setStatus('settings-status', e.message, 'bad');
    }
});

$('settings-reset').addEventListener('click', async () => {
    await loadSettings(true);
    setLanguage(pickLanguage(state.settings ? state.settings.ui_language : ''));
    applyTheme(state.settings ? state.settings.ui_theme : 'auto');
    setCoverTabVisible(state.settings ? state.settings.show_cover_tab !== false : true);
    setStatus('settings-status', t('settings.discarded'));
});

function renderSystemFacts() {
    const info = state.info;
    const facts = $('system-facts');
    if (!info) return;
    const rows = [
        [t('facts.version'), `${info.version} · ${t(`facts.mode_${info.mode}`)}${info.demo ? ` · ${t('chip.demo')}` : ''}`, ''],
        [t('facts.ffmpeg'), info.ffmpeg.found ? (info.ffmpeg.version || info.ffmpeg.path) : t('facts.missing'), info.ffmpeg.found ? '' : 'bad'],
        [t('facts.overlay'), info.ffmpeg.drawtext ? t('facts.yes') : t('facts.no_drawtext'), info.ffmpeg.drawtext ? '' : 'bad'],
        [t('facts.capture'), info.capture.supported ? t('facts.capture_ok') : t('facts.capture_no'), info.capture.supported ? '' : 'bad'],
        [t('facts.realesrgan'), info.upscaling.realesrgan ? t('facts.yes') : (info.upscaling.realesrgan_reason || t('facts.no')), info.upscaling.realesrgan ? '' : 'bad'],
        [t('facts.poster'), info.poster.full ? t('facts.poster_full') : t('facts.poster_simple'), ''],
        [t('facts.settings_file'), info.paths.settings, ''],
        [t('facts.logs'), info.paths.logs, ''],
    ];
    facts.replaceChildren(...rows.flatMap(([label, value, kind]) => [h('dt', {text: label}), h('dd', {class: kind, text: value})]));
}

async function loadUpdateStatus(refresh = false) {
    setStatus('update-status', t('update.checking'), 'busy');
    try {
        const data = await api(`/api/update/status${refresh ? '?refresh=true' : ''}`);
        const s = data.status || {};
        if (s.error) {
            setStatus('update-status', s.error, 'bad');
            $('update-run-btn').disabled = true;
            return;
        }
        const local = s.local ? s.local.slice(0, 7) : '?';
        if (s.blocked_reason) setStatus('update-status', t('update.blocked', {reason: s.blocked_reason}), 'bad');
        else if (s.behind > 0) setStatus('update-status', t('update.available', {count: s.behind, local}), 'busy');
        else setStatus('update-status', t('update.current', {local}), 'ok');
        $('update-run-btn').disabled = !(s.behind > 0);
    } catch (e) {
        setStatus('update-status', e.message, 'bad');
    }
}

$('update-refresh-btn').addEventListener('click', () => loadUpdateStatus(true));
$('update-run-btn').addEventListener('click', async () => {
    const ok = await confirmDialog({title: t('update.run_title'), text: t('update.run_text'), ok: t('settings.update_run')});
    if (!ok) return;
    setStatus('update-status', t('update.running'), 'busy');
    try {
        const data = await api('/api/update/run', {method: 'POST'});
        setStatus('update-status', data.message || t('update.done'), 'ok');
    } catch (e) {
        setStatus('update-status', e.message, 'bad');
    }
});

$('fix-config-btn').addEventListener('click', async () => {
    const ok = await confirmDialog({title: t('settings.fix_config'), text: t('settings.fix_config_text'), ok: t('common.continue')});
    if (!ok) return;
    try {
        const data = await api('/api/fix-config-permissions', {method: 'POST'});
        toast(data.message || t('common.done'), 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
});

document.querySelectorAll('[data-chown]').forEach(button => button.addEventListener('click', async () => {
    const path = $(button.dataset.chown).value.trim();
    if (!path) return;
    const ok = await confirmDialog({title: t('settings.chown'), text: t('settings.chown_text', {path}), ok: t('common.continue')});
    if (!ok) return;
    try {
        const data = await api('/api/chown', {method: 'POST', body: {path}});
        toast(data.message || t('common.done'), 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
}));

// ------------------------------------------------------------------ folder browser

const browser = {target: null, path: '/', files: false};

document.querySelectorAll('[data-browse]').forEach(button => button.addEventListener('click', () => {
    browser.target = button.dataset.browse;
    browser.files = Boolean(button.dataset.browseFiles);
    const current = $(browser.target).value.trim();
    let start = current || (state.info && state.info.platform === 'win32' ? 'C:\\' : '/');
    if (browser.files && current) start = current.replace(/[\\/][^\\/]*$/, '') || '/';
    $('browser-dialog').showModal();
    loadBrowser(start);
}));

async function loadBrowser(path) {
    const list = $('browser-list');
    list.replaceChildren(h('li', {}, h('p', {class: 'empty', text: t('common.loading')})));
    let data;
    try {
        data = await api(`/api/browse?path=${encodeURIComponent(path)}`);
    } catch (e) {
        if (path !== '/' && e.status === 404) return loadBrowser('/');
        list.replaceChildren(h('li', {}, h('p', {class: 'empty', text: e.message})));
        return;
    }
    browser.path = data.current_path;
    $('browser-current-path').textContent = data.current_path;
    const rows = [];
    if (data.parent_path) {
        rows.push(h('li', {}, h('button', {type: 'button', class: 'row', style: 'width:100%;border:0;background:none;color:inherit;font:inherit;text-align:left',
            onclick: () => loadBrowser(data.parent_path)}, icon('folder'), h('span', {class: 'name', text: '..'}))));
    }
    for (const entry of data.entries) {
        if (!entry.is_dir && !browser.files) continue;
        rows.push(h('li', {}, h('button', {
            type: 'button', class: 'row', style: 'width:100%;border:0;background:none;color:inherit;font:inherit;text-align:left',
            onclick: () => {
                if (entry.is_dir) loadBrowser(entry.path);
                else { $(browser.target).value = entry.path; $(browser.target).dispatchEvent(new Event('input', {bubbles: true})); $('browser-dialog').close(); }
            },
        }, icon(entry.is_dir ? 'folder' : 'file'), h('span', {class: 'name', text: entry.name}))));
    }
    if (!rows.length || (rows.length === 1 && data.parent_path)) rows.push(h('li', {}, h('p', {class: 'empty', text: t('browser.empty')})));
    list.replaceChildren(...rows);
}

$('browser-select').addEventListener('click', () => {
    if (browser.files) return;
    const input = $(browser.target);
    input.value = browser.path;
    input.dispatchEvent(new Event('input', {bubbles: true}));
    $('browser-dialog').close();
});

// ------------------------------------------------------------------ token dialog

$('token-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const value = $('token-input').value.trim();
    if (!value) return;
    const params = new URLSearchParams(window.location.search);
    params.set('token', value);
    window.location.search = params.toString();
});
$('token-dialog').addEventListener('close', () => { tokenDialogShown = false; });

// ------------------------------------------------------------------ first-start assistant

const wizard = {step: 1, steps: 4};

function showWizardStep(step) {
    wizard.step = step;
    document.querySelectorAll('.wizard-step').forEach(el => { el.hidden = Number(el.dataset.step) !== step; });
    document.querySelectorAll('.steps li').forEach((li, i) => li.classList.toggle('done', i < step));
    $('wizard-step-label').textContent = t('wizard.step', {step, count: wizard.steps});
    $('wizard-back').hidden = step === 1;
    $('wizard-next').textContent = step === wizard.steps ? t('wizard.finish') : t('wizard.next');
    if (step === 3) wizardCameraCheck();
    if (step === 4) {
        const rows = [
            [t('settings.language'), $('wizard-language').value === 'de' ? 'Deutsch' : 'English'],
            [t('settings.plex_root'), $('wizard-plex-root').value],
            [t('settings.dv_root'), $('wizard-dv-root').value],
        ];
        $('wizard-summary').replaceChildren(...rows.flatMap(([a, b]) => [h('dt', {text: a}), h('dd', {text: b})]));
    }
}

async function openWizard() {
    if (!state.settings) await loadSettings(true);
    $('wizard-language').value = lang;
    $('wizard-plex-root').value = (state.settings && state.settings.plex_movies_root) || '';
    $('wizard-dv-root').value = (state.settings && state.settings.dv_import_root) || '';
    $('wizard-error').hidden = true;
    showWizardStep(1);
    if (!$('wizard-dialog').open) $('wizard-dialog').showModal();
}

async function wizardCameraCheck() {
    const box = $('wizard-camera-result');
    box.className = 'check-result';
    box.textContent = t('wizard.camera_looking');
    await loadInfo();
    await loadStatus();
    if (state.info && !state.info.capture.supported) {
        box.className = 'check-result bad';
        box.textContent = t('wizard.camera_unsupported');
    } else if (state.status && state.status.device_available) {
        box.className = 'check-result ok';
        box.textContent = state.info && state.info.demo ? t('wizard.camera_demo') : t('wizard.camera_found');
    } else {
        box.className = 'check-result bad';
        box.textContent = t('wizard.camera_missing');
    }
}

$('wizard-language').addEventListener('change', (event) => { setLanguage(event.target.value); showWizardStep(wizard.step); });
$('wizard-camera-check').addEventListener('click', wizardCameraCheck);
$('wizard-back').addEventListener('click', () => showWizardStep(Math.max(1, wizard.step - 1)));
$('wizard-skip').addEventListener('click', async () => {
    try { await api('/api/settings', {method: 'POST', body: {setup_done: true}}); } catch (_) { /* ask again next time */ }
    $('wizard-dialog').close();
});

$('wizard-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (wizard.step === 2) {
        const plex = $('wizard-plex-root').value.trim();
        const dv = $('wizard-dv-root').value.trim();
        if (!plex || !dv) {
            $('wizard-error').textContent = t('settings.folders_required');
            $('wizard-error').hidden = false;
            return;
        }
        $('wizard-error').hidden = true;
    }
    if (wizard.step < wizard.steps) { showWizardStep(wizard.step + 1); return; }
    try {
        await api('/api/settings', {method: 'POST', body: {
            ui_language: $('wizard-language').value,
            plex_movies_root: $('wizard-plex-root').value.trim(),
            dv_import_root: $('wizard-dv-root').value.trim(),
            setup_done: true,
        }});
        $('wizard-dialog').close();
        toast(t('wizard.saved'), 'ok');
        await loadSettings(true);
        loadInfo();
    } catch (e) {
        $('wizard-error').textContent = e.message;
        $('wizard-error').hidden = false;
        showWizardStep(2);
    }
});

$('wizard-open-btn').addEventListener('click', openWizard);

// ------------------------------------------------------------------ start

function renderEverything() {
    for (const [id, key] of Object.entries(chipKeys)) $(`${id}-text`).textContent = t(key);
    if (state.info) renderSystemFacts();
    renderProfiles();
    renderPostprocessList();
    if (state.cover.videos.length) renderCoverList();
    if (state.movie.videos.length || state.movie.storage) renderMovieList();
    renderMergeQueue();
    if (state.player.projects.length) renderPlayerProjects();
    if (state.activeTab === 'logs') loadLogs();
    tickClock();
    if (state.status) loadStatus();
    if ($('wizard-dialog').open) showWizardStep(wizard.step);
    setCaptureRunning(state.capture.running);
    if (!state.capture.running) setStatus('capture-status', t('capture.ready'));
}

async function start() {
    let storedLang = '';
    let storedTheme = 'auto';
    try {
        storedLang = localStorage.getItem('dv2plex_language') || '';
        storedTheme = localStorage.getItem('dv2plex_theme') || 'auto';
    } catch (_) { /* ignore */ }
    lang = pickLanguage(storedLang);
    applyTheme(storedTheme);
    applyTranslations();
    tickClock();
    setInterval(tickClock, 1000);

    connectWebSocket();
    await loadInfo();
    try { state.settings = await api('/api/settings'); } catch (_) { /* token dialog or offline */ }
    if (state.settings) {
        lang = pickLanguage(state.settings.ui_language);
        applyTheme(state.settings.ui_theme);
        applyTranslations();
        setCoverTabVisible(state.settings.show_cover_tab !== false);
        fillSettings();
    }
    await loadProfiles();
    await loadStatus();
    loadMergeQueue();
    loadPostprocessList();
    renderEverything();

    const initial = window.location.hash.slice(1);
    activateTab(TABS.includes(initial) ? initial : 'capture');

    setInterval(loadStatus, 4000);
    setInterval(loadMergeQueue, 6000);
    if (state.settings && state.settings.setup_done === false && !(state.info && state.info.demo)) openWizard();
}

window.dv2plex = {openWizard, activateTab, setLanguage, applyTheme};
start();
