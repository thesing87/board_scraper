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
        // 재생 못 하는 형식은 누르면 내려받기
        const href = v.playable ? videoHref(v.path) : fileUrl(v.path, true);
        return `<a class="tile${v.playable ? '' : ' is-unplayable'}" href="${href}" data-path="${esc(v.path)}"${v.playable ? '' : ' download'}>
            <span class="thumb"><img src="${thumbUrl(v.path)}" alt="" loading="lazy" decoding="async">
                <span class="tag tag-ext">${esc(v.ext)}</span>
                ${v.subtitle ? '<span class="tag tag-sub">자막</span>' : ''}
                ${v.playable ? '' : '<span class="tag tag-no">재생 불가 · 내려받기</span>'}
                ${v.progress && v.progress.duration ? `<span class="tag tag-time">${watched ? '다 봄' : `${fmtTime(v.progress.position)} / ${fmtTime(v.progress.duration)}`}</span>` : ''}
                ${ratio ? `<span class="bar"><i style="width:${(ratio * 100).toFixed(1)}%"></i></span>` : ''}</span>
            <span class="tile-name">${esc(v.name)}</span>
            <span class="tile-sub">${esc(sub ?? fmtSize(v.size))}</span></a>`;
    }

    function folderTile(d) {
        return `<a class="tile is-folder" href="${dirHref(d.path)}">
            <span class="thumb"><img src="${thumbUrl(d.path)}" alt="" loading="lazy" decoding="async">
                <span class="tag tag-folder">${FOLDER_ICON}폴더</span></span>
            <span class="tile-name">${esc(d.name)}</span></a>`;
    }

    function recentTile(r) {
        return videoTile({ ...r, ext: r.path.split('.').pop(), subtitle: false }, r.folder || '전체');
    }

    // 썸네일을 못 뽑으면(영상이 깨졌거나 아직 못 읽음) 재생 표시가 든 빈 칸
    document.addEventListener('error', e => {
        const img = e.target;
        if (!(img instanceof HTMLImageElement)) return;
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
        $('videos').innerHTML = data.videos.map(v => videoTile(v)).join('');
        $('empty').hidden = !!(data.dirs.length || data.videos.length);
        window.scrollTo(0, scrollMemory[path] || 0);
    }

    // ==========================================
    // 재생
    // ==========================================
    const video = $('video');
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
        video.src = fileUrl(path);
        video.load();
        const playing = video.play();
        if (playing) playing.catch(() => { /* 자동 재생이 막히면 재생 단추를 누르면 됨 */ });
        clearInterval(player.timer);
        player.timer = setInterval(() => { if (!video.paused) saveProgress(); }, SAVE_EVERY_MS);
    }

    video.addEventListener('loadedmetadata', () => {
        if (player.resumeAt && player.resumeAt < video.duration) {
            video.currentTime = player.resumeAt;
            $('resume-text').textContent = `${fmtTime(player.resumeAt)}부터 이어서 재생`;
            $('resume').hidden = false;
            setTimeout(() => { $('resume').hidden = true; }, 6000);
        }
        player.resumeAt = 0;
    });
    video.addEventListener('pause', () => saveProgress());
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
