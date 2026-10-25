'use strict';

// ==========================================
// 상태 및 공용 유틸
// ==========================================
const READ_IDS_KEY = 'read_post_ids';
const READ_IDS_LIMIT = 1500;

const app = {
    state: null,        // /api/state 응답
    activeKey: null,    // 현재 탭 "board::keyword"
    page: 1,
    totalPages: 1,
    videoOnly: {},      // 탭별 동영상만 보기 여부
    highlightPostId: null
};

const ICONS = {
    external: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"></path><path d="M10 14L20 4"></path><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"></path></svg>',
    prev: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"></path></svg>',
    next: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"></path></svg>',
    close: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>'
};

function esc(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function tabKey(tab) { return tab.board + '::' + tab.keyword; }
function findTab(key) { return app.state ? app.state.tabs.find(t => tabKey(t) === key) : null; }

function storageGet(store, key, fallback) {
    try { const v = store.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}
function storageSet(store, key, value) {
    try { store.setItem(key, value); } catch (e) {}
}

function getReadIds() {
    try { return new Set(JSON.parse(storageGet(localStorage, READ_IDS_KEY, '[]'))); } catch (e) { return new Set(); }
}

function markTabRead(key) {
    // 탭을 떠나거나 새로고침할 때, 그 탭의 새 글을 모두 읽음 처리
    const tab = findTab(key);
    if (!tab || tab.new_ids.length === 0) return;
    let ids = [];
    try { ids = JSON.parse(storageGet(localStorage, READ_IDS_KEY, '[]')); } catch (e) {}
    const known = new Set(ids);
    let changed = false;
    tab.new_ids.forEach(id => {
        if (!known.has(id)) { ids.push(id); known.add(id); changed = true; }
    });
    if (changed) {
        if (ids.length > READ_IDS_LIMIT) ids = ids.slice(ids.length - READ_IDS_LIMIT);
        storageSet(localStorage, READ_IDS_KEY, JSON.stringify(ids));
    }
}

function unreadCount(tab, readIds) {
    return tab.new_ids.filter(id => !readIds.has(id)).length;
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
// 상단 상태 / 키워드 내비게이션 (데스크톱 사이드바, 모바일 칩)
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

function renderNavigation() {
    const readIds = getReadIds();
    const tabs = app.state.tabs;

    // 데스크톱: 게시판별로 묶은 키워드 목록 (게시판 순서는 처음 등장한 탭 순서)
    const groups = [];
    tabs.forEach((tab, idx) => {
        let group = groups.find(g => g.board === tab.board);
        if (!group) { group = { board: tab.board, name: tab.board_name, items: [] }; groups.push(group); }
        group.items.push({ tab, idx });
    });
    document.getElementById('keyword-groups').innerHTML = groups.length ? groups.map(group => `
        <nav class="kw-group" aria-label="${esc(group.name)}">
            <span class="kw-group-name">${esc(group.name)}</span>
            ${group.items.map(({ tab, idx }) => {
                const active = tabKey(tab) === app.activeKey;
                const unread = active ? 0 : unreadCount(tab, readIds);
                return `
                <button class="kw-item ${active ? 'active' : ''}" data-action="open-tab" data-index="${idx}" ${active ? 'aria-current="true"' : ''}>
                    <span>${esc(tab.keyword)}</span>
                    <span class="kw-side">
                        ${unread ? `<span class="kw-unread" aria-label="안 읽은 새 글 ${unread}개">${unread}</span>` : ''}
                        <span class="kw-count">${tab.total}</span>
                    </span>
                </button>`;
            }).join('')}
        </nav>`).join('') : '<span class="kw-group-name">등록된 키워드가 없습니다.</span>';

    // 모바일: 가로로 넘기는 키워드 칩
    document.getElementById('chip-row').innerHTML = tabs.map((tab, idx) => {
        const active = tabKey(tab) === app.activeKey;
        const hasUnread = !active && unreadCount(tab, readIds) > 0;
        return `
        <button class="chip ${active ? 'active' : ''}" data-action="open-tab" data-index="${idx}" ${active ? 'aria-current="true"' : ''}>
            <span>${esc(tab.keyword)}</span>
            <span class="chip-count">${tab.total}</span>
            ${hasUnread ? '<span class="chip-dot" aria-label="안 읽은 새 글"></span>' : ''}
        </button>`;
    }).join('');
    const activeChip = document.querySelector('#chip-row .chip.active');
    if (activeChip) activeChip.scrollIntoView({ block: 'nearest', inline: 'center' });

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

function openTab(key, page) {
    if (app.activeKey && app.activeKey !== key) markTabRead(app.activeKey);
    app.activeKey = key;
    app.page = page || 1;
    renderNavigation();
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

function renderComments(post) {
    if (!post.comments || post.comments.length === 0) return '';
    const items = post.comments.map(c => {
        const body = (c.content || []).map(t => t ? `<p class="comment-line">${t}</p>` : '<br>').join('');
        const isAuthor = c.author === post.author;
        const classes = ['comment'];
        if (c.is_reply) classes.push('reply');
        if (isAuthor) classes.push('by-author');
        return `
            <div class="${classes.join(' ')}">
                <span class="comment-avatar av-${avatarTone(c.author)}" aria-hidden="true">${esc(Array.from(c.author || '?')[0])}</span>
                <div class="comment-main">
                    <div class="comment-meta">
                        <span class="comment-author">${esc(c.author)}</span>
                        ${isAuthor ? '<span class="op-badge">작성자</span>' : ''}
                        <span>${esc(c.date)}</span>
                        ${c.votes && c.votes !== '0' ? `<span class="comment-votes">추천 ${esc(c.votes)}</span>` : ''}
                    </div>
                    <div class="comment-body">${body}</div>
                </div>
            </div>`;
    }).join('');
    return `<section class="comments"><h3 class="comments-title">댓글 ${esc(post.comment_count || post.comments.length)}</h3>${items}</section>`;
}

function safeLink(url) {
    return /^https?:\/\//i.test(url || '') ? url : '#';
}

function renderPost(post, isUnread) {
    const classes = ['post-card'];
    if (post.is_deleted) classes.push('is-deleted');
    const badges = [
        isUnread ? '<span class="badge badge-new">NEW</span>' : '',
        post.has_video ? '<span class="badge badge-video">동영상</span>' : '',
        post.is_syncing && !post.is_deleted ? '<span class="badge badge-sync">댓글 추적 중</span>' : '',
        post.is_deleted ? '<span class="badge badge-deleted">원문 삭제됨</span>' : ''
    ].join('');
    const link = esc(safeLink(post.link));
    const votes = post.votes && post.votes !== '0' ? `<span>추천 ${esc(post.votes)}</span>` : '';
    return `
        <article class="${classes.join(' ')}" id="post-${esc(post.id)}">
            <div class="post-head">
                ${badges ? `<div class="badges">${badges}</div>` : ''}
                <div class="title-row">
                    <h2 class="post-title">${esc(post.title)}</h2>
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

async function loadPosts() {
    const feed = document.getElementById('feed');
    const tab = findTab(app.activeKey);
    if (!tab) {
        feed.innerHTML = '<div class="empty-card">등록된 키워드가 없습니다. 관리에서 키워드를 추가해 주세요.</div>';
        return;
    }
    const requestedKey = app.activeKey;
    const videoOnly = !!app.videoOnly[requestedKey];
    const params = new URLSearchParams({ board: tab.board, keyword: tab.keyword, page: app.page, video_only: videoOnly ? '1' : '0' });
    let data;
    try {
        data = await getJSON('/api/posts?' + params.toString());
    } catch (e) {
        feed.innerHTML = '<div class="empty-card">게시글을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>';
        return;
    }
    if (requestedKey !== app.activeKey) return;  // 응답 도착 전에 다른 탭으로 이동한 경우
    app.page = data.page;
    app.totalPages = data.total_pages;
    storageSet(sessionStorage, 'last_active_tab', app.activeKey);
    storageSet(sessionStorage, 'last_active_page', String(app.page));

    const readIds = getReadIds();
    const unread = unreadCount(tab, readIds);
    const empty = data.total === 0;

    let body = '';
    if (empty) {
        body = videoOnly
            ? '<div class="empty-card">동영상이 포함된 게시글이 없습니다.</div>'
            : '<div class="empty-card">수집된 게시글이 없습니다. 새 글이 등록되면 이곳에 표시됩니다.</div>';
    } else {
        let sawUnread = false;
        let dividerShown = false;
        data.posts.forEach(post => {
            const isUnread = post.is_new && !readIds.has(post.id);
            // 안 읽은 새 글 다음부터는 이미 본 글이라는 구분선을 한 번만 표시
            if (!isUnread && sawUnread && !dividerShown) {
                body += '<div class="new-divider" role="separator">여기까지 새 글</div>';
                dividerShown = true;
            }
            if (isUnread) sawUnread = true;
            body += renderPost(post, isUnread);
        });
    }

    feed.innerHTML = `
        <div class="feed-head">
            <div>
                <h1 class="feed-title">${esc(tab.keyword)}</h1>
                <span class="feed-sub">${esc(tab.board_name)} 게시판 · ${tab.total}개 글${unread ? ` · <strong>새 글 ${unread}</strong>` : ''}</span>
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
                app.activeKey = null;
            }
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
    app.state = await getJSON('/api/state');
    renderStatus(true);
    if (!findTab(app.activeKey)) {
        app.activeKey = app.state.tabs.length ? tabKey(app.state.tabs[0]) : null;
        app.page = 1;
    }
    renderNavigation();
    await loadPosts();
}

async function refreshCurrent() {
    if (app.activeKey) markTabRead(app.activeKey);
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
    openTab(key, loc.page);
    return true;
}

async function init() {
    const savedTab = storageGet(sessionStorage, 'last_active_tab', null);
    const savedPage = parseInt(storageGet(sessionStorage, 'last_active_page', '1'), 10) || 1;
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
    if (findTab(savedTab)) {
        app.activeKey = savedTab;
        app.page = savedPage;
    } else {
        app.activeKey = app.state.tabs.length ? tabKey(app.state.tabs[0]) : null;
        app.page = 1;
    }
    renderNavigation();
    loadPosts();
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
        if (tab) openTab(tabKey(tab), 1);
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

document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.id === 'new-kw-input') {
        document.querySelector('[data-action="add-keyword"]').click();
    } else if (e.key === 'Escape' && !document.getElementById('settings').hidden) {
        setSettingsOpen(false);
    }
});

window.addEventListener('beforeunload', () => {
    if (app.activeKey) markTabRead(app.activeKey);
});

window.addEventListener('hashchange', handlePostAnchor);

window.addEventListener('scroll', () => {
    document.getElementById('floating-top-btn').classList.toggle('visible', window.scrollY > 400);
}, { passive: true });

document.addEventListener('DOMContentLoaded', init);
