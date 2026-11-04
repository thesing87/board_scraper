'use strict';

// ==========================================
// 상태 및 공용 유틸
// ==========================================
const ALL_KEY = '__all__';            // 모든 게시판을 합친 통합 피드
// 보기: 고른 게시판 안에서 어떤 글을 볼지 (하나만 고름). more: 보기 탭 끝 '더보기' 목록에 넣는 보기
const FILTERS = [
    { key: 'all', label: '모든 글' },
    { key: 'unread', label: '안 읽은 글', short: '안 읽음' },   // short: 칸이 좁은 모바일 보기 탭용
    { key: 'comments', label: '새 댓글' },
    { key: 'video', label: '동영상' },
    { key: 'image', label: '이미지' },
    { key: 'saved', label: '보관함', more: true },
    { key: 'deleted', label: '삭제됨', more: true }
];
// 글 순서: 최신순(수집 순) 또는 추천+댓글이 많은 인기순(기간: 최근 하루·일주일·한 달·전체). 기기마다 기억
const SORTS = [
    { key: 'latest', label: '최신순' },
    { key: 'popular-1', label: '인기 · 하루', days: 1 },
    { key: 'popular-7', label: '인기 · 일주일', days: 7 },
    { key: 'popular-30', label: '인기 · 한 달', days: 30 },
    { key: 'popular-all', label: '인기 · 전체' }
];
const SORT_STORAGE_KEY = 'feed_sort';
// 본문·댓글 전부 접기(제목만) 상태(게시판마다 {게시판 키: 접힘})와 단축키 안내를 접어 둔 상태 (기기마다 기억)
const FOLD_STORAGE_KEY = 'posts_folded_by_view';
const LEGACY_FOLD_STORAGE_KEY = 'posts_folded';  // 예전 버전의 모든 게시판 공통 접기 상태 (정한 적 없는 게시판의 기본값)
const KEYS_STORAGE_KEY = 'shortcut_guide_closed';
const POLL_INTERVAL_MS = 60 * 1000;   // 새 글 확인 주기
const LEGACY_READ_IDS_KEY = 'read_post_ids';

const app = {
    state: null,          // /api/state 응답
    activeKey: ALL_KEY,   // 고른 게시판: ALL_KEY(전체) 또는 "group:<게시판 ID>"
    filter: 'all',        // 고른 보기: FILTERS의 key
    previewMedia: {},     // 접힌 글 썸네일의 크게 보기용 {글 ID: 사진·동영상 목록}
    openPostIds: new Set(), // 접힌 상태에서 하나씩 펼친 글 (post-ID)
    sort: 'latest',       // 글 순서: SORTS의 key (안 읽은 글·새 댓글 보기에는 쓰지 않음)
    unreadSince: null,    // 안 읽은 글 보기를 연 서버 시각 (보는 중 읽은 글이 빠져 페이지가 밀리지 않게). 없으면 다음 요청 때 서버가 정함
    renderedUnreadIds: null, // 안 읽은 글·새 댓글 보기를 그릴 때의 글 ID (새 글 배너 계산용)
    commentIds: null,     // 새 댓글 보기를 연 때의 글 ID 목록 (보는 중 확인한 글이 빠져 페이지가 밀리지 않게)
    searchQuery: '',      // 검색 중이면 검색어
    page: 1,
    totalPages: 1,
    highlightPostId: null,
    renderedTotal: null,  // 현재 화면을 그릴 때의 글 수 (새 글 배너 계산용)
    readQueue: new Set(), // 서버에 보낼 읽음 기록
    readFlushTimer: null,
    mergeDraft: [],       // 게시판 수정 중 합치려고 고른 다른 게시판 ID (저장하면 지워짐)
    loadingCount: 0       // 진행 중인 화면 요청 수 (상단 진행 막대 표시용)
};

const ICONS = {
    external: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"></path><path d="M10 14L20 4"></path><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"></path></svg>',
    prev: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"></path></svg>',
    next: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"></path></svg>',
    close: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>',
    down: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12l7 7 7-7"></path></svg>',
    up: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"></path></svg>',
    share: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="2.5"></circle><circle cx="6" cy="12" r="2.5"></circle><circle cx="18" cy="19" r="2.5"></circle><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"></path></svg>',
    star: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"></path></svg>',
    pause: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"></rect><rect x="14" y="5" width="4" height="14" rx="1"></rect></svg>',
    play: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5l12 7-12 7z"></path></svg>',
    eye: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
    thumb: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3z"></path><path d="M7 11l4-8a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.3 20H7"></path></svg>',
    comment: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"></path></svg>',
    chevronDown: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>'
};

