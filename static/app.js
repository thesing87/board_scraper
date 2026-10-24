'use strict';

// ==========================================
// 상태 및 공용 유틸
// ==========================================
const SYNC_BADGE_TEXT = '🔄 동기화중';
const READ_IDS_KEY = 'read_post_ids';
const READ_IDS_LIMIT = 1500;

const app = {
    state: null,        // /api/state 응답
    activeKey: null,    // 현재 탭 "board::keyword"
    page: 1,
    videoOnly: {},      // 탭별 동영상만 보기 여부
    highlightPostId: null
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
    // 탭을 떠나거나 새로고침할 때, 그 탭의 새 글을 모두 읽음 처리 (기존 대시보드와 동일한 동작)
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

function hasUnread(tab, readIds) {
    return tab.new_ids.some(id => !readIds.has(id));
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
// 관리 패널
// ==========================================
function renderAdminPanel() {
    const select = document.getElementById('board-select');
    const prev = select.value;
    select.innerHTML = app.state.boards.map(b => `<option value="${esc(b.key)}">${esc(b.name)}</option>`).join('');
    if (prev) select.value = prev;

    const zone = document.getElementById('alert-management-zone');
    zone.innerHTML = app.state.boards.map(b => {
        const cfg = app.state.board_config[b.key] || { alert: true, video_alert: true };
        return `
        <div class="toggle-item">
            <span class="toggle-label">🎯 ${esc(b.name)}</span>
            <div class="toggle-group">
                ${renderAlertSwitch(b.key, 'alert', cfg.alert)}
                ${renderAlertSwitch(b.key, 'video_alert', cfg.video_alert)}
            </div>
        </div>`;
    }).join('');
}

function alertStatusText(type, on) {
    if (type === 'video_alert') return on ? '🎬 동영상 활성' : '🎬 동영상 꺼짐';
    return on ? '🔔 일반 활성' : '🔕 일반 꺼짐';
}

function renderAlertSwitch(board, type, on) {
    return `
        <div class="toggle-pair">
            <span class="toggle-status ${on ? 'status-on' : 'status-off'}">${alertStatusText(type, on)}</span>
            <label class="switch">
                <input type="checkbox" data-action="toggle-alert" data-board="${esc(board)}" data-type="${type}" ${on ? 'checked' : ''}>
                <span class="slider round"></span>
            </label>
        </div>`;
}

function setAdminPanelOpen(open) {
    document.getElementById('admin-panel-zone').style.display = open ? 'flex' : 'none';
    document.getElementById('panel-toggle-trigger').textContent = open
        ? '⚙️ 실시간 모니터링 관리 패널 접기 ▲'
        : '⚙️ 실시간 모니터링 관리 패널 열기 ▼';
    storageSet(localStorage, 'admin_panel_open', open ? 'true' : 'false');
}

function adminPassword() {
    return document.getElementById('admin-pwd-input').value.trim();
}

async function toggleBoardAlert(checkbox) {
    const pwd = adminPassword();
    const target = checkbox.checked;
    if (!pwd) {
        alert('알림 설정을 변경하려면 패널 우측의 관리자 암호를 먼저 입력해 주세요.');
        checkbox.checked = !target;
        return;
    }
    const board = checkbox.dataset.board;
    const type = checkbox.dataset.type;
    try {
        const data = await postJSON('/api/toggle-alert', { board: board, type: type, enabled: target, password: pwd });
        alert(data.message);
        if (data.success) {
            app.state.board_config[board][type] = target;
            const status = checkbox.closest('.toggle-pair').querySelector('.toggle-status');
            status.textContent = alertStatusText(type, target);
            status.className = 'toggle-status ' + (target ? 'status-on' : 'status-off');
        } else {
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
    if (!pwd) { alert('인증 관리자 비밀번호를 입력해야 합니다.'); return; }
    if (action === 'delete' && !confirm("'" + keyword + "' 키워드를 정말 삭제하시겠습니까?")) return;

    if (button) button.disabled = true;
    try {
        const data = await postJSON('/api/keyword', { action: action, keyword: keyword, board: board, password: pwd });
        alert(data.message);
        if (data.success) {
            if (action === 'add') {
                document.getElementById('new-kw-input').value = '';
                app.activeKey = board + '::' + keyword;
                app.page = 1;
            } else if (app.activeKey === board + '::' + keyword) {
                app.activeKey = null;
            }
            await loadState();
        }
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
    } finally {
        if (button) button.disabled = false;
    }
}

// ==========================================
// 탭
// ==========================================
function renderTabs() {
    const readIds = getReadIds();
    const container = document.getElementById('tab-scroll-container');
    container.innerHTML = app.state.tabs.map((tab, idx) => {
        const key = tabKey(tab);
        const active = key === app.activeKey;
        const showDot = !active && hasUnread(tab, readIds);
        const label = `[${tab.board_name}] ${tab.keyword} (${tab.total})`;
        return `
        <div class="tab-wrapper">
            <button class="tab-btn ${active ? 'active' : ''}" data-action="open-tab" data-index="${idx}"><span class="tab-dot ${showDot ? 'visible' : ''}">🔴 </span>${esc(label)}</button>
            <button class="tab-del-btn" data-action="delete-keyword" data-index="${idx}" title="키워드 삭제">×</button>
        </div>`;
    }).join('');
}

function openTab(key, page) {
    if (app.activeKey && app.activeKey !== key) markTabRead(app.activeKey);
    app.activeKey = key;
    app.page = page || 1;
    renderTabs();
    loadPosts();
}

// ==========================================
// 게시글 목록
// ==========================================
function renderPagination(withVideoToggle, page, totalPages, empty) {
    const disabledPrev = empty || page <= 1 ? 'disabled' : '';
    const disabledNext = empty || page >= totalPages ? 'disabled' : '';
    const indicator = empty ? '0 / 0' : `${page} / ${totalPages}`;
    const toggle = withVideoToggle ? `
        <div class="video-toggle-zone">
            <span class="video-toggle-label">🎬</span>
            <label class="switch">
                <input type="checkbox" class="video-only-checkbox" data-action="toggle-video-only" ${app.videoOnly[app.activeKey] ? 'checked' : ''}>
                <span class="slider round"></span>
            </label>
        </div>` : '';
    return `
        <div class="pagination-control">
            <button class="page-nav-btn" data-action="page" data-target="first" title="첫 페이지로" ${disabledPrev}>⏮️</button>
            <button class="page-nav-btn" data-action="page" data-target="prev" ${disabledPrev}>◀</button>
            <span class="page-indicator">${indicator}</span>
            <button class="page-nav-btn" data-action="page" data-target="next" ${disabledNext}>▶</button>
            <button class="page-nav-btn" data-action="page" data-target="last" title="마지막 페이지로" ${disabledNext}>⏭️</button>
            ${toggle}
        </div>`;
}

function renderContent(blocks) {
    return (blocks || []).map(block => {
        if (block === '') return '<div class="content-spacer"></div>';
        // 본문 HTML은 서버에서 저장 시 허용 목록 기반으로 정화되어 있음
        if (/^<(img|video|div|iframe)/.test(block)) return block;
        return `<p class="content-line">${block}</p>`;
    }).join('');
}

function renderComments(post) {
    if (!post.comments || post.comments.length === 0) return '';
    const items = post.comments.map(c => {
        const body = (c.content || []).map(t => t ? `<p class="comment-line">${t}</p>` : '<br>').join('');
        const replyIcon = c.is_reply ? '<span class="reply-icon">└</span>' : '';
        const isAuthor = c.author === post.author;
        const author = isAuthor
            ? `${replyIcon}<strong class="comment-author-op">${esc(c.author)} <span class="op-badge">작성자</span></strong>`
            : `${replyIcon}<strong>${esc(c.author)}</strong>`;
        return `
            <div class="comment ${c.is_reply ? 'comment-reply' : ''} ${isAuthor ? 'comment-by-op' : ''}">
                <div class="comment-meta">
                    <div>${author} <span class="comment-date">${esc(c.date)}</span></div>
                    <div class="comment-votes">👍 ${esc(c.votes)}</div>
                </div>
                <div class="comment-body">${body}</div>
            </div>`;
    }).join('');
    return `<div class="post-comments-section"><h3>💬 댓글 (${esc(post.comment_count)})</h3>${items}</div>`;
}

function safeLink(url) {
    return /^https?:\/\//i.test(url || '') ? url : '#';
}

function renderPost(post, readIds) {
    const isNew = post.is_new && !readIds.has(post.id);
    const classes = ['post-card'];
    if (isNew) classes.push('new-post');
    if (post.is_deleted) classes.push('deleted-post');
    const badges =
        (isNew ? '<span class="new-badge">NEW</span>' : '') +
        (post.is_deleted ? '<span class="deleted-badge">🗑️ 원문 삭제됨</span>' : '') +
        (post.is_syncing ? `<span class="sync-badge">${SYNC_BADGE_TEXT}</span>` : '');
    return `
        <div class="${classes.join(' ')}" id="post-${esc(post.id)}">
            <div class="post-header">
                <div class="post-title">${esc(post.title)}${badges}</div>
                <div class="post-meta">
                    <span>✍️ ${esc(post.author)}</span>
                    <span>👁️ ${esc(post.views)}</span>
                    <span>👍 ${esc(post.votes)}</span>
                    <span>🕒 ${esc(post.date)}</span>
                </div>
            </div>
            <div class="post-body">
                <div class="post-content">${renderContent(post.content)}</div>
                <div class="post-actions">
                    <a href="${esc(safeLink(post.link))}" target="_blank" rel="noopener noreferrer" class="original-link-btn">🔗 에프엠코리아 원문</a>
                </div>
                ${renderComments(post)}
            </div>
        </div>`;
}

async function loadPosts() {
    const view = document.getElementById('board-view');
    const tab = findTab(app.activeKey);
    if (!tab) {
        view.innerHTML = '<div class="post-card empty-state">등록된 키워드가 없습니다. 관리 패널에서 키워드를 추가해 주세요.</div>';
        return;
    }
    const requestedKey = app.activeKey;
    const videoOnly = !!app.videoOnly[requestedKey];
    const params = new URLSearchParams({ board: tab.board, keyword: tab.keyword, page: app.page, video_only: videoOnly ? '1' : '0' });
    let data;
    try {
        data = await getJSON('/api/posts?' + params.toString());
    } catch (e) {
        view.innerHTML = '<div class="post-card empty-state">⚠️ 게시글을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>';
        return;
    }
    if (requestedKey !== app.activeKey) return;  // 응답 도착 전에 다른 탭으로 이동한 경우
    app.page = data.page;
    storageSet(sessionStorage, 'last_active_tab', app.activeKey);
    storageSet(sessionStorage, 'last_active_page', String(app.page));

    const readIds = getReadIds();
    const empty = data.total === 0;
    let body;
    if (empty) {
        body = videoOnly
            ? '<div class="post-card empty-state">🎥 동영상이 포함된 게시글이 없습니다.</div>'
            : '<div class="post-card empty-state">수집된 게시글이 없습니다. 모니터링 중 새 글이 등록되면 수집을 시작합니다.</div>';
    } else {
        body = data.posts.map(p => renderPost(p, readIds)).join('');
    }

    view.innerHTML = `
        <div class="update-info">🔄 업데이트: ${esc(app.state.generated_at)} | ${esc(tab.board_name)} 게시판 -> [${esc(tab.keyword)}] 총 ${tab.total}개 글</div>
        ${renderPagination(true, data.page, data.total_pages, empty)}
        <div class="posts-container">${body}</div>
        ${renderPagination(false, data.page, data.total_pages, empty)}`;

    if (app.highlightPostId) {
        const target = document.getElementById('post-' + app.highlightPostId);
        app.highlightPostId = null;
        if (target) {
            setTimeout(() => {
                const top = target.getBoundingClientRect().top + window.pageYOffset - 60;
                window.scrollTo({ top: top, behavior: 'smooth' });
                target.classList.add('highlight');
                setTimeout(() => target.classList.remove('highlight'), 2500);
            }, 300);
        }
    }
}

function changePage(target) {
    const indicator = document.querySelector('#board-view .page-indicator');
    const totalPages = indicator ? parseInt(indicator.textContent.split('/')[1], 10) || 1 : 1;
    if (target === 'first') app.page = 1;
    else if (target === 'prev') app.page = Math.max(1, app.page - 1);
    else if (target === 'next') app.page = Math.min(totalPages, app.page + 1);
    else if (target === 'last') app.page = totalPages;
    loadPosts().then(() => {
        const offset = document.querySelector('.tab-container').offsetTop + 50;
        window.scrollTo({ top: offset, behavior: 'smooth' });
    });
}

// ==========================================
// 전체 상태 로드 / 새로고침 / 텔레그램 링크
// ==========================================
async function loadState() {
    app.state = await getJSON('/api/state');
    renderAdminPanel();
    if (!findTab(app.activeKey)) {
        app.activeKey = app.state.tabs.length ? tabKey(app.state.tabs[0]) : null;
        app.page = 1;
    }
    renderTabs();
    await loadPosts();
}

async function refreshCurrent() {
    if (app.activeKey) markTabRead(app.activeKey);
    await loadState();
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
    if (storageGet(localStorage, 'admin_panel_open', 'false') === 'true') setAdminPanelOpen(true);

    const savedTab = storageGet(sessionStorage, 'last_active_tab', null);
    const savedPage = parseInt(storageGet(sessionStorage, 'last_active_page', '1'), 10) || 1;
    try {
        app.state = await getJSON('/api/state');
    } catch (e) {
        document.getElementById('board-view').innerHTML = '<div class="post-card empty-state">⚠️ 서버에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.</div>';
        return;
    }
    renderAdminPanel();
    // 텔레그램 알림 링크(#post-ID)로 들어온 경우 해당 글이 있는 탭/페이지로 바로 이동
    if (await handlePostAnchor()) return;
    if (findTab(savedTab)) {
        app.activeKey = savedTab;
        app.page = savedPage;
    } else {
        app.activeKey = app.state.tabs.length ? tabKey(app.state.tabs[0]) : null;
        app.page = 1;
    }
    renderTabs();
    loadPosts();
}

// ==========================================
// 이벤트 연결 (인라인 핸들러 없이 위임 방식으로 처리하여 CSP를 엄격하게 유지)
// ==========================================
document.addEventListener('click', (e) => {
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
    } else if (action === 'toggle-admin-panel') {
        const panel = document.getElementById('admin-panel-zone');
        setAdminPanelOpen(panel.style.display !== 'flex');
    } else if (action === 'refresh') {
        refreshCurrent();
    } else if (action === 'scroll-top') {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
});

document.addEventListener('change', (e) => {
    const el = e.target;
    if (el.dataset.action === 'toggle-alert') {
        toggleBoardAlert(el);
    } else if (el.dataset.action === 'toggle-video-only') {
        app.videoOnly[app.activeKey] = el.checked;
        app.page = 1;
        loadPosts();
    }
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.id === 'new-kw-input') {
        document.querySelector('[data-action="add-keyword"]').click();
    }
});

window.addEventListener('beforeunload', () => {
    if (app.activeKey) markTabRead(app.activeKey);
});

window.addEventListener('hashchange', handlePostAnchor);

window.addEventListener('scroll', () => {
    document.getElementById('floating-top-btn').classList.toggle('visible', window.scrollY > 300);
});

document.addEventListener('DOMContentLoaded', () => {
    // 마우스 드래그로 탭 목록 가로 스크롤
    const slider = document.getElementById('tab-scroll-container');
    let isDown = false, startX = 0, scrollLeft = 0;
    slider.addEventListener('mousedown', (e) => {
        isDown = true;
        slider.classList.add('active');
        startX = e.pageX - slider.offsetLeft;
        scrollLeft = slider.scrollLeft;
    });
    ['mouseleave', 'mouseup'].forEach(ev => slider.addEventListener(ev, () => {
        isDown = false;
        slider.classList.remove('active');
    }));
    slider.addEventListener('mousemove', (e) => {
        if (!isDown) return;
        e.preventDefault();
        slider.scrollLeft = scrollLeft - (e.pageX - slider.offsetLeft - startX) * 2;
    });

    init();
});
