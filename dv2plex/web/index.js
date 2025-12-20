let ws = null;
let selectedPostprocessMovie = null;
let selectedMovieVideos = [];
let movieItemsByPath = {};
let movieExportAllRunning = false;
let movieExportSingleRunning = false;
let movieMergeRunning = false;
let selectedCoverVideo = null;
let extractedFrames = [];
let selectedFrameIndex = null;
let selectedCoverTitle = null;
let selectedCoverYear = null;
let extractingFrames = false;
let captureStartedAtIso = null;
const COVER_FRAME_COUNT = 8; // mehr zufällige Frames

const THEME_STORAGE_KEY = 'dv2plex_theme';

function normalizeThemeName(theme) {
    return theme === 'xbox360' ? 'xbox360' : 'plex';
}

function applyTheme(theme) {
    const normalized = normalizeThemeName(theme);
    document.body.classList.toggle('theme-xbox360', normalized === 'xbox360');
    try {
        localStorage.setItem(THEME_STORAGE_KEY, normalized);
    } catch (_) {
        // ignore (private mode / disabled storage)
    }
}

function getStoredTheme() {
    try {
        return normalizeThemeName(localStorage.getItem(THEME_STORAGE_KEY));
    } catch (_) {
        return 'plex';
    }
}

function formatElapsed(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function setCaptureStartedAt(isoString) {
    captureStartedAtIso = isoString || null;
}

function updateCaptureTimeUI() {
    const clockEl = document.getElementById('capture-clock');
    if (clockEl) {
        clockEl.textContent = new Date().toLocaleTimeString('de-DE');
    }

    const elapsedEl = document.getElementById('capture-elapsed');
    if (!elapsedEl) return;

    if (!captureStartedAtIso) {
        elapsedEl.textContent = '--:--:--';
        return;
    }

    const start = new Date(captureStartedAtIso);
    if (isNaN(start.getTime())) {
        elapsedEl.textContent = '--:--:--';
        return;
    }
    elapsedEl.textContent = formatElapsed(Date.now() - start.getTime());
}

// WebSocket connection
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
    
    ws.onclose = () => {
        console.log('WebSocket closed, reconnecting...');
        setTimeout(connectWebSocket, 3000);
    };
}

function handleWebSocketMessage(data) {
    switch(data.type) {
        case 'preview_frame':
            updatePreview(data.data);
            break;
        case 'progress':
            updateProgress(data.value, data.operation);
            break;
        case 'status':
            updateStatus(data.status, data.operation, data.data);
            break;
        case 'log':
            addLog(data.message, data.operation);
            addToSystemLogs(data.message);
            break;
        case 'postprocessing_finished':
            handlePostprocessingFinished(data);
            break;
        case 'cover_generation_finished':
            handleCoverGenerationFinished(data);
            break;
        case 'merge_progress':
            updateMergeQueue(data.job);
            break;
    }
}

function updatePreview(imageData) {
    const preview = document.getElementById('preview');
    // Prüfe ob bereits ein img-Element existiert
    let img = preview.querySelector('img');
    if (img) {
        // Nur src aktualisieren für flüssigere Updates
        img.src = imageData;
    } else {
        // Erstes Bild - ersetze Placeholder
        preview.innerHTML = `<img src="${imageData}" alt="Preview">`;
    }
}

function updateProgress(value, operation) {
    if (operation === 'postprocessing') {
        const progress = document.getElementById('postprocess-progress');
        const fill = document.getElementById('postprocess-progress-fill');
        progress.style.display = 'block';
        fill.style.width = value + '%';
        fill.textContent = value + '%';
    } else if (operation === 'cover_generation') {
        const progress = document.getElementById('cover-progress');
        const fill = document.getElementById('cover-progress-fill');
        progress.style.display = 'block';
        fill.style.width = value + '%';
        fill.textContent = value + '%';
    } else if (operation === 'movie_export_all') {
        const progress = document.getElementById('movie-export-progress');
        const fill = document.getElementById('movie-export-progress-fill');
        if (progress && fill) {
            progress.style.display = 'block';
            fill.style.width = value + '%';
            fill.textContent = value + '%';
        }
    } else if (operation === 'movie_export_single' || operation === 'movie_merge') {
        const progress = document.getElementById('movie-export-progress');
        const fill = document.getElementById('movie-export-progress-fill');
        if (progress && fill) {
            progress.style.display = 'block';
            fill.style.width = value + '%';
            fill.textContent = value + '%';
        }
    }
}

let captureStopPoll = null;

function startCaptureStopPoll() {
    if (captureStopPoll) {
        clearInterval(captureStopPoll);
    }
    captureStopPoll = setInterval(async () => {
        try {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            if (!data.capture_running) {
                updateStatus('capture_stopped');
                clearInterval(captureStopPoll);
                captureStopPoll = null;
            }
        } catch (e) {
            console.error('Status-Poll fehlgeschlagen:', e);
        }
    }, 2000);
}