function esc(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// 수집 사이트 (sites.py와 같은 값). 카테고리 키 'dc:갤러리id', 글 ID 'dc-갤러리id-글번호'가 디시인사이드
// 이름·짧은 표시는 기본값이고, 관리 화면에서 바꾼 값(서버 상태의 sites)으로 덮어씀
const SITES = {
    fmkorea: { name: '에펨코리아', short: 'FM' },
    dcinside: { name: '디시인사이드', short: 'DC' }
};
function setState(state) {
    app.state = state;
    Object.entries(state.sites || {}).forEach(([site, label]) => {
        if (SITES[site]) Object.assign(SITES[site], label);
    });
}
function siteLabel(site) { return SITES[site] || SITES.fmkorea; }
function siteTag(site) {
    const info = SITES[site] || SITES.fmkorea;
    return `<span class="site-tag site-${site in SITES ? site : 'fmkorea'}" title="${info.name}">${info.short}</span>`;
}
function boardSite(board) { return String(board).startsWith('dc:') ? 'dcinside' : 'fmkorea'; }
// 여러 사이트의 키워드를 함께 담은 게시판 (sites.py MULTI_SITE). 사이드바·칩에서는 사이트 묶음 앞에 따로 둠
const MULTI_SITE = 'multi';
function isMultiGroup(group) { return group.site === MULTI_SITE; }
function groupShort(group) {
    return isMultiGroup(group) ? Object.values(SITES).map(s => s.short).join('·') : siteLabel(group.site).short;
}
// 게시판 이름 앞 사이트 표시 (여러 사이트 게시판은 FM·DC)
function groupTag(group) {
    return isMultiGroup(group)
        ? `<span class="site-tag site-multi" title="여러 사이트">${esc(groupShort(group))}</span>`
        : siteTag(group.site);
}
// 게시판을 사이트별로 나눔: [[site, [group, ...]], ...] (게시판이 있는 사이트만, 여러 사이트 게시판 제외. 사이트 표시를 붙일지 판단용)
function groupsBySite(groups) {
    return Object.keys(SITES)
        .map(site => [site, groups.filter(g => (g.site || 'fmkorea') === site)])
        .filter(([, list]) => list.length);
}
// 게시판이 두 사이트 이상에 걸쳐 있는지 (사이트 표시를 붙일지)
function multiSite() {
    const groups = app.state ? app.state.groups || [] : [];
    return groupsBySite(groups).length > 1 || groups.some(isMultiGroup);
}
// 원문 주소: 대시보드에서 찾지 못한 글(텔레그램 링크)은 사이트의 원문으로
function originalUrl(postId) {
    const dc = /^dc-([a-z0-9_]+)-(\d+)$/.exec(postId);
    return dc ? `https://gall.dcinside.com/board/view/?id=${dc[1]}&no=${dc[2]}` : 'https://www.fmkorea.com/' + postId;
}

function groupKey(group) { return 'group:' + group.id; }
function memberKey(m) { return m.board + '::' + m.keyword; }
function boardName(key) {
    const board = app.state ? app.state.boards.find(b => b.key === key) : null;
    return board ? board.name : key;
}
function findGroup(key) { return app.state ? (app.state.groups || []).find(g => groupKey(g) === key) : null; }
function isAllView() { return app.activeKey === ALL_KEY; }
// 묶음 (사이드바 묶음 제목: 묶음 안 모든 게시판을 합친 피드): 'folder:<묶음 ID>'
function folderKey(folder) { return 'folder:' + folder.id; }
function findFolder(key) { return app.state ? (app.state.folders || []).find(f => folderKey(f) === key) : null; }
function isKnownView(key) { return key === ALL_KEY || !!findGroup(key) || !!findFolder(key); }
function isKnownFilter(key) { return FILTERS.some(f => f.key === key); }
function filterLabel(key) { return FILTERS.find(f => f.key === key).label; }

// 게시판을 열 때의 기본 보기: 안 읽은 글이 있으면 안 읽은 글, 없고 새 댓글이 있으면 새 댓글, 둘 다 없으면 모든 글
function defaultFilter(key) {
    const summary = viewSummary(key);
    if (!summary) return 'all';
    if (summary.unread_count > 0) return 'unread';
    if (summary.comment_count > 0) return 'comments';
    return 'all';
}

// 고른 게시판(통합 피드·게시판·묶음)의 요약: 보기별 글 수, 안 읽은 새 글·새 댓글 글 ID
// (ID는 최신 일부만 오므로 개수는 *_count로 셈)
function viewSummary(key) {
    if (!app.state) return null;
    return key === ALL_KEY ? app.state.all : findGroup(key) || findFolder(key);
}

function filterCount(summary, filter) {
    if (filter === 'unread') return summary.unread_count;
    if (filter === 'comments') return summary.comment_count;
    if (filter === 'video') return summary.video_count;
    if (filter === 'image') return summary.image_count;
    if (filter === 'deleted') return summary.deleted_count;
    if (filter === 'saved') return summary.saved_count;
    return summary.total;
}

// '모두 읽음'·새 글 배너가 다루는 글: 새 댓글 보기는 새 댓글이 달린 글, 나머지는 안 읽은 새 글.
// 삭제됨·보관함 보기는 보이는 글과 상관없는 글을 읽음 처리하게 되므로 '모두 읽음'을 숨김
function pendingIds(summary) { return app.filter === 'comments' ? summary.comment_ids : summary.unread_ids; }
function pendingCount(summary) {
    if (app.filter === 'deleted' || app.filter === 'saved') return 0;
    return app.filter === 'comments' ? summary.comment_count : summary.unread_count;
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
    // 관리자 암호가 틀리면 관리 화면에 암호 칸을 다시 보여 줌
    // 기억한 로그인 키가 더는 맞지 않으면(서버 암호를 바꿈) 로그아웃하고 다시 로그인하게 함
    if (res.status === 401 && 'password' in body) {
        needPassword('로그인이 풀렸습니다. 관리자 암호를 다시 입력해 주세요.');
        return { success: false, message: '', relogin: true };
    }
    return res.json();
}

// 화면을 그리는 요청(첫 접속·게시판 이동·페이지 넘김·새로고침) 동안 상단에 진행 막대를 표시
async function withProgress(promise) {
    app.loadingCount++;
    document.getElementById('top-progress').hidden = false;
    try {
        return await promise;
    } finally {
        app.loadingCount = Math.max(0, app.loadingCount - 1);
        if (app.loadingCount === 0) document.getElementById('top-progress').hidden = true;
    }
}

// ==========================================
// 읽음 기록 (서버에 저장하여 PC·휴대폰 간 공유)
// ==========================================
function forgetUnread(ids) {
    // 서버 응답을 기다리지 않고 화면의 안 읽은 수부터 줄임
    if (!app.state) return;
    const set = new Set(ids);
    // 안 읽은 새 글 수와 새 댓글이 달린 글 수를 함께 줄임 (읽으면 그 글의 새 댓글도 확인한 것)
    [...(app.state.groups || []), app.state.all, ...(app.state.folders || [])].forEach(summary => {
        [['unread_ids', 'unread_count'], ['comment_ids', 'comment_count']].forEach(([idsField, countField]) => {
            if (!summary[idsField]) return;
            const before = summary[idsField].length;
            summary[idsField] = summary[idsField].filter(id => !set.has(id));
            summary[countField] = Math.max(0, summary[countField] - (before - summary[idsField].length));
        });
    });
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
        const top = el.getBoundingClientRect().top;
        // 텔레그램 링크로 건너뛴 위쪽 글(data-skipped)은 지나친 것만으로는 읽음이 아니므로, 글 끝이 실제로 화면에 보일 때만
        let seen = el.dataset.skipped ? top >= 0 && top < window.innerHeight : top < window.innerHeight;
        // 새 댓글이 달린 글은 글 끝까지 내려가지 않아도 마지막 새 댓글이 화면에 다 보이면 확인한 것으로 봄
        // (이미 읽은 글에만 새 댓글이 붙으므로, 읽음 처리는 새 댓글 표시를 지우는 것뿐)
        const newComments = seen ? [] : el.closest('.post-card').querySelectorAll('.comment.is-new-comment');
        if (newComments.length) {
            // 넓은 화면에서는 댓글 칸이 따로 스크롤되므로, 그 칸에서 실제로 보이는 범위 안에 들어와야 본 것
            const box = newComments[0].closest('.comments').getBoundingClientRect();
            const bottom = newComments[newComments.length - 1].getBoundingClientRect().bottom;
            seen = bottom <= Math.min(window.innerHeight, box.bottom + 1) && (!el.dataset.skipped || bottom > Math.max(0, box.top));
        }
        if (seen) {
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

function navItem(label, count, unread, active, attrs, comments = 0) {
    return `
        <button class="kw-item ${active ? 'active' : ''}" ${attrs} ${active ? 'aria-current="true"' : ''}>
            <span>${label}</span>
            <span class="kw-side">
                ${unread ? `<span class="kw-unread" aria-label="안 읽은 새 글 ${unread}개">${unread}</span>` : ''}
                ${comments ? `<span class="kw-unread kw-comments" aria-label="새 댓글이 달린 글 ${comments}개">${comments}</span>` : ''}
                <span class="kw-count">${count}</span>
            </span>
        </button>`;
}

// 사이드바 보기 항목: 고른 항목은 왼쪽 체크 표시와 굵은 글씨로만 표시 (게시판의 파란 배경 선택과 구분)
// 보기 칸의 글 수 배지: 확인할 글이 남은 안 읽은 글(파랑)·새 댓글(주황)만 색을 넣어 눈에 띄게, 나머지는 회색
function countBadge(filter, count) {
    const tone = count > 0 && (filter === 'unread' || filter === 'comments') ? ` is-${filter}` : '';
    return `<span class="count-badge${tone}">${count}</span>`;
}

const ADD_BOARD_BUTTON = `
    <button class="icon-btn small admin-only" data-action="new-group" aria-label="게시판 만들기" title="게시판 만들기">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
    </button>`;

function renderNavigation() {
    if (!app.state) return;
    const searching = !!app.searchQuery;
    const groups = app.state.groups || [];
    const current = viewSummary(app.activeKey);
    const allActive = !searching && isAllView();
    const isActive = g => !searching && groupKey(g) === app.activeKey;
    const filterActive = key => !searching && app.filter === key;
    const filterAttrs = key => `data-action="set-view" data-filter="${key}"`;

    // 데스크톱 사이드바: 어디를 볼지 고르는 게시판(전체 + 사용자가 만든 게시판, 안 읽은 새 글 수·새 댓글이 달린 글 수).
    // 고른 게시판 안을 걸러 보는 보기는 상단 바 가운데 보기 탭(view-bar-tabs)
    // 게시판은 사용자가 만든 묶음별로 색 상자에 담아 보여 줌 (묶음 없는 게시판은 '전체' 바로 아래). '전체'는 모든 게시판을 합친 피드
    const folders = app.state.folders || [];
    const looseGroups = groups.filter(g => !folders.some(f => f.id === g.folder_id));
    const folderGroups = f => groups.filter(g => g.folder_id === f.id);
    const shownFolders = folders.filter(f => folderGroups(f).length);
    const groupLabel = g => (multiSite() ? groupTag(g) : '') + esc(g.name);
    const groupItem = g => navItem(groupLabel(g), '', g.unread_count, isActive(g),
        `data-action="open-group" data-group-id="${g.id}"`, g.comment_count);
    // 접힌 묶음은 지금 보고 있는 게시판만 남겨 어디를 보고 있는지 보이게 함
    const visibleGroups = (list, expanded) => expanded ? list : list.filter(isActive);
    const groupList = !groups.length
        ? '<span class="kw-group-name">게시판이 없습니다. 관리에서 만들어 주세요.</span>'
        : looseGroups.map(groupItem).join('') + shownFolders.map(f => {
            // 제목 줄(누르면 묶음 안 모든 게시판의 글) 옆에 묶음의 안 읽은 새 글 수 (게시판끼리 겹치는 글은 한 번만),
            // 오른쪽 끝 화살표 칸은 접기·펼치기
            const expanded = isFolderExpanded('desktop', f.id);
            const active = !searching && app.activeKey === folderKey(f);
            return `
                <div class="site-box site-box-folder">
                    <div class="site-head ${active ? 'active' : ''}">
                        <button class="site-open" data-action="open-folder" data-folder-id="${f.id}" ${active ? 'aria-current="true"' : ''}>
                            <span class="site-head-name">${esc(f.name)}</span>
                            ${f.unread_count ? `<span class="kw-unread" aria-label="안 읽은 새 글 ${f.unread_count}개">${f.unread_count}</span>` : ''}
                        </button>
                        <button class="site-toggle" data-action="toggle-folder" data-scope="desktop" data-folder-id="${f.id}"
                                aria-expanded="${expanded}" aria-label="${esc(f.name)} 묶음 ${expanded ? '접기' : '펼치기'}">
                            ${expanded ? ICONS.chevronDown : ICONS.next}</button>
                    </div>
                    ${visibleGroups(folderGroups(f), expanded).map(groupItem).join('')}
                </div>`;
        }).join('');
    document.getElementById('keyword-groups').innerHTML = `
        <nav class="kw-group" aria-label="게시판">
            <div class="sidebar-head"><span>게시판</span>${ADD_BOARD_BUTTON}</div>
            ${navItem('전체', '', app.state.all.unread_count, allActive, 'data-action="open-all"', app.state.all.comment_count)}
            ${groupList}
        </nav>`;

    // 보기 탭: 데스크톱은 상단 바 가운데, 모바일은 상단 메뉴 아래 한 줄. 자주 쓰는 보기는 탭으로, 보관함·삭제됨은 끝의 '더보기' 목록으로.
    // 글 수는 확인할 글이 남은 안 읽은 글·새 댓글 탭에만 (나머지 보기의 글 수는 '더보기' 목록과 피드 제목 아래 요약에)
    const tabBadge = f => ['unread', 'comments'].includes(f.key) && filterCount(current, f.key) > 0
        ? countBadge(f.key, filterCount(current, f.key)) : '';
    const viewTabs = (cls, mobile) => {
        const more = FILTERS.filter(f => f.more);
        const picked = more.find(f => filterActive(f.key));
        return FILTERS.filter(f => !f.more).map(f => `
            <button class="${cls}" ${filterAttrs(f.key)} aria-pressed="${filterActive(f.key)}">
                <span>${mobile ? f.short || f.label : f.label}</span>${tabBadge(f)}
            </button>`).join('') + `
            <span class="view-more">
                <button class="${cls} view-more-btn" data-action="toggle-view-more" aria-haspopup="true" aria-expanded="false" aria-pressed="${!!picked}">
                    <span>${picked ? picked.label : '더보기'}${ICONS.chevronDown}</span>
                </button>
                <span class="view-more-list" hidden>${more.map(f => `
                    <button class="view-more-option" ${filterAttrs(f.key)} aria-pressed="${filterActive(f.key)}">
                        <span>${f.label}</span>${countBadge(f.key, filterCount(current, f.key))}
                    </button>`).join('')}
                </span>
            </span>`;
    };
    document.getElementById('view-bar-tabs').innerHTML = viewTabs('view-bar-tab', false);

    // 모바일: 위는 한 줄 보기 칸, 아래는 가로로 넘기는 게시판 칩 (맨 앞이 전체, 안 읽은 새 글은 파란 점·새 댓글은 주황 점)
    document.getElementById('view-tabs').innerHTML = viewTabs('view-tab', true);
    const chip = (label, summary, active, attrs) => `
        <button class="chip ${active ? 'active' : ''}" ${attrs} ${active ? 'aria-current="true"' : ''}>
            <span>${label}</span>
            ${summary.unread_count > 0 ? '<span class="chip-dot" aria-label="안 읽은 새 글"></span>' : ''}
            ${summary.comment_count > 0 ? '<span class="chip-dot chip-dot-comments" aria-label="새 댓글"></span>' : ''}
        </button>`;
    const groupChip = g => chip(groupLabel(g), g, isActive(g), `data-action="open-group" data-group-id="${g.id}"`);
    // 묶음마다 맨 앞에 묶음 칩을 둠: 이름 부분은 묶음 안 모든 게시판의 글을 열고,
    // 오른쪽 화살표 칸은 그 묶음의 게시판 칩을 펼치거나(▴) 접음(▾).
    // 펼치면 묶음 칩과 안의 게시판 칩을 파란 테두리 상자 하나로 감싸 어디까지가 그 묶음인지 보이게 하고,
    // 접으면 지금 보는 게시판 칩만 남기고 숨은 게시판 수(+N)를 묶음 칩에 표시
    const folderChip = (f, expanded, hidden) => {
        const active = !searching && app.activeKey === folderKey(f);
        return `
        <span class="site-chip site-chip-folder ${active ? 'active' : ''}">
            <button class="site-chip-open" data-action="open-folder" data-folder-id="${f.id}" ${active ? 'aria-current="true"' : ''}>
                <span>${esc(f.name)}</span>
                ${f.unread_count ? `<span class="site-chip-count" aria-label="안 읽은 새 글 ${f.unread_count}개">${f.unread_count}</span>` : ''}
                ${hidden ? `<span class="site-chip-hidden" aria-label="숨은 게시판 ${hidden}개">+${hidden}</span>` : ''}
            </button>
            <button class="site-chip-toggle" data-action="toggle-folder" data-scope="mobile" data-folder-id="${f.id}"
                    aria-expanded="${expanded}" aria-label="${esc(f.name)} 묶음 ${expanded ? '접기' : '펼치기'}">
                ${ICONS.chevronDown}</button>
        </span>`;
    };
    const folderChips = f => {
        const expanded = isFolderExpanded('mobile', f.id);
        const inside = folderGroups(f);
        const shown = visibleGroups(inside, expanded);
        const chips = folderChip(f, expanded, inside.length - shown.length) + shown.map(groupChip).join('');
        return expanded ? `<span class="chip-folder-box">${chips}</span>` : chips;
    };
    document.getElementById('chip-row').innerHTML =
        chip('전체', app.state.all, allActive, 'data-action="open-all"') +
        looseGroups.map(groupChip).join('') +
        shownFolders.map(folderChips).join('');
}

// 묶음 상자(데스크톱)·묶음 칩(모바일)의 펼침 상태. 기기마다 따로 기억 (데스크톱은 기본 펼침, 모바일은 기본 접힘)
// 데스크톱 목록은 접은 묶음 ID, 모바일 목록은 펼친 묶음 ID
const FOLDER_EXPAND_KEYS = { desktop: 'collapsed_folders_desktop', mobile: 'expanded_folders_mobile' };
function folderExpandList(scope) {
    try { return JSON.parse(storageGet(localStorage, FOLDER_EXPAND_KEYS[scope], '[]')) || []; } catch (e) { return []; }
}
function isFolderExpanded(scope, folderId) {
    const listed = folderExpandList(scope).includes(folderId);
    return scope === 'desktop' ? !listed : listed;
}
function toggleFolderExpanded(scope, folderId) {
    const expanded = isFolderExpanded(scope, folderId);
    const list = folderExpandList(scope).filter(id => id !== folderId);
    if (scope === 'desktop' ? expanded : !expanded) list.push(folderId);
    storageSet(localStorage, FOLDER_EXPAND_KEYS[scope], JSON.stringify(list));
    renderNavigation();
}

function scrollActiveChipIntoView() {
    const activeChip = document.querySelector('#chip-row .chip.active');
    if (activeChip) activeChip.scrollIntoView({ block: 'nearest', inline: 'center' });
}

// 게시판을 바꾸거나 보기를 바꾸면 안 읽은 글·새 댓글 목록을 그 시점 기준으로 새로 잡음
// (안 읽은 글 기준 시각은 다음 글 목록 요청 때 서버의 지금 시각으로. 마지막 상태 조회 시각을 쓰면 그 뒤에 읽은 글이 다시 섞임)
function resetViewSnapshot() {
    app.unreadSince = null;
    app.commentIds = null;
}

// 게시판·보기 화면 열기 (app.filter는 호출하는 쪽에서 정함)
function openView(key, page) {
    app.activeKey = key;
    resetViewSnapshot();
    app.searchQuery = '';
    document.getElementById('search-input').value = '';
    app.page = page || 1;
    renderNavigation();
    scrollActiveChipIntoView();
    loadPosts().then(jumped => { if (!jumped) window.scrollTo({ top: 0 }); });
}

// 보기 바꾸기 (고른 게시판은 유지)
function setFilter(filter) {
    app.filter = filter;
    app.galleryReturn = null;
    openView(app.activeKey, 1);
}

// 게시판 바꾸기: 그 게시판의 기본 보기(안 읽은 글 → 새 댓글 → 모든 글)로 엶
function openBoard(key) {
    app.filter = defaultFilter(key);
    app.galleryReturn = null;
    openView(key, 1);
}

// 홈: 검색·관리 패널·텔레그램 링크(#post-ID)를 정리하고 전체 게시판 첫 화면으로
function goHome() {
    if (!document.getElementById('settings').hidden) setSettingsOpen(false);
    document.querySelector('.topbar').classList.remove('search-open');
    if (window.location.hash) history.replaceState(null, '', window.location.pathname);
    openBoard(ALL_KEY);
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

// 답글 깊이 (0: 일반 댓글). 깊이를 저장하기 전에 수집된 답글은 1단으로 봄
const MAX_REPLY_DEPTH = 4;
function replyDepth(comment) {
    if (!comment.is_reply) return 0;
    return Math.min(Math.max(parseInt(comment.depth, 10) || 1, 1), MAX_REPLY_DEPTH);
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
        const depth = replyDepth(c);
        if (c.is_reply) classes.push('reply');
        if (isNew) classes.push('is-new-comment');
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

// 조회·추천·댓글 칩: 많을수록 색을 4단계로 진하게 (기본 회색 → is-some 연하게 → is-warm 중간 → is-hot 진하게).
// 조회 100·500·1000회, 추천·댓글 1·10·20개 이상부터. 추천 0도 표시
const STAT_LEVELS = { views: [100, 500, 1000], votes: [1, 10, 20], comments: [1, 10, 20] };
function statNumber(value) {
    return parseInt(String(value || '0').replace(/[^\d]/g, ''), 10) || 0;
}
function statLevel(n, [some, warm, hot]) {
    return n >= hot ? ' is-hot' : n >= warm ? ' is-warm' : n >= some ? ' is-some' : '';
}
function renderPostStats(post) {
    const views = statNumber(post.views);
    const votes = statNumber(post.votes);
    const comments = statNumber(post.comment_count);
    return `<div class="post-stats">
        <span class="stat stat-views${statLevel(views, STAT_LEVELS.views)}" title="조회">${ICONS.eye}<span class="sr-only">조회</span>${views.toLocaleString('ko-KR')}</span>
        <span class="stat stat-votes${statLevel(votes, STAT_LEVELS.votes)}" title="추천">${ICONS.thumb}<span class="sr-only">추천</span>${votes.toLocaleString('ko-KR')}</span>
        <span class="stat stat-comments${statLevel(comments, STAT_LEVELS.comments)}" title="댓글">${ICONS.comment}<span class="sr-only">댓글</span>${comments.toLocaleString('ko-KR')}</span>
    </div>`;
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
    const keywordTags = (post.keywords && (isAllView() || findFolder(app.activeKey) || app.searchQuery || (group && group.members.length > 1)))
        ? post.keywords.map(k => `<span class="kw-chip">${multiSite() ? siteTag(boardSite(k.board)) : ''}${esc(k.board_name)} · ${esc(k.keyword)}</span>`).join('')
        : '';
    const link = esc(safeLink(post.link));
    const star = `<button class="star-btn" data-action="toggle-saved" data-post-id="${esc(post.id)}" aria-pressed="${!!post.is_saved}"
        aria-label="${post.is_saved ? '보관함에서 빼기' : '보관함에 담기'}" title="${post.is_saved ? '보관함에서 빼기' : '보관함에 담기 (오래된 글 정리에서 빠짐)'}">${ICONS.star}</button>`;
    const share = `<span class="share-wrap">
        <button class="star-btn share-btn" data-action="share-post" data-post-id="${esc(post.id)}" aria-haspopup="true" aria-expanded="false"
            aria-label="공유" title="공유">${ICONS.share}</button>
    </span>`;
    return `
        <article class="${classes.join(' ')}" id="post-${esc(post.id)}">
            <div class="post-head">
                ${badges || keywordTags ? `<div class="badges">${badges}${keywordTags}</div>` : ''}
                <div class="title-row">
                    <h2 class="post-title">${highlightTerms(post.title)}</h2>
                    <div class="title-actions">
                        ${star}
                        ${share}
                        <a class="btn-original top" href="${link}" target="_blank" rel="noopener noreferrer">원문 ${ICONS.external}</a>
                    </div>
                </div>
                <div class="post-meta">
                    <span class="author">${esc(post.author)}</span>
                    <span>${esc(post.date)}</span>
                </div>
                ${renderPostStats(post)}
                ${renderFoldPreview(post)}
            </div>
            <div class="post-content">${renderContent(post.content)}</div>
            ${renderComments(post)}
            <a class="btn-original bottom" href="${link}" target="_blank" rel="noopener noreferrer">원문 보기 ${ICONS.external}</a>
            <div class="read-sentinel" data-post-id="${esc(post.id)}" aria-hidden="true"></div>
        </article>`;
}

// ==========================================
// 동영상·이미지 모아보기: 글·댓글 없이 미디어만 격자로. 칸을 누르면 크게 보기, '글 보기'로 원래 글로 이동
// (읽음 처리는 하지 않음: 글을 실제로 열어 볼 때만)
// 페이지는 글이 아니라 미디어 개수로 나눠(서버) 항상 같은 칸 수. 데스크톱은 스크롤 없이 한 화면에 4×3, 모바일은 이미지 2×6·동영상 1×12
// ==========================================
const GALLERY_PER_PAGE = { image: 12, video: 12 };

function isGalleryView() {
    return !app.searchQuery && (app.filter === 'video' || app.filter === 'image');
}

// ==========================================
// 접힌 글 미리보기: 본문 첫 부분 한 줄과 첨부 사진·동영상 썸네일 (4개보다 많으면 3개와 +N, 누르면 전부)
// 사진·동영상 고르는 기준은 모아보기(서버 storage.post_images·post_videos)와 같음
// ==========================================
const PREVIEW_THUMBS = 3;
const MEDIA_IMAGE_SRC = /^(https?:\/\/[^/]+(\/[^?#]*)?\/files\/attach\/|\/images\/[a-z0-9_-]+\/)/i;
const YOUTUBE_EMBED = /youtube(?:-nocookie)?\.com\/embed\/([\w-]{6,})/;

function postMedia(post) {
    const videos = (post.videos || []).filter(src => /^https?:\/\//i.test(src)).map(src => {
        const yt = YOUTUBE_EMBED.exec(src);
        if (yt) return { type: 'youtube', src, thumb: `https://i.ytimg.com/vi/${yt[1]}/hqdefault.jpg` };
        return { type: /\.(mp4|webm|mov)([?#]|$)/i.test(src) ? 'file' : 'embed', src };
    });
    const doc = new DOMParser().parseFromString((post.content || []).join(''), 'text/html');
    const images = [...new Set([...doc.querySelectorAll('img')].map(img => {
        const src = img.getAttribute('src') || '';
        return src.startsWith('//') ? 'https:' + src : src;
    }).filter(src => MEDIA_IMAGE_SRC.test(src)))].map(src => ({ type: 'image', src }));
    const media = videos.concat(images);
    return media.map((m, i) => ({ ...m, index: i + 1, of: media.length,
        post: { id: post.id, title: post.title, link: post.link, keywords: post.keywords } }));
}

// 본문의 글자만 이어 붙인 첫 부분 (사진·동영상·링크 미리보기 상자는 뺌)
function postExcerpt(post) {
    const text = (post.content || []).filter(b => b && !/^<(img|video|div|iframe)/.test(b)).join(' ');
    const plain = new DOMParser().parseFromString(text, 'text/html').body.textContent || '';
    return plain.replace(/\s+/g, ' ').trim().slice(0, 200);
}

function renderFoldPreview(post) {
    const excerpt = postExcerpt(post);
    const media = postMedia(post);
    app.previewMedia[post.id] = media;
    const many = media.length > PREVIEW_THUMBS + 1;
    const thumbs = media.map((m, i) => {
        const inner = m.type === 'image' ? `<img src="${esc(m.src)}" alt="" loading="lazy">`
            : m.type === 'youtube' ? `<img src="${esc(m.thumb)}" alt="" loading="lazy">`
            : m.type === 'file' ? `<video src="${esc(m.src)}#t=0.5" preload="metadata" muted playsinline tabindex="-1"></video>` : '';
        const play = m.type !== 'image' ? `<span class="ft-play" aria-hidden="true">${ICONS.play}</span>` : '';
        return `<button class="fold-thumb${many && i >= PREVIEW_THUMBS ? ' is-extra' : ''}${m.type !== 'image' ? ' is-video' : ''}"
            data-action="open-post-media" data-post-id="${esc(post.id)}" data-index="${i}" aria-label="${m.type === 'image' ? '사진' : '동영상'} ${i + 1} 크게 보기">${inner}${play}</button>`;
    }).join('');
    const more = many ? `<button class="fold-thumb fold-more" data-action="more-thumbs" data-more="${media.length - PREVIEW_THUMBS}"
        aria-expanded="false">+${media.length - PREVIEW_THUMBS}</button>` : '';
    if (!excerpt && !media.length) return '';
    return `<div class="fold-preview">
        ${excerpt ? `<p class="fold-excerpt">${esc(excerpt)}</p>` : ''}
        ${media.length ? `<div class="fold-thumbs">${thumbs}${more}</div>` : ''}
    </div>`;
}

// +N: 그 글의 나머지 썸네일을 펼치거나 다시 3개로
function toggleMoreThumbs(btn) {
    const box = btn.closest('.fold-thumbs');
    const open = box.classList.toggle('show-all');
    btn.textContent = open ? '접기' : '+' + btn.dataset.more;
    btn.setAttribute('aria-expanded', String(open));
}

// 접힌 글의 썸네일을 누르면 그 글의 사진·동영상만 모아 크게 보기
function openPostMedia(postId, index) {
    const media = app.previewMedia[postId];
    if (!media || !media.length) return;
    app.galleryItems = media;
    openMedia(index);
}

function mediaSource(post) {
    const k = (post.keywords || [])[0];
    return k ? `${multiSite() ? siteLabel(boardSite(k.board)).short + ' ' : ''}${k.board_name} · ${k.keyword}` : post.title;
}

function renderGallery(items, kind) {
    app.galleryItems = items;
    const cells = items.map((it, i) => {
        const thumb = it.type === 'image' ? `<img src="${esc(it.src)}" alt="" loading="lazy">`
            : it.type === 'youtube' ? `<img src="${esc(it.thumb)}" alt="" loading="lazy">`
            : it.type === 'file' ? `<video src="${esc(it.src)}#t=0.5" preload="metadata" muted playsinline tabindex="-1"></video>`
            : '';
        const count = it.of > 1 ? `<span class="g-count">${it.index}/${it.of}</span>` : '';
        const play = it.type !== 'image' ? `<span class="g-play" aria-hidden="true">${ICONS.play}</span>` : '';
        return `
            <figure class="g-cell${it.type !== 'image' ? ' is-video' : ''}">
                <button class="g-open" data-action="open-media" data-index="${i}" aria-label="${esc(it.post.title)} 크게 보기">${thumb}${play}</button>
                ${count}
                <figcaption class="g-cap">
                    <span class="g-text" title="${esc(it.post.title)}">
                        <span class="g-title">${esc(it.post.title)}</span>
                        <span class="g-src">${esc(mediaSource(it.post))}</span>
                    </span>
                    <button class="g-go" data-action="goto-post" data-post-id="${esc(it.post.id)}">글 보기</button>
                </figcaption>
            </figure>`;
    }).join('');
    // 마지막 페이지에서 모자란 칸은 빈 칸으로 채워 칸 크기와 버튼 자리를 그대로
    const blanks = '<div class="g-cell is-blank" aria-hidden="true"></div>'.repeat(Math.max(0, GALLERY_PER_PAGE[kind] - items.length));
    return `<div class="gallery${kind === 'video' ? ' is-video' : ''}">${cells}${blanks}</div>`;
}

function mediaViewer() {
    let el = document.getElementById('media-viewer');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'media-viewer';
    el.className = 'media-viewer';
    el.hidden = true;
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.innerHTML = `
        <div class="mv-head">
            <span class="mv-title"></span>
            <div class="mv-actions">
                <button class="mv-btn" data-action="goto-post">이 글로 이동 ${ICONS.next}</button>
                <button class="mv-btn mv-icon" data-action="close-media" aria-label="닫기">${ICONS.close}</button>
            </div>
        </div>
        <div class="mv-body">
            <button class="mv-nav" data-action="media-step" data-step="-1" aria-label="이전">${ICONS.prev}</button>
            <div class="mv-stage"></div>
            <button class="mv-nav" data-action="media-step" data-step="1" aria-label="다음">${ICONS.next}</button>
        </div>
        <div class="mv-foot"></div>`;
    document.body.appendChild(el);
    return el;
}

function openMedia(index) {
    const items = app.galleryItems || [];
    if (!items.length) return;
    app.mediaIndex = (index + items.length) % items.length;
    const it = items[app.mediaIndex];
    const el = mediaViewer();
    el.querySelector('.mv-title').textContent = it.post.title;
    el.querySelector('[data-action="goto-post"]').dataset.postId = it.post.id;
    el.querySelector('.mv-stage').innerHTML =
        it.type === 'image' ? `<img src="${esc(it.src)}" alt="">`
        : it.type === 'file' ? `<video src="${esc(it.src)}" controls autoplay playsinline></video>`
        : `<iframe src="${esc(it.src)}" referrerpolicy="strict-origin-when-cross-origin" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
    el.querySelector('.mv-foot').innerHTML = `${app.mediaIndex + 1} / ${items.length} · ${esc(mediaSource(it.post))}`
        + (it.type === 'embed' ? ` · <a href="${esc(safeLink(it.post.link))}" target="_blank" rel="noopener noreferrer">재생이 안 되면 원문에서 보기</a>` : '');
    el.querySelectorAll('.mv-nav').forEach(b => { b.hidden = items.length < 2; });
    if (el.hidden) {
        el.hidden = false;
        document.body.classList.add('viewer-open');
        updateShortcutGuide();
    }
}

function closeMedia() {
    const el = document.getElementById('media-viewer');
    if (!el || el.hidden) return;
    el.querySelector('.mv-stage').innerHTML = '';  // 재생 중인 동영상 멈춤
    el.hidden = true;
    document.body.classList.remove('viewer-open');
    updateShortcutGuide();
}

// 모아보기에서 고른 글을 그 글이 있는 게시판·페이지에서 열고, 돌아올 모아보기 화면을 기억
function gotoPostFromGallery(postId) {
    closeMedia();
    const card = document.getElementById('post-' + postId);
    if (!isGalleryView() && card) {
        app.openPostIds.add(card.id);
        applyFold();
        window.scrollTo({ top: card.getBoundingClientRect().top + window.pageYOffset - stickyHeight() - 12 });
        scheduleReadCheck();
        return;
    }
    app.galleryReturn = { key: app.activeKey, filter: app.filter, page: app.page, sort: app.sort, scrollY: window.scrollY };
    window.location.hash = 'post-' + postId;
}

function returnToGallery() {
    const back = app.galleryReturn;
    if (!back) return;
    app.galleryReturn = null;
    if (window.location.hash) history.replaceState(null, '', window.location.pathname);
    app.filter = back.filter;
    app.sort = back.sort;
    app.activeKey = back.key;
    resetViewSnapshot();
    app.page = back.page;
    renderNavigation();
    loadPosts().then(() => window.scrollTo({ top: back.scrollY }));
}

// ==========================================
// 본문·댓글 전부 접기/펼치기 (G 키): 접으면 글마다 제목 줄만. 접힌 글은 제목 줄을 눌러 그 글만 펼침
// (접힌 글도 끝(제목 줄 아래)이 화면에 들어오면 펼친 글과 같이 읽음 처리)
// ==========================================
function foldLabel() {
    return app.folded ? `${ICONS.chevronDown} 전부 펼치기` : `${ICONS.up} 전부 접기`;
}

// 접기 상태는 게시판(전체·게시판·묶음)마다, 검색 결과는 따로 하나
function foldKey() {
    return app.searchQuery ? 'search' : app.activeKey;
}
function foldMap() {
    try {
        const map = JSON.parse(storageGet(localStorage, FOLD_STORAGE_KEY, '{}'));
        return map && typeof map === 'object' && !Array.isArray(map) ? map : {};
    } catch (e) {
        return {};
    }
}
function foldedFor(key) {
    const map = foldMap();
    return key in map ? !!map[key] : storageGet(localStorage, LEGACY_FOLD_STORAGE_KEY, '0') === '1';
}

function applyFold() {
    const feed = document.getElementById('feed');
    feed.classList.toggle('is-folded', !!app.folded && !isGalleryView());
    feed.querySelectorAll('.post-card').forEach(card => {
        card.classList.toggle('is-open', app.openPostIds.has(card.id));
    });
    const btn = feed.querySelector('[data-action="toggle-fold"]');
    if (btn) {
        btn.innerHTML = foldLabel();
        btn.setAttribute('aria-pressed', String(!!app.folded));
    }
}

function toggleFold() {
    if (isGalleryView() || !document.querySelector('#feed .post-card')) return;
    // 접거나 펼친 뒤에도 보던 글이 화면 맨 위에 남도록
    const current = currentPostCard();
    app.folded = !app.folded;
    app.openPostIds = new Set();
    const map = foldMap();
    map[foldKey()] = app.folded;
    storageSet(localStorage, FOLD_STORAGE_KEY, JSON.stringify(map));
    applyFold();
    if (current) window.scrollTo({ top: current.getBoundingClientRect().top + window.pageYOffset - stickyHeight() - 12 });
    scheduleReadCheck();
}

// 접힌 상태에서 글 제목 줄을 누르면 그 글만 펼치거나 다시 접음 (링크·버튼을 누른 경우는 제외)
function toggleCardFold(e) {
    if (!app.folded) return false;
    const head = e.target.closest('#feed .post-card .post-head');
    if (!head || e.target.closest('a, button, select, input')) return false;
    const card = head.closest('.post-card');
    if (app.openPostIds.has(card.id)) app.openPostIds.delete(card.id);
    else app.openPostIds.add(card.id);
    applyFold();
    scheduleReadCheck();
    return true;
}

// ==========================================
// 단축키 안내 (데스크톱 사이드바 아래): 지금 화면에서 쓸 수 있는 키만 진하게
// ==========================================
function updateShortcutGuide() {
    const guide = document.getElementById('shortcut-guide');
    if (!guide) return;
    const viewer = document.getElementById('media-viewer');
    const where = viewer && !viewer.hidden ? 'viewer' : isGalleryView() ? 'gallery' : 'list';
    guide.querySelectorAll('[data-keys]').forEach(row => {
        row.classList.toggle('is-off', !row.dataset.keys.split(' ').includes(where));
    });
}

function toggleShortcutGuide() {
    const guide = document.getElementById('shortcut-guide');
    const closed = !guide.classList.contains('is-closed');
    guide.classList.toggle('is-closed', closed);
    guide.querySelector('.keys-toggle').setAttribute('aria-expanded', String(!closed));
    storageSet(localStorage, KEYS_STORAGE_KEY, closed ? '1' : '0');
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

function renderSortSelect() {
    const current = currentSort().key;
    return `<select class="page-select sort-select" data-action="set-sort" aria-label="정렬">
        ${SORTS.map(s => `<option value="${s.key}" ${s.key === current ? 'selected' : ''}>${s.label}</option>`).join('')}
    </select>`;
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

// 맨 아래 페이지 선택: 기본 선택 상자는 아래로 펼쳐져 화면 밖으로 잘리므로, 버튼 위쪽으로 열리는 목록으로 직접 그림
function renderPageMenu(page, totalPages) {
    const options = Array.from({ length: totalPages }, (_, i) => `
        <button class="page-menu-option" role="option" data-action="pick-page" data-page="${i + 1}" aria-selected="${i + 1 === page}">${i + 1}</button>`).join('');
    return `
        <span class="page-jump">
            <span class="page-menu">
                <button class="page-select page-menu-btn" data-action="toggle-page-menu" aria-haspopup="listbox" aria-expanded="false" aria-label="페이지 선택 (아래)">
                    ${page}<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 15l6-6 6 6"></path></svg>
                </button>
                <span class="page-menu-list" role="listbox" aria-label="페이지" hidden>${options}</span>
            </span>
            <span class="page-total">/ ${totalPages}</span>
        </span>`;
}

function setPageMenuOpen(menu, open) {
    const list = menu.querySelector('.page-menu-list');
    list.hidden = !open;
    menu.querySelector('.page-menu-btn').setAttribute('aria-expanded', String(open));
    if (open) {
        // 현재 페이지가 목록 가운데쯤 보이도록
        const current = list.querySelector('[aria-selected="true"]');
        if (current) list.scrollTop = current.offsetTop - list.clientHeight / 2 + current.offsetHeight / 2;
    }
}

function closePageMenus(except) {
    document.querySelectorAll('.page-menu').forEach(menu => { if (menu !== except) setPageMenuOpen(menu, false); });
}

// ---------- 글 공유 (원문 주소와 제목) ----------
// 휴대폰 공유 창(navigator.share)은 https에서만 쓸 수 있어, 그 밖에서는 '링크 복사'·'텔레그램으로 보내기' 목록을 띄움
function sharePostInfo(postId) {
    const card = document.getElementById('post-' + postId);
    const link = card && card.querySelector('.btn-original.top');
    const url = link && link.getAttribute('href') !== '#' ? link.href : originalUrl(postId);
    const title = card ? card.querySelector('.post-title').textContent.trim() : '';
    return { url, title };
}

async function sharePost(button) {
    const { url, title } = sharePostInfo(button.dataset.postId);
    if (navigator.share) {
        try { await navigator.share({ title, url }); } catch (e) { /* 공유 창을 닫음 */ }
        return;
    }
    const wrap = button.closest('.share-wrap');
    const open = wrap.querySelector('.share-menu');
    closeShareMenus();
    if (open) return;  // 열려 있던 목록을 다시 누르면 닫기만
    const telegram = 'https://t.me/share/url?' + new URLSearchParams({ url, text: title }).toString();
    wrap.insertAdjacentHTML('beforeend', `
        <span class="share-menu" role="menu">
            <button class="view-more-option" role="menuitem" data-action="copy-post-link" data-post-id="${esc(button.dataset.postId)}">링크 복사</button>
            <a class="view-more-option" role="menuitem" href="${esc(telegram)}" target="_blank" rel="noopener noreferrer">텔레그램으로 보내기</a>
        </span>`);
    button.setAttribute('aria-expanded', 'true');
}

function closeShareMenus(except) {
    document.querySelectorAll('.share-menu').forEach(menu => {
        if (menu.closest('.share-wrap') === except) return;
        menu.closest('.share-wrap').querySelector('.share-btn').setAttribute('aria-expanded', 'false');
        menu.remove();
    });
}

// 클립보드 API도 https에서만 되므로, 안 되면 숨긴 입력칸을 골라 복사하는 예전 방식으로
async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (e) {
        const area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
        document.body.appendChild(area);
        area.select();
        let ok = false;
        try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
        area.remove();
        return ok;
    }
}

async function copyPostLink(postId) {
    const { url, title } = sharePostInfo(postId);
    closeShareMenus();
    showToast(await copyText(title ? `${title}\n${url}` : url) ? '링크를 복사했습니다' : '복사하지 못했습니다');
}

// 화면 아래 가운데에 잠깐 뜨는 안내
let toastTimer = null;
function showToast(message) {
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.className = 'toast';
        toast.setAttribute('role', 'status');
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 2000);
}

// 보기 탭 끝 '더보기' 목록 (보관함·삭제됨)
function setViewMoreOpen(box, open) {
    box.querySelector('.view-more-list').hidden = !open;
    box.querySelector('.view-more-btn').setAttribute('aria-expanded', String(open));
}
function closeViewMore(except) {
    document.querySelectorAll('.view-more').forEach(box => { if (box !== except) setViewMoreOpen(box, false); });
}

function renderPager(page, totalPages) {
    return `
        <nav class="pager" aria-label="페이지 이동">
            <button class="btn btn-outline" data-action="page" data-target="prev" ${page <= 1 ? 'disabled' : ''}>이전</button>
            ${renderPageMenu(page, totalPages)}
            <button class="btn btn-primary" data-action="page" data-target="next" ${page >= totalPages ? 'disabled' : ''}>다음 페이지</button>
        </nav>`;
}

function feedSubText(total) {
    if (total === undefined) total = app.renderedPostTotal;
    // 인기순은 뒤에 표시하고, 기간을 정했으면 그 기간에 수집한 글 수도 (예: 최근 일주일 인기순 12개)
    const sortNote = !isPopular() ? '' : currentSort().days
        ? ` · 최근 ${currentSort().label.replace('인기 · ', '')} 인기순 ${total}개` : ' · 인기순';
    if (app.searchQuery) return `모든 게시판에서 ${total}건${isPopular() ? ` · ${currentSort().label}` : ''}`;
    const summary = viewSummary(app.activeKey);
    if (!summary) return '';
    const unread = summary.unread_count;
    const group = findGroup(app.activeKey);
    const folder = findFolder(app.activeKey);
    // 여러 사이트 게시판은 키워드마다 사이트를 붙여 구분 (FM 싼타페, DC 싼타페)
    const memberLabel = m => (group && isMultiGroup(group) ? esc(siteLabel(boardSite(m.board)).short) + ' ' : '')
        + esc(m.keyword) + (m.paused ? ' (일시정지)' : '');
    const label = group ? `키워드 ${group.members.map(memberLabel).join(', ')}`
        : folder ? `${esc(folder.name)} 묶음의 모든 게시판` : '모든 게시판';
    if (app.filter === 'unread') return unread ? `${label} · 안 읽은 새 글 <strong>${unread}개</strong>` : '안 읽은 글을 모두 읽었습니다';
    if (app.filter === 'comments') return summary.comment_count
        ? `${label} · 읽은 뒤 새 댓글이 달린 글 <strong>${summary.comment_count}개</strong> · 최근 댓글 순` : '새 댓글을 모두 확인했습니다';
    if (app.filter === 'video' || app.filter === 'image') {
        // 모아보기: 미디어 개수와 지금 페이지의 범위 (예: 이미지 147개 중 13–24)
        const range = app.galleryRange && total ? ` 중 ${app.galleryRange[0]}–${app.galleryRange[1]}` : '';
        const period = isPopular() ? ` · ${currentSort().days ? `최근 ${currentSort().label.replace('인기 · ', '')} ` : ''}인기순` : '';
        return `${label} · ${app.filter === 'image' ? '이미지' : '동영상'} ${total}개${range}${period}`;
    }
    if (app.filter === 'deleted') return `${label} · 원문이 삭제된 글 ${summary.deleted_count}개${sortNote || ' · 최근 삭제 순'}`;
    if (app.filter === 'saved') return `${label} · 보관한 글 ${summary.saved_count}개${sortNote || ' · 최근 보관 순'}`;
    return `${label} · ${summary.total}개 글${unread ? ` · <strong>새 글 ${unread}</strong>` : ''}${sortNote}`;
}

function renderFeedSub() {
    // 읽음 처리로 안 읽은 수가 바뀌면 제목 아래 요약과 '모두 읽음' 버튼만 갱신
    const sub = document.querySelector('.feed-sub');
    if (sub && !app.searchQuery) sub.innerHTML = feedSubText();
    const btn = document.querySelector('[data-action="mark-all-read"]');
    const summary = viewSummary(app.activeKey);
    if (btn && summary) btn.hidden = app.searchQuery || pendingCount(summary) === 0;
}

// 검색 중이면 검색 결과, 아니면 '게시판|보기' (응답이 늦게 와서 다른 화면을 덮어쓰지 않게 비교용)
function currentViewKey() {
    return (app.searchQuery ? 'search:' + app.searchQuery : app.activeKey + '|' + app.filter) + '|' + currentSort().key;
}

// 지금 화면에 쓰는 정렬: 안 읽은 글(읽는 중 순서가 밀리지 않게)·새 댓글(최근 댓글 순) 보기는 항상 그 보기의 순서
function sortable() { return !!app.searchQuery || !['unread', 'comments'].includes(app.filter); }
function currentSort() {
    return (sortable() && SORTS.find(s => s.key === app.sort)) || SORTS[0];
}
function isPopular() { return currentSort().key !== 'latest'; }

function setSort(key) {
    if (!SORTS.some(s => s.key === key)) return;
    app.sort = key;
    storageSet(localStorage, SORT_STORAGE_KEY, key);
    app.page = 1;
    loadPosts();
}

async function loadPosts() {
    const feed = document.getElementById('feed');
    hideNewBanner();
    const searching = !!app.searchQuery;
    const group = findGroup(app.activeKey);
    const viewKey = currentViewKey();
    const params = new URLSearchParams({ page: app.page, video_only: !searching && app.filter === 'video' ? '1' : '0' });
    if (isGalleryView()) {
        params.set('media', app.filter);
        params.set('per', GALLERY_PER_PAGE[app.filter]);
    }
    if (!searching && app.filter === 'deleted') params.set('deleted_only', '1');
    if (!searching && app.filter === 'image') params.set('image_only', '1');
    if (!searching && app.filter === 'saved') params.set('saved_only', '1');
    if (isPopular()) {
        params.set('sort', 'popular');
        if (currentSort().days) params.set('days', currentSort().days);
    }
    if (searching) {
        params.set('q', app.searchQuery);
    } else {
        if (group) params.set('group', group.id);
        if (findFolder(app.activeKey)) params.set('folder', findFolder(app.activeKey).id);
        if (app.filter === 'unread') params.set('unread_since', app.unreadSince || 'now');
    }

    let data;
    try {
        // 방금 읽은 글이 아직 서버에 가지 않았으면 먼저 보냄 (안 그러면 안 읽은 글로 다시 옴)
        await flushReads();
        data = !searching && app.filter === 'comments'
            ? await loadCommentPosts()
            : await withProgress(getJSON('/api/posts?' + params.toString()));
    } catch (e) {
        feed.innerHTML = '<div class="empty-card">게시글을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>';
        return;
    }
    if (viewKey !== currentViewKey()) return false;  // 응답 도착 전에 다른 보기로 이동한 경우
    if (data.unread_since) app.unreadSince = data.unread_since;  // 다음 페이지도 같은 기준으로
    return renderFeed(data);
}

// 새 댓글 보기: 연 때의 글 목록(최근 댓글 순)을 고정해 두고 한 페이지 분량씩 받아 옴
async function loadCommentPosts() {
    if (!app.commentIds) app.commentIds = viewSummary(app.activeKey).comment_ids.slice();
    const perPage = app.state.posts_per_page;
    const total = app.commentIds.length;
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    const page = Math.min(Math.max(1, app.page), totalPages);
    const ids = app.commentIds.slice((page - 1) * perPage, page * perPage);
    const posts = ids.length ? (await withProgress(getJSON('/api/posts?ids=' + ids.join(',')))).posts : [];
    return { page, total_pages: totalPages, total, posts };
}

// 글 목록 응답(또는 지난 화면 캐시)을 피드로 그림
function renderFeed(data) {
    const feed = document.getElementById('feed');
    app.folded = foldedFor(foldKey());  // 이 게시판에서 마지막으로 정한 접기 상태
    feed.removeAttribute('aria-busy');
    const searching = !!app.searchQuery;
    const group = findGroup(app.activeKey);
    const filter = searching ? null : app.filter;  // 검색은 보기와 상관없이 모든 게시판에서
    app.page = data.page;
    app.totalPages = data.total_pages;
    const summary = viewSummary(app.activeKey);
    app.renderedTotal = searching || isPopular() ? null : (summary ? filterCount(summary, filter) : null);
    app.renderedPostTotal = data.total;
    app.renderedUnreadIds = filter === 'unread' ? new Set(summary.unread_ids)
        : filter === 'comments' ? new Set(app.commentIds) : null;
    app.galleryRange = isGalleryView() && data.items
        ? [(data.page - 1) * data.per_page + 1, (data.page - 1) * data.per_page + data.items.length] : null;
    document.body.classList.toggle('gallery-mode', isGalleryView());
    app.openPostIds = new Set();  // 접힌 상태에서 하나씩 펼친 글은 화면을 새로 그리면 다시 접음
    app.previewMedia = {};        // 접힌 글 썸네일의 크게 보기용 {글 ID: 사진·동영상 목록}
    if (!searching) {
        storageSet(sessionStorage, 'last_active_tab', app.activeKey);
        storageSet(sessionStorage, 'last_active_filter', app.filter);
    }

    const empty = data.total === 0;
    let body = '';
    if (empty) {
        body = !searching && !(app.state.groups || []).length
            ? '<div class="empty-card">게시판이 없습니다. 관리에서 게시판을 만들고 키워드를 등록해 주세요.</div>'
            : filter === 'unread'
            ? '<div class="empty-card">안 읽은 글이 없습니다. <button class="link-btn" data-action="set-view" data-filter="all">모든 글 보기</button></div>'
            : filter === 'comments'
            ? '<div class="empty-card">읽은 뒤 새 댓글이 달린 글이 없습니다.</div>'
            : searching ? `<div class="empty-card">'${esc(app.searchQuery)}'에 해당하는 글이 없습니다.</div>`
            : filter === 'video' ? '<div class="empty-card">동영상이 포함된 게시글이 없습니다.</div>'
            : filter === 'image' ? '<div class="empty-card">첨부 이미지가 있는 게시글이 없습니다.</div>'
            : filter === 'deleted' ? '<div class="empty-card">원문이 삭제된 글이 없습니다.</div>'
            : filter === 'saved' ? '<div class="empty-card">보관한 글이 없습니다. 글 제목 옆 별표를 누르면 보관함에 담깁니다.</div>'
            : '<div class="empty-card">수집된 게시글이 없습니다. 새 글이 등록되면 이곳에 표시됩니다.</div>';
    } else if (isGalleryView()) {
        body = renderGallery(data.items, filter);
    } else {
        let sawUnread = false;
        let dividerShown = false;
        data.posts.forEach(post => {
            const isUnread = post.is_new && !post.read_at;
            // 안 읽은 새 글 다음부터는 이미 본 글이라는 구분선을 한 번만 표시
            if (!searching && !isPopular() && !isUnread && sawUnread && !dividerShown) {
                body += '<div class="new-divider" role="separator">여기까지 새 글</div>';
                dividerShown = true;
            }
            if (isUnread) sawUnread = true;
            body += renderPost(post, isUnread);
        });
    }

    // 제목: 게시판 이름, '모든 글'이 아닌 보기는 뒤에 보기 이름
    const title = searching ? `검색: ${esc(app.searchQuery)}`
        : (group ? (multiSite() ? groupTag(group) : '') + esc(group.name)
            : findFolder(app.activeKey) ? esc(findFolder(app.activeKey).name) : '전체')
          + (filter !== 'all' ? ` · ${filterLabel(filter)}` : '');
    const headActions = searching
        ? '<button class="btn btn-outline btn-small" data-action="clear-search">검색 닫기</button>'
        : app.galleryReturn
        ? `<button class="btn btn-outline btn-small" data-action="return-gallery">${ICONS.prev} ${filterLabel(app.galleryReturn.filter)} 모아보기로</button>`
        : (empty || isGalleryView() ? '' : `<button class="btn btn-outline btn-small fold-btn" data-action="toggle-fold" aria-pressed="${app.folded}" title="본문·댓글 전부 접기/펼치기 (G)">${foldLabel()}</button>`)
        + `<button class="btn btn-outline btn-small" data-action="mark-all-read" ${summary && pendingCount(summary) ? '' : 'hidden'}>${filter === 'comments' ? '모두 확인' : '모두 읽음'}</button>`;
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
                ${sortable() ? renderSortSelect() : ''}
                ${renderPagerMini(data.page, data.total_pages, empty)}
            </div>
        </div>
        ${body}
        ${empty ? '' : renderPager(data.page, data.total_pages)}`;
    // 새 목록은 맨 위에서 시작. 맨 아래에서 '다음 페이지'를 누른 위치 그대로 읽음 확인을 하면
    // 새 글들의 끝 표식이 모두 화면 위쪽에 있는 것으로 판정되어 한꺼번에 읽음 처리되므로, 확인 전에 즉시 이동
    window.scrollTo({ top: 0 });
    // 글이 없는 화면에서는 다음 글 버튼을 숨김
    document.querySelector('.fab-next').hidden = empty || isGalleryView();
    updateNextButton();
    // 텔레그램 알림 링크(#post-ID)로 연 글이 있으면 그 글로 이동 (읽음 확인보다 먼저)
    const target = app.highlightPostId && document.getElementById('post-' + app.highlightPostId);
    app.highlightPostId = null;
    if (target) jumpToPost(target);
    anchorCommentBoxes();
    applyFold();
    updateShortcutGuide();
    observeReadSentinels();
    return !!target;
}

// 넓은 화면의 오른쪽 댓글 칸(따로 스크롤)의 시작 위치: 새 댓글이 마지막 댓글이 아니면 첫 새 댓글을 칸 맨 위에,
// 아니면(새 댓글이 마지막이거나 없으면) 최신 댓글이 보이도록 맨 아래.
// 댓글 이미지가 늦게 떠서 높이가 늘어도, 사용자가 그 칸을 직접 스크롤하기 전까지는 같은 위치를 유지 (아래 load 이벤트)
function anchorCommentBox(box) {
    if (box.dataset.userScrolled) return;
    const comments = box.querySelectorAll('.comment');
    const firstNew = box.querySelector('.comment.is-new-comment');
    if (firstNew && firstNew !== comments[comments.length - 1]) {
        box.scrollTop += firstNew.getBoundingClientRect().top - box.getBoundingClientRect().top - 8;
    } else {
        box.scrollTop = box.scrollHeight;
    }
}
function anchorCommentBoxes(root = document) {
    root.querySelectorAll('.post-card.has-comments > .comments').forEach(anchorCommentBox);
}
['wheel', 'touchstart', 'keydown', 'mousedown'].forEach(type => document.addEventListener(type, e => {
    const box = e.target.closest && e.target.closest('.post-card.has-comments > .comments');
    if (box) box.dataset.userScrolled = '1';
}, { passive: true, capture: true }));
document.addEventListener('load', e => {
    const box = e.target.closest && e.target.closest('.post-card.has-comments > .comments');
    if (box) anchorCommentBox(box);
}, true);
// 창을 넓혀 댓글 칸이 따로 스크롤되기 시작할 때도 같은 시작 위치로
window.matchMedia('(min-width: 1360px)').addEventListener('change', e => { if (e.matches) anchorCommentBoxes(); });

// 맨 위를 거쳐 미끄러지듯 내려가지 않도록 애니메이션 없이 바로 이동.
// 위쪽 글의 이미지·동영상·SNS 게시물이 늦게 떠서 높이가 바뀌면 글이 밀리므로, 사용자가 직접 스크롤하기 전까지
// (최대 몇 초) 위치를 다시 맞춤. 위쪽 글은 지나쳤을 뿐 읽은 게 아니므로 실제로 보일 때만 읽음 처리되게 표시
const JUMP_SETTLE_MS = 4000;
const USER_SCROLL_EVENTS = ['wheel', 'touchstart', 'keydown', 'mousedown'];
function jumpToPost(target) {
    const offset = stickyHeight() + 12;
    const scrollToTarget = () => window.scrollTo({ top: target.getBoundingClientRect().top + window.pageYOffset - offset });
    const above = [...document.querySelectorAll('#feed .post-card')]
        .filter(card => card.compareDocumentPosition(target) & Node.DOCUMENT_POSITION_FOLLOWING);
    above.forEach(card => {
        const sentinel = card.querySelector('.read-sentinel');
        if (sentinel) sentinel.dataset.skipped = '1';
    });
    scrollToTarget();
    target.classList.add('highlight');
    setTimeout(() => target.classList.remove('highlight'), 2500);

    if (!above.length || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(scrollToTarget);
    const stop = () => {
        observer.disconnect();
        USER_SCROLL_EVENTS.forEach(type => window.removeEventListener(type, stop));
    };
    above.forEach(card => observer.observe(card));
    USER_SCROLL_EVENTS.forEach(type => window.addEventListener(type, stop, { passive: true }));
    setTimeout(stop, JUMP_SETTLE_MS);
}

// 다음 글 버튼(F 키): 화면 맨 위에 걸친 글(위 메뉴 바로 아래에서 아직 끝나지 않은 첫 글)을 읽음 처리하고
// 다음 글의 제목이 위 메뉴 바로 아래에 오도록 이동. 페이지의 마지막 글이면 다음 페이지로
// 화면 위에 고정된 메뉴(상단 바)의 높이. 보기 탭은 데스크톱·모바일 모두 상단 바 안에 있음
function stickyHeight() {
    return document.querySelector('.topbar').offsetHeight;
}

function currentPostCard() {
    const headerBottom = document.querySelector('.topbar').getBoundingClientRect().bottom;
    return [...document.querySelectorAll('#feed .post-card')]
        .find(card => card.getBoundingClientRect().bottom > headerBottom + 8) || null;
}

// 모바일 '새 댓글' 보기: 다음 글 버튼이 글 단위가 아니라 마지막 댓글 단위로 이동
function lastCommentMode() {
    return !app.searchQuery && app.filter === 'comments' && window.matchMedia('(max-width: 899px)').matches;
}

// 떠 있는 버튼(맨 위로·다음 글 두 개를 쌓은 높이 약 120px)에 가리지 않도록 화면 아래쪽에 남기는 여백
const FAB_ROOM = 130;
function scrollToLastComment(card) {
    const comments = card.querySelectorAll('.comments .comment');
    const target = comments[comments.length - 1] || card;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // 마지막 댓글의 아래 끝을 버튼 바로 위에 맞춤 (그 위로 앞의 새 댓글들이 보이게)
    window.scrollTo({ top: target.getBoundingClientRect().bottom + window.pageYOffset - window.innerHeight + FAB_ROOM,
                      behavior: reduceMotion ? 'auto' : 'smooth' });
}

// 첫 새 댓글을 맨 위 메뉴 바로 아래에 맞춤 (그 아래로 이어지는 댓글이 보이게).
// 모바일은 아래로 내리면 맨 위 제목 줄이 숨으므로, 숨은 뒤의 위 메뉴 높이 기준
function newCommentTop() {
    return stickyHeight() - document.querySelector('.topbar .topbar-row').offsetHeight + 12;
}
function scrollToComment(comment) {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: comment.getBoundingClientRect().top + window.pageYOffset - newCommentTop(),
                      behavior: reduceMotion ? 'auto' : 'smooth' });
}

// 글마다 멈출 곳: 첫 새 댓글(마지막 댓글이 아닐 때) → 마지막 댓글. 글 순서대로 이어서,
// 아직 화면에서 다 보지 못한 첫 멈출 곳으로 이동 (페이지 끝이면 다음 페이지).
// 첫 새 댓글은 위에 맞춰 둔 뒤면 지나간 것으로 봄 (화면보다 긴 댓글에서 같은 곳에 멈추지 않게)
function goNextLastComment() {
    const limit = window.innerHeight - FAB_ROOM + 8;
    const stops = [...document.querySelectorAll('#feed .post-card')].flatMap(card => {
        const comments = card.querySelectorAll('.comments .comment');
        const last = comments[comments.length - 1];
        if (!last) return [{ card, el: card }];
        const firstNew = card.querySelector('.comments .comment.is-new-comment');
        return (firstNew && firstNew !== last ? [{ card, el: firstNew, top: true }] : []).concat([{ card, el: last }]);
    });
    const next = stops.find(stop => {
        const rect = stop.el.getBoundingClientRect();
        return rect.bottom > limit && !(stop.top && rect.top <= newCommentTop() + 8);
    });
    if (!next) {
        if (app.page < app.totalPages) changePage('next');
    } else if (next.top) {
        scrollToComment(next.el);
    } else {
        scrollToLastComment(next.card);
    }
}

// 다음 글 버튼의 이름: 모바일 '새 댓글' 보기에서는 마지막 댓글로 이동
function updateNextButton() {
    const label = lastCommentMode() ? '마지막 댓글로' : '다음 글';
    const btn = document.querySelector('.fab-next');
    btn.setAttribute('aria-label', label);
    btn.title = lastCommentMode() ? label : label + ' (F)';
}

function goNextPost() {
    if (lastCommentMode()) { goNextLastComment(); return; }
    const cards = [...document.querySelectorAll('#feed .post-card')];
    const current = currentPostCard();
    if (!cards.length || !current) return;
    const sentinel = current.querySelector('.read-sentinel');
    if (sentinel && !sentinel.dataset.read) {
        sentinel.dataset.read = '1';
        markRead([sentinel.dataset.postId]);
    }
    const next = cards[cards.indexOf(current) + 1];
    if (!next) {
        if (app.page < app.totalPages) changePage('next');
        return;
    }
    // 모바일은 아래로 내리면 맨 위 제목 줄이 숨으므로, 숨은 뒤의 위 메뉴 높이에 맞춤
    const topbar = document.querySelector('.topbar');
    const mobile = window.matchMedia('(max-width: 899px)').matches;
    const offset = stickyHeight() - (mobile ? topbar.querySelector('.topbar-row').offsetHeight : 0) + 12;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: next.getBoundingClientRect().top + window.pageYOffset - offset, behavior: reduceMotion ? 'auto' : 'smooth' });
}

function changePage(target) {
    if (target === 'prev') app.page = Math.max(1, app.page - 1);
    else if (target === 'next') app.page = Math.min(app.totalPages, app.page + 1);
    else app.page = Math.min(Math.max(1, Number(target) || 1), app.totalPages);
    loadPosts();
}

function markAllRead() {
    const summary = viewSummary(app.activeKey);
    if (!summary || pendingIds(summary).length === 0) return;
    const ids = pendingIds(summary).slice();
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
    setState(fresh);
    renderStatus(true);
    renderNavigation();
    renderFeedSub();
    // 관리 패널을 열어 둔 채 기다리면 추가한 카테고리의 확인 결과가 바로 보이게
    if (!document.getElementById('settings').hidden) {
        renderBoardChecks();
        renderCategorySettings();
    }
    if (app.searchQuery || app.renderedTotal === null) return;
    const summary = viewSummary(app.activeKey);
    if (!summary) return;
    const added = app.renderedUnreadIds
        ? pendingIds(summary).filter(id => !app.renderedUnreadIds.has(id)).length
        : filterCount(summary, app.filter) - app.renderedTotal;
    if (added > 0) {
        const banner = document.getElementById('new-banner');
        const what = app.filter === 'comments' ? '새 댓글이 달린 글' : app.filter === 'deleted' ? '새로 삭제된 글'
            : app.filter === 'saved' ? '새로 보관한 글' : '새 글';
        banner.innerHTML = `${ICONS.up}<span>${what} ${added}개 · 눌러서 보기</span>`;
        banner.hidden = false;
    }
}

// 보관함에 담기·빼기: 별표를 먼저 바꿔 보여 주고, 실패하면 되돌림. 보기별 글 수는 서버 상태로 다시 받음
async function toggleSaved(button) {
    const saved = button.getAttribute('aria-pressed') !== 'true';
    const setPressed = on => {
        button.setAttribute('aria-pressed', String(on));
        button.setAttribute('aria-label', on ? '보관함에서 빼기' : '보관함에 담기');
        button.title = on ? '보관함에서 빼기' : '보관함에 담기 (오래된 글 정리에서 빠짐)';
    };
    setPressed(saved);
    button.disabled = true;
    try {
        const data = await postJSON('/api/saved', { id: button.dataset.postId, saved: saved });
        if (!data.success) throw new Error(data.message);
        // 보관함 보기에서는 뺀 글을 그대로 두어 다시 담을 수 있게 하고, 글 수만 갱신 (새 글 배너가 뜨지 않게 기준도 맞춤)
        if (app.filter === 'saved' && app.renderedTotal !== null) app.renderedTotal += saved ? 1 : -1;
        await pollState();
    } catch (e) {
        setPressed(!saved);
        alert('보관함에 반영하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
        button.disabled = false;
    }
}

async function showNewPosts() {
    hideNewBanner();
    app.page = 1;
    resetViewSnapshot();
    await loadPosts();
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
    renderBoardChecks();
    renderGroupSettings();
    renderSiteSettings();
    renderCategorySettings();

    const groups = app.state.groups || [];
    document.getElementById('settings-alerts').innerHTML = (groups.length ? groups.map(g => `
        <div class="alert-row">
            <span class="alert-row-name">${multiSite() ? groupTag(g) : ''}${esc(g.name)}</span>
            <span class="alert-switches">
                ${alertSwitch(g.id, 'alert', g.alert, g.name + ' 전체 알림')}
                ${alertSwitch(g.id, 'video_alert', g.video_alert, g.name + ' 동영상 알림')}
                ${alertSwitch(g.id, 'digest', g.digest, g.name + ' 하루 요약')}
            </span>
        </div>`).join('') : '<span class="settings-hint">게시판을 만들면 게시판별로 알림을 설정할 수 있습니다.</span>') + `
        <span class="settings-hint alert-hint">하루 요약: 매일 ${app.state.digest_hour}시에 최근 24시간 새 글 중 추천·댓글이 많은 글 5개를 한 번에 보냅니다. 글이 많아 전체 알림을 꺼 둔 게시판에 알맞습니다.</span>
        <div class="alert-row alert-row-saved">
            <span class="alert-row-name">⭐ 보관한 글에 새 댓글</span>
            <span class="alert-switches">${alertSwitch('', 'saved_comment', app.state.saved_comment_alert, '보관한 글 새 댓글 알림')}</span>
        </div>`;
}

// ---------- 게시판 만들기·수정·삭제 (키워드는 게시판에 등록) ----------
function renderGroupSettings() {
    const editing = (app.state.groups || []).find(g => g.id === app.editingGroupId) || null;
    if (!editing) app.editingGroupId = null;
    if (app.groupDraft === undefined) {
        app.groupDraft = editing
            ? editing.members.map(m => ({ board: m.board, keyword: m.keyword, paused: !!m.paused, ignores: m.ignores.slice() })) : [];
        // 이 게시판이 수집할 카테고리: 수정이면 등록된 키워드의 카테고리, 새 게시판이면 첫 카테고리
        const first = app.state.boards.find(b => b.status !== 'invalid');
        app.draftBoards = editing ? [...new Set(app.groupDraft.map(m => m.board))] : (first ? [first.key] : []);
        // 새로 연 양식은 찾을 곳을 처음 값(카테고리가 둘 이상이면 '공통')으로
        document.getElementById('group-kw-target').innerHTML = '';
    }
    renderBoardChecks();

    // 편집 양식은 '새 게시판'이나 '수정'을 눌렀을 때만 펼침. 무시할 표현·합치기는 '고급 설정'에 접어 둠 (게시판 합치기는 수정할 때만)
    const form = document.getElementById('group-form');
    const wasHidden = form.hidden;
    form.hidden = !(editing || app.groupFormOpen);
    if (wasHidden && !form.hidden) {
        document.getElementById('group-advanced').open = app.groupDraft.some(m => m.ignores.length);
    }
    document.getElementById('group-advanced-merge').hidden = !editing;
    document.getElementById('group-form-title').textContent = editing ? `'${editing.name}' 게시판 수정` : '새 게시판';
    // 새 게시판을 넣을 묶음 (수정할 때는 아래 게시판 목록의 묶음 고르기로 옮김)
    const folderSelect = document.getElementById('group-folder-select');
    const prevFolder = folderSelect.value;
    folderSelect.innerHTML = '<option value="">묶음 없음</option>'
        + (app.state.folders || []).map(f => `<option value="${f.id}">${esc(f.name)}</option>`).join('');
    if ((app.state.folders || []).some(f => String(f.id) === prevFolder)) folderSelect.value = prevFolder;
    folderSelect.hidden = !!editing;
    document.getElementById('group-save-btn').textContent = editing ? '저장' : '만들기';
    const nameInput = document.getElementById('group-name-input');
    if (app.groupNameDraft !== undefined) nameInput.value = app.groupNameDraft;
    else nameInput.value = editing ? editing.name : '';

    // 이 게시판에 등록할 키워드: 고른 카테고리 모두에서 찾는 '공통' 키워드를 먼저, 카테고리별 키워드는 사이트·카테고리와 함께
    const entries = app.draftEntries = draftEntries();
    const entryBadge = e => e.common
        ? '<span class="site-tag site-multi" title="고른 카테고리 모두에서 찾음">공통</span>'
        : `${siteTag(boardSite(e.members[0].board))}<span class="kw-tag-board">${esc(boardName(e.members[0].board))}</span>`;
    const entryName = e => (e.common ? '공통 ' : boardName(e.members[0].board) + ' ') + e.keyword;
    document.getElementById('group-keywords').innerHTML = entries.length ? entries.map((e, idx) => {
        const paused = e.members.every(m => m.paused);
        return `
        <span class="kw-tag${paused ? ' is-paused' : ''}">
            ${entryBadge(e)}${esc(e.keyword)}${paused ? '<span class="kw-tag-paused">일시정지</span>' : ''}
            <button data-action="toggle-draft-pause" data-index="${idx}" aria-pressed="${paused}"
                aria-label="${esc(entryName(e))} 키워드 ${paused ? '다시 수집' : '일시정지'}" title="${paused ? '다시 수집' : '일시정지 (모은 글은 그대로, 수집만 멈춤)'}">${paused ? ICONS.play : ICONS.pause}</button>
            <button data-action="remove-draft-keyword" data-index="${idx}" aria-label="${esc(entryName(e))} 키워드 빼기">${ICONS.close}</button>
        </span>`;
    }).join('') : '<span class="settings-hint">아직 등록한 키워드가 없습니다.</span>';

    // 무시할 표현: 붙일 키워드를 고르는 상자(고른 키워드 유지)와 키워드별 표현 (공통 키워드는 모든 카테고리의 그 키워드에 함께)
    const ignoreSelect = document.getElementById('group-ignore-keyword');
    const selected = ignoreSelect.value;
    ignoreSelect.innerHTML = entries.map((e, idx) => `<option value="${idx}">${esc(entryName(e))}</option>`).join('');
    if (selected && Number(selected) < entries.length) ignoreSelect.value = selected;
    document.getElementById('group-ignores').innerHTML = entries.flatMap((e, idx) => entryIgnores(e).map((phrase, pIdx) => `
        <span class="kw-tag">
            ${entryBadge(e)}<span class="kw-tag-board">${esc(e.keyword)} 무시</span>${esc(phrase)}
            <button data-action="remove-draft-ignore" data-index="${idx}" data-phrase-index="${pIdx}" aria-label="${esc(entryName(e))} 키워드의 무시할 표현 ${esc(phrase)} 빼기">${ICONS.close}</button>
        </span>`)).join('');

    // 다른 게시판 합치기 (수정 중일 때만): 고른 게시판의 키워드를 이 게시판으로 옮기고, 저장하면 그 게시판은 지움
    const mergeRow = document.getElementById('group-merge-row');
    mergeRow.hidden = !editing;
    if (editing) {
        const others = (app.state.groups || []).filter(g => g.id !== editing.id && !app.mergeDraft.includes(g.id));
        const mergeSelect = document.getElementById('group-merge-select');
        mergeSelect.innerHTML = others.length
            ? others.map(g => `<option value="${g.id}">${esc(groupShort(g))} ${esc(g.name)}</option>`).join('')
            : '<option value="">합칠 게시판 없음</option>';
        mergeSelect.disabled = !others.length;
        const merging = app.mergeDraft.map(id => (app.state.groups || []).find(g => g.id === id)).filter(Boolean);
        document.getElementById('group-merge-note').textContent = merging.length
            ? `저장하면 ${merging.map(g => `'${groupShort(g)} ${g.name}'`).join(', ')} 게시판을 이 게시판에 합치고 지웁니다. (알림 설정은 이 게시판 것을 씀)`
            : '';
    }

    const groups = app.state.groups || [];
    const memberText = (m, g) => (isMultiGroup(g) ? esc(siteLabel(boardSite(m.board)).short) + ' ' : '') + esc(m.keyword) + (m.paused ? ' (일시정지)' : '') + (m.ignores.length ? ` (무시: ${m.ignores.map(esc).join(', ')})` : '');
    // 게시판 목록: 묶음 순서대로(묶음 없는 게시판 먼저) 묶음 고르기와 같은 묶음 안 순서 옮기기
    const folders = app.state.folders || [];
    const folderOptions = g => `<option value="" ${folders.some(f => f.id === g.folder_id) ? '' : 'selected'}>묶음 없음</option>`
        + folders.map(f => `<option value="${f.id}" ${f.id === g.folder_id ? 'selected' : ''}>${esc(f.name)}</option>`).join('');
    const ordered = [null, ...folders.map(f => f.id)].flatMap(id => groups.filter(g =>
        id === null ? !folders.some(f => f.id === g.folder_id) : g.folder_id === id));
    document.getElementById('settings-groups').innerHTML = ordered.length ? ordered.map(g => `
        <div class="group-row">
            <div class="group-row-main">
                <span class="group-row-name">${multiSite() ? groupTag(g) : ''}${esc(g.name)}</span>
                <span class="group-row-members">${g.members.map(m => memberText(m, g)).join(' · ') || '(키워드 없음)'} · ${g.total}개 글</span>
                <span class="group-row-arrange">
                    <select class="input select select-small" data-action="set-group-folder" data-group-id="${g.id}" aria-label="${esc(g.name)} 게시판의 묶음">${folderOptions(g)}</select>
                    <button class="icon-btn small" data-action="move-group" data-group-id="${g.id}" data-direction="up" aria-label="${esc(g.name)} 위로">${ICONS.up}</button>
                    <button class="icon-btn small" data-action="move-group" data-group-id="${g.id}" data-direction="down" aria-label="${esc(g.name)} 아래로">${ICONS.down}</button>
                </span>
            </div>
            <button class="btn btn-outline btn-small" data-action="edit-group" data-group-id="${g.id}">수정</button>
            <button class="btn btn-outline btn-small btn-danger" data-action="delete-group" data-group-id="${g.id}">삭제</button>
        </div>`).join('') : '<span class="settings-hint">만든 게시판이 없습니다.</span>';
    renderFolderSettings();
}

// 무시할 표현 비교 기준 (서버와 같이 대소문자 무시, 연속 공백은 하나로)
function normPhrase(text) { return text.split(/\s+/).filter(Boolean).join(' ').toLowerCase(); }

// 키워드 태그 단위: 고른 카테고리가 둘 이상이고 모든 카테고리에 있는 키워드는 '공통' 하나로 묶고, 나머지는 카테고리별로 하나씩
// (고른 카테고리 순서대로). 공통 키워드의 일시정지·무시할 표현·빼기는 묶인 모든 카테고리에 함께 적용
function draftEntries() {
    const boards = app.draftBoards;
    const has = (board, keyword) => app.groupDraft.some(m => m.board === board && m.keyword === keyword);
    const common = boards.length > 1
        ? [...new Set(app.groupDraft.map(m => m.keyword))].filter(k => boards.every(b => has(b, k))) : [];
    return [
        ...common.map(k => ({ common: true, keyword: k, members: app.groupDraft.filter(m => m.keyword === k) })),
        ...boards.flatMap(b => app.groupDraft.filter(m => m.board === b && !common.includes(m.keyword))
            .map(m => ({ common: false, keyword: m.keyword, members: [m] })))
    ];
}

// 키워드 태그의 무시할 표현 (공통 키워드는 카테고리마다 다를 수 있어 모두 합쳐 한 번씩)
function entryIgnores(entry) {
    const seen = new Set();
    return entry.members.flatMap(m => m.ignores).filter(p => !seen.has(normPhrase(p)) && seen.add(normPhrase(p)));
}

// 키워드를 찾을 곳: '공통'(고른 카테고리 모두) 또는 카테고리 하나
function addDraftKeyword() {
    const input = document.getElementById('group-kw-input');
    const keyword = input.value.trim();
    const target = document.getElementById('group-kw-target').value;
    const boards = target === '*' ? app.draftBoards : app.draftBoards.filter(b => b === target);
    if (!boards.length) { alert('수집할 카테고리를 먼저 골라 주세요.'); return; }
    if (!keyword) { input.focus(); return; }
    const added = boards.filter(b => !app.groupDraft.some(m => m.board === b && m.keyword === keyword));
    if (!added.length) {
        alert('이미 등록한 키워드입니다.');
        return;
    }
    added.forEach(b => app.groupDraft.push({ board: b, keyword: keyword, paused: false, ignores: [] }));
    input.value = '';
    renderGroupSettings();
    input.focus();
}

function addDraftIgnore() {
    const input = document.getElementById('group-ignore-input');
    const phrase = input.value.trim();
    const entry = (app.draftEntries || [])[Number(document.getElementById('group-ignore-keyword').value)];
    if (!entry) { alert('키워드를 먼저 등록해 주세요.'); return; }
    if (!phrase) { input.focus(); return; }
    if (entry.members.every(m => m.ignores.some(p => normPhrase(p) === normPhrase(phrase)))) {
        alert('이미 등록한 무시할 표현입니다.');
        return;
    }
    entry.members.forEach(m => { if (!m.ignores.some(p => normPhrase(p) === normPhrase(phrase))) m.ignores.push(phrase); });
    input.value = '';
    renderGroupSettings();
    input.focus();
}

// 수집할 카테고리 고르기 (게시판 만들기·수정): 누를 때마다 넣고 빼기. 뺄 때 그 카테고리의 키워드도 함께 빠짐.
// 이미 고른 카테고리가 둘 이상이면 새로 넣는 카테고리에도 공통 키워드를 등록
function toggleDraftBoard(board) {
    if (app.draftBoards.includes(board)) {
        const members = app.groupDraft.filter(m => m.board === board);
        if (members.length && !confirm(`'${boardName(board)}' 카테고리의 키워드 ${members.length}개도 함께 뺍니다. 뺄까요?`)) return;
        app.groupDraft = app.groupDraft.filter(m => m.board !== board);
        app.draftBoards = app.draftBoards.filter(b => b !== board);
    } else {
        const common = draftEntries().filter(e => e.common);
        app.draftBoards.push(board);
        common.forEach(e => app.groupDraft.push({
            board: board, keyword: e.keyword, paused: e.members.every(m => m.paused), ignores: entryIgnores(e)
        }));
    }
    renderGroupSettings();
}

// 카테고리 고르기 칩과 키워드를 찾을 곳 상자 (확인을 통과하지 못한 카테고리는 뺌)
function renderBoardChecks() {
    if (!app.draftBoards) return;
    const boards = app.state.boards.filter(b => b.status !== 'invalid');
    app.draftBoards = app.draftBoards.filter(key => boards.some(b => b.key === key) || app.groupDraft.some(m => m.board === key));
    document.getElementById('group-board-checks').innerHTML = boards.map(b => `
        <button type="button" class="board-check" data-action="toggle-draft-board" data-board="${esc(b.key)}" aria-pressed="${app.draftBoards.includes(b.key)}">
            ${siteTag(b.site)}${esc(b.name)}${b.status === 'pending' ? ' (확인 대기)' : ''}
        </button>`).join('');
    const target = document.getElementById('group-kw-target');
    const prev = target.value;
    const options = (app.draftBoards.length > 1 ? [['*', '공통']] : [])
        .concat(app.draftBoards.map(key => [key, `${siteLabel(boardSite(key)).short} ${boardName(key)}`]));
    target.innerHTML = options.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join('');
    if (options.some(([value]) => value === prev)) target.value = prev;
    target.disabled = !options.length;
}

// 고른 게시판의 키워드를 지금 수정 중인 게시판에 넣고, 저장할 때 그 게시판을 지우도록 기억
function addDraftMerge() {
    const id = Number(document.getElementById('group-merge-select').value);
    const source = (app.state.groups || []).find(g => g.id === id);
    if (!source) return;
    source.members.forEach(m => {
        if (!app.groupDraft.some(d => d.board === m.board && d.keyword === m.keyword)) {
            app.groupDraft.push({ board: m.board, keyword: m.keyword, paused: !!m.paused, ignores: m.ignores.slice() });
        }
    });
    source.members.forEach(m => { if (!app.draftBoards.includes(m.board)) app.draftBoards.push(m.board); });
    app.mergeDraft.push(id);
    renderGroupSettings();
}

function resetGroupForm() {
    app.groupFormOpen = false;
    app.mergeDraft = [];
    app.draftBoards = undefined;
    app.editingGroupId = null;
    app.groupDraft = undefined;
    app.groupNameDraft = undefined;
    document.getElementById('group-kw-input').value = '';
    document.getElementById('group-ignore-input').value = '';
    renderGroupSettings();
}

// 다른 게시판에 없는 키워드는 게시판에서 빠지면 수집을 멈추고 모은 글도 삭제됨 (합쳐서 지울 게시판의 키워드도 포함)
function droppedKeywords(groupId, keepMembers, mergeIds = []) {
    const keep = new Set(keepMembers.map(memberKey));
    const leaving = new Set([groupId, ...mergeIds]);
    const others = new Set((app.state.groups || []).filter(g => !leaving.has(g.id)).flatMap(g => g.members.map(memberKey)));
    const seen = new Set();
    return (app.state.groups || []).filter(g => leaving.has(g.id)).flatMap(g => g.members)
        .filter(m => !keep.has(memberKey(m)) && !others.has(memberKey(m)) && !seen.has(memberKey(m)) && seen.add(memberKey(m)));
}

async function saveGroup(button) {
    const pwd = adminPassword();
    const name = document.getElementById('group-name-input').value.trim();
    // 입력만 하고 '추가'를 누르지 않은 키워드도 함께 등록
    if (document.getElementById('group-kw-input').value.trim()) addDraftKeyword();
    if (document.getElementById('group-ignore-input').value.trim()) addDraftIgnore();
    const members = app.groupDraft.map(m => ({ board: m.board, keyword: m.keyword, paused: !!m.paused, ignores: m.ignores.slice() }));
    if (!name) { alert('게시판 이름을 입력해 주세요.'); document.getElementById('group-name-input').focus(); return; }
    if (members.length === 0) { alert('키워드를 하나 이상 등록해 주세요.'); document.getElementById('group-kw-input').focus(); return; }
    if (!pwd) { needPassword(); return; }

    const editingId = app.editingGroupId;
    const mergeIds = editingId ? app.mergeDraft.slice() : [];
    const dropped = editingId ? droppedKeywords(editingId, members, mergeIds) : [];
    if (dropped.length && !confirm(`뺀 키워드 ${dropped.map(m => m.keyword).join(', ')}는 수집을 멈추고 모은 글도 삭제됩니다. 저장할까요?`)) return;
    button.disabled = true;
    try {
        const data = await postJSON('/api/group', {
            action: editingId ? 'update' : 'create', id: editingId, name: name, members: members, merge_ids: mergeIds, password: pwd,
            folder_id: editingId || !document.getElementById('group-folder-select').value
                ? null : Number(document.getElementById('group-folder-select').value)
        });
        if (!data.success) { if (data.message) alert(data.message); return; }
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
    if (!pwd) { needPassword(); return; }
    const dropped = droppedKeywords(groupId, []);
    const note = dropped.length ? `\n(키워드 ${dropped.map(m => m.keyword).join(', ')}는 수집을 멈추고 모은 글도 삭제됩니다)` : '';
    if (!confirm(`'${group.name}' 게시판을 삭제할까요?${note}`)) return;
    button.disabled = true;
    try {
        const data = await postJSON('/api/group', { action: 'delete', id: groupId, password: pwd });
        if (!data.success) { if (data.message) alert(data.message); return; }
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

// ---------- 카테고리 (수집할 에펨코리아 게시판. 추가하면 수집기가 다음 주기에 확인) ----------
const CATEGORY_STATUS = {
    pending: { label: '확인 대기', cls: 'cat-pending' },
    ok: { label: '수집 중', cls: 'cat-ok' },
    invalid: { label: '수집 불가', cls: 'cat-invalid' }
};

// 키워드 등록용 카테고리 선택: 수집할 수 없는 카테고리는 빼고, 확인 전인 카테고리는 표시해서 보여줌
// 사이트 이름·짧은 표시 편집 (저장하면 사이드바·FM·DC 표시·텔레그램 알림에 바로 반영)
function renderSiteSettings() {
    document.getElementById('settings-sites').innerHTML = Object.entries(SITES).map(([site, label]) => `
        <div class="group-row site-row">
            ${siteTag(site)}
            <input class="input site-name-input" data-site="${site}" value="${esc(label.name)}" maxlength="20" aria-label="${esc(label.name)} 이름" autocomplete="off">
            <input class="input site-short-input" data-site="${site}" value="${esc(label.short)}" maxlength="4" aria-label="${esc(label.name)} 짧은 표시" autocomplete="off">
            <button class="btn btn-outline btn-small" data-action="save-site" data-site="${site}">저장</button>
        </div>`).join('');
}

async function saveSite(site, button) {
    const row = button.closest('.site-row');
    const name = row.querySelector('.site-name-input').value.trim();
    const short = row.querySelector('.site-short-input').value.trim();
    if (!name || !short) { alert('이름과 짧은 표시를 모두 입력해 주세요.'); return; }
    const pwd = adminPassword();
    if (!pwd) { needPassword(); return; }
    button.disabled = true;
    try {
        const data = await postJSON('/api/site', { site: site, name: name, short: short, password: pwd });
        if (!data.success) { if (data.message) alert(data.message); return; }
        await loadState();
        renderSettings();
        alert(data.message);
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
    } finally {
        button.disabled = false;
    }
}

function renderCategorySettings() {
    const boards = app.state.boards || [];
    document.getElementById('settings-categories').innerHTML = boards.length ? boards.map(b => {
        const status = CATEGORY_STATUS[b.status] || CATEGORY_STATUS.pending;
        // 확인은 됐지만 등록한 키워드가 없으면 실제로 수집하는 글은 없음
        const label = b.status === 'ok' && !b.keyword_count ? '확인됨' : status.label;
        const usage = b.keyword_count
            ? `키워드 ${b.keyword_count}개${b.groups.length ? ` (${b.groups.map(esc).join(', ')})` : ''}`
            : '키워드 없음';
        return `
        <div class="group-row">
            <div class="group-row-main">
                <span class="group-row-name">${siteTag(b.site)}${esc(b.name)} <span class="cat-status ${status.cls}">${label}</span></span>
                <span class="group-row-members">${esc(b.key)} · ${usage}</span>
                ${b.status === 'invalid' && b.message ? `<span class="cat-message">${esc(b.message)}</span>` : ''}
            </div>
            ${b.status === 'invalid' ? `<button class="btn btn-outline btn-small" data-action="recheck-category" data-key="${esc(b.key)}">다시 확인</button>` : ''}
            <button class="btn btn-outline btn-small" data-action="rename-category" data-key="${esc(b.key)}">이름</button>
            <button class="btn btn-outline btn-small btn-danger" data-action="delete-category" data-key="${esc(b.key)}">삭제</button>
        </div>`;
    }).join('') : '<span class="settings-hint">등록된 카테고리가 없습니다.</span>';
}

async function categoryRequest(body, button) {
    const pwd = adminPassword();
    if (!pwd) { needPassword(); return false; }
    button.disabled = true;
    try {
        const data = await postJSON('/api/category', { ...body, password: pwd });
        if (!data.success) { if (data.message) alert(data.message); return false; }
        await loadState();
        renderSettings();
        return data;
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
        return false;
    } finally {
        button.disabled = false;
    }
}

async function addCategory(button) {
    const input = document.getElementById('category-input');
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    const data = await categoryRequest({ action: 'create', input: value }, button);
    if (data) {
        input.value = '';
        alert(data.message);
    }
}

// ---------- 묶음 (사이드바에서 게시판을 묶어 보여 줌) ----------
function renderFolderSettings() {
    const folders = app.state.folders || [];
    const groups = app.state.groups || [];
    document.getElementById('settings-folders').innerHTML = folders.length ? folders.map((f, i) => {
        const names = groups.filter(g => g.folder_id === f.id).map(g => esc(g.name));
        return `
        <div class="group-row">
            <div class="group-row-main">
                <span class="group-row-name">${esc(f.name)}</span>
                <span class="group-row-members">${names.length ? names.join(' · ') : '(비어 있음 · 사이드바에 보이지 않음)'}</span>
            </div>
            <button class="icon-btn small" data-action="move-folder" data-folder-id="${f.id}" data-direction="up" aria-label="${esc(f.name)} 묶음 위로" ${i === 0 ? 'disabled' : ''}>${ICONS.up}</button>
            <button class="icon-btn small" data-action="move-folder" data-folder-id="${f.id}" data-direction="down" aria-label="${esc(f.name)} 묶음 아래로" ${i === folders.length - 1 ? 'disabled' : ''}>${ICONS.down}</button>
            <button class="btn btn-outline btn-small" data-action="rename-folder" data-folder-id="${f.id}">이름</button>
            <button class="btn btn-outline btn-small btn-danger" data-action="delete-folder" data-folder-id="${f.id}">삭제</button>
        </div>`;
    }).join('') : '<span class="settings-hint">만든 묶음이 없습니다. 게시판은 사이드바에 묶음 없이 보입니다.</span>';
}

// 묶음·게시판 배치 요청 (관리자 암호 필요). 성공하면 상태를 다시 받아 사이드바와 관리 화면을 그림
async function adminRequest(url, body, button) {
    const pwd = adminPassword();
    if (!pwd) { needPassword(); return null; }
    if (button) button.disabled = true;
    try {
        const data = await postJSON(url, { ...body, password: pwd });
        if (!data.success) { if (data.message) alert(data.message); return null; }
        await loadState();
        renderSettings();
        return data;
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
        return null;
    } finally {
        if (button) button.disabled = false;
    }
}
function folderRequest(body, button) { return adminRequest('/api/folder', body, button); }
function arrangeGroup(body, control) { return adminRequest('/api/group', { action: 'arrange', ...body }, control); }

async function addFolder(button) {
    const input = document.getElementById('folder-name-input');
    const name = input.value.trim();
    if (!name) { input.focus(); return; }
    if (await folderRequest({ action: 'create', name: name }, button)) input.value = '';
}

async function renameFolder(folderId, button) {
    const folder = (app.state.folders || []).find(f => f.id === folderId);
    if (!folder) return;
    const name = prompt(`'${folder.name}' 묶음의 새 이름`, folder.name);
    if (name === null || !name.trim() || name.trim() === folder.name) return;
    await folderRequest({ action: 'rename', id: folderId, name: name.trim() }, button);
}

async function deleteFolder(folderId, button) {
    const folder = (app.state.folders || []).find(f => f.id === folderId);
    if (!folder || !confirm(`'${folder.name}' 묶음을 삭제할까요? 안에 있던 게시판은 지워지지 않고 묶음 없이 남습니다.`)) return;
    await folderRequest({ action: 'delete', id: folderId }, button);
}

async function renameCategory(key, button) {
    const board = app.state.boards.find(b => b.key === key);
    if (!board) return;
    const name = prompt(`'${board.name}' 카테고리의 새 이름`, board.name);
    if (name === null || !name.trim() || name.trim() === board.name) return;
    await categoryRequest({ action: 'rename', key: key, name: name.trim() }, button);
}

async function deleteCategory(key, button) {
    const board = app.state.boards.find(b => b.key === key);
    if (!board) return;
    // 키워드가 등록된 카테고리는 서버에서도 거부함 (지우면 그 키워드를 쓰는 게시판을 고칠 수 없게 됨)
    if (board.keyword_count) {
        alert(`키워드가 등록되어 있어 삭제할 수 없습니다.${board.groups.length ? `\n(${board.groups.join(', ')} 게시판에서 이 카테고리 키워드를 먼저 빼 주세요)` : ''}`);
        return;
    }
    if (!confirm(`'${board.name}' 카테고리를 삭제할까요?`)) return;
    await categoryRequest({ action: 'delete', key: key }, button);
}

// ---------- 수집 상태 (수집 주기·차단 의심·크롬·백업·최근 경고) ----------
function parseServerTime(ts) {
    return ts ? new Date(ts.replace(' ', 'T')) : null;
}

function agoText(ts, now) {
    const t = parseServerTime(ts);
    if (!t) return '';
    const minutes = Math.floor((parseServerTime(now) - t) / 60000);
    if (minutes < 1) return '방금';
    if (minutes < 60) return `${minutes}분 전`;
    if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}시간 전`;
    return `${Math.floor(minutes / 60 / 24)}일 전`;
}

function renderRuntimeStatus(s) {
    const hm = ts => esc((ts || '').slice(11, 16));
    const row = (label, value) => `<div class="status-row"><span class="status-label">${label}</span><span class="status-value">${value}</span></div>`;
    const c = s.last_cycle;
    const rows = [
        // started_at이 없으면 웹서버가 수집기 상태를 받지 못한 것 (수집기 컨테이너가 시작 전이거나 멈춤)
        row('상태', !s.started_at
            ? '<span class="status-warn">수집기 상태 없음</span> (수집기가 시작 중이거나 멈춤)'
            : s.stalled_minutes
            ? `<span class="status-warn">멈춤 의심 · ${s.stalled_minutes}분째 진행 없음</span> (텔레그램으로 알림)`
            : s.block_streak
            ? `<span class="status-warn">차단 의심 · 연속 ${s.block_streak}회</span> (다음 확인 ${hm(s.next_check_at)})`
            : '<span class="status-ok">정상 수집 중</span>'),
        row('마지막 수집', c
            ? `${hm(c.finished_at)} (${agoText(c.finished_at, s.now)}) · ${c.seconds}초 · 새 글 ${c.new}, 갱신 ${c.updated}, 오류 ${c.errors}`
            : '아직 없음 (시작 직후)'),
        row('실행', s.started_at ? `${hm(s.started_at)}부터 (${agoText(s.started_at, s.now)}) · 주기 ${s.cycles}회` : '-'),
        row('크롬', s.chrome_started_at ? `${hm(s.chrome_started_at)} 시작 · 재시작 ${s.chrome_restarts}회` : '-'),
        row('DB 백업', s.last_backup ? `${esc(s.last_backup.file)} (${hm(s.last_backup.at)})` : '오늘 백업 있음 또는 아직 안 함'),
        row('오래된 글 정리', s.last_prune ? `${s.last_prune.deleted}건 정리 (${hm(s.last_prune.at)})` : '-')
    ];
    const problems = (s.recent_problems || []).slice(0, 5);
    const problemList = problems.length
        ? `<ul class="status-problems">${problems.map(p => `<li><span class="status-time">${esc(p.time.slice(5, 16))}</span>${esc(p.message)}</li>`).join('')}</ul>`
        : '<span class="settings-hint">최근 경고·오류 없음</span>';
    document.getElementById('settings-status').innerHTML = rows.join('') +
        `<div class="status-row status-row-block"><span class="status-label">최근 경고·오류</span>${problemList}</div>`;
}

async function loadRuntimeStatus() {
    const box = document.getElementById('settings-status');
    try {
        renderRuntimeStatus(await getJSON('/api/status'));
    } catch (e) {
        box.innerHTML = '<span class="settings-hint">수집 상태를 불러오지 못했습니다.</span>';
    }
}

function setSettingsOpen(open) {
    const panel = document.getElementById('settings');
    panel.hidden = !open;
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
        // 관리 화면은 관리자로 로그인한 기기에서만
        if (!adminPassword()) { panel.hidden = true; document.body.style.overflow = ''; openLogin(); return; }
        renderSettings();
        setSettingsTab(app.settingsTab || 'groups');
    }
}

// 관리 화면 탭: 고른 칸만 보여 주고, 수집 상태는 그 탭을 열 때 새로 받아 옴
function setSettingsTab(tab) {
    app.settingsTab = tab;
    document.querySelectorAll('.settings-tab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
    document.querySelectorAll('.settings-pane').forEach(p => { p.hidden = p.dataset.pane !== tab; });
    document.querySelector('.settings-body').scrollTop = 0;
    if (tab === 'status') loadRuntimeStatus();
}

// 게시판 탭의 편집 양식 열기 (새 게시판). 사이드바 '+'에서 부르면 관리 화면부터 엶
function openNewGroupForm() {
    if (!adminPassword()) { openLogin(); return; }
    if (document.getElementById('settings').hidden) setSettingsOpen(true);
    setSettingsTab('groups');
    resetGroupForm();
    app.groupFormOpen = true;
    renderGroupSettings();
    document.getElementById('group-name-input').focus();
}

// ---------- 관리자 로그인 ----------
// 암호로 한 번 로그인하면 서버가 준 로그인 키를 이 기기(localStorage)에 기억해 다시 묻지 않고, 관리 요청에 암호 대신 보냄.
// 로그인 전에는 관리 버튼·게시판 만들기(+) 대신 자물쇠 버튼만 보임 (body.is-admin)
const ADMIN_TOKEN_KEY = 'admin_token';
function adminPassword() {
    return storageGet(localStorage, ADMIN_TOKEN_KEY, '');
}

function updateAdminUI() {
    document.body.classList.toggle('is-admin', !!adminPassword());
}

function openLogin(message) {
    const box = document.getElementById('login');
    box.hidden = false;
    const error = document.getElementById('login-error');
    error.textContent = message || '';
    error.hidden = !message;
    const input = document.getElementById('admin-pwd-input');
    input.value = '';
    input.focus();
}

function closeLogin() {
    document.getElementById('login').hidden = true;
}

async function submitLogin() {
    const input = document.getElementById('admin-pwd-input');
    const error = document.getElementById('login-error');
    const button = document.getElementById('login-submit');
    if (!input.value.trim()) { input.focus(); return; }
    button.disabled = true;
    try {
        const res = await fetch('/api/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify({ password: input.value })
        });
        const data = await res.json();
        if (!data.success) {
            error.textContent = data.message.replace(/^❌\s*/, '');
            error.hidden = false;
            input.select();
            return;
        }
        storageSet(localStorage, ADMIN_TOKEN_KEY, data.token);
        input.value = '';
        closeLogin();
        updateAdminUI();
        setSettingsOpen(true);
    } catch (e) {
        error.textContent = '요청 중 오류가 발생했습니다.';
        error.hidden = false;
    } finally {
        button.disabled = false;
    }
}

function logout() {
    storageRemove(localStorage, ADMIN_TOKEN_KEY);
    setSettingsOpen(false);
    updateAdminUI();
}

// 기억한 로그인 키가 없거나 더는 맞지 않을 때(서버 암호를 바꿈 등): 로그아웃하고 로그인 창을 띄움
function needPassword(message) {
    logout();
    openLogin(message || '관리자 암호를 입력해 주세요.');
}

async function toggleGroupAlert(checkbox) {
    const pwd = adminPassword();
    const target = checkbox.checked;
    if (!pwd) {
        checkbox.checked = !target;
        needPassword();
        return;
    }
    const groupId = Number(checkbox.dataset.groupId);
    const type = checkbox.dataset.type;
    try {
        const data = await postJSON('/api/toggle-alert', { group: groupId, type: type, enabled: target, password: pwd });
        const group = (app.state.groups || []).find(g => g.id === groupId);
        if (data.success) {
            if (type === 'saved_comment') app.state.saved_comment_alert = target;
            else if (group) group[type] = target;
            renderNavigation();
        } else {
            if (data.message) alert(data.message);
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
    setState(await withProgress(getJSON('/api/state')));
    renderStatus(true);
    if (!isKnownView(app.activeKey)) {
        app.activeKey = ALL_KEY;
        app.filter = defaultFilter(ALL_KEY);
        app.page = 1;
    }
    renderNavigation();
    await loadPosts();
}

async function refreshCurrent() {
    try {
        // 새로고침하면 안 읽은 글 보기에서 이미 읽은 글은 빠짐
        app.unreadSince = null;
        app.commentIds = null;
        await loadState();
    } catch (e) {
        renderStatus(false);
    }
}

async function handlePostAnchor() {
    const match = /^#post-(\d+|dc-[a-z0-9_]+-\d+)$/.exec(window.location.hash);
    if (!match) {
        // 모아보기에서 글로 이동한 뒤 브라우저 '뒤로'를 누르면 모아보기로
        if (!window.location.hash && app.galleryReturn) returnToGallery();
        return false;
    }
    const postId = match[1];
    let loc;
    try {
        loc = await getJSON('/api/locate?id=' + encodeURIComponent(postId));
    } catch (e) {
        return false;
    }
    if (!loc.found) {
        window.location.replace(originalUrl(postId));
        return true;
    }
    const key = loc.group ? 'group:' + loc.group : ALL_KEY;
    app.filter = 'all';  // 글 위치(페이지)는 그 게시판의 모든 글·최신순 기준
    app.sort = 'latest';
    app.highlightPostId = postId;
    openView(key, loc.page);
    return true;
}

async function init() {
    updateAdminUI();
    app.sort = storageGet(localStorage, SORT_STORAGE_KEY, 'latest');
    app.openPostIds = new Set();
    if (storageGet(localStorage, KEYS_STORAGE_KEY, '0') === '1') {
        const guide = document.getElementById('shortcut-guide');
        guide.classList.add('is-closed');
        guide.querySelector('.keys-toggle').setAttribute('aria-expanded', 'false');
    }
    let savedTab = storageGet(sessionStorage, 'last_active_tab', null);
    let savedFilter = storageGet(sessionStorage, 'last_active_filter', null);
    // 예전 버전의 '안 읽은 글'·'새 댓글' 탭은 전체 게시판의 해당 보기로
    if (savedTab === '__unread__' || savedTab === '__comments__') {
        savedFilter = savedTab === '__unread__' ? 'unread' : 'comments';
        savedTab = ALL_KEY;
    }
    // 예전 버전이 저장한 페이지 번호는 더 쓰지 않음
    storageRemove(sessionStorage, 'last_active_page');
    // 예전 버전이 저장한 '지난 화면' 캐시 정리
    storageRemove(localStorage, 'state_cache_v1');
    storageRemove(localStorage, 'feed_cache_v1');
    await migrateLegacyReads();
    try {
        setState(await withProgress(getJSON('/api/state')));
    } catch (e) {
        renderStatus(false);
        document.getElementById('feed').innerHTML = '<div class="empty-card">서버에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.</div>';
        return;
    }
    renderStatus(true);
    setInterval(pollState, POLL_INTERVAL_MS);
    // 텔레그램 알림 링크(#post-ID)로 들어온 경우 해당 글이 있는 탭/페이지로 바로 이동
    if (await handlePostAnchor()) return;
    // 같은 탭에서 새로고침하면 보던 게시판·보기의 첫 페이지,
    // 새로 들어오면 첫 화면(전체 게시판의 기본 보기: 안 읽은 글 → 새 댓글 → 모든 글)
    if (isKnownView(savedTab)) {
        app.activeKey = savedTab;
        app.filter = isKnownFilter(savedFilter) ? savedFilter : 'all';
    } else {
        app.activeKey = ALL_KEY;
        app.filter = defaultFilter(ALL_KEY);
    }
    app.page = 1;
    app.unreadSince = null;
    // 글 목록까지 받은 뒤 게시판 목록과 함께 한 번에 표시 (그때까지는 뼈대 화면)
    await loadPosts();
    renderNavigation();
    scrollActiveChipIntoView();
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

// SNS 게시물 화면(iframe)은 내용 높이를 메시지로 알려 주므로, 그 높이로 맞춰 안쪽 세로 스크롤 없이 전부 보이게 함
// (원래는 인스타그램 embed.js·X widgets.js가 하는 일이지만 외부 스크립트는 넣지 않음)
// - 인스타그램: {type: 'MEASURE', details: {height}}
// - X(트위터): {"twttr.embed": {method: 'twttr.private.resize', params: [{height, width}]}}
const SNS_EMBEDS = [
    { origin: /^https:\/\/(www\.)?instagram\.com$/, selector: 'iframe[src*="instagram.com"]',
      height: data => data?.type === 'MEASURE' && data.details?.height },
    { origin: /^https:\/\/platform\.twitter\.com$/, selector: 'iframe[src*="platform.twitter.com/embed"]',
      height: data => data?.['twttr.embed']?.method === 'twttr.private.resize' && data['twttr.embed'].params?.[0]?.height }
];
window.addEventListener('message', (e) => {
    const embed = SNS_EMBEDS.find(s => s.origin.test(e.origin));
    if (!embed) return;
    let data;
    try { data = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; } catch { return; }
    const height = Number(embed.height(data));
    if (!(height > 0)) return;
    const iframe = [...document.querySelectorAll(`.post-content ${embed.selector}`)]
        .find(f => f.contentWindow === e.source);
    if (iframe) iframe.style.setProperty('height', `${Math.ceil(height)}px`, 'important');
});

document.addEventListener('click', (e) => {
    if (handleVideoClick(e)) return;
    if (toggleCardFold(e)) return;
    // 크게 보기 창의 어두운 바깥을 누르면 닫음
    if (e.target.id === 'media-viewer' || e.target.classList.contains('mv-stage')) { closeMedia(); return; }
    // 페이지 목록 바깥을 누르면 닫음
    closePageMenus(e.target.closest('.page-menu'));
    closeViewMore(e.target.closest('[data-action="toggle-view-more"]') && e.target.closest('.view-more'));
    // 공유 목록 바깥을 누르면 닫음 (텔레그램 링크는 열린 뒤 닫음: 누르는 중에 지우면 링크가 열리지 않을 수 있음)
    closeShareMenus(e.target.closest('.share-wrap'));
    if (e.target.closest('.share-menu a')) setTimeout(() => closeShareMenus(), 0);
    const backdrop = document.getElementById('settings');
    if (e.target === backdrop) { setSettingsOpen(false); return; }
    if (e.target.id === 'login') { closeLogin(); return; }
    const el = e.target.closest('[data-action]');
    if (!el || el.tagName === 'INPUT') return;
    const action = el.dataset.action;
    if (action === 'open-media') {
        openMedia(Number(el.dataset.index));
    } else if (action === 'media-step') {
        openMedia(app.mediaIndex + Number(el.dataset.step));
    } else if (action === 'close-media') {
        closeMedia();
    } else if (action === 'goto-post') {
        gotoPostFromGallery(el.dataset.postId);
    } else if (action === 'return-gallery') {
        returnToGallery();
    } else if (action === 'go-home') {
        e.preventDefault();
        goHome();
    } else if (action === 'open-all') {
        openBoard(ALL_KEY);
    } else if (action === 'set-view') {
        setFilter(el.dataset.filter);
    } else if (action === 'open-group') {
        openBoard('group:' + el.dataset.groupId);
    } else if (action === 'save-group') {
        saveGroup(el);
    } else if (action === 'add-draft-merge') {
        addDraftMerge();
    } else if (action === 'edit-group') {
        app.mergeDraft = [];
        app.editingGroupId = Number(el.dataset.groupId);
        app.groupDraft = undefined;
        app.groupNameDraft = undefined;
        renderGroupSettings();
        document.querySelector('.settings-body').scrollTop = 0;
        document.getElementById('group-name-input').focus();
    } else if (action === 'new-group') {
        openNewGroupForm();
    } else if (action === 'settings-tab') {
        setSettingsTab(el.dataset.tab);
    } else if (action === 'add-draft-keyword') {
        addDraftKeyword();
    } else if (action === 'toggle-draft-pause') {
        const entry = app.draftEntries[Number(el.dataset.index)];
        const paused = !entry.members.every(m => m.paused);
        entry.members.forEach(m => { m.paused = paused; });
        renderGroupSettings();
    } else if (action === 'toggle-draft-board') {
        toggleDraftBoard(el.dataset.board);
    } else if (action === 'share-post') {
        sharePost(el);
    } else if (action === 'copy-post-link') {
        copyPostLink(el.dataset.postId);
    } else if (action === 'toggle-saved') {
        toggleSaved(el);
    } else if (action === 'remove-draft-keyword') {
        const entry = app.draftEntries[Number(el.dataset.index)];
        app.groupDraft = app.groupDraft.filter(m => !entry.members.includes(m));
        renderGroupSettings();
    } else if (action === 'add-draft-ignore') {
        addDraftIgnore();
    } else if (action === 'remove-draft-ignore') {
        const entry = app.draftEntries[Number(el.dataset.index)];
        const phrase = normPhrase(entryIgnores(entry)[Number(el.dataset.phraseIndex)]);
        entry.members.forEach(m => { m.ignores = m.ignores.filter(p => normPhrase(p) !== phrase); });
        renderGroupSettings();
    } else if (action === 'cancel-group-edit') {
        resetGroupForm();
    } else if (action === 'delete-group') {
        deleteGroup(Number(el.dataset.groupId), el);
    } else if (action === 'add-category') {
        addCategory(el);
    } else if (action === 'rename-category') {
        renameCategory(el.dataset.key, el);
    } else if (action === 'recheck-category') {
        categoryRequest({ action: 'recheck', key: el.dataset.key }, el);
    } else if (action === 'delete-category') {
        deleteCategory(el.dataset.key, el);
    } else if (action === 'page') {
        changePage(el.dataset.target);
    } else if (action === 'toggle-view-more') {
        const box = el.closest('.view-more');
        setViewMoreOpen(box, box.querySelector('.view-more-list').hidden);
    } else if (action === 'toggle-page-menu') {
        const menu = el.closest('.page-menu');
        setPageMenuOpen(menu, menu.querySelector('.page-menu-list').hidden);
    } else if (action === 'pick-page') {
        closePageMenus();
        changePage(el.dataset.page);
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
    } else if (action === 'refresh-status') {
        loadRuntimeStatus();
    } else if (action === 'open-login') {
        openLogin();
    } else if (action === 'close-login') {
        closeLogin();
    } else if (action === 'logout') {
        logout();
    } else if (action === 'close-settings') {
        setSettingsOpen(false);
    } else if (action === 'refresh') {
        refreshCurrent();
    } else if (action === 'scroll-top') {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (action === 'open-post-media') {
        openPostMedia(el.dataset.postId, Number(el.dataset.index));
    } else if (action === 'more-thumbs') {
        toggleMoreThumbs(el);
    } else if (action === 'toggle-fold') {
        toggleFold();
    } else if (action === 'toggle-keys') {
        toggleShortcutGuide();
    } else if (action === 'next-post') {
        goNextPost();
    } else if (action === 'save-site') {
        saveSite(el.dataset.site, el);
    } else if (action === 'open-folder') {
        openBoard('folder:' + el.dataset.folderId);
    } else if (action === 'toggle-folder') {
        toggleFolderExpanded(el.dataset.scope, Number(el.dataset.folderId));
    } else if (action === 'add-folder') {
        addFolder(el);
    } else if (action === 'rename-folder') {
        renameFolder(Number(el.dataset.folderId), el);
    } else if (action === 'delete-folder') {
        deleteFolder(Number(el.dataset.folderId), el);
    } else if (action === 'move-folder') {
        folderRequest({ action: 'move', id: Number(el.dataset.folderId), direction: el.dataset.direction }, el);
    } else if (action === 'move-group') {
        arrangeGroup({ id: Number(el.dataset.groupId), direction: el.dataset.direction }, el);
    }
});

document.addEventListener('change', (e) => {
    if (e.target.dataset.action === 'toggle-alert') toggleGroupAlert(e.target);
    else if (e.target.dataset.action === 'set-group-folder') {
        const value = e.target.value;
        arrangeGroup({ id: Number(e.target.dataset.groupId), folder_id: value ? Number(value) : null }, e.target);
    }
    else if (e.target.dataset.action === 'go-page') changePage(e.target.value);
    else if (e.target.dataset.action === 'set-sort') setSort(e.target.value);
});

document.addEventListener('input', (e) => {
    if (e.target.id === 'group-name-input') app.groupNameDraft = e.target.value;
});

document.addEventListener('submit', (e) => {
    if (e.target.id === 'login-form') {
        e.preventDefault();
        submitLogin();
    } else if (e.target.id === 'search-form') {
        e.preventDefault();
        runSearch(document.getElementById('search-input').value);
        document.getElementById('search-input').blur();
    }
});

// 모아보기·크게 보기의 이전(-1)·다음(1) 키: 좌우 화살표 또는 A·D (Ctrl·Alt 등을 함께 누르면 아님)
function mediaStep(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return 0;
    return { ArrowLeft: -1, ArrowRight: 1, a: -1, d: 1 }[e.key.length === 1 ? e.key.toLowerCase() : e.key] || 0;
}

document.addEventListener('keydown', (e) => {
    const viewer = document.getElementById('media-viewer');
    if (viewer && !viewer.hidden) {
        // 크게 보기 중에는 좌우 화살표(또는 A·D)로 넘기고 Esc로 닫음 (F 등 다른 단축키는 쓰지 않음)
        const step = mediaStep(e);
        if (e.key === 'Escape') closeMedia();
        else if (step) openMedia(app.mediaIndex + step);
        else return;
        e.preventDefault();
        return;
    }
    if (e.key === 'Enter' && e.target.id === 'group-kw-input') {
        e.preventDefault();
        addDraftKeyword();
    } else if (e.key === 'Enter' && e.target.id === 'group-ignore-input') {
        e.preventDefault();
        addDraftIgnore();
    } else if (e.key === 'Enter' && e.target.id === 'category-input') {
        e.preventDefault();
        addCategory(document.querySelector('[data-action="add-category"]'));
    } else if (e.key === 'Escape' && document.querySelector('.page-menu-list:not([hidden])')) {
        closePageMenus();
    } else if (e.key === 'Escape' && document.querySelector('.share-menu')) {
        closeShareMenus();
    } else if (e.key === 'Escape' && document.querySelector('.view-more-list:not([hidden])')) {
        closeViewMore();
    } else if (e.key === 'Escape' && !document.getElementById('login').hidden) {
        closeLogin();
    } else if (e.key === 'Escape' && !document.getElementById('settings').hidden) {
        setSettingsOpen(false);
    } else if (e.key === 'Escape' && e.target.id === 'search-input' && app.searchQuery) {
        clearSearch();
    } else if (mediaStep(e) && isGalleryView()
               && !e.target.closest('input, textarea, select, [contenteditable]') && document.getElementById('settings').hidden
               && document.getElementById('login').hidden) {
        // 모아보기에서는 크게 보기와 같은 키(좌우 화살표 또는 A·D)로 이전·다음 페이지
        const next = mediaStep(e) > 0;
        if (next ? app.page < app.totalPages : app.page > 1) changePage(next ? 'next' : 'prev');
    } else if (['f', 'j', 'g'].includes(e.key.toLowerCase()) && !e.ctrlKey && !e.metaKey && !e.altKey
               && !e.target.closest('input, textarea, select, [contenteditable]')
               && document.getElementById('settings').hidden && document.getElementById('login').hidden && !isGalleryView()) {
        // 입력 중이거나 관리 화면이 열려 있지 않을 때만: F(예전 J도 그대로) 다음 글, G 본문·댓글 전부 접기/펼치기
        if (e.key.toLowerCase() === 'g') toggleFold();
        else goNextPost();
    }
});

// 페이지를 떠나거나 백그라운드로 갈 때 남은 읽음 기록 전송, 다시 보일 때 바로 새 글 확인
window.addEventListener('pagehide', () => flushReads(true));
document.addEventListener('visibilitychange', () => {
    if (document.hidden) flushReads(true);
    else pollState();
});

window.addEventListener('hashchange', handlePostAnchor);

// 모바일: 아래로 내리면 맨 위 제목 줄(홈·검색·관리)만 숨기고, 조금이라도 위로 올리거나 맨 위 근처면 다시 보임.
// 손 떨림 같은 작은 움직임에 깜빡이지 않도록 마지막으로 바꾼 위치에서 일정 거리 이상 움직였을 때만 바꿈
const TITLE_ROW_SCROLL_STEP = 10;
let titleRowScrollY = 0;
function updateTitleRow() {
    const topbar = document.querySelector('.topbar');
    const row = topbar.querySelector('.topbar-row');
    const y = window.scrollY;
    const keepShown = !window.matchMedia('(max-width: 899px)').matches || y < row.offsetHeight
        || topbar.classList.contains('search-open') || !document.getElementById('settings').hidden;
    if (keepShown) {
        topbar.classList.remove('title-hidden');
        titleRowScrollY = y;
        return;
    }
    if (Math.abs(y - titleRowScrollY) < TITLE_ROW_SCROLL_STEP) return;
    topbar.style.setProperty('--title-row-h', row.offsetHeight + 'px');
    topbar.classList.toggle('title-hidden', y > titleRowScrollY);
    titleRowScrollY = y;
}

window.addEventListener('scroll', () => {
    document.getElementById('floating-top-btn').classList.toggle('visible', window.scrollY > 400);
    updateTitleRow();
    scheduleReadCheck();
}, { passive: true });
window.addEventListener('resize', () => { updateTitleRow(); scheduleReadCheck(); }, { passive: true });
// 댓글 칸 안의 스크롤은 창으로 전달되지 않으므로 캡처 단계에서 받아 새 댓글 확인 (넓은 화면)
document.addEventListener('scroll', e => {
    if (e.target !== document && e.target.classList && e.target.classList.contains('comments')) scheduleReadCheck();
}, { passive: true, capture: true });

document.addEventListener('DOMContentLoaded', init);
