'use strict';

// ==========================================
// 상태 및 공용 유틸
// ==========================================
const ALL_KEY = '__all__';            // 모든 키워드를 합친 통합 피드
const POLL_INTERVAL_MS = 60 * 1000;   // 새 글 확인 주기
const LEGACY_READ_IDS_KEY = 'read_post_ids';

const app = {
    state: null,          // /api/state 응답
    activeKey: ALL_KEY,   // 현재 보기: ALL_KEY 또는 "board::keyword"
    searchQuery: '',      // 검색 중이면 검색어
    page: 1,
    totalPages: 1,
    videoOnly: {},        // 보기별 동영상만 보기 여부
    highlightPostId: null,
    renderedTotal: null,  // 현재 화면을 그릴 때의 글 수 (새 글 배너 계산용)
    readQueue: new Set(), // 서버에 보낼 읽음 기록
    readFlushTimer: null
};

const ICONS = {
    external: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"></path><path d="M10 14L20 4"></path><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"></path></svg>',
    prev: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"></path></svg>',
    next: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"></path></svg>',
    close: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>',
    up: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"></path></svg>'
};

function esc(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function tabKey(tab) { return tab.board + '::' + tab.keyword; }
function findTab(key) { return app.state ? app.state.tabs.find(t => tabKey(t) === key) : null; }
function isAllView() { return app.activeKey === ALL_KEY; }

// 현재 보기(통합 또는 키워드)의 요약: 글 수, 안 읽은 새 글 ID
function viewSummary(key) {
    if (!app.state) return null;
    if (key === ALL_KEY) return { total: app.state.all.total, unread_ids: app.state.all.unread_ids };
    return findTab(key);
}

function storageGet(store, key, fallback) {
    try { const v = store.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}
function storageSet(store, key, value) {
    try { store.setItem(key, value); } catch (e) {}
}
function storageRemove(store, key) {
    try { store.removeItem(key); } catch (e) {}
}

async function getJSON(url) {
    const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
    if (!res.ok && res.status !== 404) throw new Error('HTTP ' + res.status);
    return res.json();
}

async function postJSON(url, body) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(body)
    });
    return res.json();
}

// ==========================================
// 읽음 기록 (서버에 저장하여 PC·휴대폰 간 공유)
// ==========================================
function forgetUnread(ids) {
    // 서버 응답을 기다리지 않고 화면의 안 읽은 수부터 줄임
    if (!app.state) return;
    const set = new Set(ids);
    app.state.tabs.forEach(t => { t.unread_ids = t.unread_ids.filter(id => !set.has(id)); });
    app.state.all.unread_ids = app.state.all.unread_ids.filter(id => !set.has(id));
}

function markRead(ids) {
    let added = false;
    ids.forEach(id => { if (!app.readQueue.has(id)) { app.readQueue.add(id); added = true; } });
    if (!added) return;
    forgetUnread(ids);
    renderNavigation();
    renderFeedSub();
    clearTimeout(app.readFlushTimer);
    app.readFlushTimer = setTimeout(flushReads, 1500);
}

