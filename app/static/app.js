'use strict';

// 키워드 게시판 화면 (app.js): 상태·공용 유틸, 읽음 기록, 내비게이션.
// 한 화면의 스크립트를 순서대로 나눈 파일 중 첫 번째 (app.js, app-feed.js, app-view.js, app-admin.js, app-main.js). 전역 이름을 함께 씀

// ==========================================
// 상태 및 공용 유틸
// ==========================================
const ALL_KEY = '__all__';            // 모든 게시판을 합친 통합 피드
// 보기: 고른 게시판 안에서 어떤 글을 볼지 (하나만 고름). more: 보기 탭 끝 '더보기' 목록에 넣는 보기
const FILTERS = [
    { key: 'all', label: '모든 글' },
    { key: 'unread', label: '안 읽은 글', short: '안 읽음' },   // short: 칸이 좁은 모바일 보기 탭용
    { key: 'comments', label: '새 댓글' },
    // 게시판별 인기글 (글 목록이 아니라 게시판마다 추천+댓글이 많은 글 몇 개씩). 칸이 좁은 모바일은 '더보기' 목록에
    { key: 'popular', label: '인기글', mobileMore: true },
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
    searchHere: false,    // 검색 범위: 지금 게시판·묶음 안에서만 (아니면 모든 게시판)
    searchDays: 0,        // 검색 기간(일): 최근 그 기간에 수집한 글만. 0이면 전체 기간
    page: 1,
    totalPages: 1,
    highlightPostId: null,
    renderedTotal: null,  // 현재 화면을 그릴 때의 글 수 (새 글 배너 계산용)
    readQueue: new Set(), // 서버에 보낼 읽음 기록
    recentReads: new Map(), // 최근에 읽은 글 {글 ID: 읽은 시각(ms)} (받아 온 상태가 그보다 먼저 만들어졌을 때 다시 빼려고)
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
// 상태를 받아 오는 동안 읽은 글이 있으면, 받아 온 상태는 읽기 전에 만들어졌으므로 그 글이 안 읽은 글로 다시 들어와 있음
// (화면은 '안 읽은 글 1'인데 눌러 보면 아무 글도 없고, 다음 상태 확인 때까지 남았음). 최근에 읽은 글은 다시 빼 줌
const RECENT_READ_MS = 3 * 60 * 1000;
function setState(state) {
    app.state = state;
    Object.entries(state.sites || {}).forEach(([site, label]) => {
        if (SITES[site]) Object.assign(SITES[site], label);
    });
    const cutoff = Date.now() - RECENT_READ_MS;
    app.recentReads.forEach((at, id) => { if (at < cutoff) app.recentReads.delete(id); });
    if (app.recentReads.size) forgetUnread([...app.recentReads.keys()], ['unread']);
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
function forgetUnread(ids, kinds = ['unread', 'comment']) {
    // 서버 응답을 기다리지 않고 화면의 안 읽은 수부터 줄임
    if (!app.state) return;
    const set = new Set(ids);
    // 안 읽은 새 글 수와 새 댓글이 달린 글 수를 함께 줄임 (읽으면 그 글의 새 댓글도 확인한 것).
    // 받아 온 상태에 최근 읽은 글을 다시 뺄 때는 안 읽은 글만 (읽은 뒤에 달린 댓글은 새 댓글이 맞으므로)
    const fields = [['unread_ids', 'unread_count'], ['comment_ids', 'comment_count']].filter((_, i) => kinds.includes(['unread', 'comment'][i]));
    [...(app.state.groups || []), app.state.all, ...(app.state.folders || [])].forEach(summary => {
        fields.forEach(([idsField, countField]) => {
            if (!summary[idsField]) return;
            const before = summary[idsField].length;
            summary[idsField] = summary[idsField].filter(id => !set.has(id));
            summary[countField] = Math.max(0, summary[countField] - (before - summary[idsField].length));
        });
    });
}

function markRead(ids) {
    let added = false;
    const now = Date.now();
    ids.forEach(id => {
        app.recentReads.set(id, now);
        if (!app.readQueue.has(id)) { app.readQueue.add(id); added = true; }
    });
    if (!added) return;
    forgetUnread(ids);
    renderNavigation();
    renderFeedSub();
    clearTimeout(app.readFlushTimer);
    app.readFlushTimer = setTimeout(flushReads, 1500);
}

// 보내지 못한 읽음 기록은 다시 보낼 때까지 남겨 둠: 연결이 끊긴 경우뿐 아니라 서버가 처리하지 못한 경우(5xx 등)도.
// (서버가 DB에 쓰지 못한 동안 읽은 기록이 그냥 사라졌던 적이 있음.) 이 기기에도 저장해 두어, 새로고침·앱을 닫아도
// 다음에 열 때 다시 보냄 (migrateLegacyReads). 형식이 잘못된 요청(400)은 다시 보내도 같으므로 버림
const READ_RETRY_MS = 30 * 1000;
const PENDING_READS_MAX = 2000;
function savePendingReads() {
    if (app.readQueue.size === 0) { storageRemove(localStorage, LEGACY_READ_IDS_KEY); return; }
    storageSet(localStorage, LEGACY_READ_IDS_KEY, JSON.stringify(Array.from(app.readQueue).slice(-PENDING_READS_MAX)));
}

async function flushReads(useBeacon) {
    clearTimeout(app.readFlushTimer);
    if (app.readQueue.size === 0) return;
    const ids = Array.from(app.readQueue);
    app.readQueue.clear();
    let failed = false;
    for (let i = 0; i < ids.length; i += 400) {
        const chunk = ids.slice(i, i + 400);
        const body = JSON.stringify({ ids: chunk });
        if (useBeacon && navigator.sendBeacon) {
            // 페이지를 떠나는 중: 결과를 기다릴 수 없으므로 보내기 대기열에 넣지 못했을 때만 남겨 둠
            if (!navigator.sendBeacon('/api/read', new Blob([body], { type: 'application/json' }))) {
                chunk.forEach(id => app.readQueue.add(id));
                failed = true;
            }
            continue;
        }
        try {
            const res = await fetch('/api/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true });
            if (!res.ok && res.status !== 400) throw new Error('읽음 기록 실패 ' + res.status);
        } catch (e) {
            chunk.forEach(id => app.readQueue.add(id));  // 실패하면 다음에 다시 전송
            failed = true;
        }
    }
    savePendingReads();
    if (failed && !useBeacon) app.readFlushTimer = setTimeout(flushReads, READ_RETRY_MS);
}

async function migrateLegacyReads() {
    // 보내지 못하고 이 기기에 남겨 둔 읽음 기록(예전 버전이 저장해 둔 기록 포함)을 서버로 보냄
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
        // 모바일은 아래 보기 탭바에 가린 부분을 뺀 높이까지만 보인 것으로 봄
        const bottomEdge = viewBottom();
        let seen = el.dataset.skipped ? top >= 0 && top < bottomEdge : top < bottomEdge;
        // 새 댓글이 달린 글은 글 끝까지 내려가지 않아도 마지막 새 댓글이 화면에 다 보이면 확인한 것으로 봄
        // (이미 읽은 글에만 새 댓글이 붙으므로, 읽음 처리는 새 댓글 표시를 지우는 것뿐)
        // (댓글이 여러 페이지면 지금 보이는 페이지의 새 댓글만)
        const newComments = seen ? [] : shownComments(el.closest('.post-card'), '.comment.is-new-comment');
        if (newComments.length) {
            // 넓은 화면에서는 댓글 칸이 따로 스크롤되므로, 그 칸에서 실제로 보이는 범위 안에 들어와야 본 것
            const box = newComments[0].closest('.comments').getBoundingClientRect();
            const bottom = newComments[newComments.length - 1].getBoundingClientRect().bottom;
            seen = bottom <= Math.min(bottomEdge, box.bottom + 1) && (!el.dataset.skipped || bottom > Math.max(0, box.top));
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
    const top = topItems();
    const folderGroups = f => groups.filter(g => g.folder_id === f.id);
    // 맨 위 단계 순서대로 게시판·(빈 묶음은 빼고) 묶음을 그림
    const renderTop = (group, folder) => top.map(t => t.kind === 'group' ? group(t.item)
        : folderGroups(t.item).length ? folder(t.item) : '').join('');
    const groupLabel = g => (multiSite() ? groupTag(g) : '') + esc(g.name);
    const groupItem = g => navItem(groupLabel(g), '', g.unread_count, isActive(g),
        `data-action="open-group" data-group-id="${g.id}"`, g.comment_count);
    // 접힌 묶음은 지금 보고 있는 게시판만 남겨 어디를 보고 있는지 보이게 함
    const visibleGroups = (list, expanded) => expanded ? list : list.filter(isActive);
    const groupList = !groups.length
        ? '<span class="kw-group-name">게시판이 없습니다. 관리에서 만들어 주세요.</span>'
        : renderTop(groupItem, f => {
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
        });
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
        const inMore = f => f.more || (mobile && f.mobileMore);
        const more = FILTERS.filter(inMore);
        const picked = more.find(f => filterActive(f.key));
        return FILTERS.filter(f => !inMore(f)).map(f => `
            <button class="${cls}" ${filterAttrs(f.key)} aria-pressed="${filterActive(f.key)}">
                <span>${mobile ? f.short || f.label : f.label}</span>${tabBadge(f)}
            </button>`).join('') + `
            <span class="view-more">
                <button class="${cls} view-more-btn" data-action="toggle-view-more" aria-haspopup="true" aria-expanded="false" aria-pressed="${!!picked}">
                    <span>${picked ? picked.label : '더보기'}${ICONS.chevronDown}</span>
                </button>
                <span class="view-more-list" hidden>${more.map(f => `
                    <button class="view-more-option" ${filterAttrs(f.key)} aria-pressed="${filterActive(f.key)}">
                        <span>${f.label}</span>${f.key === 'popular' ? '' : countBadge(f.key, filterCount(current, f.key))}
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
        renderTop(groupChip, folderChips);
}

// '전체' 아래 맨 위 단계의 순서: 묶음 없는 게시판과 묶음을 한 줄로 섞어 position 순 (같으면 게시판 먼저).
// [{ kind: 'group' | 'folder', item }]
function topItems() {
    const folders = app.state.folders || [];
    const loose = (app.state.groups || []).filter(g => !folders.some(f => f.id === g.folder_id));
    return [...loose.map(g => ({ kind: 'group', item: g, order: 0 })), ...folders.map(f => ({ kind: 'folder', item: f, order: 1 }))]
        .sort((a, b) => (a.item.position || 0) - (b.item.position || 0) || a.order - b.order || a.item.id - b.item.id);
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
    app.searchQuery = ''; app.searchHere = false; app.searchDays = 0;
    document.getElementById('search-input').value = '';
    app.page = page || 1;
    renderNavigation();
    scrollActiveChipIntoView();
    return loadPosts().then(jumped => { if (!jumped) window.scrollTo({ top: 0 }); });
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
    return openView(key, 1);
}

// 홈: 검색·관리 패널·텔레그램 링크(#post-ID)를 정리하고 전체 게시판 첫 화면으로
function goHome() {
    if (!document.getElementById('settings').hidden) setSettingsOpen(false);
    document.querySelector('.topbar').classList.remove('search-open');
    if (window.location.hash) history.replaceState(null, '', window.location.pathname);
    openBoard(ALL_KEY);
}
