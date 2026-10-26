'use strict';

// ==========================================
// 상태 및 공용 유틸
// ==========================================
const ALL_KEY = '__all__';            // 모든 게시판을 합친 통합 피드
const UNREAD_KEY = '__unread__';      // 모든 게시판의 안 읽은 새 글 모아보기 (첫 화면)
const POLL_INTERVAL_MS = 60 * 1000;   // 새 글 확인 주기
const LEGACY_READ_IDS_KEY = 'read_post_ids';

const app = {
    state: null,          // /api/state 응답
    activeKey: ALL_KEY,   // 현재 보기: UNREAD_KEY, ALL_KEY 또는 "group:<게시판 ID>"
    unreadSince: null,    // 안 읽은 글 보기를 연 서버 시각 (보는 중 읽은 글이 빠져 페이지가 밀리지 않게)
    renderedUnreadIds: null, // 안 읽은 글 보기를 그릴 때의 안 읽은 글 ID (새 글 배너 계산용)
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

function groupKey(group) { return 'group:' + group.id; }
function memberKey(m) { return m.board + '::' + m.keyword; }
function boardName(key) {
    const board = app.state ? app.state.boards.find(b => b.key === key) : null;
    return board ? board.name : key;
}
function findGroup(key) { return app.state ? (app.state.groups || []).find(g => groupKey(g) === key) : null; }
function isAllView() { return app.activeKey === ALL_KEY; }
function isUnreadView() { return app.activeKey === UNREAD_KEY; }
function isKnownView(key) { return key === ALL_KEY || key === UNREAD_KEY || !!findGroup(key); }

// 첫 화면: 안 읽은 글이 있으면 안 읽은 글 모아보기, 없으면 가장 최근에 알림이 간 게시판, 그것도 없으면 전체
function homeKey() {
    if (!app.state) return ALL_KEY;
    if (app.state.unread.total > 0) return UNREAD_KEY;
    const latest = app.state.latest_alert_group;
    return latest && findGroup('group:' + latest) ? 'group:' + latest : ALL_KEY;
}

// 현재 보기(통합 피드·게시판)의 요약: 글 수, 안 읽은 새 글 ID
function viewSummary(key) {
    if (!app.state) return null;
    if (key === UNREAD_KEY) return app.state.unread;
    return key === ALL_KEY ? app.state.all : findGroup(key);
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
    (app.state.groups || []).forEach(g => { g.unread_ids = g.unread_ids.filter(id => !set.has(id)); });
    app.state.all.unread_ids = app.state.all.unread_ids.filter(id => !set.has(id));
    const unread = app.state.unread;
    const before = unread.unread_ids.length;
    unread.unread_ids = unread.unread_ids.filter(id => !set.has(id));
    unread.total = Math.max(0, unread.total - (before - unread.unread_ids.length));
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
    const searching = !!app.searchQuery;
    const groups = app.state.groups || [];
    const allActive = !searching && isAllView();
    const unreadActive = !searching && isUnreadView();
    const unreadTotal = app.state.unread.total;
    const isActive = g => !searching && groupKey(g) === app.activeKey;

    // 데스크톱: 안 읽은 글 + 통합 피드 + 사용자가 만든 게시판
    document.getElementById('keyword-groups').innerHTML = `
        <nav class="kw-group" aria-label="통합">
            ${navItem('안 읽은 글', '', unreadTotal, unreadActive, 'data-action="open-unread"')}
            ${navItem('전체', app.state.all.total, app.state.all.unread_ids.length, allActive, 'data-action="open-all"')}
        </nav>
        <nav class="kw-group" aria-label="게시판">
            ${groups.length ? groups.map(g => navItem(esc(g.name), g.total, g.unread_ids.length, isActive(g),
                `data-action="open-group" data-group-id="${g.id}"`)).join('')
                : '<span class="kw-group-name">게시판이 없습니다. 관리에서 만들어 주세요.</span>'}
        </nav>`;

    // 모바일: 가로로 넘기는 칩 (맨 앞이 통합 피드)
    const chip = (label, count, hasUnread, active, attrs) => `
        <button class="chip ${active ? 'active' : ''}" ${attrs} ${active ? 'aria-current="true"' : ''}>
            <span>${label}</span>
            <span class="chip-count">${count}</span>
            ${hasUnread ? '<span class="chip-dot" aria-label="안 읽은 새 글"></span>' : ''}
        </button>`;
    document.getElementById('chip-row').innerHTML =
        chip('안 읽은 글', unreadTotal, false, unreadActive, 'data-action="open-unread"') +
        chip('전체', app.state.all.total, app.state.all.unread_ids.length > 0, allActive, 'data-action="open-all"') +
        groups.map(g => chip(esc(g.name), g.total, g.unread_ids.length > 0, isActive(g),
            `data-action="open-group" data-group-id="${g.id}"`)).join('');

    // 사이드바 하단 알림 요약 (게시판별)
    const summary = groups.map(g => `${g.name} · ${alertMode(g)}`);
    document.getElementById('alert-summary').textContent = summary.length ? summary.join('\n') : '게시판이 없습니다.';
}

function alertMode(group) {
    return group.alert ? '전체 알림' : (group.video_alert ? '동영상 글만' : '알림 꺼짐');
}

function scrollActiveChipIntoView() {
    const activeChip = document.querySelector('#chip-row .chip.active');
    if (activeChip) activeChip.scrollIntoView({ block: 'nearest', inline: 'center' });
}

function openView(key, page) {
    app.activeKey = key;
    if (key === UNREAD_KEY) app.unreadSince = app.state.generated_at;
    app.searchQuery = '';
    document.getElementById('search-input').value = '';
    app.page = page || 1;
    renderNavigation();
    scrollActiveChipIntoView();
    loadPosts().then(() => window.scrollTo({ top: 0 }));
}

// 홈: 검색·관리 패널·텔레그램 링크(#post-ID)를 정리하고 통합 피드 첫 페이지로
function goHome() {
    if (!document.getElementById('settings').hidden) setSettingsOpen(false);
    document.querySelector('.topbar').classList.remove('search-open');
    if (window.location.hash) history.replaceState(null, '', window.location.pathname);
    openView(homeKey(), 1);
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

// 저장된 댓글 HTML을 이미지 요청 없이 해석 (DOMParser 문서는 화면에 붙지 않아 리소스를 불러오지 않음)
const commentParser = new DOMParser();
function parseCommentHtml(comment) {
    return commentParser.parseFromString((comment.content || []).join(' '), 'text/html').body;
}

// 에펨코리아 답글은 본문 맨 앞에 상대 닉네임 링크(a.findParent)가 붙어 있음
function replyTargetName(comment) {
    const link = parseCommentHtml(comment).querySelector('a.findParent');
    return link ? link.textContent.trim() : '';
}

// 답글 깊이 (0: 일반 댓글). 깊이를 저장하기 전에 수집된 답글은 1단으로 봄
const MAX_REPLY_DEPTH = 4;
function replyDepth(comment) {
    if (!comment.is_reply) return 0;
    return Math.min(Math.max(parseInt(comment.depth, 10) || 1, 1), MAX_REPLY_DEPTH);
}

// 답글의 원댓글: 깊이를 알면 위쪽에서 한 단계 얕은 가장 가까운 댓글,
// 아니면 상대 닉네임으로 쓴 가장 가까운 댓글, 없으면 바로 위의 일반 댓글
function findParentComment(comments, idx) {
    const depth = parseInt(comments[idx].depth, 10) || 0;
    if (depth >= 1) {
        for (let i = idx - 1; i >= 0; i--) {
            const d = comments[i].is_reply ? (parseInt(comments[i].depth, 10) || 1) : 0;
            if (d === depth - 1) return comments[i];
        }
    }
    const target = replyTargetName(comments[idx]);
    for (let i = idx - 1; i >= 0; i--) {
        if (target && comments[i].author === target) return comments[i];
    }
    for (let i = idx - 1; i >= 0; i--) {
        if (!comments[i].is_reply) return comments[i];
    }
    return null;
}

const REPLY_QUOTE_LENGTH = 40;
function commentSnippet(comment) {
    const body = parseCommentHtml(comment);
    body.querySelectorAll('a.findParent').forEach(a => a.remove());
    body.querySelectorAll('img').forEach(img => img.replaceWith(' (이미지) '));
    const text = body.textContent.replace(/\s+/g, ' ').trim() || '(내용 없음)';
    return text.length > REPLY_QUOTE_LENGTH ? text.slice(0, REPLY_QUOTE_LENGTH) + '…' : text;
}

function renderComments(post) {
    if (!post.comments || post.comments.length === 0) {
        // 넓은 화면의 2단 배치에서 오른쪽 댓글 자리를 유지하기 위한 빈 댓글 칸 (좁은 화면에서는 CSS로 숨김)
        return '<section class="comments is-empty"><h3 class="comments-title">댓글 0</h3><p class="comments-empty">아직 댓글이 없습니다.</p></section>';
    }
    const items = post.comments.map((c, idx) => {
        const body = (c.content || []).map(t => t ? `<p class="comment-line">${t}</p>` : '<br>').join('');
        const isAuthor = c.author === post.author;
        const isNew = isNewComment(c, post);
        const classes = ['comment'];
        const depth = replyDepth(c);
        if (c.is_reply) classes.push('reply');
        if (isAuthor) classes.push('by-author');
        if (isNew) classes.push('is-new-comment');
        // 새 답글은 어느 댓글에 단 답글인지 원댓글을 한 줄 인용
        const parent = c.is_reply && isNew ? findParentComment(post.comments, idx) : null;
        const quote = parent ? `
                    <div class="reply-quote"><span class="reply-quote-author">${esc(parent.author)}</span>${esc(commentSnippet(parent))}</div>` : '';
        return `
            <div class="${classes.join(' ')}"${depth ? ` style="--depth: ${depth}"` : ''}>
                <span class="comment-avatar av-${avatarTone(c.author)}" aria-hidden="true">${esc(Array.from(c.author || '?')[0])}</span>
                <div class="comment-main">
                    <div class="comment-meta">
                        <span class="comment-author">${esc(c.author)}</span>
                        ${isAuthor ? '<span class="op-badge">작성자</span>' : ''}
                        ${isNew ? `<span class="new-comment-badge">${c.is_reply ? '새 답글' : '새 댓글'}</span>` : ''}
                        <span>${esc(c.date)}</span>
                        ${c.votes && c.votes !== '0' ? `<span class="comment-votes">추천 ${esc(c.votes)}</span>` : ''}
                    </div>${quote}
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
    // 통합 피드·검색·키워드가 여러 개인 게시판에서는 어느 키워드로 모인 글인지 표시
    const group = findGroup(app.activeKey);
    const keywordTags = (post.keywords && (isAllView() || isUnreadView() || app.searchQuery || (group && group.members.length > 1)))
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
    if (app.searchQuery) return `모든 게시판에서 ${total}건`;
    const summary = viewSummary(app.activeKey);
    if (!summary) return '';
    const unread = summary.unread_ids.length;
    if (isUnreadView()) return unread ? `모든 게시판의 안 읽은 새 글 <strong>${summary.total}개</strong>` : '안 읽은 글을 모두 읽었습니다';
    const group = findGroup(app.activeKey);
    const label = group ? `키워드 ${group.members.map(m => esc(m.keyword)).join(', ')}` : '모든 게시판';
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
    const group = findGroup(app.activeKey);
    const viewKey = searching ? 'search:' + app.searchQuery : app.activeKey;
    const videoOnly = !!app.videoOnly[app.activeKey];
    const params = new URLSearchParams({ page: app.page, video_only: videoOnly ? '1' : '0' });
    if (searching) params.set('q', app.searchQuery);
    else if (group) params.set('group', group.id);
    else if (isUnreadView()) {
        if (!app.unreadSince) app.unreadSince = app.state.generated_at;
        params.set('unread_since', app.unreadSince);
    }

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
    app.renderedUnreadIds = isUnreadView() ? new Set(app.state.unread.unread_ids) : null;
    if (!searching) {
        storageSet(sessionStorage, 'last_active_tab', app.activeKey);
        storageSet(sessionStorage, 'last_active_page', String(app.page));
    }

    const empty = data.total === 0;
    let body = '';
    if (empty) {
        const latest = findGroup('group:' + app.state.latest_alert_group);
        body = isUnreadView() && !videoOnly
            ? `<div class="empty-card">안 읽은 글이 없습니다.${latest ? ` <button class="link-btn" data-action="open-group" data-group-id="${latest.id}">최근 알림 게시판(${esc(latest.name)}) 보기</button>` : ''}</div>`
            : !searching && !(app.state.groups || []).length
            ? '<div class="empty-card">게시판이 없습니다. 관리에서 게시판을 만들고 키워드를 등록해 주세요.</div>'
            : searching ? `<div class="empty-card">'${esc(app.searchQuery)}'에 해당하는 글이 없습니다.</div>`
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

    const title = searching ? `검색: ${esc(app.searchQuery)}` : group ? esc(group.name) : isUnreadView() ? '안 읽은 글' : '전체';
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
    const added = isUnreadView() && app.renderedUnreadIds
        ? summary.unread_ids.filter(id => !app.renderedUnreadIds.has(id)).length
        : summary.total - app.renderedTotal;
    if (added > 0) {
        const banner = document.getElementById('new-banner');
        banner.innerHTML = `${ICONS.up}<span>새 글 ${added}개 · 눌러서 보기</span>`;
        banner.hidden = false;
    }
}

async function showNewPosts() {
    hideNewBanner();
    app.page = 1;
    if (isUnreadView()) app.unreadSince = app.state.generated_at;
    await loadPosts();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ==========================================
// 관리 패널
// ==========================================
function alertSwitch(groupId, type, on, label) {
    return `
        <label class="switch">
            <input type="checkbox" data-action="toggle-alert" data-group-id="${groupId}" data-type="${type}" aria-label="${esc(label)}" ${on ? 'checked' : ''}>
            <span class="slider"></span>
        </label>`;
}

function renderSettings() {
    const select = document.getElementById('group-board-select');
    const prev = select.value;
    select.innerHTML = app.state.boards.map(b => `<option value="${esc(b.key)}">${esc(b.name)}</option>`).join('');
    if (prev) select.value = prev;

    renderGroupSettings();

    const groups = app.state.groups || [];
    document.getElementById('settings-alerts').innerHTML = groups.length ? groups.map(g => `
        <div class="alert-row">
            <span class="alert-row-name">${esc(g.name)}</span>
            <span class="alert-switches">
                ${alertSwitch(g.id, 'alert', g.alert, g.name + ' 전체 알림')}
                ${alertSwitch(g.id, 'video_alert', g.video_alert, g.name + ' 동영상 알림')}
            </span>
        </div>`).join('') : '<span class="settings-hint">게시판을 만들면 게시판별로 알림을 설정할 수 있습니다.</span>';
}

// ---------- 게시판 만들기·수정·삭제 (키워드는 게시판에 등록) ----------
function renderGroupSettings() {
    const editing = (app.state.groups || []).find(g => g.id === app.editingGroupId) || null;
    if (!editing) app.editingGroupId = null;
    if (app.groupDraft === undefined) app.groupDraft = editing ? editing.members.map(m => ({ board: m.board, keyword: m.keyword })) : [];

    document.getElementById('group-form-title').textContent = editing ? `'${editing.name}' 게시판 수정` : '게시판 만들기';
    document.getElementById('group-save-btn').textContent = editing ? '저장' : '만들기';
    document.getElementById('group-cancel-btn').hidden = !editing;
    const nameInput = document.getElementById('group-name-input');
    if (app.groupNameDraft !== undefined) nameInput.value = app.groupNameDraft;
    else nameInput.value = editing ? editing.name : '';

    // 이 게시판에 등록할 키워드 (카테고리와 함께 표시)
    document.getElementById('group-keywords').innerHTML = app.groupDraft.length ? app.groupDraft.map((m, idx) => `
        <span class="kw-tag">
            <span class="kw-tag-board">${esc(boardName(m.board))}</span>${esc(m.keyword)}
            <button data-action="remove-draft-keyword" data-index="${idx}" aria-label="${esc(boardName(m.board) + ' ' + m.keyword)} 키워드 빼기">${ICONS.close}</button>
        </span>`).join('') : '<span class="settings-hint">아직 등록한 키워드가 없습니다.</span>';

    const groups = app.state.groups || [];
    document.getElementById('settings-groups').innerHTML = groups.length ? groups.map(g => `
        <div class="group-row">
            <div class="group-row-main">
                <span class="group-row-name">${esc(g.name)}</span>
                <span class="group-row-members">${g.members.map(m => esc(m.keyword)).join(' · ') || '(키워드 없음)'} · ${g.total}개 글</span>
            </div>
            <button class="btn btn-outline btn-small" data-action="edit-group" data-group-id="${g.id}">수정</button>
            <button class="btn btn-outline btn-small btn-danger" data-action="delete-group" data-group-id="${g.id}">삭제</button>
        </div>`).join('') : '<span class="settings-hint">만든 게시판이 없습니다.</span>';
}

function addDraftKeyword() {
    const input = document.getElementById('group-kw-input');
    const keyword = input.value.trim();
    const board = document.getElementById('group-board-select').value;
    if (!keyword) { input.focus(); return; }
    if (app.groupDraft.some(m => m.board === board && m.keyword === keyword)) {
        alert('이미 등록한 키워드입니다.');
        return;
    }
    app.groupDraft.push({ board: board, keyword: keyword });
    input.value = '';
    renderGroupSettings();
    input.focus();
}

function resetGroupForm() {
    app.editingGroupId = null;
    app.groupDraft = undefined;
    app.groupNameDraft = undefined;
    document.getElementById('group-kw-input').value = '';
    renderGroupSettings();
}

// 다른 게시판에 없는 키워드는 게시판에서 빠지면 수집을 멈추고 모은 글도 삭제됨
function droppedKeywords(groupId, keepMembers) {
    const keep = new Set(keepMembers.map(memberKey));
    const others = new Set((app.state.groups || []).filter(g => g.id !== groupId).flatMap(g => g.members.map(memberKey)));
    const group = (app.state.groups || []).find(g => g.id === groupId);
    return group ? group.members.filter(m => !keep.has(memberKey(m)) && !others.has(memberKey(m))) : [];
}

async function saveGroup(button) {
    const pwd = adminPassword();
    const name = document.getElementById('group-name-input').value.trim();
    // 입력만 하고 '추가'를 누르지 않은 키워드도 함께 등록
    if (document.getElementById('group-kw-input').value.trim()) addDraftKeyword();
    const members = app.groupDraft.slice();
    if (!name) { alert('게시판 이름을 입력해 주세요.'); document.getElementById('group-name-input').focus(); return; }
    if (members.length === 0) { alert('키워드를 하나 이상 등록해 주세요.'); document.getElementById('group-kw-input').focus(); return; }
    if (!pwd) { alert('관리자 암호를 입력해야 합니다.'); document.getElementById('admin-pwd-input').focus(); return; }

    const editingId = app.editingGroupId;
    const dropped = editingId ? droppedKeywords(editingId, members) : [];
    if (dropped.length && !confirm(`뺀 키워드 ${dropped.map(m => m.keyword).join(', ')}는 수집을 멈추고 모은 글도 삭제됩니다. 저장할까요?`)) return;
    button.disabled = true;
    try {
        const data = await postJSON('/api/group', {
            action: editingId ? 'update' : 'create', id: editingId, name: name, members: members, password: pwd
        });
        if (!data.success) { alert(data.message); return; }
        resetGroupForm();
        // 만들거나 고친 게시판을 바로 열어서 보여줌
        app.activeKey = 'group:' + data.id;
        app.searchQuery = '';
        app.page = 1;
        setSettingsOpen(false);
        await loadState();
        window.scrollTo({ top: 0 });
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
    } finally {
        button.disabled = false;
    }
}

async function deleteGroup(groupId, button) {
    const group = (app.state.groups || []).find(g => g.id === groupId);
    if (!group) return;
    const pwd = adminPassword();
    if (!pwd) { alert('관리자 암호를 입력해야 합니다.'); document.getElementById('admin-pwd-input').focus(); return; }
    const dropped = droppedKeywords(groupId, []);
    const note = dropped.length ? `\n(키워드 ${dropped.map(m => m.keyword).join(', ')}는 수집을 멈추고 모은 글도 삭제됩니다)` : '';
    if (!confirm(`'${group.name}' 게시판을 삭제할까요?${note}`)) return;
    button.disabled = true;
    try {
        const data = await postJSON('/api/group', { action: 'delete', id: groupId, password: pwd });
        if (!data.success) { alert(data.message); return; }
        if (app.activeKey === 'group:' + groupId) { app.activeKey = ALL_KEY; app.page = 1; }
        if (app.editingGroupId === groupId) resetGroupForm();
        await loadState();
        renderSettings();
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
    } finally {
        button.disabled = false;
    }
}

function setSettingsOpen(open) {
    const panel = document.getElementById('settings');
    panel.hidden = !open;
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
        renderSettings();
        const pwd = document.getElementById('admin-pwd-input');
        (pwd.value ? document.getElementById('group-name-input') : pwd).focus();
    }
}

function adminPassword() {
    return document.getElementById('admin-pwd-input').value.trim();
}

async function toggleGroupAlert(checkbox) {
    const pwd = adminPassword();
    const target = checkbox.checked;
    if (!pwd) {
        alert('알림 설정을 변경하려면 관리자 암호를 먼저 입력해 주세요.');
        checkbox.checked = !target;
        document.getElementById('admin-pwd-input').focus();
        return;
    }
    const groupId = Number(checkbox.dataset.groupId);
    const type = checkbox.dataset.type;
    try {
        const data = await postJSON('/api/toggle-alert', { group: groupId, type: type, enabled: target, password: pwd });
        const group = (app.state.groups || []).find(g => g.id === groupId);
        if (data.success) {
            if (group) group[type] = target;
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

// ==========================================
// 전체 상태 로드 / 새로고침 / 텔레그램 링크
// ==========================================
async function loadState() {
    await flushReads();
    app.state = await getJSON('/api/state');
    renderStatus(true);
    if (!isKnownView(app.activeKey)) {
        app.activeKey = homeKey();
        app.page = 1;
    }
    renderNavigation();
    await loadPosts();
}

async function refreshCurrent() {
    try {
        // 새로고침하면 안 읽은 글 보기에서 이미 읽은 글은 빠짐
        app.unreadSince = null;
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
    const key = loc.group ? 'group:' + loc.group : ALL_KEY;
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
    setInterval(pollState, POLL_INTERVAL_MS);
    // 텔레그램 알림 링크(#post-ID)로 들어온 경우 해당 글이 있는 탭/페이지로 바로 이동
    if (await handlePostAnchor()) return;
    // 같은 탭에서 새로고침하면 보던 화면 유지, 새로 들어오면 첫 화면(안 읽은 글 → 최근 알림 게시판 → 전체)
    if (isKnownView(savedTab)) {
        app.activeKey = savedTab;
        app.page = savedPage;
    } else {
        app.activeKey = homeKey();
        app.page = 1;
    }
    renderNavigation();
    scrollActiveChipIntoView();
    loadPosts();
}

// ==========================================
// 이벤트 연결 (인라인 핸들러 없이 위임 방식으로 처리하여 CSP를 엄격하게 유지)
// ==========================================
// 에펨코리아 동영상 썸네일에는 가운데 재생 버튼이 그림으로 들어 있어 눌러도 반응이 없으므로,
// 멈춘 동영상의 화면 부분(아래쪽 컨트롤 막대 제외)을 누르면 재생. 기본 동작은 막아 두 번 토글되지 않게 함
const VIDEO_CONTROLS_HEIGHT = 56;
function handleVideoClick(e) {
    const video = e.target;
    if (video.tagName !== 'VIDEO' || !video.closest('.post-content, .comment-body') || !video.paused) return false;
    if (e.clientY > video.getBoundingClientRect().bottom - VIDEO_CONTROLS_HEIGHT) return false;
    e.preventDefault();
    video.play().catch(() => {});
    return true;
}

document.addEventListener('click', (e) => {
    if (handleVideoClick(e)) return;
    const backdrop = document.getElementById('settings');
    if (e.target === backdrop) { setSettingsOpen(false); return; }
    const el = e.target.closest('[data-action]');
    if (!el || el.tagName === 'INPUT') return;
    const action = el.dataset.action;
    if (action === 'go-home') {
        e.preventDefault();
        goHome();
    } else if (action === 'open-all') {
        openView(ALL_KEY, 1);
    } else if (action === 'open-unread') {
        openView(UNREAD_KEY, 1);
    } else if (action === 'open-group') {
        openView('group:' + el.dataset.groupId, 1);
    } else if (action === 'save-group') {
        saveGroup(el);
    } else if (action === 'edit-group') {
        app.editingGroupId = Number(el.dataset.groupId);
        app.groupDraft = undefined;
        app.groupNameDraft = undefined;
        renderGroupSettings();
        document.getElementById('group-name-input').focus();
    } else if (action === 'add-draft-keyword') {
        addDraftKeyword();
    } else if (action === 'remove-draft-keyword') {
        app.groupDraft.splice(Number(el.dataset.index), 1);
        renderGroupSettings();
    } else if (action === 'cancel-group-edit') {
        resetGroupForm();
    } else if (action === 'delete-group') {
        deleteGroup(Number(el.dataset.groupId), el);
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
    if (e.target.dataset.action === 'toggle-alert') toggleGroupAlert(e.target);
    else if (e.target.dataset.action === 'go-page') changePage(e.target.value);
});

document.addEventListener('input', (e) => {
    if (e.target.id === 'group-name-input') app.groupNameDraft = e.target.value;
});

document.addEventListener('submit', (e) => {
    if (e.target.id === 'search-form') {
        e.preventDefault();
        runSearch(document.getElementById('search-input').value);
        document.getElementById('search-input').blur();
    }
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.id === 'group-kw-input') {
        e.preventDefault();
        addDraftKeyword();
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
