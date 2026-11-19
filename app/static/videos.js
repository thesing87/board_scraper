// 동영상: NAS 동영상 폴더 둘러보기와 브라우저에서 바로 재생 (관리자 전용).
// - 주소의 #d=폴더 는 목록, #v=영상 은 재생 화면 (뒤로 가기로 목록에 돌아옴)
// - 로그인은 다른 페이지와 같은 로그인 키(localStorage admin_token). 영상·썸네일 요청에는 키를 담을 수 없어서
//   키를 한 번 보내 동영상 API에만 쓰는 쿠키를 받아 둠 (/api/videos/session)
// - 재생은 브라우저의 기본 재생기(<video>). 서버가 Range 요청을 받아 원하는 위치로 바로 건너뜀
// - 보던 위치는 서버에 저장해 폰·PC에서 이어 봄
'use strict';

(function () {
    const TOKEN_KEY = 'admin_token';
    const SAVE_EVERY_MS = 10000;
    // 이보다 앞이거나 끝에 가까우면 이어 보기 대신 처음부터
    const RESUME_MIN = 10, RESUME_END_MARGIN = 20;
    // 이만큼도 안 보고 닫은 영상은 이어 보기에 올리지 않음 (초)
    const SAVE_MIN = 5;
    // 영상이 이만큼 안 열리면 '준비 중' 안내
    const PREP_NOTICE_MS = 1500;
    // 재생 시작 뒤 이만큼 지나 다음 영상 미리 고치기 (처음 받는 데이터와 디스크를 다투지 않게)
    const NEXT_PREPARE_DELAY_MS = 15000;
    const STATS_KEY = 'videos_stats_open';
    // 소리 크기·음소거: 모든 영상에 같은 값을 쓰고 이 기기에 저장 (다음 영상·다시 열어도 그대로)
    const VOLUME_KEY = 'videos_volume';
    // 건너뛴 프레임이 이 비율을 넘으면 기기 성능 부족으로 봄
    const DROP_BAD_RATIO = 0.05;
    // 변환 진행 상황을 다시 묻는 간격
    const CONVERT_POLL_MS = 2000;
    // ffmpeg 화면 형식 이름 → 안내에 쓸 이름
    const CODEC_NAMES = { mpeg4: 'MPEG-4 Part 2(DivX·Xvid)', msmpeg4v3: 'MS MPEG-4(DivX 3)', msmpeg4v2: 'MS MPEG-4', wmv3: 'WMV', wmv2: 'WMV',
                          wmv1: 'WMV', vc1: 'VC-1(WMV)', mpeg1video: 'MPEG-1', mpeg2video: 'MPEG-2', flv1: 'FLV', indeo5: 'Indeo' };

    const $ = id => document.getElementById(id);
    const esc = v => String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const enc = encodeURIComponent;
    const storageGet = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch (e) { return fallback; } };
    const storageSet = (key, value) => { try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key); } catch (e) { /* 저장 불가 */ } };
    const fmtTime = sec => {
        sec = Math.max(0, Math.floor(sec || 0));
        const h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60;
        return (h ? `${h}:${String(m).padStart(2, '0')}` : `${m}`) + `:${String(s).padStart(2, '0')}`;
    };
    const fmtMinutes = sec => sec >= 3600 ? `${Math.floor(sec / 3600)}시간 ${Math.round(sec / 60) % 60}분` : `${Math.max(1, Math.round(sec / 60))}분`;
    const fmtSize = bytes => bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)}GB` : `${Math.max(1, Math.round(bytes / 1e6))}MB`;

    // ==========================================
    // 서버 통신
    // ==========================================
    class LoginNeeded extends Error {}

    async function getJson(url) {
        const res = await fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
        if (res.status === 401) throw new LoginNeeded();
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(`서버 오류 (${res.status})`);
        return res.json();
    }

    async function postJson(url, body, keepalive) {
        const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
                                       credentials: 'same-origin', keepalive: !!keepalive });
        let data = {};
        try { data = await res.json(); } catch (e) { /* 본문 없음 */ }
        return { status: res.status, data };
    }

    async function renewSession() {
        const token = storageGet(TOKEN_KEY, '');
        if (!token) return false;
        const { status } = await postJson('/api/videos/session', { password: token });
        if (status === 401) storageSet(TOKEN_KEY, '');
        return status === 200;
    }

    async function api(url) {
        try {
            return await getJson(url);
        } catch (e) {
            if (!(e instanceof LoginNeeded)) throw e;
            if (await renewSession()) return getJson(url);
            throw e;
        }
    }

    function showLogin() {
        closePlayerView();
        $('content').hidden = true;
        $('notice').hidden = true;
        $('login').hidden = false;
        $('login-password').focus();
    }

    $('login').addEventListener('submit', async e => {
        e.preventDefault();
        const password = $('login-password').value;
        if (!password) return;
        $('login-error').textContent = '';
        const { status, data } = await postJson('/api/videos/session', { password });
        if (status === 200 && data.token) {
            storageSet(TOKEN_KEY, data.token);
            $('login-password').value = '';
            $('login').hidden = true;
            route();
        } else {
            $('login-error').textContent = String(data.message || '로그인하지 못했습니다.').replace(/^❌\s*/, '');
        }
    });

    // ==========================================
    // 목록
    // ==========================================
    const FOLDER_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path></svg>';
    const thumbUrl = path => `/api/videos/thumb?p=${enc(path)}`;
    const fileUrl = (path, download) => `/api/videos/file?p=${enc(path)}${download ? '&download=1' : ''}`;
    const videoHref = path => `#v=${enc(path)}`;
    const dirHref = path => path ? `#d=${enc(path)}` : '#';
    const scrollMemory = {};
    let currentDir = '';
    let currentList = [];

    function progressRatio(p) {
        if (!p || !p.duration) return 0;
        return Math.min(1, p.position / p.duration);
    }

    function videoTile(v, sub) {
        const ratio = progressRatio(v.progress);
        const watched = v.progress && v.progress.duration - v.progress.position <= RESUME_END_MARGIN;
        const conv = convertLabel(v);
        return `<a class="tile${conv ? ' is-unplayable' : ''}" href="${videoHref(v.path)}" data-path="${esc(v.path)}">
            <span class="thumb"><img src="${thumbUrl(v.path)}" alt="" loading="lazy" decoding="async">
                <span class="tag tag-ext">${esc(v.ext)}</span>
                ${v.subtitle ? '<span class="tag tag-sub">자막</span>' : ''}
                ${conv ? `<span class="tag tag-no">${esc(conv)}</span>` : ''}
                ${v.progress && v.progress.duration ? `<span class="tag tag-time">${watched ? '다 봄' : `${fmtTime(v.progress.position)} / ${fmtTime(v.progress.duration)}`}</span>` : ''}
                ${ratio ? `<span class="bar"><i style="width:${(ratio * 100).toFixed(1)}%"></i></span>` : ''}</span>
            <span class="tile-name">${esc(v.name)}</span>
            <span class="tile-sub">${esc(sub ?? fmtSize(v.size))}</span></a>`;
    }

    // 변환이 필요한데 아직 안 된 영상의 칸 위 글자 (필요 없거나 다 됐으면 빈 글자)
    function convertLabel(v) {
        if (v.converted || !v.convert) return '';
        const job = v.job;
        if (job && job.state === 'running') return `변환 중 ${Math.floor((job.progress || 0) * 100)}%`;
        if (job && job.state === 'queued') return job.auto ? '자동 변환 대기' : '변환 대기';
        if (job && job.state === 'failed') return '변환 실패';
        return '변환 필요';
    }

    function renderConvertBar(list) {
        const waiting = list.filter(v => v.convert && !v.converted && !(v.job && ['queued', 'running'].includes(v.job.state)));
        $('conv-bar').hidden = !waiting.length;
        $('conv-bar-text').textContent = `이 폴더에 브라우저가 못 여는 영상 ${waiting.length}개`;
    }

    $('conv-folder').addEventListener('click', async () => {
        $('conv-folder').disabled = true;
        const { status, data } = await postJson('/api/videos/convert', { action: 'folder', path: currentDir });
        $('conv-folder').disabled = false;
        if (status === 200) {
            $('conv-bar-text').textContent = `${data.queued}개를 자동 변환 순서에 넣었습니다.`;
            setTimeout(() => showLibrary(currentDir), 1500);
        } else {
            $('conv-bar-text').textContent = String(data.message || '예약하지 못했습니다.').replace(/^❌\s*/, '');
        }
    });

    // 폴더 칸: 처음에는 폴더 대표 한 장, 안의 영상 목록을 받으면(loadSamples) 여러 장을 작게 모아 보여 줌
    function folderTile(d) {
        return `<a class="tile is-folder" href="${dirHref(d.path)}" data-path="${esc(d.path)}">
            <span class="thumb"><span class="mosaic"><img src="${thumbUrl(d.path)}" alt="" loading="lazy" decoding="async"></span>
                <span class="tag tag-folder">${FOLDER_ICON}<span class="folder-label">폴더</span></span></span>
            <span class="tile-name">${esc(d.name)}</span></a>`;
    }

    async function loadSamples(path) {
        let data;
        try { data = await api(`/api/videos/samples?p=${enc(path)}`); } catch (e) { return; }
        if (!data || currentDir !== path || $('content').hidden) return;
        $('folders').querySelectorAll('.tile.is-folder').forEach(tile => {
            const list = data.samples[tile.dataset.path];
            if (!list) return;
            if (list.length >= 2) {
                const shown = list.slice(0, 4);
                const mosaic = tile.querySelector('.mosaic');
                mosaic.className = `mosaic is-${shown.length}`;
                mosaic.innerHTML = shown.map(p => `<img src="${thumbUrl(p)}" alt="" loading="lazy" decoding="async">`).join('');
            }
            tile.querySelector('.folder-label').textContent = list.length >= 4 ? '폴더' : `영상 ${list.length}개`;
        });
    }

    function recentTile(r) {
        return videoTile({ ...r, ext: r.path.split('.').pop(), subtitle: false }, r.folder || '전체');
    }

    // 썸네일을 못 뽑으면(영상이 깨졌거나 아직 못 읽음) 재생 표시가 든 빈 칸
    document.addEventListener('error', e => {
        const img = e.target;
        if (!(img instanceof HTMLImageElement)) return;
        if (img.parentElement.classList.contains('mosaic') && img.parentElement.children.length > 1) {
            img.classList.add('is-missing');
            img.removeAttribute('src');
            return;
        }
        const holder = img.closest('.thumb');
        if (!holder) return;
        holder.classList.add('no-thumb');
        img.remove();
    }, true);

    function renderCrumbs(path) {
        const parts = path ? path.split('/') : [];
        const items = [parts.length ? '<a href="#">전체</a>' : '<span class="here">전체</span>'];
        parts.forEach((part, i) => {
            const sub = parts.slice(0, i + 1).join('/');
            items.push('<span class="sep">›</span>');
            items.push(i === parts.length - 1 ? `<span class="here">${esc(part)}</span>` : `<a href="${dirHref(sub)}">${esc(part)}</a>`);
        });
        $('crumbs').innerHTML = items.join('');
    }

    function showNotice(html) {
        $('login').hidden = true;
        $('content').hidden = true;
        $('notice').hidden = false;
        $('notice').innerHTML = html;
    }

    async function showLibrary(path) {
        closePlayerView();
        let data;
        try {
            await player.pendingSave;
            data = await api(`/api/videos/list?p=${enc(path)}`);
        } catch (e) {
            if (e instanceof LoginNeeded) { showLogin(); return; }
            showNotice(`목록을 불러오지 못했습니다. ${esc(e.message || '')}`);
            return;
        }
        if (data && data.configured === false) {
            showNotice('동영상 폴더가 연결되지 않았습니다.<br>NAS의 동영상 폴더를 웹서버 컨테이너의 <code>/videos</code>에 연결해 주세요.');
            return;
        }
        if (!data) {
            if (path) { location.replace('#'); return; }
            showNotice('동영상 폴더를 찾을 수 없습니다.');
            return;
        }
        $('login').hidden = true;
        $('notice').hidden = true;
        $('content').hidden = false;
        document.title = data.name ? `${data.name} · 동영상` : '동영상';
        renderCrumbs(data.path);
        currentList = data.videos;
        const recent = data.recent || [];
        $('recent').hidden = !recent.length;
        $('recent-list').innerHTML = recent.map(recentTile).join('');
        $('folders').innerHTML = data.dirs.map(folderTile).join('');
        if (data.dirs.length) loadSamples(data.path);
        $('videos').innerHTML = data.videos.map(v => videoTile(v)).join('');
        renderConvertBar(data.videos);
        $('empty').hidden = !!(data.dirs.length || data.videos.length);
        window.scrollTo(0, scrollMemory[path] || 0);
    }

    // ==========================================
    // 재생
    // ==========================================
    const video = $('video');

    function applyVolume() {
        let saved = null;
        try { saved = JSON.parse(storageGet(VOLUME_KEY, 'null')); } catch (e) { saved = null; }
        if (!saved || typeof saved.volume !== 'number') return;
        video.volume = Math.min(1, Math.max(0, saved.volume));
        video.muted = !!saved.muted;
    }
    applyVolume();
    // 브라우저 기본 재생기의 소리 단추·막대로 바꾸면 저장
    video.addEventListener('volumechange', () => {
        storageSet(VOLUME_KEY, JSON.stringify({ volume: Math.round(video.volume * 100) / 100, muted: video.muted }));
    });
    // 다른 창(탭)에서 바꾸면 이 창에도 맞춤
    window.addEventListener('storage', e => { if (e.key === VOLUME_KEY) applyVolume(); });
    const player = { path: null, timer: null, lastSaved: null, pendingSave: null, resumeAt: 0 };

    function saveProgress(keepalive) {
        if (!player.path || !isFinite(video.duration) || !video.duration) return;
        const position = Math.round(video.currentTime * 10) / 10;
        if (position < SAVE_MIN && !player.saved) return;
        player.saved = true;
        const key = `${player.path}:${Math.round(position)}`;
        if (player.lastSaved === key) return;
        player.lastSaved = key;
        player.pendingSave = postJson('/api/videos/progress', { path: player.path, position, duration: Math.round(video.duration * 10) / 10 }, keepalive)
            .catch(() => { player.lastSaved = null; });
    }

    // ==========================================
    // 재생 정보: 미리 받아 둔 시간·받는 속도·멈춰서 기다린 횟수(네트워크), 건너뛴 프레임(기기 성능)
    // 받는 속도는 '미리 받아 둔 끝 지점이 1초에 몇 초분 늘었는지 × 영상 평균 비트레이트'로 어림함
    // ==========================================
    // frames: 1초마다 (건너뛴 프레임 수, 그린 프레임 수). 건너뛰기·이어 보기 직후에는 키프레임부터 목표 위치까지 풀고 버린 프레임이
    // '건너뛴 프레임'으로 잡혀(이 NAS 영상은 키프레임이 10초마다라 수백 장) 기기 성능 문제로 잘못 보이므로, 그동안은 세지 않음
    const stats = { timer: null, waits: 0, lastEnd: null, lastAt: 0, speeds: [], frames: [], dropped: 0, total: 0, quietUntil: 0 };
    const FRAME_WINDOW = 10;     // 최근 몇 초의 프레임으로 판단할지
    const SEEK_QUIET_MS = 3000;  // 건너뛰기·재생 시작 뒤 프레임을 세지 않는 시간

    function bufferedAhead() {
        const t = video.currentTime;
        for (let i = 0; i < video.buffered.length; i++) {
            if (video.buffered.start(i) <= t + 0.5 && video.buffered.end(i) >= t) return { ahead: video.buffered.end(i) - t, end: video.buffered.end(i) };
        }
        return { ahead: 0, end: t };
    }

    const mbps = bits => `${(bits / 1e6).toFixed(bits >= 1e7 ? 0 : 1)}Mbps`;

    function resetStats() {
        stats.waits = 0;
        stats.lastEnd = null;
        stats.speeds = [];
        const q = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : null;
        stats.frames = [];
        stats.dropped = 0;
        stats.total = 0;
        stats.quietUntil = performance.now() + SEEK_QUIET_MS;
        stats.last = q ? [q.droppedVideoFrames, q.totalVideoFrames] : null;
    }

    function renderStats() {
        if ($('stats').hidden || !player.path) return;
        const info = currentList.find(v => v.path === player.path);
        const bitrate = info && info.size && isFinite(video.duration) && video.duration ? info.size * 8 / video.duration : 0;
        const { ahead, end } = bufferedAhead();
        const now = performance.now();
        if (stats.lastEnd != null && end >= stats.lastEnd && now > stats.lastAt) {
            const grew = (end - stats.lastEnd) / ((now - stats.lastAt) / 1000);
            // 다 받아 두면 더 늘지 않으므로 그때는 속도를 세지 않음
            if (end < video.duration - 1) { stats.speeds.push(grew * bitrate); if (stats.speeds.length > 5) stats.speeds.shift(); }
        }
        stats.lastEnd = end;
        stats.lastAt = now;
        const speed = stats.speeds.length ? stats.speeds.reduce((a, b) => a + b, 0) / stats.speeds.length : null;
        const q = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : null;
        // 재생 중이고 건너뛰기 직후가 아닐 때만 1초 동안 늘어난 만큼을 셈
        if (q && stats.last) {
            const d = q.droppedVideoFrames - stats.last[0], t = q.totalVideoFrames - stats.last[1];
            if (!video.paused && !video.seeking && now > stats.quietUntil && t >= 0 && d >= 0) {
                stats.frames.push([d, t]);
                if (stats.frames.length > FRAME_WINDOW) stats.frames.shift();
                stats.dropped += d;
                stats.total += t;
            }
        }
        if (q) stats.last = [q.droppedVideoFrames, q.totalVideoFrames];
        const recent = stats.frames.reduce((acc, [d, t]) => [acc[0] + d, acc[1] + t], [0, 0]);
        const dropped = q ? recent[0] : null;
        const total = q ? recent[1] : null;
        const dropRatio = total ? dropped / total : 0;

        const set = (id, text, cls) => { const el = $(id); el.textContent = text; el.className = cls || ''; };
        const full = end >= video.duration - 1;
        set('st-buffer', full ? '끝까지 받음' : `${ahead.toFixed(1)}초`, ahead < 3 && !full && !video.paused ? 'is-bad' : ahead >= 10 || full ? 'is-ok' : '');
        set('st-speed', speed == null ? (full ? '–' : '재는 중') : mbps(speed), speed != null && bitrate && speed < bitrate ? 'is-bad' : speed != null ? 'is-ok' : '');
        set('st-bitrate', bitrate ? mbps(bitrate) : '–');
        set('st-waits', `${stats.waits}번`, stats.waits ? 'is-bad' : '');
        set('st-dropped', q ? `최근 ${stats.frames.length}초 ${dropped} / ${total} (${(dropRatio * 100).toFixed(1)}%) · 전체 ${stats.dropped}` : '이 브라우저는 알 수 없음',
            dropRatio > DROP_BAD_RATIO ? 'is-bad' : '');
        set('st-size', video.videoWidth ? `${video.videoWidth}×${video.videoHeight}` : '–');

        let verdict = '재생 중 문제 없음', cls = 'is-ok';
        if (stats.waits && (ahead < 1 || (speed != null && bitrate && speed < bitrate))) {
            verdict = '네트워크가 느려 멈춤: 받는 속도가 영상에 필요한 속도보다 느립니다'; cls = 'is-bad';
        } else if (dropRatio > DROP_BAD_RATIO && stats.frames.length >= 5 && total > 60) {
            verdict = '기기가 영상을 푸는 속도가 부족해 화면이 끊김'; cls = 'is-bad';
        } else if (stats.waits) {
            verdict = '잠깐 멈췄던 적이 있음 (건너뛰기 직후라면 정상)'; cls = '';
        }
        $('stats-verdict').textContent = verdict;
        $('stats-verdict').className = `stats-verdict ${cls}`;
    }

    function setStatsOpen(open) {
        $('stats').hidden = !open;
        $('stats-btn').setAttribute('aria-pressed', String(open));
        storageSet(STATS_KEY, open ? '1' : '');
        clearInterval(stats.timer);
        if (open) { renderStats(); stats.timer = setInterval(renderStats, 1000); }
    }
    $('stats-btn').addEventListener('click', () => setStatsOpen($('stats').hidden));
    // 재생 중에 데이터가 모자라 멈춤 (건너뛰기 직후의 기다림은 세지 않음)
    let seekingAt = 0;
    video.addEventListener('seeking', () => { seekingAt = performance.now(); stats.lastEnd = null; stats.quietUntil = seekingAt + SEEK_QUIET_MS; stats.frames = []; });
    video.addEventListener('playing', () => { stats.quietUntil = Math.max(stats.quietUntil, performance.now() + 1000); });
    video.addEventListener('waiting', () => { if (performance.now() - seekingAt > 1500 && video.currentTime > 0.5) stats.waits++; });

    function nextVideo() {
        const i = currentList.findIndex(v => v.path === player.path);
        return i >= 0 ? currentList.slice(i + 1).find(v => v.playable) : null;
    }

    function showMessage(html) {
        $('player-msg').innerHTML = html;
        $('player-msg').hidden = false;
    }

    async function openPlayer(path) {
        // 쿠키가 없으면 먼저 받아 둠 (영상 요청은 401을 알 수 없으므로)
        try {
            const probe = await api(`/api/videos/list?p=${enc(path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '')}`);
            if (probe && probe.videos) currentList = probe.videos;
        } catch (e) {
            if (e instanceof LoginNeeded) { showLogin(); return; }
        }
        const info = currentList.find(v => v.path === path);
        if ($('content').hidden === false) scrollMemory[currentDir] = window.scrollY;
        player.path = path;
        player.lastSaved = null;
        // 전에 본 영상이면 처음으로 되감은 위치도 저장 (안 본 영상은 SAVE_MIN초 넘게 봐야 저장)
        player.saved = !!(info && info.progress);
        const name = info ? info.name : path.split('/').pop();
        $('player-title').textContent = name;
        document.title = `${name} · 동영상`;
        $('player-download').href = fileUrl(path, true);
        $('player-download').setAttribute('download', '');
        $('player-msg').hidden = true;
        $('resume').hidden = true;
        $('player-next').hidden = true;
        $('player').hidden = false;
        document.body.classList.add('is-playing');
        video.innerHTML = '';
        if (info && info.subtitle) {
            const track = document.createElement('track');
            track.kind = 'subtitles';
            track.label = '한국어';
            track.srclang = 'ko';
            track.src = `/api/videos/subs?p=${enc(path)}`;
            track.default = true;
            video.appendChild(track);
        }
        const saved = info && info.progress;
        player.resumeAt = saved && saved.position > RESUME_MIN && saved.duration - saved.position > RESUME_END_MARGIN ? saved.position : 0;
        clearTimeout(player.convTimer);
        video.removeAttribute('src');
        video.load();
        let st = null;
        try { st = await api(`/api/videos/status?p=${enc(path)}`); } catch (e) { /* 모르면 그냥 재생해 봄 */ }
        if (player.path !== path) return;
        if (st && st.mode !== 'direct' && !st.converted) {
            showConvert(path, st);
            return;
        }
        startPlayback(path);
    }

    // ==========================================
    // 변환 (브라우저가 못 여는 영상: video_convert.py)
    // ==========================================
    function convertButtons(buttons) {
        return `<div class="conv-actions">${buttons.join('')}</div>`;
    }

    function showConvert(path, st) {
        const info = st.info || {};
        const job = st.job;
        const codec = CODEC_NAMES[info.video] || info.video || '알 수 없음';
        const length = info.duration ? ` · 길이 ${fmtTime(info.duration)}` : '';
        const dl = `<a href="${fileUrl(path, true)}" download>내려받기</a>`;
        let html;
        if (job && job.state === 'running') {
            const pct = Math.floor((job.progress || 0) * 100);
            const left = job.speed && info.duration ? ` · 남은 시간 약 ${fmtMinutes(info.duration * (1 - (job.progress || 0)) / job.speed)}` : '';
            const what = st.mode === 'remux' ? '브라우저에 맞게 포장을 바꾸는 중' : '브라우저용으로 변환하는 중';
            html = `<b>${what}… ${pct}%</b><div class="conv-bar-track"><i style="width:${pct}%"></i></div>`
                + `<small>${job.speed ? `실시간의 ${job.speed.toFixed(1)}배 속도${left}` : '속도 재는 중'}. 창을 닫아도 계속 변환합니다.</small>`
                + convertButtons(['<button type="button" data-conv="cancel" class="is-sub">변환 취소</button>']);
        } else if (job && job.state === 'queued') {
            html = job.auto
                ? `<b>자동 변환 순서를 기다리는 중입니다</b><small>직접 고른 변환이 끝난 뒤 차례로 변환합니다. 먼저 보려면 지금 변환하세요 (예상 약 ${fmtMinutes(st.estimate || 0)}).</small>`
                    + convertButtons(['<button type="button" data-conv="start">지금 변환</button>', '<button type="button" data-conv="cancel" class="is-sub">자동 변환 안 함</button>'])
                : '<b>변환 대기 중</b><small>앞의 변환이 끝나면 바로 시작합니다.</small>'
                    + convertButtons(['<button type="button" data-conv="cancel" class="is-sub">취소</button>']);
        } else if (job && job.state === 'failed') {
            html = `<b>변환하지 못했습니다</b><small>${esc(job.error || '')}</small>`
                + convertButtons(['<button type="button" data-conv="start">다시 시도</button>', dl]);
        } else if (st.mode === 'remux') {
            // 화면은 그대로 쓰고 포장·소리만 바꾸면 되는 영상: 금방 끝나므로 바로 시작
            html = '<b>브라우저에 맞게 준비하는 중…</b><small>화면은 그대로 두고 포장·소리만 바꿉니다. 보통 1분 안에 끝납니다.</small>';
            postJson('/api/videos/convert', { action: 'start', path }).then(({ status, data }) => {
                if (player.path === path && status === 200) showConvert(path, data);
            });
        } else {
            html = `<b>이 영상은 변환해야 볼 수 있습니다</b>`
                + `<small>화면 형식 ${esc(codec)}${info.height ? ` · ${info.width}×${info.height}` : ''}${length}<br>`
                + `브라우저가 이 형식을 풀지 못해 NAS에서 MP4로 바꿔 둡니다. 예상 약 ${fmtMinutes(st.estimate || 0)} (한 번만, 원본은 그대로).</small>`
                + convertButtons(['<button type="button" data-conv="start">지금 변환</button>', dl]);
        }
        showMessage(html);
        $('player-msg').classList.add('is-convert');
        clearTimeout(player.convTimer);
        // 대기·진행 중이면 계속 물어보다가 다 되면 바로 재생
        if (job && ['queued', 'running'].includes(job.state)) {
            player.convTimer = setTimeout(() => pollConvert(path), CONVERT_POLL_MS);
        }
    }

    async function pollConvert(path) {
        if (player.path !== path) return;
        let st = null;
        try { st = await api(`/api/videos/status?p=${enc(path)}`); } catch (e) { /* 잠깐 끊김: 다시 */ }
        if (player.path !== path) return;
        if (!st) { player.convTimer = setTimeout(() => pollConvert(path), CONVERT_POLL_MS * 2); return; }
        if (st.converted || st.mode === 'direct') {
            $('player-msg').hidden = true;
            startPlayback(path);
            return;
        }
        showConvert(path, st);
    }

    $('player-msg').addEventListener('click', async e => {
        const btn = e.target.closest('[data-conv]');
        if (!btn || !player.path) return;
        const path = player.path;
        btn.disabled = true;
        const { status, data } = await postJson('/api/videos/convert', { action: btn.dataset.conv, path });
        if (player.path !== path) return;
        if (status === 200) showConvert(path, data);
        else { btn.disabled = false; showMessage(esc(String(data.message || '처리하지 못했습니다.').replace(/^❌\s*/, ''))); }
    });

    function startPlayback(path) {
        $('player-msg').classList.remove('is-convert');
        video.src = fileUrl(path);
        video.load();
        // 처음 여는 영상 중 일부는 서버가 표시 순서를 고쳐 보내느라(video_fix.py) 길면 수십 초 걸림
        clearTimeout(player.prepTimer);
        player.prepTimer = setTimeout(() => {
            if (player.path === path && video.readyState === 0 && $('player-msg').hidden) {
                showMessage('처음 여는 영상이라 재생 준비 중입니다…<br><small>긴 영상은 수십 초 걸릴 수 있습니다. 다음부터는 바로 열립니다.</small>');
                player.prepShown = true;
            }
        }, PREP_NOTICE_MS);
        player.prepShown = false;
        player.nextPrepared = false;
        resetStats();
        setStatsOpen(storageGet(STATS_KEY, '') === '1');
        const playing = video.play();
        if (playing) playing.catch(() => { /* 자동 재생이 막히면 재생 단추를 누르면 됨 */ });
        clearInterval(player.timer);
        player.timer = setInterval(() => { if (!video.paused) saveProgress(); }, SAVE_EVERY_MS);
    }

    video.addEventListener('loadedmetadata', () => {
        clearTimeout(player.prepTimer);
        if (player.prepShown) { $('player-msg').hidden = true; player.prepShown = false; }
        if (video.videoWidth === 0 && player.path) {
            showMessage(`이 영상은 화면 형식(MPEG-4 Part 2·HEVC 등)을 브라우저가 풀지 못해 화면이 나오지 않습니다.<br>`
                + `소리만 들리면 이 경우입니다. 내려받아 다른 재생기로 보세요.<br><a href="${fileUrl(player.path, true)}" download>내려받기</a>`);
        }
        if (player.resumeAt && player.resumeAt < video.duration) {
            video.currentTime = player.resumeAt;
            $('resume-text').textContent = `${fmtTime(player.resumeAt)}부터 이어서 재생`;
            $('resume').hidden = false;
            setTimeout(() => { $('resume').hidden = true; }, 6000);
        }
        player.resumeAt = 0;
    });
    video.addEventListener('pause', () => saveProgress());
    // 재생이 시작되면 다음 영상을 서버가 미리 고쳐 두게 함 → '다음 영상'이 바로 열림
    video.addEventListener('playing', () => {
        if (player.nextPrepared || !player.path) return;
        player.nextPrepared = true;
        const next = nextVideo();
        if (next) setTimeout(() => { if (player.path) api(`/api/videos/prepare?p=${enc(next.path)}`).catch(() => {}); }, NEXT_PREPARE_DELAY_MS);
    });
    video.addEventListener('ended', () => {
        saveProgress();
        const next = nextVideo();
        if (next) {
            $('next-btn').textContent = `다음 영상: ${next.name}`;
            $('next-btn').dataset.path = next.path;
            $('player-next').hidden = false;
        }
    });
    video.addEventListener('error', () => {
        if (!player.path) return;
        showMessage(`이 브라우저에서 재생할 수 없는 영상입니다.<br>MKV는 크롬·엣지(안드로이드 포함)에서 재생됩니다.<br><a href="${fileUrl(player.path, true)}" download>내려받기</a>`);
    });
    $('resume-start').addEventListener('click', () => { video.currentTime = 0; $('resume').hidden = true; video.play().catch(() => {}); });
    $('next-btn').addEventListener('click', () => location.replace(videoHref($('next-btn').dataset.path)));

    function closePlayerView() {
        if ($('player').hidden) return;
        saveProgress();
        clearInterval(player.timer);
        video.pause();
        video.removeAttribute('src');
        video.innerHTML = '';
        video.load();
        player.path = null;
        clearTimeout(player.convTimer);
        $('player-msg').classList.remove('is-convert');
        clearInterval(stats.timer);
        $('player').hidden = true;
        document.body.classList.remove('is-playing');
    }

    function closePlayer() {
        const folder = player.path && player.path.includes('/') ? player.path.slice(0, player.path.lastIndexOf('/')) : currentDir;
        if (history.state && history.state.fromList) history.back();
        else location.replace(dirHref(folder));
    }
    $('player-close').addEventListener('click', closePlayer);
    document.addEventListener('keydown', e => {
        if ($('player').hidden) return;
        if (e.key === 'Escape' && !document.fullscreenElement) closePlayer();
    });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') saveProgress(true); });
    window.addEventListener('pagehide', () => saveProgress(true));

    // 목록에서 영상을 누르면 '목록에서 왔음'을 기록 (닫을 때 뒤로 가기로 돌아가 목록 위치가 그대로)
    document.addEventListener('click', e => {
        const link = e.target.closest('a.tile[href^="#v="]');
        if (!link) return;
        e.preventDefault();
        scrollMemory[currentDir] = window.scrollY;
        history.pushState({ fromList: true }, '', link.getAttribute('href'));
        route();
    });

    // ==========================================
    // 주소(#) → 화면
    // ==========================================
    function route() {
        const params = new URLSearchParams(location.hash.slice(1));
        if (params.has('v')) {
            openPlayer(params.get('v'));
        } else {
            currentDir = params.get('d') || '';
            showLibrary(currentDir);
        }
    }
    window.addEventListener('popstate', route);
    route();
})();
