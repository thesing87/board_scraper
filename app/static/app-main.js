'use strict';

// 키워드 게시판 화면 (app-main.js): 전체 상태 로드, 이벤트 연결, 시작.
// 한 화면의 스크립트를 순서대로 나눈 파일 중 하나 (app.js, app-feed.js, app-view.js, app-admin.js, app-main.js). 전역 이름을 함께 씀

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
    // 공유받은 게시판·묶음 주소(#board-게시판ID, #folder-묶음ID): 그 게시판의 기본 보기로 엶. 없는 게시판이면 전체로
    const boardLink = /^#(board|folder)-(\d+)$/.exec(window.location.hash);
    if (boardLink && app.state) {
        history.replaceState(history.state, '', window.location.pathname);
        const key = (boardLink[1] === 'board' ? 'group:' : 'folder:') + boardLink[2];
        app.galleryReturn = null;
        if (isKnownView(key)) openBoard(key);
        else openBoard(ALL_KEY);
        return true;
    }
    // 대시보드의 게시판별 인기글 카드(#popular)로 들어오면 전체 게시판의 인기글 보기 (기간은 오늘)
    if (window.location.hash === '#popular') {
        history.replaceState(history.state, '', window.location.pathname);
        storageSet(localStorage, POPULAR_DAYS_KEY, '1');
        app.filter = 'popular';
        app.galleryReturn = null;
        openView(ALL_KEY, 1);
        return true;
    }
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

// 상단 바 높이(메뉴 줄 포함)를 CSS 변수로: 왼쪽 게시판 목록·댓글 칸·모아보기 높이가 이 아래에 맞춰짐
function trackTopbarHeight() {
    const topbar = document.querySelector('.topbar');
    const update = () => document.documentElement.style.setProperty('--topbar-h', topbar.offsetHeight + 'px');
    update();
    new ResizeObserver(update).observe(topbar);
}

