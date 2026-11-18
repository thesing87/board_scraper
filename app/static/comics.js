// 만화: NAS 만화 폴더 둘러보기와 한 장씩 넘겨 보기.
// - 주소의 #d=폴더 는 목록, #b=책 은 보기 화면 (뒤로 가기로 목록에 돌아옴)
// - 로그인은 키워드 게시판과 같은 로그인 키(localStorage admin_token). 이미지 요청에는 키를 담을 수 없어서
//   키를 한 번 보내 만화 API에만 쓰는 쿠키를 받아 둠 (/api/comics/session)
// - 보기 화면은 페이지마다 한 칸인 가로(또는 세로) 스크롤에 칸마다 한 장씩 멈추게 함(scroll-snap).
//   가로로 긴 양면 페이지는 서버가 알려 준 크기로 미리 두 칸으로 나눔. 지금 칸 앞뒤 몇 장만 이미지를 붙임
'use strict';

(function () {
    const TOKEN_KEY = 'admin_token';
    const SETTINGS_KEY = 'comics_settings_v1';
    // 지금 칸 앞뒤로 이미지를 붙여 두는 칸 수 (멀리 있는 칸은 비워 메모리를 아낌)
    const KEEP_AROUND = 3;
    // 미리 받아 두는 다음 장 수
    const PRELOAD_AHEAD = 4;
    const SAVE_DELAY_MS = 800;
    // 이보다 가로가 길면(가로/세로) 양면 페이지로 봄
    const SPREAD_RATIO = 1.15;
    // '자동'일 때 두 페이지로 보는 화면: 가로가 이 이상이고 가로가 세로보다 긴 화면 (데스크탑)
    const DOUBLE_MIN_WIDTH = 900;

    const $ = id => document.getElementById(id);
    const esc = v => String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const enc = encodeURIComponent;
    const storageGet = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch (e) { return fallback; } };
    const storageSet = (key, value) => { try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key); } catch (e) { /* 저장 불가 */ } };

    function loadSettings() {
        // layout: auto(넓은 화면은 두 페이지) · single · double, cover: 두 페이지 보기에서 첫 장(표지)은 혼자
        const defaults = { dir: 'rtl', split: true, layout: 'auto', cover: true };
        try { return { ...defaults, ...JSON.parse(storageGet(SETTINGS_KEY, '{}')) }; } catch (e) { return defaults; }
    }
    const settings = loadSettings();
    const saveSettings = () => storageSet(SETTINGS_KEY, JSON.stringify(settings));

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

    // 쿠키가 없거나 풀렸을 때: 이 기기에 기억한 로그인 키로 쿠키를 다시 받음. 실패하면 false
    async function renewSession() {
        const token = storageGet(TOKEN_KEY, '');
        if (!token) return false;
        const { status } = await postJson('/api/comics/session', { password: token });
        if (status === 401) storageSet(TOKEN_KEY, '');
        return status === 200;
    }

    // 로그인이 필요하면 한 번 쿠키를 다시 받아 재시도, 그래도 안 되면 로그인 화면
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
        closeReaderView();
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
        const { status, data } = await postJson('/api/comics/session', { password });
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
    const FOLDER_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path></svg>';
    const coverUrl = path => `/api/comics/cover?p=${enc(path)}`;
    const bookHref = path => `#b=${enc(path)}`;
    const dirHref = path => path ? `#d=${enc(path)}` : '#';

    function progressInfo(p) {
        if (!p) return { ratio: 0, label: '', done: false };
        const done = p.page >= p.pages - 1;
        return { ratio: done ? 1 : (p.page + 1) / p.pages, label: done ? '다 읽음' : `${p.page + 1}/${p.pages}`, done };
    }

    function bookCard(book) {
        const p = progressInfo(book.progress);
        return `<a class="book" href="${bookHref(book.path)}">
            <span class="book-cover"><img src="${coverUrl(book.path)}" alt="" loading="lazy" decoding="async">
                ${p.label ? `<span class="badge${p.done ? ' is-done' : ''}">${esc(p.label)}</span>` : ''}
                ${p.ratio ? `<span class="bar"><i style="width:${(p.ratio * 100).toFixed(1)}%"></i></span>` : ''}</span>
            <span class="book-name">${esc(book.name)}</span></a>`;
    }

    // 폴더(시리즈) 칸: 안에 든 첫 책의 표지와 이름. 몇 권인지는 목록을 먼저 보여 준 뒤 따로 받아 채움 (loadCounts)
    function folderCard(dir) {
        return `<a class="folder-card" href="${dirHref(dir.path)}" data-path="${esc(dir.path)}">
            <span class="book-cover"><img src="${coverUrl(dir.path)}" alt="" loading="lazy" decoding="async">
                <span class="folder-badge">${FOLDER_ICON}<span class="folder-count"></span></span></span>
            <span class="book-name">${esc(dir.name)}</span></a>`;
    }

    async function loadCounts(path) {
        let data;
        try { data = await api(`/api/comics/counts?p=${enc(path)}`); } catch (e) { return; }
        // 그사이 다른 폴더로 옮겼으면 버림
        if (!data || currentDir !== path || $('content').hidden) return;
        $('folders').querySelectorAll('.folder-card').forEach(card => {
            const c = data.counts[card.dataset.path];
            if (!c) return;
            card.querySelector('.folder-count').textContent = c.books ? `${c.books}권` : c.dirs ? `폴더 ${c.dirs}개` : c.images ? `이미지 ${c.images}장` : '';
        });
    }

    // 표지를 못 받으면(이미지 없는 폴더 등) 그림 대신 이름 첫 글자를 크게
    document.addEventListener('error', e => {
        const img = e.target;
        if (!(img instanceof HTMLImageElement)) return;
        const holder = img.closest('.book-cover');
        if (!holder) return;
        const name = holder.parentElement.querySelector('.book-name');
        holder.dataset.initial = name ? name.textContent.trim().slice(0, 1) : '';
        holder.classList.add('no-cover');
        img.remove();
    }, true);

    function renderCrumbs(path) {
        const parts = path ? path.split('/') : [];
        const items = [parts.length ? `<a href="#">전체</a>` : '<span class="here">전체</span>'];
        parts.forEach((part, i) => {
            const sub = parts.slice(0, i + 1).join('/');
            items.push('<span class="sep">›</span>');
            items.push(i === parts.length - 1 ? `<span class="here">${esc(part)}</span>` : `<a href="${dirHref(sub)}">${esc(part)}</a>`);
        });
        $('crumbs').innerHTML = items.join('');
    }

    async function showLibrary(path) {
        closeReaderView();
        let data;
        try {
            await reader.pendingSave;
            data = await api(`/api/comics/list?p=${enc(path)}`);
        } catch (e) {
            if (e instanceof LoginNeeded) { showLogin(); return; }
            showNotice(`목록을 불러오지 못했습니다. ${esc(e.message || '')}`);
            return;
        }
        if (data && data.configured === false) {
            showNotice('만화 폴더가 연결되지 않았습니다.<br>NAS의 만화 폴더를 웹서버 컨테이너의 <code>/comics</code>에 연결하거나 '
                + '<code>COMICS_DIR</code> 환경변수로 폴더를 지정해 주세요.');
            return;
        }
        if (!data) {
            // 없는 폴더 (이름이 바뀌었거나 지워짐): 처음 목록으로
            if (path) { location.replace('#'); return; }
            showNotice('만화 폴더를 찾을 수 없습니다.');
            return;
        }
        $('login').hidden = true;
        $('notice').hidden = true;
        $('content').hidden = false;
        document.title = data.name ? `${data.name} · 만화` : '만화';
        renderCrumbs(data.path);

        const recent = data.recent || [];
        $('recent').hidden = !recent.length;
        $('recent-list').innerHTML = recent.map(r => {
            const p = progressInfo(r.progress);
            return `<a class="recent-item" href="${bookHref(r.path)}"><img src="${coverUrl(r.path)}" alt="" loading="lazy" decoding="async">
                <span style="min-width:0"><div class="recent-name">${esc(r.name)}</div><div class="recent-folder">${esc(r.folder || '전체')} · ${esc(p.label)}</div>
                <div class="bar"><i style="width:${(p.ratio * 100).toFixed(1)}%"></i></div></span></a>`;
        }).join('');

        $('folders').innerHTML = data.dirs.map(folderCard).join('');
        if (data.dirs.length) loadCounts(data.path);
        // 폴더에 이미지가 바로 들어 있으면 그 폴더 자체도 한 권
        const books = data.images && data.path
            ? [{ name: `${data.name} (이미지 ${data.images}장)`, path: data.path, progress: data.images_progress }, ...data.books]
            : data.books;
        $('books').innerHTML = books.map(bookCard).join('');
        $('empty').hidden = !!(data.dirs.length || books.length);
        const y = scrollMemory[path];
        window.scrollTo(0, y || 0);
    }

    function showNotice(html) {
        $('login').hidden = true;
        $('content').hidden = true;
        $('notice').hidden = false;
        $('notice').innerHTML = html;
    }

    // 책을 보고 돌아오면 목록을 보던 위치로
    const scrollMemory = {};
    let currentDir = '';

    // ==========================================
    // 보기 화면
    // ==========================================
    const reader = { book: null, views: [], current: 0, saveTimer: null, lastSaved: null, pendingSave: null, scrollRaf: 0, preloaded: new Set() };
    const pager = $('pager');
    const pageUrl = n => `/api/comics/page?p=${enc(reader.book.path)}&n=${n}`;

    // 두 페이지로 볼지: 위아래 넘김은 늘 한 페이지, '자동'은 넓은 가로 화면에서만
    function useDouble() {
        if (settings.dir === 'vertical') return false;
        if (settings.layout === 'double') return true;
        if (settings.layout === 'single') return false;
        return window.innerWidth >= DOUBLE_MIN_WIDTH && window.innerWidth > window.innerHeight;
    }

    const isWide = (book, i) => { const size = book.sizes[i]; return !!size && size[0] > size[1] * SPREAD_RATIO; };
    // 한 칸에 보이는 페이지 번호들
    const viewPages = view => (view.end ? [] : view.pair != null ? [view.page, view.pair] : [view.page]);
    const findView = page => reader.views.findIndex(x => !x.end && viewPages(x).includes(page));

    // 두 페이지 칸: 표지는 혼자(설정), 가로로 긴 양면 페이지와 마지막 남는 한 장도 혼자, 나머지는 두 장씩
    function buildDoubleViews(book) {
        const views = [];
        let i = 0;
        if (settings.cover && book.count) { views.push({ page: 0, half: null }); i = 1; }
        while (i < book.count) {
            if (isWide(book, i) || i === book.count - 1 || isWide(book, i + 1)) { views.push({ page: i, half: null }); i++; continue; }
            views.push({ page: i, pair: i + 1, half: null });
            i += 2;
        }
        views.push({ end: true });
        return views;
    }

    // 칸 목록: [{page, half: null|'left'|'right', pair?}] + 마지막 '다 읽음' 칸 {end: true}
    function buildViews(book) {
        if (useDouble()) return buildDoubleViews(book);
        const portrait = window.innerHeight >= window.innerWidth;
        const views = [];
        for (let i = 0; i < book.count; i++) {
            const size = book.sizes[i];
            const wide = settings.split && portrait && size && size[0] > size[1] * SPREAD_RATIO;
            if (!wide) { views.push({ page: i, half: null }); continue; }
            // 일본식(오른쪽부터 읽음)은 오른쪽 반이 먼저
            const order = settings.dir === 'rtl' ? ['right', 'left'] : ['left', 'right'];
            views.push({ page: i, half: order[0] }, { page: i, half: order[1] });
        }
        views.push({ end: true });
        return views;
    }

    const horizontal = () => settings.dir !== 'vertical';
    // 일본식은 칸을 뒤집어 놓아(첫 장이 오른쪽 끝) 오른쪽에서 왼쪽으로 넘김
    const slotOf = v => settings.dir === 'rtl' ? reader.views.length - 1 - v : v;
    const viewOfSlot = s => settings.dir === 'rtl' ? reader.views.length - 1 - s : s;

    function renderSlots() {
        pager.classList.toggle('is-vertical', !horizontal());
        const order = reader.views.map((_, v) => v);
        if (settings.dir === 'rtl') order.reverse();
        pager.innerHTML = order.map(v => reader.views[v].end ? endSlotHtml() : slotHtml(v)).join('');
        pager.querySelectorAll('[data-action]').forEach(btn => btn.addEventListener('click', e => { e.stopPropagation(); endAction(btn.dataset.action); }));
        layoutPages();
    }

    // 두 장 칸은 읽는 순서대로 놓음: 일본식은 앞 장이 오른쪽, 나머지는 앞 장이 왼쪽
    function slotHtml(v) {
        const view = reader.views[v];
        if (view.pair == null) return `<div class="slot" data-v="${v}"><div class="page" data-p="${view.page}"></div></div>`;
        const shown = settings.dir === 'rtl' ? [view.pair, view.page] : [view.page, view.pair];
        return `<div class="slot is-pair" data-v="${v}">${shown.map(p => `<div class="page" data-p="${p}"></div>`).join('')}</div>`;
    }

    function endSlotHtml() {
        const next = reader.book.next;
        return `<div class="slot slot-end" data-end="1"><h3>마지막 페이지입니다</h3><p>${esc(reader.book.name)}</p>
            ${next ? `<button type="button" class="is-primary" data-action="next">다음 권: ${esc(next.name)}</button>` : ''}
            <button type="button" data-action="close">목록으로</button></div>`;
    }

    function endAction(action) {
        if (action === 'next' && reader.book.next) location.replace(bookHref(reader.book.next.path));
        else closeReader();
    }

    // 페이지 크기를 알면 화면에 맞는 상자로, 반쪽 칸은 이미지 두 배 너비에서 한쪽만 보이게
    function layoutPages() {
        const W = pager.clientWidth, H = pager.clientHeight;
        pager.querySelectorAll('.slot[data-v]').forEach(slot => {
            const view = reader.views[+slot.dataset.v];
            if (view.pair != null) { layoutPair(slot, W, H); return; }
            const page = slot.firstElementChild;
            const size = reader.book.sizes[view.page];
            if (!size) { page.style.cssText = ''; return; }
            const ratio = (view.half ? size[0] / 2 : size[0]) / size[1];
            const w = Math.min(W, H * ratio), h = w / ratio;
            page.style.width = `${Math.floor(w)}px`;
            page.style.height = `${Math.floor(h)}px`;
            page.style.flex = '0 0 auto';
            page.style.backgroundSize = view.half ? '200% 100%' : '100% 100%';
            page.style.backgroundPosition = view.half || 'center';
        });
    }

    // 두 장 칸: 높이를 같게 맞춰 두 장을 합친 너비가 화면에 들어가게 (크기를 모르면 반씩)
    function layoutPair(slot, W, H) {
        const pages = [...slot.children];
        const sizes = pages.map(el => reader.book.sizes[+el.dataset.p]);
        if (sizes.some(s => !s)) { pages.forEach(el => { el.style.cssText = ''; }); return; }
        const ratios = sizes.map(s => s[0] / s[1]);
        const h = Math.min(H, W / (ratios[0] + ratios[1]));
        pages.forEach((el, k) => {
            el.style.width = `${Math.floor(h * ratios[k])}px`;
            el.style.height = `${Math.floor(h)}px`;
            el.style.flex = '0 0 auto';
            el.style.backgroundSize = '100% 100%';
            el.style.backgroundPosition = 'center';
        });
    }

    function attachImages() {
        const lo = reader.current - KEEP_AROUND, hi = reader.current + KEEP_AROUND;
        pager.querySelectorAll('.slot[data-v] .page').forEach(page => {
            const v = +page.parentElement.dataset.v;
            const want = v >= lo && v <= hi;
            const n = +page.dataset.p;
            if (want && page.dataset.n !== String(n)) {
                page.dataset.n = String(n);
                page.classList.add('is-loading');
                page.classList.remove('is-error');
                const img = new Image();
                img.decoding = 'async';
                img.onload = () => { if (page.dataset.n === String(n)) { page.style.backgroundImage = `url("${img.src}")`; page.classList.remove('is-loading'); } };
                img.onerror = () => { if (page.dataset.n === String(n)) { page.classList.remove('is-loading'); page.classList.add('is-error'); } };
                img.src = pageUrl(n);
            } else if (!want && page.dataset.n) {
                delete page.dataset.n;
                page.style.backgroundImage = '';
                page.classList.remove('is-loading', 'is-error');
            }
        });
        // 다음 장 몇 개를 미리 받아 브라우저에 둠 (넘길 때 바로 보이게)
        const view = reader.views[reader.current];
        if (view && !view.end) {
            for (let n = Math.max(...viewPages(view)) + 1; n <= Math.min(view.page + PRELOAD_AHEAD + KEEP_AROUND, reader.book.count - 1); n++) {
                if (reader.preloaded.has(n)) continue;
                reader.preloaded.add(n);
                const img = new Image();
                img.src = pageUrl(n);
            }
        }
    }

    function scrollToView(v, smooth) {
        const s = slotOf(v);
        const opts = horizontal() ? { left: s * pager.clientWidth } : { top: s * pager.clientHeight };
        pager.scrollTo({ ...opts, behavior: smooth ? 'smooth' : 'instant' });
    }

    function setCurrent(v) {
        v = Math.max(0, Math.min(reader.views.length - 1, v));
        const changed = v !== reader.current;
        reader.current = v;
        attachImages();
        updateChrome();
        if (changed) scheduleSave();
    }

    function onScroll() {
        if (reader.scrollRaf) return;
        reader.scrollRaf = requestAnimationFrame(() => {
            reader.scrollRaf = 0;
            const s = horizontal() ? Math.round(pager.scrollLeft / pager.clientWidth) : Math.round(pager.scrollTop / pager.clientHeight);
            setCurrent(viewOfSlot(s));
        });
    }

    function go(delta) {
        const v = Math.max(0, Math.min(reader.views.length - 1, reader.current + delta));
        if (v === reader.current) return;
        scrollToView(v, true);
    }

    // 지금 보고 있는 마지막 페이지 (두 장 칸이면 뒤 장. 읽은 위치로 저장)
    function currentPage() {
        const view = reader.views[reader.current];
        return view.end ? reader.book.count - 1 : Math.max(...viewPages(view));
    }

    function updateChrome() {
        const page = currentPage();
        const view = reader.views[reader.current];
        const pages = viewPages(view);
        $('reader-count').textContent = view.end ? '끝'
            : pages.length === 2 ? `${pages[0] + 1}-${pages[1] + 1} / ${reader.book.count}` : `${page + 1} / ${reader.book.count}`;
        const slider = $('reader-slider');
        slider.max = String(Math.max(0, reader.book.count - 1));
        if (document.activeElement !== slider) slider.value = String(page);
        slider.classList.toggle('is-rtl', settings.dir === 'rtl');
    }

    function scheduleSave() {
        clearTimeout(reader.saveTimer);
        reader.saveTimer = setTimeout(saveProgress, SAVE_DELAY_MS);
    }

    function saveProgress(keepalive) {
        clearTimeout(reader.saveTimer);
        if (!reader.book || !reader.book.count) return;
        const page = currentPage();
        const key = `${reader.book.path}:${page}`;
        if (reader.lastSaved === key) return;
        reader.lastSaved = key;
        // 목록이 저장을 기다렸다가 불러오도록 (닫자마자 목록을 받으면 방금 읽은 곳이 빠짐)
        reader.pendingSave = postJson('/api/comics/progress', { path: reader.book.path, page, pages: reader.book.count }, keepalive)
            .catch(() => { reader.lastSaved = null; });
    }

    function toggleChrome(force) {
        const hidden = force !== undefined ? !force : !$('reader').classList.contains('is-chrome-hidden');
        $('reader').classList.toggle('is-chrome-hidden', hidden);
        if (hidden) setSettingsOpen(false);
    }

    function setSettingsOpen(open) {
        $('reader-settings').hidden = !open;
        $('reader-settings-btn').setAttribute('aria-expanded', String(open));
    }

    function renderSettings() {
        $('set-dir').querySelectorAll('button').forEach(b => b.setAttribute('aria-checked', String(b.dataset.v === settings.dir)));
        $('set-split').checked = settings.split;
        const vertical = settings.dir === 'vertical';
        $('set-layout').querySelectorAll('button').forEach(b => {
            b.setAttribute('aria-checked', String(b.dataset.v === settings.layout));
            b.disabled = vertical;
        });
        $('set-cover').checked = settings.cover;
        const double = useDouble();
        $('set-layout-hint').textContent = vertical ? '위아래로 넘길 때는 한 페이지씩 봅니다.'
            : settings.layout === 'auto' ? `자동: 지금 화면에서는 ${double ? '두 페이지' : '한 페이지'} (넓은 가로 화면에서 두 페이지)` : '';
        $('set-cover-row').hidden = !double;
        // 반으로 나누기는 한 페이지로 볼 때만
        $('set-split-row').hidden = double;
        $('reader-layout-btn').hidden = vertical;
        $('reader-layout-label').textContent = double ? '2쪽' : '1쪽';
        $('reader-layout-btn').setAttribute('aria-label', double ? '한 페이지로 보기' : '두 페이지로 보기');
    }

    // 설정을 바꾸면 칸을 다시 만들고 같은 페이지로
    function rebuild() {
        const page = currentPage();
        reader.views = buildViews(reader.book);
        renderSlots();
        renderSettings();
        const v = Math.max(0, findView(page));
        reader.current = -1;
        scrollToView(v, false);
        setCurrent(v);
    }

    async function openReader(path) {
        // 읽던 위치가 바뀌었을 수 있어 매번 새로 받음 (서버가 책 정보를 기억해 두어 가벼움)
        {
            let book;
            try {
                book = await api(`/api/comics/book?p=${enc(path)}`);
            } catch (e) {
                if (e instanceof LoginNeeded) { showLogin(); return; }
                window.alert('책을 열지 못했습니다.');
                history.back();
                return;
            }
            if (!book || !book.count) {
                window.alert(book ? '이 책에는 이미지가 없습니다.' : '책을 찾을 수 없습니다.');
                location.replace(dirHref(currentDir));
                return;
            }
            saveProgress();
            reader.book = book;
            reader.preloaded = new Set();
            reader.lastSaved = null;
        }
        const book = reader.book;
        if ($('content').hidden === false) scrollMemory[currentDir] = window.scrollY;
        $('reader').hidden = false;
        document.body.classList.add('is-reading');
        $('reader-title').textContent = book.name;
        document.title = `${book.name} · 만화`;
        renderSettings();
        setSettingsOpen(false);
        toggleChrome(false);
        reader.views = buildViews(book);
        renderSlots();
        // 읽던 곳부터 (다 읽은 책은 처음부터)
        const saved = book.progress && book.progress.page < book.count - 1 ? book.progress.page : 0;
        const v = Math.max(0, findView(saved));
        reader.current = -1;
        reader.lastSaved = `${book.path}:${saved}`;
        scrollToView(v, false);
        setCurrent(v);
        pager.focus({ preventScroll: true });
    }

    function closeReaderView() {
        if ($('reader').hidden) return;
        saveProgress();
        $('reader').hidden = true;
        document.body.classList.remove('is-reading');
        pager.innerHTML = '';
    }

    function closeReader() {
        const folder = reader.book ? reader.book.folder : currentDir;
        // 목록에서 열었으면 뒤로 가기, 주소로 바로 열었으면 그 책의 폴더로
        if (history.state && history.state.fromList) history.back();
        else location.replace(dirHref(folder));
    }

    // 화면 누르기: 양옆 30%는 앞뒤 장, 가운데는 메뉴 보이기·숨기기
    pager.addEventListener('click', e => {
        if (e.target.closest('.slot-end')) return;
        const x = e.clientX / window.innerWidth;
        if (x > 0.3 && x < 0.7) { toggleChrome(); return; }
        const left = x <= 0.3;
        // 일본식은 왼쪽이 다음 장, 나머지는 오른쪽이 다음 장
        go(settings.dir === 'rtl' ? (left ? 1 : -1) : (left ? -1 : 1));
        toggleChrome(false);
    });
    pager.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', () => {
        if ($('reader').hidden || !reader.book) return;
        rebuild();
    });
    document.addEventListener('keydown', e => {
        if ($('reader').hidden) return;
        const rtl = settings.dir === 'rtl';
        const map = { ArrowLeft: rtl ? 1 : -1, ArrowRight: rtl ? -1 : 1, ArrowDown: 1, ArrowUp: -1, PageDown: 1, PageUp: -1, ' ': 1 };
        if (e.key === 'Escape') { closeReader(); return; }
        if (e.key in map && e.target.tagName !== 'INPUT') { e.preventDefault(); go(map[e.key]); }
    });
    $('reader-close').addEventListener('click', closeReader);
    $('reader-settings-btn').addEventListener('click', () => setSettingsOpen($('reader-settings').hidden));
    $('set-dir').addEventListener('click', e => {
        const btn = e.target.closest('button[data-v]');
        if (!btn || btn.dataset.v === settings.dir) return;
        settings.dir = btn.dataset.v;
        saveSettings();
        renderSettings();
        rebuild();
    });
    function setLayout(layout) {
        settings.layout = layout;
        saveSettings();
        renderSettings();
        rebuild();
    }
    $('set-layout').addEventListener('click', e => {
        const btn = e.target.closest('button[data-v]');
        if (btn && !btn.disabled && btn.dataset.v !== settings.layout) setLayout(btn.dataset.v);
    });
    // 위쪽 '1쪽/2쪽' 버튼: 지금 보이는 것과 반대로 고정
    $('reader-layout-btn').addEventListener('click', () => setLayout(useDouble() ? 'single' : 'double'));
    $('set-cover').addEventListener('change', e => {
        settings.cover = e.target.checked;
        saveSettings();
        rebuild();
    });
    $('set-split').addEventListener('change', e => {
        settings.split = e.target.checked;
        saveSettings();
        rebuild();
    });
    const slider = $('reader-slider');
    slider.addEventListener('input', () => { $('reader-count').textContent = `${+slider.value + 1} / ${reader.book.count}`; });
    slider.addEventListener('change', () => {
        const v = findView(+slider.value);
        if (v >= 0) { scrollToView(v, false); setCurrent(v); }
        slider.blur();
    });
    // 앱을 닫거나 다른 앱으로 갈 때 읽던 곳을 바로 저장
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') saveProgress(true); });
    window.addEventListener('pagehide', () => saveProgress(true));

    // 목록에서 책을 누르면 '목록에서 왔음'을 기록 (닫을 때 뒤로 가기로 돌아가 목록 위치가 그대로)
    document.addEventListener('click', e => {
        const link = e.target.closest('a.book, a.recent-item');
        if (!link) return;
        e.preventDefault();
        scrollMemory[currentDir] = window.scrollY;
        history.pushState({ fromList: true }, '', link.getAttribute('href'));
        route();
    });

    // ==========================================
    // 주소(#) → 화면
    // ==========================================
    function parseHash() {
        const hash = location.hash.slice(1);
        const params = new URLSearchParams(hash);
        if (params.has('b')) return { book: params.get('b') };
        return { dir: params.get('d') || '' };
    }

    function route() {
        const target = parseHash();
        if (target.book != null) {
            openReader(target.book);
        } else {
            currentDir = target.dir;
            showLibrary(target.dir);
        }
    }

    // # 이동(직접 입력·location.replace)과 뒤로 가기 모두 popstate로 옴
    window.addEventListener('popstate', route);
    route();
})();
