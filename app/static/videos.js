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
    // 위쪽 줄·이전·다음 버튼이 떠 있는 시간 (누르거나 마우스를 움직인 뒤)
    const UI_HIDE_MS = 3000;
    const STATS_KEY = 'videos_stats_open';
    // 소리 크기·음소거: 모든 영상에 같은 값을 쓰고 이 기기에 저장 (다음 영상·다시 열어도 그대로)
    const VOLUME_KEY = 'videos_volume';
    // 건너뛴 프레임이 이 비율을 넘으면 기기 성능 부족으로 봄
    const DROP_BAD_RATIO = 0.05;
    // 변환 진행 상황을 다시 묻는 간격
    const CONVERT_POLL_MS = 2000;
    // 이만큼(초) 재생하면 조회수 1회 (잘못 눌렀다 바로 닫은 것은 세지 않음. 같은 영상 30분 안에 다시 세지 않는 것은 서버가)
    const VIEW_AFTER_SEC = 10;
    // 재생바를 이만큼(초) 끝 가까이로 넘기면 바로 다음 영상
    const END_JUMP_SEC = 0.5;
    const RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
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
    // 즐겨찾기 보기(#fav) 중인지, 즐겨찾기한 영상 경로 (서버가 목록마다 favorite으로 알려 줌)
    let viewFav = false;
    const favs = new Set();
    const scrollKey = () => viewFav ? '\u0000fav' : currentDir;
    const STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6-4.9-4.6 6.6-.8z"></path></svg>';
    function noteFavs(list) {
        (list || []).forEach(v => { if (v.favorite) favs.add(v.path); else if (v.favorite === false) favs.delete(v.path); });
    }
    function renderFavCount(count) {
        if (typeof count === 'number') $('fav-count').textContent = count ? String(count) : '';
    }

    function progressRatio(p) {
        if (!p || !p.duration) return 0;
        return Math.min(1, p.position / p.duration);
    }

    function videoTile(v, sub, rank) {
        const ratio = progressRatio(v.progress);
        const watched = v.progress && v.progress.duration - v.progress.position <= RESUME_END_MARGIN;
        const conv = convertLabel(v);
        return `<a class="tile${conv ? ' is-unplayable' : ''}" href="${videoHref(v.path)}" data-path="${esc(v.path)}">
            <span class="thumb"><img src="${thumbUrl(v.path)}" alt="" loading="lazy" decoding="async">
                ${favStar(v.path)}
                <span class="tag tag-ext">${esc(v.ext)}</span>
                ${v.subtitle ? '<span class="tag tag-sub">자막</span>' : ''}
                ${conv ? `<span class="tag tag-no">${esc(conv)}</span>` : ''}
                ${v.progress && v.progress.duration ? `<span class="tag tag-time">${watched ? '다 봄' : `${fmtTime(v.progress.position)} / ${fmtTime(v.progress.duration)}`}</span>` : ''}
                ${rank ? `<span class="tag tag-rank">${rank}위</span>` : ''}
                ${ratio ? `<span class="bar"><i style="width:${(ratio * 100).toFixed(1)}%"></i></span>` : ''}</span>
            <span class="tile-name">${esc(v.name)}</span>
            <span class="tile-sub">${esc(sub ?? fmtSize(v.size))}${v.views ? ` · <span class="tile-views">조회 ${v.views.toLocaleString()}회</span>` : ''}</span></a>`;
    }

    function favStar(path) {
        const on = favs.has(path);
        const label = on ? '즐겨찾기에서 빼기' : '즐겨찾기에 넣기';
        return `<span class="fav-star${on ? ' is-on' : ''}" role="button" tabindex="0" aria-pressed="${on}" aria-label="${label}" title="${label}">${STAR}</span>`;
    }

    // 변환이 필요한데 아직 안 된 영상의 칸 위 글자 (필요 없거나 다 됐으면 빈 글자)
    // 자동 변환 시간 (서버가 상태에 함께 보냄: auto_hours [시작, 끝])
    let AUTO_HOURS = [2, 8];
    const autoHours = () => `${AUTO_HOURS[0]}시~${AUTO_HOURS[1]}시`;

    function convertLabel(v) {
        if (v.converted || !v.convert) return '';
        const job = v.job;
        if (job && job.state === 'running') return `변환 중 ${Math.floor((job.progress || 0) * 100)}%`;
        if (job && job.state === 'queued') return job.auto ? '새벽 자동 변환 대기' : '변환 대기';
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
            if (Array.isArray(data.auto_hours)) AUTO_HOURS = data.auto_hours;
            $('conv-bar-text').textContent = `${data.queued}개를 새벽 자동 변환(${autoHours()})에 넣었습니다.`;
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

    const fmtAgo = sec => {
        const d = Math.max(0, Date.now() / 1000 - sec);
        if (d < 3600) return `${Math.max(1, Math.round(d / 60))}분 전`;
        if (d < 86400) return `${Math.round(d / 3600)}시간 전`;
        if (d < 86400 * 30) return `${Math.round(d / 86400)}일 전`;
        return new Date(sec * 1000).toLocaleDateString('ko-KR');
    };

    // 최근 추가: 맨 위 폴더에서만, 목록을 먼저 보여 주고 따로 받아 채움 (전체 폴더를 훑는 데 처음에는 몇 초 걸림)
    async function loadLatest() {
        let data;
        try { data = await api('/api/videos/latest'); } catch (e) { return; }
        if (!data || currentDir !== '' || $('content').hidden || viewFav) return;
        noteFavs(data.videos);
        $('latest').hidden = !data.videos.length;
        $('latest-list').innerHTML = data.videos.map(v => videoTile(v, `${v.folder || '전체'} · ${fmtAgo(v.added)}`)).join('');
    }

    // ==========================================
    // 검색 (동영상 폴더 전체, 이름·폴더에 낱말이 모두 들어간 영상)
    // ==========================================
    const SEARCH_DELAY_MS = 250;
    let searchTimer = null, searchSeq = 0;

    function setSearchMode(on) {
        $('search-results').hidden = !on;
        $('library-view').hidden = on || viewFav;
        $('fav-view').hidden = on || !viewFav;
        $('vsearch-clear').hidden = !$('vsearch-input').value;
    }

    async function runSearch() {
        const q = $('vsearch-input').value.trim();
        const seq = ++searchSeq;
        if (!q) { setSearchMode(false); return; }
        setSearchMode(true);
        $('search-count').textContent = '찾는 중…';
        let data;
        try { data = await api(`/api/videos/search?q=${enc(q)}`); } catch (e) {
            if (seq === searchSeq) $('search-count').textContent = '검색하지 못했습니다.';
            return;
        }
        if (seq !== searchSeq || !data) return;
        noteFavs(data.videos);
        $('search-count').textContent = data.total
            ? `‘${q}’ 영상 ${data.total}개${data.total > data.videos.length ? ` (앞의 ${data.videos.length}개)` : ''}`
            : `‘${q}’에 맞는 영상이 없습니다.`;
        $('search-list').innerHTML = data.videos.map(v => videoTile(v, v.folder || '전체')).join('');
    }

    $('vsearch-input').addEventListener('input', () => {
        clearTimeout(searchTimer);
        $('vsearch-clear').hidden = !$('vsearch-input').value;
        searchTimer = setTimeout(runSearch, SEARCH_DELAY_MS);
    });
    $('vsearch').addEventListener('submit', e => { e.preventDefault(); clearTimeout(searchTimer); runSearch(); $('vsearch-input').blur(); });
    $('vsearch-input').addEventListener('keydown', e => { if (e.key === 'Escape') { $('vsearch-input').value = ''; runSearch(); } });
    $('vsearch-clear').addEventListener('click', () => { $('vsearch-input').value = ''; runSearch(); $('vsearch-input').focus(); });

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
        viewFav = false;
        renderTabs();
        noteFavs(data.videos);
        noteFavs(data.recent);
        renderFavCount(data.favorite_count);
        renderCrumbs(data.path);
        renderRandomButton();
        currentList = data.videos;
        const recent = data.recent || [];
        $('recent').hidden = !recent.length;
        $('recent-list').innerHTML = recent.map(recentTile).join('');
        $('folders').innerHTML = data.dirs.map(folderTile).join('');
        if (data.dirs.length) loadSamples(data.path);
        $('videos').innerHTML = data.videos.map(v => videoTile(v)).join('');
        $('latest').hidden = true;
        if (!data.path) loadLatest();
        const popular = data.popular || [];
        noteFavs(popular);
        $('popular').hidden = !popular.length;
        $('popular-list').innerHTML = popular.map((v, i) => videoTile(v, v.folder || '전체', i < 3 ? i + 1 : 0)).join('');
        // 검색어가 남아 있으면(검색 결과에서 영상을 열었다가 돌아옴) 검색 결과를 다시 보여 줌
        if ($('vsearch-input').value.trim()) runSearch(); else setSearchMode(false);
        renderConvertBar(data.videos);
        $('empty').hidden = !!(data.dirs.length || data.videos.length);
        window.scrollTo(0, scrollMemory[scrollKey()] || 0);
    }

    // ==========================================
    // 즐겨찾기: 썸네일 왼쪽 위 별·재생 화면 위쪽 줄 별로 넣고 빼기 (서버에 저장 → 폰·PC 같음),
    // 즐겨찾기 보기(#fav)는 모든 폴더의 즐겨찾기를 최근에 넣은 것부터, 랜덤은 즐겨찾기만
    // ==========================================
    function renderTabs() {
        $('tab-all').setAttribute('aria-selected', String(!viewFav));
        $('tab-fav').setAttribute('aria-selected', String(viewFav));
        // '전체'를 누르면 보던 폴더로
        $('tab-all').setAttribute('href', dirHref(currentDir));
    }

    async function showFavorites() {
        closePlayerView();
        let data;
        try {
            await player.pendingSave;
            data = await api('/api/videos/favorites');
        } catch (e) {
            if (e instanceof LoginNeeded) { showLogin(); return; }
            showNotice(`즐겨찾기를 불러오지 못했습니다. ${esc(e.message || '')}`);
            return;
        }
        if (data && data.configured === false) {
            showNotice('동영상 폴더가 연결되지 않았습니다.<br>NAS의 동영상 폴더를 웹서버 컨테이너의 <code>/videos</code>에 연결해 주세요.');
            return;
        }
        if (!data || !data.videos) { showNotice('즐겨찾기를 불러오지 못했습니다.'); return; }
        $('login').hidden = true;
        $('notice').hidden = true;
        $('content').hidden = false;
        document.title = '즐겨찾기 · 동영상';
        viewFav = true;
        renderTabs();
        noteFavs(data.videos);
        renderFavCount(data.videos.length);
        currentList = data.videos;
        $('fav-title').textContent = data.videos.length ? `즐겨찾기 ${data.videos.length.toLocaleString()}개` : '즐겨찾기';
        $('fav-list').innerHTML = data.videos.map(v => videoTile(v, v.folder || '전체')).join('');
        $('fav-empty').hidden = !!data.videos.length;
        $('fav-random-btn').hidden = !data.videos.length;
        if ($('vsearch-input').value.trim()) runSearch(); else setSearchMode(false);
        window.scrollTo(0, scrollMemory[scrollKey()] || 0);
    }

    // 탭을 누르면 검색을 끝내고 그 화면으로
    ['tab-all', 'tab-fav'].forEach(id => $(id).addEventListener('click', () => {
        if (!$('vsearch-input').value) return;
        $('vsearch-input').value = '';
        clearTimeout(searchTimer);
        searchSeq++;
        setSearchMode(false);
    }));

    async function setFavorite(path, on, retried) {
        on ? favs.add(path) : favs.delete(path);
        renderFavMarks(path);
        const { status, data } = await postJson('/api/videos/favorite', { path, on }).catch(() => ({ status: 0, data: {} }));
        if (status === 401 && !retried && await renewSession()) return setFavorite(path, on, true);
        if (status !== 200) {
            // 저장하지 못하면 되돌림
            on ? favs.delete(path) : favs.add(path);
            renderFavMarks(path);
            return false;
        }
        renderFavCount(data.count);
        return true;
    }

    // 화면에 보이는 같은 영상의 별(목록 여러 곳·재생 화면)을 모두 맞춤
    function renderFavMarks(path) {
        const on = favs.has(path);
        const label = on ? '즐겨찾기에서 빼기' : '즐겨찾기에 넣기';
        document.querySelectorAll('a.tile[data-path]').forEach(tile => {
            if (tile.dataset.path !== path) return;
            const star = tile.querySelector('.fav-star');
            if (!star) return;
            star.classList.toggle('is-on', on);
            star.setAttribute('aria-pressed', String(on));
            star.setAttribute('aria-label', label);
            star.title = label;
        });
        if (player.path === path) renderFavButton();
    }

    // 별을 누르면 영상을 열지 않고 넣고 빼기만 (영상 칸을 누르는 처리보다 먼저 받음)
    function onStar(e) {
        const star = e.target.closest && e.target.closest('.fav-star');
        if (!star) return;
        e.preventDefault();
        e.stopPropagation();
        const tile = star.closest('a.tile');
        if (tile) setFavorite(tile.dataset.path, !favs.has(tile.dataset.path));
    }
    document.addEventListener('click', onStar, true);
    document.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') onStar(e); }, true);

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
    const player = { path: null, timer: null, lastSaved: null, pendingSave: null, resumeAt: 0, played: 0, lastTime: 0, viewSent: false, autoFrom: null };

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

    // ==========================================
    // 랜덤 재생: 폴더(하위 폴더 포함, 맨 위면 전체)에서 바로 재생되는 영상을 누를 때마다 새로 섞어 차례로.
    // 다 돌면 다시 섞어 이어 감(같은 영상이 바로 이어지지 않게). 이전은 방금 본 영상. 목록으로 돌아가면 끝
    // ==========================================
    let random = null;  // { base: [{path,name,folder}], order: 섞은 순서(다 돌면 이어 붙임), pos: 지금 위치, on: 켜졌는지, fav: 즐겨찾기만인지 }

    function shuffled(list) {
        const a = list.slice();
        for (let i = a.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [a[i], a[j]] = [a[j], a[i]];
        }
        return a;
    }

    function randomNext() {
        if (random.pos >= random.order.length - 1) {
            const more = shuffled(random.base);
            const cur = random.order[random.pos];
            if (more.length > 1 && cur && more[0].path === cur.path) more.push(more.shift());
            random.order = random.order.concat(more);
        }
        return random.order[random.pos + 1];
    }

    // 영상을 열 때: 랜덤 순서의 앞·뒤 영상이면 위치를 옮기고, 랜덤과 상관없는 영상이면 랜덤을 끝냄 (꺼 둔 동안은 그대로 둠)
    function syncRandom(path) {
        if (!random || !random.on) return;
        const at = [random.pos, random.pos + 1, random.pos - 1].find(i => random.order[i] && random.order[i].path === path);
        if (at === undefined) random = null;
        else random.pos = at;
    }

    function renderRandom() {
        const chip = $('random-chip');
        chip.hidden = !random;
        $('random-from').hidden = !(random && random.on);
        if (!random) return;
        const total = random.base.length;
        const what = random.fav ? '즐겨찾기 랜덤' : '랜덤';
        $('random-chip-text').textContent = random.on ? `랜덤 ${(random.pos % total) + 1} / ${total.toLocaleString()}` : '랜덤 끔';
        chip.classList.toggle('is-fav', !!random.fav);
        chip.setAttribute('aria-pressed', String(random.on));
        chip.title = random.on ? `${what} 재생 끄기 (같은 폴더 순서로)` : `${what} 재생 다시 켜기`;
        const cur = random.order[random.pos];
        $('random-from').textContent = `폴더: ${cur && cur.folder ? cur.folder.replace(/\//g, ' / ') : '전체'}`;
    }

    $('random-chip').addEventListener('click', () => {
        if (!random) return;
        random.on = !random.on;
        player.nextPrepared = false;
        updateNavButtons();
    });

    function renderRandomButton() {
        $('random-text').textContent = currentDir ? '이 폴더 랜덤 재생' : '전체 랜덤 재생';
    }

    // fav: 즐겨찾기만 (폴더와 상관없이)
    async function startRandom(fav) {
        const btn = $(fav ? 'fav-random-btn' : 'random-btn');
        const text = $(fav ? 'fav-random-text' : 'random-text');
        btn.disabled = true;
        let data = null;
        try { data = await api(fav ? '/api/videos/random?fav=1' : `/api/videos/random?p=${enc(currentDir)}`); } catch (e) {
            if (e instanceof LoginNeeded) { showLogin(); return; }
        } finally { btn.disabled = false; }
        const list = (data && data.videos) || [];
        if (!list.length) {
            text.textContent = '재생할 영상이 없습니다';
            setTimeout(() => { if (fav) text.textContent = '즐겨찾기 랜덤 재생'; else renderRandomButton(); }, 2000);
            return;
        }
        const order = shuffled(list);
        random = { base: list, order, pos: 0, on: true, fav };
        scrollMemory[scrollKey()] = window.scrollY;
        history.pushState({ fromList: true }, '', videoHref(order[0].path));
        route();
    }
    $('random-btn').addEventListener('click', () => startRandom(false));
    $('fav-random-btn').addEventListener('click', () => startRandom(true));

    function nextVideo() {
        if (random && random.on) return randomNext();
        const i = currentList.findIndex(v => v.path === player.path);
        return i >= 0 ? currentList.slice(i + 1).find(v => v.playable) : null;
    }

    function prevVideo() {
        if (random && random.on) return random.pos > 0 ? random.order[random.pos - 1] : null;
        const i = currentList.findIndex(v => v.path === player.path);
        return i > 0 ? currentList.slice(0, i).reverse().find(v => v.playable) : null;
    }

    // 영상 위 양옆의 이전·다음 버튼: 같은 폴더에서 재생할 수 있는 앞·뒤 영상 (없으면 흐리게, 이름은 버튼 아래)
    function updateNavButtons() {
        const nextLabel = random && random.on ? (random.fav ? '즐겨찾기 랜덤 다음' : '랜덤 다음') : '다음';
        [['prev-btn', 'prev-name', prevVideo(), '이전'], ['next-nav-btn', 'next-name', nextVideo(), nextLabel]].forEach(([id, nameId, v, label]) => {
            const btn = $(id);
            btn.disabled = !v;
            btn.dataset.path = v ? v.path : '';
            btn.title = v ? `${label} 영상: ${v.name}` : `${label} 영상 없음`;
            $(nameId).textContent = v ? `${label} · ${v.name}` : '';
        });
        renderRandom();
    }

    // 위쪽 줄·이전·다음은 누르거나 마우스를 움직이면 떴다가 UI_HIDE_MS 뒤 사라짐 (일시정지 중·버튼 위에 마우스가 있으면 그대로)
    function showUi() {
        $('player').classList.add('ui-on');
        clearTimeout(player.uiTimer);
        player.uiTimer = setTimeout(hideUi, UI_HIDE_MS);
    }
    // force: 휴대폰에서 영상을 눌러 숨길 때 (일시정지 중이어도)
    function hideUi(force) {
        if ($('player').hidden) return;
        if (force !== true) {
            if (video.paused) return;
            if ($('player').querySelector('.player-top:hover, .p-side:hover, .p-bottom:hover') || !$('seek-menu').hidden || !$('more-menu').hidden || bar.dragging) {
                player.uiTimer = setTimeout(hideUi, UI_HIDE_MS); return;
            }
        }
        clearTimeout(player.uiTimer);
        $('player').classList.remove('ui-on');
    }
    $('player').addEventListener('pointermove', e => { if (e.pointerType === 'mouse') showUi(); });
    // 영상을 누르면: 마우스는 재생·일시정지, 휴대폰은 조작 줄 보이기·숨기기
    $('player').addEventListener('pointerdown', e => {
        if (e.pointerType !== 'mouse' && e.target === video && $('player').classList.contains('ui-on')) { player.tapHide = true; return; }
        player.tapHide = false;
        showUi();
    });
    video.addEventListener('click', e => {
        if (player.tapHide) { hideUi(true); return; }
        if (e.pointerType === 'mouse' || !e.pointerType) togglePlay();
    });
    video.addEventListener('play', showUi);
    video.addEventListener('pause', showUi);

    // 전체화면은 재생 화면 전체를 키움 (영상만 키우면 그 위에 이전·다음 버튼을 못 올림)
    // 아이폰은 요소 전체화면이 없어 아이폰 재생기로 엶 (그때는 이전·다음 버튼 없음)
    const fullscreenEl = () => document.fullscreenElement || document.webkitFullscreenElement || null;
    function toggleFullscreen() {
        const el = $('player');
        if (fullscreenEl()) {
            const exit = document.exitFullscreen || document.webkitExitFullscreen;
            if (exit) Promise.resolve(exit.call(document)).catch(() => {});
            return;
        }
        const req = el.requestFullscreen || el.webkitRequestFullscreen;
        if (req) {
            Promise.resolve(req.call(el)).then(() => {
                // 휴대폰: 가로 영상이면 화면을 가로로 (못 하는 기기는 그냥 둠)
                if (video.videoWidth > video.videoHeight && screen.orientation && screen.orientation.lock) screen.orientation.lock('landscape').catch(() => {});
            }).catch(() => {});
        } else if (video.webkitEnterFullscreen) {
            video.webkitEnterFullscreen();
        }
    }
    function onFullscreenChange() {
        const on = fullscreenEl() === $('player');
        $('player').classList.toggle('is-fs', on);
        $('fs-btn').setAttribute('aria-label', on ? '전체화면 끝내기' : '전체화면');
        $('fs-btn').title = on ? '전체화면 끝내기' : '전체화면';
    }
    document.addEventListener('fullscreenchange', onFullscreenChange);
    document.addEventListener('webkitfullscreenchange', onFullscreenChange);
    $('fs-btn').addEventListener('click', toggleFullscreen);
    video.addEventListener('dblclick', e => { if (e.target === video) toggleFullscreen(); });

    // ==========================================
    // 아래 조작 줄: 재생·시간·두꺼운 재생바·소리·⋮(속도·자막)·전체화면 (브라우저 기본 조작 막대 대신)
    // ==========================================
    function togglePlay() {
        if (!player.path || video.readyState < 1 && !video.src) return;
        if (video.paused || video.ended) video.play().catch(() => {}); else video.pause();
    }
    function renderPlayState() {
        const playing = !video.paused && !video.ended;
        $('player').classList.toggle('is-playing-now', playing);
        $('play-btn').setAttribute('aria-label', playing ? '일시정지' : '재생');
        $('play-btn').title = playing ? '일시정지 (Space)' : '재생 (Space)';
    }
    ['play', 'pause', 'ended', 'emptied'].forEach(ev => video.addEventListener(ev, renderPlayState));
    $('play-btn').addEventListener('click', togglePlay);

    // 재생바: 막대 8px, 위아래 28px 어디를 눌러도 됨. 끄는 동안은 그림만 옮기고 놓을 때 건너뜀(끌면서 영상을 계속 찾으면 NAS가 바빠짐)
    const bar = { dragging: false, ratio: 0 };
    const barEnd = () => (isFinite(video.duration) && video.duration > 0) ? video.duration : seekEnd();
    function barRatio(e) {
        const r = $('seekbar').querySelector('.sb-track').getBoundingClientRect();
        return r.width ? Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) : 0;
    }
    function drawBar(doneRatio) {
        const end = barEnd();
        const pct = v => `${(Math.min(1, Math.max(0, v)) * 100).toFixed(2)}%`;
        const done = doneRatio ?? (end ? video.currentTime / end : 0);
        $('sb-done').style.width = pct(done);
        $('sb-knob').style.left = pct(done);
        let buffered = 0;
        for (let i = 0; i < video.buffered.length; i++) {
            if (video.buffered.start(i) <= video.currentTime + 0.5) buffered = Math.max(buffered, video.buffered.end(i));
        }
        $('sb-buf').style.width = pct(end ? buffered / end : 0);
        const shown = doneRatio != null ? doneRatio * end : video.currentTime;
        $('p-time').textContent = `${fmtTime(shown)} / ${isFinite(video.duration) && video.duration ? fmtTime(video.duration) : '--:--'}`;
        $('seekbar').setAttribute('aria-valuemax', String(Math.round(end || 0)));
        $('seekbar').setAttribute('aria-valuenow', String(Math.round(shown || 0)));
    }
    function showTip(ratio) {
        const end = barEnd();
        const tip = $('sb-tip');
        tip.textContent = end ? fmtTime(ratio * end) : '';
        // 막대 양 끝에서는 글자가 화면 밖으로 나가지 않게
        const track = $('seekbar').querySelector('.sb-track');
        const w = track.offsetWidth, half = tip.offsetWidth / 2;
        const x = Math.min(Math.max(ratio * w, half - 6), w - half + 6);
        tip.style.left = `${x + track.offsetLeft}px`;
        $('sb-hover').style.left = `${(ratio * 100).toFixed(2)}%`;
    }
    function commitSeek(ratio) {
        const end = barEnd();
        if (!end) return;
        const target = ratio * end;
        // 끝까지 넘기면 바로 다음 영상
        if (isFinite(video.duration) && target >= video.duration - END_JUMP_SEC && goNextAuto()) return;
        video.currentTime = Math.max(0, Math.min(end, target));
    }
    $('seekbar').addEventListener('pointerdown', e => {
        if (e.button !== 0 || !player.path || !barEnd()) return;
        e.preventDefault();
        bar.dragging = true;
        $('seekbar').setPointerCapture(e.pointerId);
        $('seekbar').classList.add('is-drag');
        bar.ratio = barRatio(e);
        drawBar(bar.ratio);
        showTip(bar.ratio);
    });
    $('seekbar').addEventListener('pointermove', e => {
        if (bar.dragging) {
            bar.ratio = barRatio(e);
            drawBar(bar.ratio);
            showTip(bar.ratio);
        } else if (e.pointerType === 'mouse' && barEnd()) {
            $('seekbar').classList.add('is-hover');
            showTip(barRatio(e));
        }
    });
    $('seekbar').addEventListener('pointerleave', () => $('seekbar').classList.remove('is-hover'));
    function endDrag(e, commit) {
        if (!bar.dragging) return;
        bar.dragging = false;
        $('seekbar').classList.remove('is-drag');
        if (e.pointerType !== 'mouse') $('seekbar').classList.remove('is-hover');
        if (commit) commitSeek(bar.ratio);
        drawBar();
        showUi();
    }
    $('seekbar').addEventListener('pointerup', e => endDrag(e, true));
    $('seekbar').addEventListener('pointercancel', e => endDrag(e, false));
    ['timeupdate', 'durationchange', 'progress', 'loadedmetadata', 'seeking', 'emptied'].forEach(ev =>
        video.addEventListener(ev, () => { if (!bar.dragging) drawBar(); }));

    // 소리: 단추는 음소거, 마우스를 올리면 옆에 크기 막대 (휴대폰은 기기 소리 단추로)
    function renderVolume() {
        const muted = video.muted || video.volume === 0;
        $('mute-btn').classList.toggle('is-muted', muted);
        $('mute-btn').setAttribute('aria-label', muted ? '소리 켜기' : '음소거');
        $('mute-btn').title = muted ? '소리 켜기 (M)' : '음소거 (M)';
        $('vol').value = String(video.muted ? 0 : video.volume);
    }
    video.addEventListener('volumechange', renderVolume);
    renderVolume();
    $('mute-btn').addEventListener('click', () => {
        if (video.muted || video.volume === 0) { video.muted = false; if (video.volume === 0) video.volume = 0.5; } else video.muted = true;
    });
    $('vol').addEventListener('input', () => { video.volume = Number($('vol').value); video.muted = video.volume === 0; });

    // ⋮: 재생 속도(이번에 보는 동안 다음 영상에도), 자막 보기
    let rate = 1;
    function renderRates() {
        $('rate-options').innerHTML = RATES.map(r =>
            `<button type="button" role="menuitemradio" data-rate="${r}" aria-checked="${r === rate}">${r === 1 ? '보통' : `${r}배`}</button>`).join('');
    }
    renderRates();
    function applyRate() { video.defaultPlaybackRate = rate; video.playbackRate = rate; }
    function setMoreMenu(open) {
        $('more-menu').hidden = !open;
        $('more-btn').setAttribute('aria-expanded', String(open));
        if (open) {
            const track = video.textTracks[0];
            $('subs-row').hidden = !track;
            if (track) $('subs-toggle').setAttribute('aria-checked', String(track.mode === 'showing'));
        } else showUi();
    }
    $('more-btn').addEventListener('click', () => setMoreMenu($('more-menu').hidden));
    $('rate-options').addEventListener('click', e => {
        const b = e.target.closest('button[data-rate]');
        if (!b) return;
        rate = Number(b.dataset.rate);
        applyRate();
        renderRates();
        setMoreMenu(false);
        flashOsd(rate === 1 ? '보통 속도' : `${rate}배 속도`);
    });
    $('subs-toggle').addEventListener('click', () => {
        const track = video.textTracks[0];
        if (!track) return;
        track.mode = track.mode === 'showing' ? 'hidden' : 'showing';
        player.subsOff = track.mode !== 'showing';
        setMoreMenu(false);
    });
    document.addEventListener('pointerdown', e => { if (!$('more-menu').hidden && !e.target.closest('.more-wrap')) setMoreMenu(false); });

    // 끝까지 넘기거나 영상이 끝나면 바로 다음 영상 (새 영상 위에 '다음 영상 · 이름'). 다음이 없으면 false
    function goNextAuto() {
        const next = nextVideo();
        if (!next) return false;
        player.autoFrom = next.path;
        goTo(next.path);
        return true;
    }

    function goTo(path) {
        if (path) location.replace(videoHref(path));
    }
    $('prev-btn').addEventListener('click', () => goTo($('prev-btn').dataset.path));
    $('next-nav-btn').addEventListener('click', () => goTo($('next-nav-btn').dataset.path));

    function renderFavButton() {
        const on = !!player.path && favs.has(player.path);
        const label = on ? '즐겨찾기에서 빼기' : '즐겨찾기에 넣기';
        $('fav-btn').setAttribute('aria-pressed', String(on));
        $('fav-btn').setAttribute('aria-label', label);
        $('fav-btn').title = label;
    }

    // 가운데에 잠깐 뜨는 글자 (건너뛰기 '+10초'와 같은 자리)
    function flashOsd(text, ms) {
        const osd = $('seek-osd');
        osd.textContent = text;
        osd.classList.add('show');
        clearTimeout(player.osdTimer);
        player.osdTimer = setTimeout(() => osd.classList.remove('show'), ms || (text.length > 6 ? 1400 : 700));
    }

    // 조회수 (제목 옆)
    function renderViews(n) {
        $('player-views').textContent = n ? `조회 ${n.toLocaleString()}회` : '';
    }
    // VIEW_AFTER_SEC만큼 실제로 재생하면(건너뛴 시간은 빼고) 1회
    video.addEventListener('timeupdate', () => {
        const t = video.currentTime, d = t - player.lastTime;
        player.lastTime = t;
        if (!player.path || player.viewSent || video.paused || video.seeking || !(d > 0 && d < 1.5)) return;
        player.played += d;
        if (player.played < VIEW_AFTER_SEC) return;
        player.viewSent = true;
        const path = player.path;
        postJson('/api/videos/view', { path }).then(({ status, data }) => {
            if (status !== 200) { if (player.path === path) player.viewSent = false; return; }
            const item = currentList.find(v => v.path === path);
            if (item) item.views = data.views;
            if (player.path === path) renderViews(data.views);
        }).catch(() => { if (player.path === path) player.viewSent = false; });
    });

    $('fav-btn').addEventListener('click', async () => {
        const path = player.path;
        if (!path) return;
        const on = !favs.has(path);
        const ok = await setFavorite(path, on);
        if (player.path === path) flashOsd(ok ? (on ? '즐겨찾기에 넣었어요' : '즐겨찾기에서 뺐어요') : '저장하지 못했어요');
    });

    function showMessage(html) {
        $('player-msg').innerHTML = html;
        $('player-msg').hidden = false;
    }

    async function openPlayer(path) {
        // 쿠키가 없으면 먼저 받아 둠 (영상 요청은 401을 알 수 없으므로)
        try {
            const probe = await api(`/api/videos/list?p=${enc(path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '')}`);
            if (probe && probe.videos) { currentList = probe.videos; noteFavs(probe.videos); renderFavCount(probe.favorite_count); }
        } catch (e) {
            if (e instanceof LoginNeeded) { showLogin(); return; }
        }
        const info = currentList.find(v => v.path === path);
        if ($('content').hidden === false) scrollMemory[scrollKey()] = window.scrollY;
        syncRandom(path);
        // 목록의 검색창 등에 남은 커서를 뺌 (그대로면 키보드가 가려진 검색창으로 감)
        const focused = document.activeElement;
        if (focused && focused !== document.body && !$('player').contains(focused)) focused.blur();
        player.path = path;
        player.lastSaved = null;
        // 전에 본 영상이면 처음으로 되감은 위치도 저장 (안 본 영상은 SAVE_MIN초 넘게 봐야 저장)
        player.saved = !!(info && info.progress);
        const name = info ? info.name : path.split('/').pop();
        $('player-title').textContent = name;
        renderViews(info ? info.views : 0);
        player.played = 0;
        player.lastTime = 0;
        player.viewSent = false;
        renderFavButton();
        setMoreMenu(false);
        // 끝나서 저절로 넘어온 영상이면 잠깐 알림
        if (player.autoFrom === path) setTimeout(() => { if (player.path === path) flashOsd(`다음 영상 · ${name}`, 2000); }, 300);
        player.autoFrom = null;
        document.title = `${name} · 동영상`;
        $('player-download').href = fileUrl(path, true);
        $('player-download').setAttribute('download', '');
        $('player-msg').hidden = true;
        $('resume').hidden = true;
        updateNavButtons();
        $('player').hidden = false;
        showUi();
        document.body.classList.add('is-playing');
        video.innerHTML = '';
        if (info && info.subtitle) {
            const track = document.createElement('track');
            track.kind = 'subtitles';
            track.label = '한국어';
            track.srclang = 'ko';
            track.src = `/api/videos/subs?p=${enc(path)}`;
            track.default = !player.subsOff;
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
        if (Array.isArray(st.auto_hours)) AUTO_HOURS = st.auto_hours;
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
                ? `<b>새벽 자동 변환(${autoHours()})을 기다리는 중입니다</b><small>그 시간에 차례로 변환합니다. 먼저 보려면 지금 변환하세요 (예상 약 ${fmtMinutes(st.estimate || 0)}).</small>`
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
        applyRate();
        drawBar();
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
        goNextAuto();
    });
    video.addEventListener('error', () => {
        if (!player.path) return;
        showMessage(`이 브라우저에서 재생할 수 없는 영상입니다.<br>MKV는 크롬·엣지(안드로이드 포함)에서 재생됩니다.<br><a href="${fileUrl(player.path, true)}" download>내려받기</a>`);
    });
    $('resume-start').addEventListener('click', () => { video.currentTime = 0; $('resume').hidden = true; video.play().catch(() => {}); });

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
        clearTimeout(player.uiTimer);
        $('seek-menu').hidden = true;
        $('seek-btn').setAttribute('aria-expanded', 'false');
        $('more-menu').hidden = true;
        $('more-btn').setAttribute('aria-expanded', 'false');
        random = null;
        renderRandom();
        if (fullscreenEl()) toggleFullscreen();
        document.body.classList.remove('is-playing');
    }

    function closePlayer() {
        const folder = player.path && player.path.includes('/') ? player.path.slice(0, player.path.lastIndexOf('/')) : currentDir;
        if (history.state && history.state.fromList) history.back();
        // 즐겨찾기 보기에서 열었으면(다음 영상으로 넘어가 뒤로 가기 기록이 없어도) 즐겨찾기 보기로
        else location.replace(viewFav ? '#fav' : dirHref(folder));
    }
    $('player-close').addEventListener('click', closePlayer);
    // ← / →: 어느 영상이든 정한 초씩 (크롬 기본 재생기는 재생바에 초점이 있으면 영상 길이에 비례해 건너뛰어 영상마다 달랐음).
    // 초는 위쪽 줄 버튼으로 고르고 이 기기에 저장. 재생기 안쪽보다 먼저 받으려고 capture 단계에서 처리
    const SEEK_STEPS = [5, 10, 15, 30, 60];
    const SEEK_KEY = 'videos_seek_step';
    let seekStep = 10;
    function setSeekStep(sec, save) {
        seekStep = SEEK_STEPS.includes(sec) ? sec : 10;
        if (save) storageSet(SEEK_KEY, String(seekStep));
        $('seek-text').textContent = `${seekStep}초`;
        $('seek-options').innerHTML = SEEK_STEPS.map(s =>
            `<button type="button" role="menuitemradio" data-sec="${s}" aria-checked="${s === seekStep}">${s}초</button>`).join('');
    }
    function setSeekMenu(open) {
        $('seek-menu').hidden = !open;
        $('seek-btn').setAttribute('aria-expanded', String(open));
        if (!open) showUi();
    }
    setSeekStep(Number(storageGet(SEEK_KEY, '10')), false);
    window.addEventListener('storage', e => { if (e.key === SEEK_KEY) setSeekStep(Number(e.newValue), false); });
    $('seek-btn').addEventListener('click', () => setSeekMenu($('seek-menu').hidden));
    $('seek-options').addEventListener('click', e => {
        const b = e.target.closest('button[data-sec]');
        if (!b) return;
        setSeekStep(Number(b.dataset.sec), true);
        setSeekMenu(false);
    });
    document.addEventListener('pointerdown', e => { if (!$('seek-menu').hidden && !e.target.closest('.seek-wrap')) setSeekMenu(false); });
    // 건너뛸 수 있는 끝: 영상 길이. 길이를 모르는 영상(앞에 길이 정보가 없는 MKV·WebM 등은 Infinity)은 지금 건너뛸 수 있는 데까지
    function seekEnd() {
        if (isFinite(video.duration) && video.duration > 0) return video.duration;
        const s = video.seekable;
        return s && s.length ? s.end(s.length - 1) : video.currentTime + seekStep;
    }
    function seekBy(dir) {
        video.currentTime = Math.max(0, Math.min(seekEnd(), video.currentTime + dir * seekStep));
        flashOsd(`${dir > 0 ? '+' : '−'}${seekStep}초`);
    }
    window.addEventListener('keydown', e => {
        if ($('player').hidden || e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        const t = e.target;
        // 재생 화면 안의 입력칸만 양보 (재생 화면 뒤에 가려진 검색창에 커서가 남아 있어도 영상을 건너뜀)
        if (t && t !== video && $('player').contains(t) && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
        // 영상 길이를 모를 때도 늘 여기서 처리 (그냥 넘기면 크롬 기본 재생기가 영상마다 다른 간격으로 건너뜀)
        e.preventDefault();
        e.stopPropagation();
        if (video.readyState < 1) return;  // 아직 열리는 중
        seekBy(e.key === 'ArrowRight' ? 1 : -1);
    }, true);
    document.addEventListener('keydown', e => {
        if ($('player').hidden) return;
        if (e.key === 'Escape' && !$('seek-menu').hidden) { setSeekMenu(false); return; }
        if (e.key === 'Escape' && !$('more-menu').hidden) { setMoreMenu(false); return; }
        const t = e.target;
        const typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) && $('player').contains(t) && t.type !== 'range';
        if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
            // 단추에 초점이 있을 때 Space는 그 단추를 누름 → 재생 단추 말고는 영상 재생·일시정지로
            if ((e.key === ' ' && !(t && t.closest && t.closest('button') && t.id !== 'play-btn')) || e.key === 'k' || e.key === 'K') {
                e.preventDefault(); togglePlay(); showUi(); return;
            }
            if (e.key === 'm' || e.key === 'M') { $('mute-btn').click(); showUi(); return; }
            if (e.key === 'f' || e.key === 'F') { toggleFullscreen(); return; }
        }
        if (e.key === 'Escape' && !document.fullscreenElement) closePlayer();
        // Shift+← / Shift+→: 이전·다음 영상 (화살표만 누르면 브라우저가 앞뒤로 건너뜀)
        if (e.shiftKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
            const btn = $(e.key === 'ArrowLeft' ? 'prev-btn' : 'next-nav-btn');
            if (!btn.disabled) { e.preventDefault(); goTo(btn.dataset.path); }
        }
    });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') saveProgress(true); });
    window.addEventListener('pagehide', () => saveProgress(true));

    // 목록에서 영상을 누르면 '목록에서 왔음'을 기록 (닫을 때 뒤로 가기로 돌아가 목록 위치가 그대로)
    document.addEventListener('click', e => {
        const link = e.target.closest('a.tile[href^="#v="]');
        if (!link) return;
        e.preventDefault();
        scrollMemory[scrollKey()] = window.scrollY;
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
        } else if (params.has('fav')) {
            showFavorites();
        } else {
            currentDir = params.get('d') || '';
            showLibrary(currentDir);
        }
    }
    window.addEventListener('popstate', route);
    route();
})();