async function flushReads(useBeacon) {
    clearTimeout(app.readFlushTimer);
    if (app.readQueue.size === 0) return;
    const ids = Array.from(app.readQueue);
    app.readQueue.clear();
    for (let i = 0; i < ids.length; i += 400) {
        const chunk = ids.slice(i, i + 400);
        const body = JSON.stringify({ ids: chunk });
        if (useBeacon && navigator.sendBeacon) {
            navigator.sendBeacon('/api/read', new Blob([body], { type: 'application/json' }));
            continue;
        }
        try {
            await fetch('/api/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true });
        } catch (e) {
            chunk.forEach(id => app.readQueue.add(id));  // 실패하면 다음에 다시 전송
        }
    }
}

async function migrateLegacyReads() {
    // 예전 버전이 브라우저에 저장해 둔 읽음 기록을 서버로 한 번 옮김
    let ids = [];
    try { ids = JSON.parse(storageGet(localStorage, LEGACY_READ_IDS_KEY, '[]')); } catch (e) {}
    if (!Array.isArray(ids) || ids.length === 0) return;
    ids.forEach(id => app.readQueue.add(String(id)));
    await flushReads();
    if (app.readQueue.size === 0) storageRemove(localStorage, LEGACY_READ_IDS_KEY);
}

// 글 카드 끝(표식)이 화면에 들어오거나 이미 위로 지나가면 읽음 처리 (탭을 떠날 때 전체를 읽음 처리하던 방식 대체)
// 크게 건너뛰는 스크롤에서도 놓치지 않도록 '보이는 중'이 아니라 '화면 아래쪽 경계를 넘었는지'로 판정
let readCheckScheduled = false;
function checkReadSentinels() {
    readCheckScheduled = false;
    const ids = [];
    document.querySelectorAll('.read-sentinel:not([data-read])').forEach(el => {
        if (el.getBoundingClientRect().top < window.innerHeight) {
            el.dataset.read = '1';
            ids.push(el.dataset.postId);
        }
    });
    if (ids.length) markRead(ids);
}

function scheduleReadCheck() {
    if (readCheckScheduled) return;
    readCheckScheduled = true;
    requestAnimationFrame(checkReadSentinels);
}

function observeReadSentinels() {
    scheduleReadCheck();
}

// ==========================================
// 상단 상태 / 내비게이션 (데스크톱 사이드바, 모바일 칩)
// ==========================================
function renderStatus(ok) {
    const pill = document.getElementById('status-pill');
    const text = document.getElementById('status-text');
    if (!ok) {
        pill.classList.add('is-error');
        text.textContent = '서버 연결 실패';
        return;
    }
    pill.classList.remove('is-error');
    const time = (app.state.generated_at || '').slice(11, 16);
    text.textContent = '수집 중 · ' + time + ' 업데이트';
}

function navItem(label, count, unread, active, attrs) {
    return `
        <button class="kw-item ${active ? 'active' : ''}" ${attrs} ${active ? 'aria-current="true"' : ''}>
            <span>${label}</span>
            <span class="kw-side">
                ${unread ? `<span class="kw-unread" aria-label="안 읽은 새 글 ${unread}개">${unread}</span>` : ''}
                <span class="kw-count">${count}</span>
            </span>
        </button>`;
}

function renderNavigation() {
    if (!app.state) return;
    const tabs = app.state.tabs;
    const searching = !!app.searchQuery;

    // 데스크톱: 통합 피드 + 게시판별로 묶은 키워드 목록
    const groups = [];
    tabs.forEach((tab, idx) => {
        let group = groups.find(g => g.board === tab.board);
        if (!group) { group = { board: tab.board, name: tab.board_name, items: [] }; groups.push(group); }
        group.items.push({ tab, idx });
    });
    const allActive = !searching && isAllView();
    const allItem = `<nav class="kw-group" aria-label="통합">${navItem('전체', app.state.all.total, app.state.all.unread_ids.length, allActive, 'data-action="open-all"')}</nav>`;
    document.getElementById('keyword-groups').innerHTML = allItem + (groups.length ? groups.map(group => `
        <nav class="kw-group" aria-label="${esc(group.name)}">
            <span class="kw-group-name">${esc(group.name)}</span>
            ${group.items.map(({ tab, idx }) => navItem(esc(tab.keyword), tab.total, tab.unread_ids.length,
                !searching && tabKey(tab) === app.activeKey, `data-action="open-tab" data-index="${idx}"`)).join('')}
        </nav>`).join('') : '<span class="kw-group-name">등록된 키워드가 없습니다.</span>');

    // 모바일: 가로로 넘기는 칩 (맨 앞이 통합 피드)
    const chip = (label, count, hasUnread, active, attrs) => `
        <button class="chip ${active ? 'active' : ''}" ${attrs} ${active ? 'aria-current="true"' : ''}>
            <span>${label}</span>
            <span class="chip-count">${count}</span>
            ${hasUnread ? '<span class="chip-dot" aria-label="안 읽은 새 글"></span>' : ''}
        </button>`;
    document.getElementById('chip-row').innerHTML =
        chip('전체', app.state.all.total, app.state.all.unread_ids.length > 0, allActive, 'data-action="open-all"') +
        tabs.map((tab, idx) => chip(esc(tab.keyword), tab.total, tab.unread_ids.length > 0,
            !searching && tabKey(tab) === app.activeKey, `data-action="open-tab" data-index="${idx}"`)).join('');

    // 사이드바 하단 알림 요약
    const summary = app.state.boards
        .filter(b => groups.some(g => g.board === b.key))
        .map(b => {
            const cfg = app.state.board_config[b.key] || { alert: true, video_alert: true };
            const mode = cfg.alert ? '전체 알림' : (cfg.video_alert ? '동영상 글만' : '알림 꺼짐');
            return `${b.name} · ${mode}`;
        });
    document.getElementById('alert-summary').textContent = summary.length ? summary.join('\n') : '등록된 키워드가 없습니다.';
}

function scrollActiveChipIntoView() {
    const activeChip = document.querySelector('#chip-row .chip.active');
    if (activeChip) activeChip.scrollIntoView({ block: 'nearest', inline: 'center' });
}

function openView(key, page) {
    app.activeKey = key;
    app.searchQuery = '';
    document.getElementById('search-input').value = '';
    app.page = page || 1;
    renderNavigation();
    scrollActiveChipIntoView();
    loadPosts().then(() => window.scrollTo({ top: 0 }));
}

// ==========================================
// 피드
// ==========================================
function renderContent(blocks) {
    return (blocks || []).map(block => {
        if (block === '') return '<div class="content-spacer"></div>';
        // 본문 HTML은 서버에서 저장 시 허용 목록 기반으로 정화되어 있음
        if (/^<(img|video|div|iframe)/.test(block)) return block;
        return `<p class="content-line">${block}</p>`;
    }).join('')
        // 페이지는 no-referrer 정책이지만, 유튜브 임베드는 출처(Referer)가 없으면 '오류 153: 동영상 플레이어 구성 오류'를 냄.
        // 이미지 핫링크 차단을 피하려고 페이지 정책은 유지하고 iframe에만 출처(도메인)를 보내도록 허용
        .replace(/<iframe\b/gi, '<iframe referrerpolicy="strict-origin-when-cross-origin"');
}

function avatarTone(name) {
    // 같은 닉네임은 항상 같은 색이 되도록 이름으로 6가지 색 중 하나를 고정 선택
    let hash = 0;
    for (const ch of String(name || '')) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
    return hash % 6;
}

function isNewComment(comment, post) {
    // 이미 읽은 글에서, 마지막으로 읽은 뒤 처음 수집된 댓글
    return !!(post.read_at && comment.first_seen && comment.first_seen > post.read_at);
}

function renderComments(post) {
    if (!post.comments || post.comments.length === 0) {
        // 넓은 화면의 2단 배치에서 오른쪽 댓글 자리를 유지하기 위한 빈 댓글 칸 (좁은 화면에서는 CSS로 숨김)
        return '<section class="comments is-empty"><h3 class="comments-title">댓글 0</h3><p class="comments-empty">아직 댓글이 없습니다.</p></section>';
    }
    const items = post.comments.map(c => {
        const body = (c.content || []).map(t => t ? `<p class="comment-line">${t}</p>` : '<br>').join('');
        const isAuthor = c.author === post.author;
        const isNew = isNewComment(c, post);
        const classes = ['comment'];
        if (c.is_reply) classes.push('reply');
        if (isAuthor) classes.push('by-author');
        if (isNew) classes.push('is-new-comment');
        return `
            <div class="${classes.join(' ')}">
                <span class="comment-avatar av-${avatarTone(c.author)}" aria-hidden="true">${esc(Array.from(c.author || '?')[0])}</span>
                <div class="comment-main">
                    <div class="comment-meta">
                        <span class="comment-author">${esc(c.author)}</span>
                        ${isAuthor ? '<span class="op-badge">작성자</span>' : ''}
                        ${isNew ? '<span class="new-comment-badge">새 댓글</span>' : ''}
                        <span>${esc(c.date)}</span>
                        ${c.votes && c.votes !== '0' ? `<span class="comment-votes">추천 ${esc(c.votes)}</span>` : ''}
                    </div>
                    <div class="comment-body">${body}</div>
                </div>
            </div>`;
    }).join('');
    // 수집 시점의 댓글 수 표기와 실제 수집된 댓글 개수 중 큰 값 (새 댓글이 수집됐는데 수 표기가 늦게 갱신되는 경우 대비)
    const count = Math.max(parseInt(String(post.comment_count).replace(/[^\d]/g, ''), 10) || 0, post.comments.length);
    return `<section class="comments"><h3 class="comments-title">댓글 ${count}</h3>${items}</section>`;
}

function safeLink(url) {
    return /^https?:\/\//i.test(url || '') ? url : '#';
}

function highlightTerms(text) {
    // 검색어를 제목에서 강조 (이스케이프한 뒤 표시용 태그만 추가)
    const escaped = esc(text);
    if (!app.searchQuery) return escaped;
    const terms = app.searchQuery.split(/\s+/).filter(Boolean).map(t => esc(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (!terms.length) return escaped;
    return escaped.replace(new RegExp('(' + terms.join('|') + ')', 'gi'), '<mark>$1</mark>');
}

function renderPost(post, isUnread) {
    const classes = ['post-card'];
    if (post.is_deleted) classes.push('is-deleted');
    // 넓은 화면에서는 댓글 유무와 관계없이 모든 글을 본문·댓글 2단으로 나눔
    classes.push('has-comments');
    const newComments = (post.comments || []).filter(c => isNewComment(c, post)).length;
    const badges = [
        isUnread ? '<span class="badge badge-new">NEW</span>' : '',
        newComments ? `<span class="badge badge-new-comments">새 댓글 ${newComments}</span>` : '',
        post.has_video ? '<span class="badge badge-video">동영상</span>' : '',
        post.is_syncing && !post.is_deleted ? '<span class="badge badge-sync">댓글 추적 중</span>' : '',
        post.is_deleted ? '<span class="badge badge-deleted">원문 삭제됨</span>' : ''
    ].join('');
    // 통합 피드·검색에서는 어느 키워드로 모인 글인지 표시
    const keywordTags = (post.keywords && (isAllView() || app.searchQuery))
        ? post.keywords.map(k => `<span class="kw-chip">${esc(k.board_name)} · ${esc(k.keyword)}</span>`).join('')
        : '';
    const link = esc(safeLink(post.link));
    const votes = post.votes && post.votes !== '0' ? `<span>추천 ${esc(post.votes)}</span>` : '';
    return `
        <article class="${classes.join(' ')}" id="post-${esc(post.id)}">
            <div class="post-head">
                ${badges || keywordTags ? `<div class="badges">${badges}${keywordTags}</div>` : ''}
                <div class="title-row">
                    <h2 class="post-title">${highlightTerms(post.title)}</h2>
                    <a class="btn-original top" href="${link}" target="_blank" rel="noopener noreferrer">원문 ${ICONS.external}</a>
                </div>
                <div class="post-meta">
                    <span class="author">${esc(post.author)}</span>
                    <span>${esc(post.date)}</span>
                    <span>조회 ${esc(post.views)}</span>
                    ${votes}
                    <span>댓글 ${esc(post.comment_count)}</span>
                </div>
            </div>
            <div class="post-content">${renderContent(post.content)}</div>
            ${renderComments(post)}
            <a class="btn-original bottom" href="${link}" target="_blank" rel="noopener noreferrer">원문 보기 ${ICONS.external}</a>
            <div class="read-sentinel" data-post-id="${esc(post.id)}" aria-hidden="true"></div>
        </article>`;
}

function renderPageSelect(page, totalPages, label) {
    // 원하는 페이지로 바로 이동하는 선택 상자 ("3 / 11" 형태)
    const options = Array.from({ length: totalPages }, (_, i) =>
        `<option value="${i + 1}" ${i + 1 === page ? 'selected' : ''}>${i + 1}</option>`).join('');
    return `
        <span class="page-jump">
            <select class="page-select" data-action="go-page" aria-label="${label}">${options}</select>
            <span class="page-total">/ ${totalPages}</span>
        </span>`;
}

function renderPagerMini(page, totalPages, empty) {
    if (empty) return '';
    return `
        <nav class="pager-mini" aria-label="페이지 이동">
            <button class="icon-btn" data-action="page" data-target="prev" aria-label="이전 페이지" ${page <= 1 ? 'disabled' : ''}>${ICONS.prev}</button>
            ${renderPageSelect(page, totalPages, '페이지 선택')}
            <button class="icon-btn" data-action="page" data-target="next" aria-label="다음 페이지" ${page >= totalPages ? 'disabled' : ''}>${ICONS.next}</button>
        </nav>`;
}

function renderPager(page, totalPages) {
    return `
        <nav class="pager" aria-label="페이지 이동">
            <button class="btn btn-outline" data-action="page" data-target="prev" ${page <= 1 ? 'disabled' : ''}>이전</button>
            ${renderPageSelect(page, totalPages, '페이지 선택 (아래)')}
            <button class="btn btn-primary" data-action="page" data-target="next" ${page >= totalPages ? 'disabled' : ''}>다음 페이지</button>
        </nav>`;
}

function feedSubText(total) {
    if (app.searchQuery) return `모든 키워드에서 ${total}건`;
    const summary = viewSummary(app.activeKey);
    if (!summary) return '';
    const unread = summary.unread_ids.length;
    const label = isAllView() ? '모든 키워드' : `${esc(findTab(app.activeKey).board_name)} 게시판`;
    return `${label} · ${summary.total}개 글${unread ? ` · <strong>새 글 ${unread}</strong>` : ''}`;
}

function renderFeedSub() {
    // 읽음 처리로 안 읽은 수가 바뀌면 제목 아래 요약과 '모두 읽음' 버튼만 갱신
    const sub = document.querySelector('.feed-sub');
    if (sub && !app.searchQuery) sub.innerHTML = feedSubText();
    const btn = document.querySelector('[data-action="mark-all-read"]');
    const summary = viewSummary(app.activeKey);
    if (btn && summary) btn.hidden = app.searchQuery || summary.unread_ids.length === 0;
}

async function loadPosts() {
    const feed = document.getElementById('feed');
    hideNewBanner();
    const searching = !!app.searchQuery;
    const tab = isAllView() ? null : findTab(app.activeKey);
    if (!searching && !isAllView() && !tab) {
        feed.innerHTML = '<div class="empty-card">등록된 키워드가 없습니다. 관리에서 키워드를 추가해 주세요.</div>';
        return;
    }
    const viewKey = searching ? 'search:' + app.searchQuery : app.activeKey;
    const videoOnly = !!app.videoOnly[app.activeKey];
    const params = new URLSearchParams({ page: app.page, video_only: videoOnly ? '1' : '0' });
    if (searching) params.set('q', app.searchQuery);
    else if (isAllView()) params.set('scope', 'all');
    else { params.set('board', tab.board); params.set('keyword', tab.keyword); }

    let data;
    try {
        data = await getJSON('/api/posts?' + params.toString());
    } catch (e) {
        feed.innerHTML = '<div class="empty-card">게시글을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>';
        return;
    }
    const currentKey = app.searchQuery ? 'search:' + app.searchQuery : app.activeKey;
    if (viewKey !== currentKey) return;  // 응답 도착 전에 다른 보기로 이동한 경우
    app.page = data.page;
    app.totalPages = data.total_pages;
    const summary = viewSummary(app.activeKey);
    app.renderedTotal = searching ? null : (summary ? summary.total : null);
    if (!searching) {
        storageSet(sessionStorage, 'last_active_tab', app.activeKey);
        storageSet(sessionStorage, 'last_active_page', String(app.page));
    }

    const empty = data.total === 0;
    let body = '';
    if (empty) {
        body = searching ? `<div class="empty-card">'${esc(app.searchQuery)}'에 해당하는 글이 없습니다.</div>`
            : videoOnly ? '<div class="empty-card">동영상이 포함된 게시글이 없습니다.</div>'
            : '<div class="empty-card">수집된 게시글이 없습니다. 새 글이 등록되면 이곳에 표시됩니다.</div>';
    } else {
        let sawUnread = false;
        let dividerShown = false;
        data.posts.forEach(post => {
            const isUnread = post.is_new && !post.read_at;
            // 안 읽은 새 글 다음부터는 이미 본 글이라는 구분선을 한 번만 표시
            if (!searching && !isUnread && sawUnread && !dividerShown) {
                body += '<div class="new-divider" role="separator">여기까지 새 글</div>';
                dividerShown = true;
            }
            if (isUnread) sawUnread = true;
            body += renderPost(post, isUnread);
        });
    }

    const title = searching ? `검색: ${esc(app.searchQuery)}` : (isAllView() ? '전체' : esc(tab.keyword));
    const headActions = searching
        ? '<button class="btn btn-outline btn-small" data-action="clear-search">검색 닫기</button>'
        : `<button class="btn btn-outline btn-small" data-action="mark-all-read" ${summary && summary.unread_ids.length ? '' : 'hidden'}>모두 읽음</button>`;
    feed.innerHTML = `
        <div class="feed-head">
            <div class="feed-head-text">
                <div class="feed-title-row">
                    <h1 class="feed-title">${title}</h1>
                    ${headActions}
                </div>
                <span class="feed-sub">${feedSubText(data.total)}</span>
            </div>
            <div class="feed-tools">
                <div class="segmented" role="group" aria-label="글 필터">
                    <button data-action="set-filter" data-video="0" aria-pressed="${!videoOnly}">전체</button>
                    <button data-action="set-filter" data-video="1" aria-pressed="${videoOnly}">동영상만</button>
                </div>
                ${renderPagerMini(data.page, data.total_pages, empty)}
            </div>
        </div>
        ${body}
        ${empty ? '' : renderPager(data.page, data.total_pages)}`;
    observeReadSentinels();

    if (app.highlightPostId) {
        const target = document.getElementById('post-' + app.highlightPostId);
        app.highlightPostId = null;
        if (target) {
            setTimeout(() => {
                const offset = document.querySelector('.topbar').offsetHeight + 12;
                window.scrollTo({ top: target.getBoundingClientRect().top + window.pageYOffset - offset, behavior: 'smooth' });
                target.classList.add('highlight');
                setTimeout(() => target.classList.remove('highlight'), 2500);
            }, 300);
        }
    }
}

function changePage(target) {
    if (target === 'prev') app.page = Math.max(1, app.page - 1);
    else if (target === 'next') app.page = Math.min(app.totalPages, app.page + 1);
    else app.page = Math.min(Math.max(1, Number(target) || 1), app.totalPages);
    loadPosts().then(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
}

function markAllRead() {
    const summary = viewSummary(app.activeKey);
    if (!summary || summary.unread_ids.length === 0) return;
    const ids = summary.unread_ids.slice();
    markRead(ids);
    flushReads();
    // 화면의 NEW 표시와 구분선도 바로 정리
    document.querySelectorAll('.badge-new').forEach(el => el.remove());
    document.querySelectorAll('.new-divider').forEach(el => el.remove());
}

// ==========================================
// 검색
// ==========================================
function runSearch(query) {
    const q = (query || '').trim();
    if (!q) { clearSearch(); return; }
    app.searchQuery = q;
    app.page = 1;
    renderNavigation();
    loadPosts().then(() => window.scrollTo({ top: 0 }));
}

function clearSearch() {
    app.searchQuery = '';
    document.getElementById('search-input').value = '';
    document.querySelector('.topbar').classList.remove('search-open');
    app.page = 1;
    renderNavigation();
    loadPosts().then(() => window.scrollTo({ top: 0 }));
}

// ==========================================
// 새 글 실시간 확인 (1분마다 조용히 확인하고 배너로 알림)
// ==========================================
function hideNewBanner() {
    document.getElementById('new-banner').hidden = true;
}

async function pollState() {
    if (document.hidden || !app.state) return;
    await flushReads();
    let fresh;
    try {
        fresh = await getJSON('/api/state');
    } catch (e) {
        renderStatus(false);
        return;
    }
    app.state = fresh;
    renderStatus(true);
    renderNavigation();
    renderFeedSub();
    if (app.searchQuery || app.renderedTotal === null) return;
    const summary = viewSummary(app.activeKey);
    if (!summary) return;
    const added = summary.total - app.renderedTotal;
    if (added > 0) {
        const banner = document.getElementById('new-banner');
        banner.innerHTML = `${ICONS.up}<span>새 글 ${added}개 · 눌러서 보기</span>`;
        banner.hidden = false;
    }
}

async function showNewPosts() {
    hideNewBanner();
    app.page = 1;
    await loadPosts();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ==========================================
// 관리 패널
// ==========================================
function alertSwitch(boardKey, type, on, label) {
    return `
        <label class="switch">
            <input type="checkbox" data-action="toggle-alert" data-board="${esc(boardKey)}" data-type="${type}" aria-label="${esc(label)}" ${on ? 'checked' : ''}>
            <span class="slider"></span>
        </label>`;
}

function renderSettings() {
    const select = document.getElementById('board-select');
    const prev = select.value;
    select.innerHTML = app.state.boards.map(b => `<option value="${esc(b.key)}">${esc(b.name)}</option>`).join('');
    if (prev) select.value = prev;
    else {
        const active = findTab(app.activeKey);
        if (active) select.value = active.board;
    }

    document.getElementById('settings-keywords').innerHTML = app.state.tabs.map((tab, idx) => `
        <span class="kw-tag">
            <span class="kw-tag-board">${esc(tab.board_name)}</span>${esc(tab.keyword)}
            <button data-action="delete-keyword" data-index="${idx}" aria-label="${esc(tab.board_name + ' ' + tab.keyword)} 키워드 삭제">${ICONS.close}</button>
        </span>`).join('');

    document.getElementById('settings-alerts').innerHTML = app.state.boards.map(b => {
        const cfg = app.state.board_config[b.key] || { alert: true, video_alert: true };
        return `
            <div class="alert-row">
                <span class="alert-row-name">${esc(b.name)}</span>
                <span class="alert-switches">
                    ${alertSwitch(b.key, 'alert', cfg.alert, b.name + ' 전체 알림')}
                    ${alertSwitch(b.key, 'video_alert', cfg.video_alert, b.name + ' 동영상 알림')}
                </span>
            </div>`;
    }).join('');
}

function setSettingsOpen(open) {
    const panel = document.getElementById('settings');
    panel.hidden = !open;
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
        renderSettings();
        const pwd = document.getElementById('admin-pwd-input');
        (pwd.value ? document.getElementById('new-kw-input') : pwd).focus();
    }
}

function adminPassword() {
    return document.getElementById('admin-pwd-input').value.trim();
}

async function toggleBoardAlert(checkbox) {
    const pwd = adminPassword();
    const target = checkbox.checked;
    if (!pwd) {
        alert('알림 설정을 변경하려면 관리자 암호를 먼저 입력해 주세요.');
        checkbox.checked = !target;
        document.getElementById('admin-pwd-input').focus();
        return;
    }
    const board = checkbox.dataset.board;
    const type = checkbox.dataset.type;
    try {
        const data = await postJSON('/api/toggle-alert', { board: board, type: type, enabled: target, password: pwd });
        if (data.success) {
            app.state.board_config[board][type] = target;
            renderNavigation();
        } else {
            alert(data.message);
            checkbox.checked = !target;
        }
    } catch (e) {
        alert('알림 상태 요청 중 오류가 발생했습니다.');
        checkbox.checked = !target;
    }
}

async function manageKeyword(action, keyword, board, button) {
    const pwd = adminPassword();
    if (!keyword) { alert('키워드를 입력해 주세요.'); return; }
    if (!pwd) { alert('관리자 암호를 입력해야 합니다.'); document.getElementById('admin-pwd-input').focus(); return; }
    if (action === 'delete' && !confirm("'" + keyword + "' 키워드를 정말 삭제하시겠습니까?")) return;

    if (button) button.disabled = true;
    try {
        const data = await postJSON('/api/keyword', { action: action, keyword: keyword, board: board, password: pwd });
        if (data.success) {
            if (action === 'add') {
                document.getElementById('new-kw-input').value = '';
                app.activeKey = board + '::' + keyword;
                app.page = 1;
            } else if (app.activeKey === board + '::' + keyword) {
                app.activeKey = ALL_KEY;
            }
            app.searchQuery = '';
            await loadState();
            renderSettings();
        } else {
            alert(data.message);
        }
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
    } finally {
        if (button) button.disabled = false;
    }
}

// ==========================================
// 전체 상태 로드 / 새로고침 / 텔레그램 링크
// ==========================================
async function loadState() {
    await flushReads();
    app.state = await getJSON('/api/state');
    renderStatus(true);
    if (app.activeKey !== ALL_KEY && !findTab(app.activeKey)) {
        app.activeKey = ALL_KEY;
        app.page = 1;
    }
    renderNavigation();
    await loadPosts();
}

async function refreshCurrent() {
    try {
        await loadState();
    } catch (e) {
        renderStatus(false);
    }
}

async function handlePostAnchor() {
    const match = /^#post-(\d+)$/.exec(window.location.hash);
    if (!match) return false;
    const postId = match[1];
    let loc;
    try {
        loc = await getJSON('/api/locate?id=' + encodeURIComponent(postId));
    } catch (e) {
        return false;
    }
    if (!loc.found) {
        window.location.replace('https://www.fmkorea.com/' + postId);
        return true;
    }
    const key = loc.board + '::' + loc.keyword;
    app.videoOnly[key] = false;
    app.highlightPostId = postId;
    openView(key, loc.page);
    return true;
}

async function init() {
    const savedTab = storageGet(sessionStorage, 'last_active_tab', null);
    const savedPage = parseInt(storageGet(sessionStorage, 'last_active_page', '1'), 10) || 1;
    await migrateLegacyReads();
    try {
        app.state = await getJSON('/api/state');
    } catch (e) {
        renderStatus(false);
        document.getElementById('feed').innerHTML = '<div class="empty-card">서버에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.</div>';
        return;
    }
    renderStatus(true);
    // 텔레그램 알림 링크(#post-ID)로 들어온 경우 해당 글이 있는 탭/페이지로 바로 이동
    if (await handlePostAnchor()) return;
    if (savedTab === ALL_KEY || findTab(savedTab)) {
        app.activeKey = savedTab;
        app.page = savedPage;
    } else {
        app.activeKey = ALL_KEY;
        app.page = 1;
    }
    renderNavigation();
    scrollActiveChipIntoView();
    loadPosts();
    setInterval(pollState, POLL_INTERVAL_MS);
}

// ==========================================
// 이벤트 연결 (인라인 핸들러 없이 위임 방식으로 처리하여 CSP를 엄격하게 유지)
// ==========================================
document.addEventListener('click', (e) => {
    const backdrop = document.getElementById('settings');
    if (e.target === backdrop) { setSettingsOpen(false); return; }
    const el = e.target.closest('[data-action]');
    if (!el || el.tagName === 'INPUT') return;
    const action = el.dataset.action;
    if (action === 'open-tab') {
        const tab = app.state.tabs[Number(el.dataset.index)];
        if (tab) openView(tabKey(tab), 1);
    } else if (action === 'open-all') {
        openView(ALL_KEY, 1);
    } else if (action === 'delete-keyword') {
        const tab = app.state.tabs[Number(el.dataset.index)];
        if (tab) manageKeyword('delete', tab.keyword, tab.board, el);
    } else if (action === 'add-keyword') {
        manageKeyword('add', document.getElementById('new-kw-input').value.trim(), document.getElementById('board-select').value, el);
    } else if (action === 'page') {
        changePage(el.dataset.target);
    } else if (action === 'set-filter') {
        app.videoOnly[app.activeKey] = el.dataset.video === '1';
        app.page = 1;
        loadPosts();
    } else if (action === 'mark-all-read') {
        markAllRead();
    } else if (action === 'show-new') {
        showNewPosts();
    } else if (action === 'toggle-search') {
        const topbar = document.querySelector('.topbar');
        topbar.classList.toggle('search-open');
        if (topbar.classList.contains('search-open')) document.getElementById('search-input').focus();
    } else if (action === 'clear-search') {
        clearSearch();
    } else if (action === 'open-settings') {
        setSettingsOpen(true);
    } else if (action === 'close-settings') {
        setSettingsOpen(false);
    } else if (action === 'refresh') {
        refreshCurrent();
    } else if (action === 'scroll-top') {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
});

document.addEventListener('change', (e) => {
    if (e.target.dataset.action === 'toggle-alert') toggleBoardAlert(e.target);
    else if (e.target.dataset.action === 'go-page') changePage(e.target.value);
});

document.addEventListener('submit', (e) => {
    if (e.target.id === 'search-form') {
        e.preventDefault();
        runSearch(document.getElementById('search-input').value);
        document.getElementById('search-input').blur();
    }
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.id === 'new-kw-input') {
        document.querySelector('[data-action="add-keyword"]').click();
    } else if (e.key === 'Escape' && !document.getElementById('settings').hidden) {
        setSettingsOpen(false);
    } else if (e.key === 'Escape' && e.target.id === 'search-input' && app.searchQuery) {
        clearSearch();
    }
});

// 페이지를 떠나거나 백그라운드로 갈 때 남은 읽음 기록 전송, 다시 보일 때 바로 새 글 확인
window.addEventListener('pagehide', () => flushReads(true));
document.addEventListener('visibilitychange', () => {
    if (document.hidden) flushReads(true);
    else pollState();
});

window.addEventListener('hashchange', handlePostAnchor);

window.addEventListener('scroll', () => {
    document.getElementById('floating-top-btn').classList.toggle('visible', window.scrollY > 400);
    scheduleReadCheck();
}, { passive: true });
window.addEventListener('resize', scheduleReadCheck, { passive: true });

document.addEventListener('DOMContentLoaded', init);