function updateStatus(status, operation, payload = null) {
    const startBtn = document.getElementById('capture-start-btn');
    const stopBtn = document.getElementById('capture-stop-btn');
    const captureStatus = document.getElementById('capture-status');

    if (status === 'capture_started') {
        startBtn.disabled = true;
        stopBtn.disabled = false;
        stopBtn.classList.add('btn-danger');
        captureStatus.textContent = 'Aufnahme läuft...';
        if (payload && payload.started_at) {
            setCaptureStartedAt(payload.started_at);
        }
        if (captureStopPoll) {
            clearInterval(captureStopPoll);
            captureStopPoll = null;
        }
        
        if (payload) {
            if (payload.title) {
                document.getElementById('capture-title').value = payload.title;
            }
            if (payload.year) {
                document.getElementById('capture-year').value = payload.year;
            }
        }
    } else if (status === 'capture_stopping') {
        startBtn.disabled = true;
        stopBtn.disabled = true;
        stopBtn.classList.add('btn-danger');
        captureStatus.textContent = 'Stoppe Aufnahme... Abschluss läuft.';
    } else if (status === 'capture_stopped') {
        startBtn.disabled = false;
        stopBtn.disabled = true;
        stopBtn.classList.remove('btn-danger');
        captureStatus.textContent = 'Fertig! Du kannst das nächste Video digitalisieren.';
        setCaptureStartedAt(null);
        if (captureStopPoll) {
            clearInterval(captureStopPoll);
            captureStopPoll = null;
        }
    }
    
    if (operation === 'postprocessing') {
        const statusEl = document.getElementById('postprocess-status');
        statusEl.textContent = status;
    } else if (operation === 'cover_generation') {
        const statusEl = document.getElementById('cover-status');
        statusEl.textContent = status;
    }

    // Movie Export All status handling
    if (operation === 'movie_export_all') {
        const exportAllBtn = document.getElementById('export-all-btn');
        const movieStatus = document.getElementById('movie-status');
        const progress = document.getElementById('movie-export-progress');
        if (status === 'movie_export_all_started') {
            movieExportAllRunning = true;
            if (exportAllBtn) exportAllBtn.disabled = true;
            if (progress) progress.style.display = 'block';
            if (movieStatus) {
                movieStatus.textContent = `Export All gestartet (${payload?.total ?? '?'} Videos)...`;
                movieStatus.className = 'status';
            }
        } else if (status === 'movie_export_all_finished') {
            movieExportAllRunning = false;
            if (exportAllBtn) exportAllBtn.disabled = false;
            if (movieStatus) {
                movieStatus.textContent = `Export All fertig. Skipped: ${payload?.skipped ?? 0}, Fehler: ${payload?.failed ?? 0}`;
                movieStatus.className = 'status success';
            }
            // Refresh list so exported badges are correct
            loadMovieList();
        } else if (status === 'movie_export_all_failed') {
            movieExportAllRunning = false;
            if (exportAllBtn) exportAllBtn.disabled = false;
            if (movieStatus) {
                movieStatus.textContent = `Export All fehlgeschlagen: ${payload?.error ?? 'Unbekannter Fehler'}`;
                movieStatus.className = 'status error';
            }
        } else if (status === 'movie_export_item_started') {
            markMovieItem(payload?.video_path, 'running');
        } else if (status === 'movie_export_item_done') {
            markMovieItem(payload?.video_path, 'exported');
        } else if (status === 'movie_export_item_skipped') {
            markMovieItem(payload?.video_path, 'exported');
        } else if (status === 'movie_export_item_failed') {
            markMovieItem(payload?.video_path, 'failed', payload?.error);
        }
    }

    // Single export handling (async)
    if (operation === 'movie_export_single') {
        const exportBtn = document.getElementById('export-btn');
        const exportAllBtn = document.getElementById('export-all-btn');
        const movieStatus = document.getElementById('movie-status');
        if (status === 'movie_export_single_started') {
            movieExportSingleRunning = true;
            if (exportBtn) exportBtn.disabled = true;
            if (exportAllBtn) exportAllBtn.disabled = true;
            if (movieStatus) {
                movieStatus.textContent = 'Export gestartet (läuft im Hintergrund)...';
                movieStatus.className = 'status';
            }
            markMovieItem(payload?.video_path, 'running');
            updateMovieButtons();
        } else if (status === 'movie_export_single_done') {
            movieExportSingleRunning = false;
            if (exportBtn) exportBtn.disabled = false;
            if (exportAllBtn) exportAllBtn.disabled = false;
            if (movieStatus) {
                movieStatus.textContent = 'Export fertig.';
                movieStatus.className = 'status success';
            }
            markMovieItem(payload?.video_path, 'exported');
            updateMovieButtons();
            loadMovieList();
        } else if (status === 'movie_export_single_failed') {
            movieExportSingleRunning = false;
            if (exportBtn) exportBtn.disabled = false;
            if (exportAllBtn) exportAllBtn.disabled = false;
            if (movieStatus) {
                movieStatus.textContent = `Export fehlgeschlagen: ${payload?.error ?? 'Unbekannter Fehler'}`;
                movieStatus.className = 'status error';
            }
            markMovieItem(payload?.video_path, 'failed', payload?.error);
            updateMovieButtons();
        }
    }

    // Merge handling (async)
    if (operation === 'movie_merge') {
        const mergeBtn = document.getElementById('merge-btn');
        const movieStatus = document.getElementById('movie-status');
        if (status === 'movie_merge_started') {
            movieMergeRunning = true;
            if (mergeBtn) mergeBtn.disabled = true;
            if (movieStatus) {
                movieStatus.textContent = `Merge gestartet (${payload?.count ?? '?'} Videos) – läuft im Hintergrund...`;
                movieStatus.className = 'status';
            }
            updateMovieButtons();
        } else if (status === 'movie_merge_finished') {
            movieMergeRunning = false;
            if (movieStatus) {
                movieStatus.textContent = 'Merge + Export fertig.';
                movieStatus.className = 'status success';
            }
            updateMovieButtons();
            loadMovieList();
        } else if (status === 'movie_merge_failed') {
            movieMergeRunning = false;
            if (movieStatus) {
                movieStatus.textContent = `Merge fehlgeschlagen: ${payload?.error ?? 'Unbekannter Fehler'}`;
                movieStatus.className = 'status error';
            }
            updateMovieButtons();
        }
    }
}

function markMovieItem(videoPath, state, errorMessage = null) {
    if (!videoPath) return;
    const el = movieItemsByPath[videoPath];
    if (!el) return;
    const badge = el.querySelector('.badge');
    if (!badge) return;
    if (state === 'exported') {
        badge.textContent = 'Exportiert';
        badge.style.background = 'rgba(40, 167, 69, 0.9)';
        badge.style.color = '#000';
        badge.title = '';
    } else if (state === 'running') {
        badge.textContent = 'Export...';
        badge.style.background = 'rgba(229, 160, 13, 0.9)';
        badge.style.color = '#000';
        badge.title = '';
    } else if (state === 'failed') {
        badge.textContent = 'Fehler';
        badge.style.background = 'rgba(220, 53, 69, 0.9)';
        badge.style.color = '#000';
        badge.title = errorMessage || 'Export fehlgeschlagen';
    }
}