async function init() {
    trackTopbarHeight();
    // 위쪽 바로가기 메뉴의 게시판·인기글은 페이지를 다시 읽지 않고 이 화면에서 보기만 바꿈
    // (다시 읽으면 마지막에 보던 보기로 열려, 인기글 보기에서 '게시판'을 눌러도 인기글이 다시 열렸음)
    if (window.siteNav) {
        window.siteNav.onSamePage = key => {
            if (!document.getElementById('settings').hidden) setSettingsOpen(false);
            app.searchQuery = '';
            if (key === 'popular') {
                app.filter = 'popular';
                app.galleryReturn = null;
                openView(ALL_KEY, 1);
            } else {
                goHome();
            }
        };
    }
    updateAdminUI();
    applyFontSize();
    applyTheme();
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
    // 대시보드의 게시판 칩(#board-게시판ID)으로 들어오면 그 게시판의 기본 보기
    const boardAnchor = /^#board-(\d+)$/.exec(window.location.hash);
    if (boardAnchor) {
        history.replaceState(history.state, '', window.location.pathname);
        if (isKnownView('group:' + boardAnchor[1])) {
            savedTab = 'group:' + boardAnchor[1];
            savedFilter = defaultFilter(savedTab);
        }
    }
    // 위쪽 바로가기 메뉴의 '게시판'(#home)은 마지막에 보던 보기(인기글 등)가 아니라 전체 게시판의 기본 보기
    if (window.location.hash === '#home') {
        history.replaceState(history.state, '', window.location.pathname);
        savedTab = ALL_KEY;
        savedFilter = defaultFilter(ALL_KEY);
    }
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
    // 본문 사진을 누르면 크게 보기
    if (e.target.tagName === 'IMG' && e.target.closest('#feed .post-content') && openBodyImage(e.target)) {
        e.preventDefault();   // 사진을 감싼 원본 사진 링크로 이동하지 않게
        return;
    }
    // 크게 보기 창의 어두운 바깥을 누르면 닫음
    if (e.target.id === 'media-viewer' || e.target.classList.contains('mv-stage')) { closeMedia(); return; }
    // 페이지 목록 바깥을 누르면 닫음
    closePageMenus(e.target.closest('.page-menu'));
    closeViewMore(e.target.closest('[data-action="toggle-view-more"]') && e.target.closest('.view-more'));
    // 모바일 정렬·페이지 이동 목록 바깥을 누르면 닫음
    if (!e.target.closest('.feed-tools, [data-action="toggle-feed-tools"]')) {
        document.querySelectorAll('.feed-head.tools-open').forEach(head => {
            head.classList.remove('tools-open');
            head.querySelector('.feed-tools-btn')?.setAttribute('aria-expanded', 'false');
        });
    }
    // 공유 목록 바깥을 누르면 닫음
    closeShareMenus(e.target.closest('.share-wrap'));
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
    } else if (action === 'popular-days') {
        setPopularDays(Number(el.dataset.days));
    } else if (action === 'open-board-popular') {
        openBoardPopular(Number(el.dataset.groupId));
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
    } else if (action === 'share-board') {
        shareBoard();
    } else if (action === 'share-post') {
        sharePost(el);
    } else if (action === 'share-link') {
        shareLink(el.dataset.postId, el.dataset.kind);
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
    } else if (action === 'next-new-comment') {
        jumpToNextNewComment();
    } else if (action === 'comments-to-bottom') {
        scrollCommentsToBottom(el);
    } else if (action === 'activate-embed') {
        el.remove();
    } else if (action === 'comment-page') {
        const section = el.closest('.comments');
        setCommentPage(section, Number(section.dataset.page) + Number(el.dataset.step));
    } else if (action === 'expand-body') {
        expandBody(el);
    } else if (action === 'set-font-size') {
        setFontSize(el.dataset.size);
    } else if (action === 'set-theme') {
        setTheme(el.dataset.theme);
    } else if (action === 'toggle-feed-tools') {
        const head = el.closest('.feed-head');
        el.setAttribute('aria-expanded', String(head.classList.toggle('tools-open')));
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
    } else if (action === 'dismiss-new') {
        dismissNewBanner();
    } else if (action === 'toggle-search') {
        const topbar = document.querySelector('.topbar');
        topbar.classList.toggle('search-open');
        if (topbar.classList.contains('search-open')) document.getElementById('search-input').focus();
    } else if (action === 'clear-search') {
        clearSearch();
    } else if (action === 'search-scope') {
        setSearchScope(el.dataset.here === '1');
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
    else if (e.target.dataset.action === 'set-popular-min') setPopularMin(e.target);
    else if (e.target.dataset.action === 'search-days') setSearchDays(Number(e.target.value));
    else if (e.target.dataset.action === 'search-author') setSearchAuthor(e.target.value);
    else if (e.target.dataset.action === 'set-group-folder') {
        const value = e.target.value;
        arrangeGroup({ id: Number(e.target.dataset.groupId), folder_id: value ? Number(value) : null }, e.target);
    }
    else if (e.target.dataset.action === 'go-page') changePage(e.target.value);
    else if (e.target.dataset.action === 'go-comment-page') setCommentPage(e.target.closest('.comments'), Number(e.target.value));
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

// 모바일: 아래로 내리면 위 메뉴(제목 줄)와 아래 게시판 칩 줄을 숨겨 글을 넓게 보고, 조금이라도 위로 올리거나 맨 위 근처면 다시 보임.
// 보기 탭은 화면 아래 탭바에 있어 늘 보임.
// 손 떨림 같은 작은 움직임에 깜빡이지 않도록 마지막으로 바꾼 위치에서 일정 거리 이상 움직였을 때만 바꿈
const TITLE_ROW_SCROLL_STEP = 10;
let titleRowScrollY = 0;
function updateTitleRow() {
    const topbar = document.querySelector('.topbar');
    const y = window.scrollY;
    const keepShown = !isMobile() || y < topbar.offsetHeight
        || topbar.classList.contains('search-open') || !document.getElementById('settings').hidden;
    if (keepShown) {
        topbar.classList.remove('title-hidden');
        document.body.classList.remove('chips-hidden');
        titleRowScrollY = y;
        return;
    }
    if (Math.abs(y - titleRowScrollY) < TITLE_ROW_SCROLL_STEP) return;
    // 아래 그림자까지 가려지도록 조금 더 올림
    topbar.style.setProperty('--title-row-h', (topbar.offsetHeight + 4) + 'px');
    topbar.classList.toggle('title-hidden', y > titleRowScrollY);
    // 아래 게시판 칩 줄도 위 메뉴와 함께 숨기고 보임
    document.body.classList.toggle('chips-hidden', y > titleRowScrollY);
    titleRowScrollY = y;
}

// 모바일 당겨서 새로고침: 맨 위에서 손가락을 아래로 충분히 당겼다 놓으면 페이지를 다시 불러오지 않고 새 글을 받아 옴.
// 브라우저 자체의 당겨서 새로고침(페이지 전체 다시 읽기)은 CSS overscroll-behavior로 막음
const PULL_TRIGGER = 110;   // 손가락이 이만큼(px) 내려가면 놓을 때 새로고침
let pull = null;
function pullBlocked() {
    return !isMobile() || window.scrollY > 0 || !document.getElementById('settings').hidden
        || !document.getElementById('login').hidden || document.body.classList.contains('viewer-open');
}
function resetPull(indicator) {
    indicator.classList.add('is-releasing');
    indicator.classList.remove('is-ready');
    indicator.style.transform = '';
    indicator.style.opacity = '';
    setTimeout(() => indicator.classList.remove('is-releasing'), 250);
}
document.addEventListener('touchstart', e => {
    if (pull && pull.refreshing) return;
    pull = !pullBlocked() && e.touches.length === 1 ? { startY: e.touches[0].clientY, dy: 0 } : null;
}, { passive: true });
document.addEventListener('touchmove', e => {
    if (!pull || pull.refreshing) return;
    const indicator = document.getElementById('pull-refresh');
    pull.dy = e.touches[0].clientY - pull.startY;
    if (pull.dy <= 0 || window.scrollY > 0) {
        pull = null;
        resetPull(indicator);
        return;
    }
    const shift = Math.min(pull.dy * 0.5, 80);
    indicator.style.transform = `translateY(${shift - 48}px) rotate(${pull.dy * 2}deg)`;
    indicator.style.opacity = String(Math.min(1, pull.dy / PULL_TRIGGER));
    indicator.classList.toggle('is-ready', pull.dy >= PULL_TRIGGER);
}, { passive: true });
document.addEventListener('touchend', async () => {
    if (!pull || pull.refreshing) return;
    const indicator = document.getElementById('pull-refresh');
    if (pull.dy < PULL_TRIGGER) {
        pull = null;
        resetPull(indicator);
        return;
    }
    pull.refreshing = true;
    indicator.style.transform = '';
    indicator.style.opacity = '';
    indicator.classList.add('is-refreshing');
    try {
        await refreshCurrent();
    } finally {
        indicator.classList.remove('is-refreshing');
        resetPull(indicator);
        pull = null;
    }
});

window.addEventListener('scroll', () => {
    document.getElementById('floating-top-btn').classList.toggle('visible', window.scrollY > 400);
    scheduleNewCommentJump();
    updateTitleRow();
    scheduleReadCheck();
    scheduleGrowCommentBoxes();
}, { passive: true });
window.addEventListener('resize', () => { updateTitleRow(); scheduleReadCheck(); }, { passive: true });
// 댓글 칸 안의 스크롤은 창으로 전달되지 않으므로 캡처 단계에서 받아 새 댓글 확인 (넓은 화면)
document.addEventListener('scroll', e => {
    if (e.target !== document && e.target.classList && e.target.classList.contains('comments')) {
        scheduleReadCheck();
        updateCommentsBottom(e.target);
    }
}, { passive: true, capture: true });

document.addEventListener('DOMContentLoaded', init);