function formatBytes(bytes) {
    if (bytes === null || bytes === undefined || isNaN(bytes)) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let v = Number(bytes);
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i++;
    }
    return `${v.toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}

function updateMovieStorageStatus(storage) {
    const el = document.getElementById('movie-storage-status');
    if (!el || !storage) return;
    el.style.display = 'block';

    const free = storage.free_bytes;
    const req = storage.required_bytes;
    const fitsAll = storage.fits_all;

    const freeTxt = free == null ? '—' : formatBytes(free);
    const reqTxt = req == null ? '—' : formatBytes(req);
    const countTxt = storage.required_count ?? 0;
    const rootTxt = storage.plex_root || '';

    el.textContent = `Ziel: ${rootTxt} · Frei: ${freeTxt} · Benötigt (nicht exportiert): ${reqTxt} (${countTxt} Videos) · ${fitsAll ? 'Passt ✅' : 'Zu wenig Speicher ❌'}`;
    el.className = 'status ' + (fitsAll ? 'success' : 'error');
}

async function loadStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        if (data.capture_running) {
            updateStatus('capture_started', null, data.active_capture || null);
            // Starte Polling, um zu erkennen wenn dvgrab von selbst beendet wird
            // (z.B. Band zu Ende, Signal verloren)
            startCaptureStopPoll();
        } else {
            updateStatus('capture_stopped');
        }
        
        if (data.active_capture) {
            if (data.active_capture.title) {
                document.getElementById('capture-title').value = data.active_capture.title;
            }
            if (data.active_capture.year) {
                document.getElementById('capture-year').value = data.active_capture.year;
            }
            if (data.active_capture.started_at) {
                setCaptureStartedAt(data.active_capture.started_at);
            }
        }
    } catch (error) {
        console.error('Status konnte nicht geladen werden:', error);
    }
}

function addLog(message, operation) {
    const logId = operation === 'postprocessing' ? 'postprocess-log' :
                  operation === 'cover_generation' ? 'cover-log' : 'movie-log';
    const log = document.getElementById(logId);
    if (log) {
        log.innerHTML += message + '\\n';
        log.scrollTop = log.scrollHeight;
    }
}

function handlePostprocessingFinished(data) {
    document.getElementById('postprocess-progress').style.display = 'none';
    const status = document.getElementById('postprocess-status');
    status.textContent = data.success ? 'Erfolgreich!' : 'Fehler!';
    status.className = 'status ' + (data.success ? 'success' : 'error');
    loadPostprocessList();
}

function handleCoverGenerationFinished(data) {
    document.getElementById('cover-progress').style.display = 'none';
    const status = document.getElementById('cover-status');
    status.textContent = data.success ? 'Erfolgreich!' : 'Fehler!';
    status.className = 'status ' + (data.success ? 'success' : 'error');
    if (data.message) {
        addLog(data.message, 'cover_generation');
    }
}

// Tab switching
function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    event.target.closest('.tab').classList.add('active');
    document.getElementById(tabName).classList.add('active');
    
    if (tabName === 'postprocess') {
        loadPostprocessList();
    } else if (tabName === 'movie') {
        loadMovieList();
    } else if (tabName === 'cover') {
        loadCoverVideoList();
    } else if (tabName === 'player') {
        loadPlayerProjects();
    } else if (tabName === 'settings') {
        loadSettings();
    }
}

function applyCoverTabVisibility(show) {
    const tab = document.getElementById('tab-cover');
    const content = document.getElementById('cover');
    if (tab) tab.style.display = show ? '' : 'none';
    if (content) content.style.display = show ? '' : 'none';

    // Wenn Cover gerade aktiv ist und wir es ausblenden, auf Capture zurückschalten.
    if (!show && content && content.classList.contains('active')) {
        const captureTab = document.getElementById('tab-capture');
        if (captureTab) captureTab.click();
    }
}

// Capture functions
async function startCapture() {
    const title = document.getElementById('capture-title').value;
    const year = document.getElementById('capture-year').value;
    const autoRewind = document.getElementById('auto-rewind').checked;
    
    if (!title || !year) {
        alert('Bitte Titel und Jahr eingeben');
        return;
    }
    
    try {
        const response = await fetch('/api/capture/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title, year, auto_rewind_play: autoRewind})
        });
        
        const data = await response.json();
        if (response.ok) {
            updateStatus('capture_started', null, {title, year});
            // Starte Polling, um zu erkennen wenn dvgrab von selbst beendet wird
            // (z.B. Band zu Ende, Signal verloren, Inaktivitätsmonitor)
            startCaptureStopPoll();
        } else {
            alert(data.detail || 'Fehler beim Starten der Aufnahme');
        }
    } catch (error) {
        alert('Fehler: ' + error.message);
    }
}

async function stopCapture() {
    try {
        const response = await fetch('/api/capture/stop', {method: 'POST'});
        const data = await response.json();
        if (response.ok) {
            updateStatus('capture_stopping');
            if (data.message) {
                document.getElementById('capture-status').textContent = data.message;
            }
            startCaptureStopPoll();
        } else {
            alert(data.detail || 'Fehler beim Stoppen der Aufnahme');
        }
    } catch (error) {
        alert('Fehler: ' + error.message);
    }
}

async function rewindCamera() {
    await fetch('/api/capture/rewind', {method: 'POST'});
}

async function playCamera() {
    await fetch('/api/capture/play', {method: 'POST'});
}

async function pauseCamera() {
    await fetch('/api/capture/pause', {method: 'POST'});
}

// Load upscaling profiles
async function loadUpscalingProfiles() {
    try {
        const response = await fetch('/api/upscaling/profiles');
        const data = await response.json();
        const select = document.getElementById('profile-select');
        select.innerHTML = '';
        
        data.profiles.forEach(profile => {
            const option = document.createElement('option');
            option.value = profile;
            option.textContent = profile;
            if (profile === data.default_profile) {
                option.selected = true;
            }
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Fehler beim Laden der Profile:', error);
        // Fallback
        const select = document.getElementById('profile-select');
        select.innerHTML = '<option value="realesrgan_2x">realesrgan_2x</option>';
    }
}

// Postprocess functions
async function loadPostprocessList() {
    try {
        const response = await fetch('/api/postprocess/list');
        const data = await response.json();
        const list = document.getElementById('postprocess-list');
        list.innerHTML = '';
        selectedPostprocessMovie = null;
        const delBtn = document.getElementById('postprocess-delete-btn');
        if (delBtn) delBtn.disabled = true;
        
        if (data.movies.length === 0) {
            list.innerHTML = '<div class="list-item">Keine offenen Projekte 🎉</div>';
            return;
        }
        
        data.movies.forEach(movie => {
            const item = document.createElement('div');
            item.className = 'list-item';
            item.textContent = movie.display;
            item.onclick = () => {
                document.querySelectorAll('#postprocess-list .list-item').forEach(i => i.classList.remove('selected'));
                item.classList.add('selected');
                selectedPostprocessMovie = movie.path;
                const delBtn = document.getElementById('postprocess-delete-btn');
                if (delBtn) delBtn.disabled = !selectedPostprocessMovie;
            };
            list.appendChild(item);
        });
    } catch (error) {
        console.error('Fehler beim Laden der Liste:', error);
    }
}

async function deleteSelectedPostprocessProject() {
    if (!selectedPostprocessMovie) {
        alert('Bitte ein Projekt auswählen');
        return;
    }
    if (!confirm('Wirklich löschen? Es werden LowRes und HighRes dieses Projekts entfernt.')) {
        return;
    }
    try {
        const response = await fetch('/api/project/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({paths: [selectedPostprocessMovie]})
        });
        const data = await response.json();
        if (!response.ok) {
            alert(data.detail || 'Fehler beim Löschen');
            return;
        }
        addLog('Projekt gelöscht', 'postprocessing');
        await loadPostprocessList();
        await loadMovieList();
    } catch (error) {
        alert('Fehler: ' + error.message);
    }
}

async function processSelected() {
    if (!selectedPostprocessMovie) {
        alert('Bitte einen Film auswählen');
        return;
    }
    
    const profile = document.getElementById('profile-select').value;
    
    try {
        const response = await fetch('/api/postprocess/process', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({movie_dir: selectedPostprocessMovie, profile_name: profile})
        });
        
        const data = await response.json();
        if (response.ok) {
            document.getElementById('postprocess-status').textContent = 'Postprocessing gestartet...';
            document.getElementById('postprocess-log').innerHTML = '';
        } else {
            alert(data.detail || 'Fehler beim Starten des Postprocessings');
        }
    } catch (error) {
        alert('Fehler: ' + error.message);
    }
}

async function processAll() {
    // Similar to processSelected but for all movies
    const response = await fetch('/api/postprocess/list');
    const data = await response.json();
    if (data.movies.length === 0) {
        alert('Keine Filme zu verarbeiten');
        return;
    }
    
    if (!confirm(`Es werden ${data.movies.length} Filme verarbeitet. Fortfahren?`)) {
        return;
    }
    
    const profile = document.getElementById('profile-select').value;
    for (const movie of data.movies) {
        await fetch('/api/postprocess/process', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({movie_dir: movie.path, profile_name: profile})
        });
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
}

// Movie Mode functions
async function loadMovieList() {
    try {
        const response = await fetch('/api/movie/list');
        const data = await response.json();
        const list = document.getElementById('movie-list');
        list.innerHTML = '';
        movieItemsByPath = {};
        updateMovieStorageStatus(data.storage);
        
        data.videos.forEach(video => {
            const item = document.createElement('div');
            item.className = 'list-item';
            const exported = !!video.exported;
            const badgeText = exported ? 'Exportiert' : 'Nicht exportiert';
            const badgeBg = exported ? 'rgba(40, 167, 69, 0.9)' : 'rgba(153, 153, 153, 0.9)';
            const sizeTxt = formatBytes(video.size_bytes);
            const fitsNow = (video.fits_now === undefined || video.fits_now === null) ? true : !!video.fits_now;
            const fitsIcon = exported ? '✅' : (fitsNow ? '✅' : '❌');
            const fitsTitle = exported
                ? 'Bereits exportiert'
                : (fitsNow ? 'Passt auf die Platte (Stand jetzt)' : 'Zu wenig freier Speicher (Stand jetzt)');
            item.innerHTML = `
                <span class="icon">🎞️</span>
                <span class="name" title="${video.display}">${video.display}</span>
                <span class="badge" style="background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.12); color: var(--plex-text);" title="${fitsTitle}">${fitsIcon} ${sizeTxt}</span>
                <span class="badge" style="background:${badgeBg}; color:#000;" title="${video.expected_target || ''}">${badgeText}</span>
            `;
            item.onclick = () => {
                if (item.classList.contains('selected')) {
                    item.classList.remove('selected');
                    selectedMovieVideos = selectedMovieVideos.filter(v => v !== video.path);
                } else {
                    item.classList.add('selected');
                    selectedMovieVideos.push(video.path);
                }
                updateMovieButtons();
            };
            list.appendChild(item);
            movieItemsByPath[video.path] = item;
        });
    } catch (error) {
        console.error('Fehler beim Laden der Liste:', error);
    }
}

function updateMovieButtons() {
    const mergeBtn = document.getElementById('merge-btn');
    const exportBtn = document.getElementById('export-btn');
    const exportAllBtn = document.getElementById('export-all-btn');
    const deleteBtn = document.getElementById('movie-delete-btn');
    mergeBtn.disabled = selectedMovieVideos.length < 2;
    exportBtn.disabled = selectedMovieVideos.length !== 1;
    if (mergeBtn) mergeBtn.disabled = (selectedMovieVideos.length < 2) || movieMergeRunning;
    if (exportBtn) exportBtn.disabled = (selectedMovieVideos.length !== 1) || movieExportSingleRunning || movieExportAllRunning;
    if (exportAllBtn) exportAllBtn.disabled = movieExportAllRunning || movieExportSingleRunning || movieMergeRunning;
    if (deleteBtn) deleteBtn.disabled = (selectedMovieVideos.length < 1) || movieMergeRunning || movieExportSingleRunning || movieExportAllRunning;
}

async function deleteSelectedMovieProjects() {
    if (!selectedMovieVideos || selectedMovieVideos.length < 1) {
        alert('Bitte mindestens ein Video auswählen');
        return;
    }
    if (!confirm(`Wirklich löschen? Es werden LowRes und HighRes der ausgewählten Projekt(e) entfernt (${selectedMovieVideos.length} Auswahl).`)) {
        return;
    }
    try {
        const response = await fetch('/api/project/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({paths: selectedMovieVideos})
        });
        const data = await response.json();
        if (!response.ok) {
            alert(data.detail || 'Fehler beim Löschen');
            return;
        }
        selectedMovieVideos = [];
        updateMovieButtons();
        await loadMovieList();
        addLog('Projekt(e) gelöscht', 'movie');
    } catch (error) {
        alert('Fehler: ' + error.message);
    }
}

async function exportAllVideos() {
    if (movieExportAllRunning) return;
    if (!confirm('Alle HighRes-Videos werden nach Plex exportiert. Fortfahren?')) {
        return;
    }
    const btn = document.getElementById('export-all-btn');
    if (btn) btn.disabled = true;
    movieExportAllRunning = true;
    updateMovieButtons();
    try {
        const response = await fetch('/api/movie/export-all', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({skip_existing: true})
        });
        const data = await response.json();
        if (!response.ok) {
            movieExportAllRunning = false;
            if (btn) btn.disabled = false;
            updateMovieButtons();
            alert(data.detail || 'Fehler beim Export All');
            return;
        }
        document.getElementById('movie-status').textContent = data.message || 'Export All gestartet...';
        document.getElementById('movie-status').className = 'status';
        addLog(data.message || 'Export All gestartet', 'movie');
    } catch (error) {
        movieExportAllRunning = false;
        if (btn) btn.disabled = false;
        updateMovieButtons();
        alert('Fehler: ' + error.message);
    }
}

async function mergeVideos() {
    if (selectedMovieVideos.length < 2) {
        alert('Bitte mindestens 2 Videos auswählen');
        return;
    }
    
    const title = document.getElementById('movie-title').value;
    const year = document.getElementById('movie-year').value;
    
    if (!title || !year) {
        alert('Bitte Titel und Jahr eingeben');
        return;
    }
    
    if (!confirm(`Es werden ${selectedMovieVideos.length} Videos zu '${title} (${year})' gemerged. Fortfahren?`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/movie/merge', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({video_paths: selectedMovieVideos, title, year})
        });
        
        const data = await response.json();
        if (response.ok) {
            document.getElementById('movie-status').textContent = data.message || 'Merge gestartet...';
            document.getElementById('movie-status').className = 'status';
            addLog(data.message || 'Merge gestartet', 'movie');
            movieMergeRunning = true;
            updateMovieButtons();
        } else {
            alert(data.detail || 'Fehler beim Mergen');
        }
    } catch (error) {
        alert('Fehler: ' + error.message);
    }
}

async function exportVideo() {
    if (selectedMovieVideos.length !== 1) {
        alert('Bitte genau ein Video auswählen');
        return;
    }
    
    if (!confirm('Video wird nach PlexMovies exportiert. Fortfahren?')) {
        return;
    }
    
    try {
        const response = await fetch('/api/movie/export', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({video_path: selectedMovieVideos[0]})
        });
        
        const data = await response.json();
        if (response.ok) {
            document.getElementById('movie-status').textContent = data.message || 'Export gestartet...';
            document.getElementById('movie-status').className = 'status';
            addLog(data.message || 'Export gestartet', 'movie');
            movieExportSingleRunning = true;
            updateMovieButtons();
        } else {
            alert(data.detail || 'Fehler beim Exportieren');
        }
    } catch (error) {
        alert('Fehler: ' + error.message);
    }
}

// Video Player functions
async function loadPlayerProjects() {
    const list = document.getElementById('player-project-list');
    list.innerHTML = '<div style="padding: 14px; color: var(--plex-text-secondary);">Lade Projekte...</div>';
    try {
        const response = await fetch('/api/player/projects');
        const data = await response.json();
        renderPlayerProjects(data.projects || []);
    } catch (error) {
        console.error('Fehler beim Laden der Projekte:', error);
        list.innerHTML = '<div style="padding: 14px; color: var(--plex-text-secondary);">Fehler beim Laden.</div>';
    }
}

function renderPlayerProjects(projects) {
    const list = document.getElementById('player-project-list');
    list.innerHTML = '';
    if (!projects.length) {
        list.innerHTML = '<div style="padding: 14px; color: var(--plex-text-secondary);">Keine Projekte gefunden. Prüfe den DV_Import-Ordner.</div>';
        return;
    }

    projects.forEach(project => {
        const card = document.createElement('div');
        card.className = 'player-card';

        const title = document.createElement('h4');
        title.style.fontWeight = '700';
        title.textContent = project.title;
        card.appendChild(title);

        const lowresSection = document.createElement('div');
        lowresSection.className = 'player-section';
        lowresSection.innerHTML = '<small>LowRes</small>';
        if (project.lowres && project.lowres.length) {
            project.lowres.forEach(file => {
                const chip = document.createElement('div');
                chip.className = 'player-chip';
                chip.textContent = file.name;
                chip.onclick = () => playVideo(file.path, `${project.title} · LowRes · ${file.name}`);
                lowresSection.appendChild(chip);
            });
        } else {
            const empty = document.createElement('div');
            empty.style.fontSize = '12px';
            empty.style.color = 'var(--plex-text-secondary)';
            empty.textContent = 'Keine LowRes-Dateien';
            lowresSection.appendChild(empty);
        }
        card.appendChild(lowresSection);

        const highresSection = document.createElement('div');
        highresSection.className = 'player-section';
        highresSection.innerHTML = '<small>HighRes</small>';
        if (project.highres && project.highres.length) {
            project.highres.forEach(file => {
                const chip = document.createElement('div');
                chip.className = 'player-chip';
                chip.textContent = file.name;
                chip.onclick = () => playVideo(file.path, `${project.title} · HighRes · ${file.name}`);
                highresSection.appendChild(chip);
            });
        } else {
            const empty = document.createElement('div');
            empty.style.fontSize = '12px';
            empty.style.color = 'var(--plex-text-secondary)';
            empty.textContent = 'Keine HighRes-Dateien';
            highresSection.appendChild(empty);
        }
        card.appendChild(highresSection);

        list.appendChild(card);
    });
}

function playVideo(path, label) {
    const video = document.getElementById('player-video');
    const nowPlaying = document.getElementById('player-now-playing');
    const placeholder = document.getElementById('player-placeholder');
    if (!path || !video) return;
    if (placeholder) placeholder.style.display = 'none';
    video.style.display = 'block';
    video.src = `/api/player/stream?path=${encodeURIComponent(path)}`;
    video.play().catch(() => {});
    nowPlaying.textContent = `Spielt: ${label}`;
}

// Cover functions
async function loadCoverVideoList() {
    try {
        const response = await fetch('/api/cover/videos');
        const data = await response.json();
        const list = document.getElementById('cover-video-list');
        list.innerHTML = '';
        
        data.videos.forEach(video => {
            const item = document.createElement('div');
            item.className = 'list-item';
            item.textContent = video.display;
            item.onclick = () => {
                document.querySelectorAll('#cover-video-list .list-item').forEach(i => i.classList.remove('selected'));
                item.classList.add('selected');
                selectedCoverVideo = video.path;
                selectedCoverTitle = video.title || video.display || video.path.split('/').pop();
                selectedCoverYear = video.year || '';
                document.getElementById('extract-frames-btn').disabled = false;
                const meta = document.getElementById('cover-meta');
                meta.style.display = 'block';
                meta.textContent = `Ausgewählt: ${selectedCoverTitle}${selectedCoverYear ? ' (' + selectedCoverYear + ')' : ''}`;
            };
            list.appendChild(item);
        });
    } catch (error) {
        console.error('Fehler beim Laden der Liste:', error);
    }
}

async function extractFrames() {
    if (extractingFrames) return;
    if (!selectedCoverVideo) {
        alert('Bitte ein Video auswählen');
        return;
    }
    
    extractingFrames = true;
    document.getElementById('extract-frames-btn').disabled = true;
    document.getElementById('cover-status').textContent = 'Extrahiere Frames...';
    document.getElementById('cover-status').className = 'status';
    
    try {
        const response = await fetch('/api/cover/extract', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({video_path: selectedCoverVideo, count: COVER_FRAME_COUNT})
        });
        
        const data = await response.json();
        if (response.ok) {
            extractedFrames = data.frames;
            displayFrames(data.frames);
            document.getElementById('cover-status').textContent = `${data.frames.length} Frames extrahiert`;
            document.getElementById('cover-status').className = 'status success';
        } else {
            alert(data.detail || 'Fehler bei Frame-Extraktion');
            document.getElementById('cover-status').textContent = 'Fehler bei Frame-Extraktion';
            document.getElementById('cover-status').className = 'status error';
        }
    } catch (error) {
        alert('Fehler: ' + error.message);
        document.getElementById('cover-status').textContent = 'Fehler: ' + error.message;
        document.getElementById('cover-status').className = 'status error';
    } finally {
        extractingFrames = false;
        document.getElementById('extract-frames-btn').disabled = false;
    }
}

function displayFrames(frames) {
    const grid = document.getElementById('frame-grid');
    grid.innerHTML = '';
    
    frames.forEach((frame, index) => {
        const item = document.createElement('div');
        item.className = 'frame-item';
        item.innerHTML = `<img src="${frame.data}" alt="Frame ${index + 1}">`;
        item.onclick = () => {
            document.querySelectorAll('.frame-item').forEach(f => f.classList.remove('selected'));
            item.classList.add('selected');
            selectedFrameIndex = index;
            document.getElementById('generate-cover-btn').disabled = false;
        };
        grid.appendChild(item);
    });
}

async function generateCover() {
    if (selectedFrameIndex === null || !extractedFrames[selectedFrameIndex]) {
        alert('Bitte einen Frame auswählen');
        return;
    }
    
    const title = selectedCoverTitle || (selectedCoverVideo ? selectedCoverVideo.split('/').pop() : '');
    const year = selectedCoverYear || null;
    
    try {
        const response = await fetch('/api/cover/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                frame_path: extractedFrames[selectedFrameIndex].path,
                title,
                year
            })
        });
        
        const data = await response.json();
        if (response.ok) {
            document.getElementById('cover-status').textContent = 'Generiere Cover...';
            document.getElementById('cover-progress').style.display = 'block';
        } else {
            alert(data.detail || 'Fehler bei Cover-Generierung');
        }
    } catch (error) {
        alert('Fehler: ' + error.message);
    }
}

// Settings functions
let currentBrowserTarget = null;
let currentBrowserPath = '/';

async function fixConfigPermissions() {
    if (!confirm('Config-Berechtigungen korrigieren?\\n\\nDies führt "sudo chown" auf den Config-Ordner aus.')) {
        return;
    }
    
    document.getElementById('settings-status').textContent = 'Korrigiere Berechtigungen...';
    document.getElementById('settings-status').className = 'status';
    
    try {
        const response = await fetch('/api/fix-config-permissions', {
            method: 'POST'
        });
        
        const data = await response.json();
        if (response.ok) {
            document.getElementById('settings-status').textContent = '✓ Berechtigungen korrigiert! Versuche erneut zu speichern.';
            document.getElementById('settings-status').className = 'status success';
        } else {
            throw new Error(data.detail || 'Fehler');
        }
    } catch (error) {
        document.getElementById('settings-status').textContent = 'Fehler: ' + error.message;
        document.getElementById('settings-status').className = 'status error';
    }
}

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        
        document.getElementById('settings-plex-root').value = data.plex_movies_root || '';
        document.getElementById('settings-dv-root').value = data.dv_import_root || '';
        document.getElementById('settings-ffmpeg').value = data.ffmpeg_path || '';
        document.getElementById('settings-auto-postprocess').checked = data.auto_postprocess || false;
        document.getElementById('settings-auto-upscale').checked = data.auto_upscale || false;
        document.getElementById('settings-auto-export').checked = data.auto_export || false;
        const showCover = (data.show_cover_tab === undefined || data.show_cover_tab === null) ? true : !!data.show_cover_tab;
        const coverCb = document.getElementById('settings-show-cover');
        if (coverCb) {
            coverCb.checked = showCover;
            coverCb.onchange = () => applyCoverTabVisibility(coverCb.checked);
        }
        applyCoverTabVisibility(showCover);

        const themeSelect = document.getElementById('settings-theme');
        if (themeSelect) {
            const theme = normalizeThemeName(data.ui_theme || getStoredTheme() || 'plex');
            themeSelect.value = theme;
            applyTheme(theme);
            themeSelect.onchange = () => applyTheme(themeSelect.value);
        }
        
        document.getElementById('settings-status').textContent = 'Einstellungen geladen.';
        document.getElementById('settings-status').className = 'status';
        refreshUpdateStatus();
    } catch (error) {
        console.error('Fehler beim Laden der Einstellungen:', error);
        document.getElementById('settings-status').textContent = 'Fehler beim Laden!';
        document.getElementById('settings-status').className = 'status error';
    }
}

async function saveSettings() {
    const settings = {
        plex_movies_root: document.getElementById('settings-plex-root').value,
        dv_import_root: document.getElementById('settings-dv-root').value,
        ffmpeg_path: document.getElementById('settings-ffmpeg').value,
        auto_postprocess: document.getElementById('settings-auto-postprocess').checked,
        auto_upscale: document.getElementById('settings-auto-upscale').checked,
        auto_export: document.getElementById('settings-auto-export').checked,
        ui_theme: normalizeThemeName(document.getElementById('settings-theme')?.value || getStoredTheme() || 'plex'),
        show_cover_tab: document.getElementById('settings-show-cover')?.checked ?? true
    };

    applyTheme(settings.ui_theme);
    applyCoverTabVisibility(!!settings.show_cover_tab);
    
    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(settings)
        });
        
        const data = await response.json();
        if (response.ok) {
            document.getElementById('settings-status').textContent = '✓ Einstellungen gespeichert!';
            document.getElementById('settings-status').className = 'status success';
        } else {
            throw new Error(data.detail || 'Fehler beim Speichern');
        }
    } catch (error) {
        document.getElementById('settings-status').textContent = 'Fehler: ' + error.message;
        document.getElementById('settings-status').className = 'status error';
    }
}

function setUpdateStatus(text, kind = 'normal') {
    const el = document.getElementById('update-status');
    el.textContent = text;
    el.className = 'status';
    if (kind === 'success') el.classList.add('success');
    if (kind === 'error') el.classList.add('error');
}

async function refreshUpdateStatus() {
    try {
        setUpdateStatus('Lade Update-Status...');
        const response = await fetch('/api/update/status');
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Fehler beim Laden des Update-Status');
        }
        const status = data.status || {};
        const blocked = status.blocked_reason ? ` (blockiert: ${status.blocked_reason})` : '';
        const behind = typeof status.behind === 'number' ? status.behind : '?';
        const remote = status.remote ? status.remote.slice(0, 7) : 'unbekannt';
        const local = status.local ? status.local.slice(0, 7) : 'unbekannt';
        setUpdateStatus(`Local ${local} | Remote ${remote} | Behind ${behind}${blocked}`, 'success');
    } catch (error) {
        console.error(error);
        setUpdateStatus('Fehler beim Laden des Update-Status: ' + error.message, 'error');
    }
}

async function runUpdate() {
    const btn = document.getElementById('update-run-btn');
    btn.disabled = true;
    setUpdateStatus('Update wird ausgeführt...');
    try {
        const response = await fetch('/api/update/run', {method: 'POST'});
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || data.error || 'Update fehlgeschlagen');
        }
        const msg = data.message || (data.success ? 'Update erfolgreich' : 'Kein Update nötig');
        setUpdateStatus(msg, data.success ? 'success' : 'normal');
    } catch (error) {
        setUpdateStatus('Fehler: ' + error.message, 'error');
    } finally {
        btn.disabled = false;
        refreshUpdateStatus();
    }
}

async function applyChown(target) {
    let path;
    if (target === 'plex') {
        path = document.getElementById('settings-plex-root').value;
    } else if (target === 'dv') {
        path = document.getElementById('settings-dv-root').value;
    }
    
    if (!path) {
        alert('Bitte zuerst einen Pfad angeben');
        return;
    }
    
    if (!confirm(`Berechtigungen für "${path}" ändern?\\n\\nDies führt "sudo chown -R" aus.`)) {
        return;
    }
    
    document.getElementById('settings-status').textContent = 'Ändere Berechtigungen...';
    document.getElementById('settings-status').className = 'status';
    
    try {
        const response = await fetch('/api/chown', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: path})
        });
        
        const data = await response.json();
        if (response.ok) {
            document.getElementById('settings-status').textContent = '✓ Berechtigungen erfolgreich geändert!';
            document.getElementById('settings-status').className = 'status success';
        } else {
            throw new Error(data.detail || 'Fehler bei chown');
        }
    } catch (error) {
        document.getElementById('settings-status').textContent = 'Fehler: ' + error.message;
        document.getElementById('settings-status').className = 'status error';
    }
}

function browsePath(target) {
    currentBrowserTarget = target;
    
    // Start path based on current value or default
    let startPath = '/';
    if (target === 'plex') {
        startPath = document.getElementById('settings-plex-root').value || '/home';
    } else if (target === 'dv') {
        startPath = document.getElementById('settings-dv-root').value || '/home';
    } else if (target === 'ffmpeg') {
        startPath = document.getElementById('settings-ffmpeg').value || '/usr/bin';
    }
    
    // Navigate to parent if it's a file
    if (startPath && !startPath.endsWith('/')) {
        const parts = startPath.split('/');
        parts.pop();
        startPath = parts.join('/') || '/';
    }
    
    loadBrowserDirectory(startPath);
    document.getElementById('browser-modal').classList.add('active');
}

async function loadBrowserDirectory(path) {
    try {
        const response = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
        const data = await response.json();
        
        currentBrowserPath = data.current_path;
        document.getElementById('browser-current-path').textContent = data.current_path;
        
        const list = document.getElementById('browser-list');
        list.innerHTML = '';
        
        // Parent directory entry
        if (data.parent_path) {
            const parentItem = document.createElement('div');
            parentItem.className = 'browser-item folder';
            parentItem.innerHTML = '<span class="icon">📁</span><span class="name">..</span>';
            parentItem.onclick = () => loadBrowserDirectory(data.parent_path);
            list.appendChild(parentItem);
        }
        
        // Directory entries
        data.entries.forEach(entry => {
            const item = document.createElement('div');
            item.className = 'browser-item' + (entry.is_dir ? ' folder' : '');
            item.innerHTML = `<span class="icon">${entry.is_dir ? '📁' : '📄'}</span><span class="name">${entry.name}</span>`;
            
            if (entry.is_dir) {
                item.onclick = () => loadBrowserDirectory(entry.path);
            }
            
            list.appendChild(item);
        });
        
        if (data.entries.length === 0) {
            list.innerHTML += '<div class="browser-item" style="color: var(--plex-text-secondary);">Leeres Verzeichnis</div>';
        }
    } catch (error) {
        console.error('Fehler beim Laden:', error);
        document.getElementById('browser-list').innerHTML = '<div class="browser-item error">Fehler: ' + error.message + '</div>';
    }
}

function closeBrowser() {
    document.getElementById('browser-modal').classList.remove('active');
}

function selectCurrentPath() {
    if (currentBrowserTarget === 'plex') {
        document.getElementById('settings-plex-root').value = currentBrowserPath;
    } else if (currentBrowserTarget === 'dv') {
        document.getElementById('settings-dv-root').value = currentBrowserPath;
    } else if (currentBrowserTarget === 'ffmpeg') {
        document.getElementById('settings-ffmpeg').value = currentBrowserPath;
    }
    closeBrowser();
}

// Merge Queue Functions
function updateMergeQueue(job) {
    const container = document.getElementById('merge-queue-container');
    const current = document.getElementById('merge-queue-current');
    const title = document.getElementById('merge-current-title');
    const status = document.getElementById('merge-current-status');
    const progress = document.getElementById('merge-progress-fill');
    const message = document.getElementById('merge-current-message');
    
    if (job) {
        container.style.display = 'block';
        current.style.display = 'block';
        title.textContent = `${job.title} (${job.year})`;
        status.textContent = job.status;
        status.className = 'badge badge-' + job.status;
        progress.style.width = job.progress + '%';
        message.textContent = job.message;
        
        // Update status badge color
        if (job.status === 'completed') {
            status.style.background = '#2ecc71';
        } else if (job.status === 'failed') {
            status.style.background = '#e74c3c';
        } else if (job.status === 'running') {
            status.style.background = 'var(--plex-gold)';
        } else {
            status.style.background = 'var(--plex-text-secondary)';
        }
    }
}

async function loadMergeQueueStatus() {
    try {
        const response = await fetch('/api/merge/queue');
        const data = await response.json();
        
        // Capture-Tab Mini-Widget
        const container = document.getElementById('merge-queue-container');
        const pending = document.getElementById('merge-queue-pending');
        
        if (data.current_job || data.pending_count > 0) {
            container.style.display = 'block';
            
            if (data.current_job) {
                updateMergeQueue(data.current_job);
            }
            
            if (data.pending_count > 0) {
                pending.textContent = `${data.pending_count} Job(s) in der Warteschlange`;
            } else {
                pending.textContent = '';
            }
        } else {
            container.style.display = 'none';
        }

        // Queue-Tab
        const currentBlock = document.getElementById('queue-current');
        const currentTitle = document.getElementById('queue-current-title');
        const currentStatus = document.getElementById('queue-current-status');
        const currentMessage = document.getElementById('queue-current-message');
        const currentProgress = document.getElementById('queue-progress-fill');
        const list = document.getElementById('queue-list');

        if (data.current_job) {
            currentBlock.style.display = 'block';
            currentTitle.textContent = `${data.current_job.title} (${data.current_job.year})`;
            currentStatus.textContent = data.current_job.status;
            currentStatus.className = 'badge badge-' + data.current_job.status;
            currentMessage.textContent = data.current_job.message || '';
            currentProgress.style.width = data.current_job.progress + '%';
        } else {
            currentBlock.style.display = 'none';
        }

        if (data.jobs && data.jobs.length > 0) {
            list.innerHTML = data.jobs.map(j => {
                const color = j.status === 'completed' ? '#2ecc71' :
                              j.status === 'failed' ? '#e74c3c' :
                              j.status === 'running' ? 'var(--plex-gold)' : '#999';
                return `<div style="padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.06); display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-weight: 600;">${j.title} (${j.year})</div>
                        <div style="font-size: 12px; color: var(--plex-text-secondary);">${j.message || ''}</div>
                    </div>
                    <div style="text-align: right;">
                        <div class="badge" style="background: ${color}; color: #000;">${j.status}</div>
                        <div style="font-size: 11px; color: var(--plex-text-secondary);">${j.progress}%</div>
                    </div>
                </div>`;
            }).join('');
        } else {
            list.innerHTML = '<div style="color: var(--plex-text-secondary); padding: 12px;">Keine Jobs in der Queue.</div>';
        }
    } catch (e) {
        console.error('Merge-Queue-Status konnte nicht geladen werden:', e);
    }
}

// Logs Functions
let allLogs = [];

async function refreshLogs() {
    try {
        const response = await fetch('/api/logs?limit=200');
        const data = await response.json();
        allLogs = data.logs;
        filterLogs();
    } catch (e) {
        console.error('Logs konnten nicht geladen werden:', e);
    }
}

function filterLogs() {
    const filter = document.getElementById('log-filter').value;
    const container = document.getElementById('system-logs');
    
    let filteredLogs = allLogs;
    if (filter) {
        filteredLogs = allLogs.filter(l => l.category === filter);
    }
    
    if (filteredLogs.length === 0) {
        container.innerHTML = '<div style="color: var(--plex-text-secondary); padding: 20px; text-align: center;">Keine Logs vorhanden</div>';
        return;
    }
    
    container.innerHTML = filteredLogs.map(log => {
        const time = new Date(log.timestamp).toLocaleTimeString('de-DE');
        const categoryColor = log.category === 'merge' ? 'var(--plex-gold)' : 
                             log.category === 'capture' ? 'var(--plex-orange)' : '#999';
        return `<div style="margin-bottom: 4px; border-left: 3px solid ${categoryColor}; padding-left: 8px;">
            <span style="color: var(--plex-text-secondary); font-size: 10px;">[${time}]</span>
            <span>${log.message}</span>
        </div>`;
    }).join('');
    
    // Scroll to bottom
    container.scrollTop = container.scrollHeight;
}

function addToSystemLogs(message) {
    const container = document.getElementById('system-logs');
    const time = new Date().toLocaleTimeString('de-DE');
    
    // Add to allLogs
    allLogs.push({
        timestamp: new Date().toISOString(),
        message: message,
        category: 'general'
    });
    
    // Keep only last 200
    if (allLogs.length > 200) {
        allLogs = allLogs.slice(-200);
    }
    
    // Add to DOM
    const div = document.createElement('div');
    div.style.marginBottom = '4px';
    div.style.borderLeft = '3px solid #999';
    div.style.paddingLeft = '8px';
    div.innerHTML = `<span style="color: var(--plex-text-secondary); font-size: 10px;">[${time}]</span>
        <span>${message}</span>`;
    container.appendChild(div);
    
    // Scroll to bottom
    container.scrollTop = container.scrollHeight;
}

async function clearLogs() {
    try {
        await fetch('/api/logs/clear', { method: 'POST' });
        allLogs = [];
        document.getElementById('system-logs').innerHTML = 
            '<div style="color: var(--plex-text-secondary); padding: 20px; text-align: center;">Logs gelöscht</div>';
    } catch (e) {
        console.error('Logs konnten nicht gelöscht werden:', e);
    }
}

// Periodic status updates
setInterval(() => {
    loadMergeQueueStatus();
}, 5000);

// Clock/Dauer im Digitalisieren-Tab
setInterval(() => {
    updateCaptureTimeUI();
}, 1000);

// Initialize
applyTheme(getStoredTheme());
connectWebSocket();
loadStatus();
updateCaptureTimeUI();
loadUpscalingProfiles();
loadPostprocessList();
loadSettings();
loadMergeQueueStatus();
refreshLogs();
