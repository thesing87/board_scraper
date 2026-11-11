'use strict';

// 키워드 게시판 화면 (app-view.js): 단축키 안내, 정렬·페이지, 글 목록 불러오기, 댓글 칸, 검색, 새 글 확인.
// 한 화면의 스크립트를 순서대로 나눈 파일 중 하나 (app.js, app-feed.js, app-view.js, app-admin.js, app-main.js). 전역 이름을 함께 씀

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

// ---------- 글 공유 ----------
// 공유 버튼을 누르면 무엇을 보낼지 고르는 목록: '원문 보내기'(에펨코리아·디시 원래 글 주소) 또는
// '이 글 보내기'(이 게시판 페이지에서 그 글을 여는 주소, /board/#post-글ID). 고르면 휴대폰 공유 창(navigator.share, https에서만)을 띄우고,
// 공유 창이 없는 브라우저에서는 제목과 주소를 복사
function sharePostInfo(postId, kind) {
    const card = document.getElementById('post-' + postId);
    const title = card ? card.querySelector('.post-title').textContent.trim() : '';
    // 게시판 페이지 주소(지금은 /board/) 그대로에 #post-글ID
    if (kind === 'dashboard') return { url: `${location.origin}${location.pathname}#post-${postId}`, title };
    const link = card && card.querySelector('.btn-original.top');
    const url = link && link.getAttribute('href') !== '#' ? link.href : originalUrl(postId);
    return { url, title };
}

function sharePost(button) {
    const wrap = button.closest('.share-wrap');
    const open = wrap.querySelector('.share-menu');
    closeShareMenus();
    if (open) return;  // 열려 있던 목록을 다시 누르면 닫기만
    const id = esc(button.dataset.postId);
    wrap.insertAdjacentHTML('beforeend', `
        <span class="share-menu" role="menu">
            <button class="view-more-option" role="menuitem" data-action="share-link" data-kind="original" data-post-id="${id}">
                <span>원문 보내기</span><span class="share-hint">원래 사이트 글</span></button>
            <button class="view-more-option" role="menuitem" data-action="share-link" data-kind="dashboard" data-post-id="${id}">
                <span>이 글 보내기</span><span class="share-hint">키워드 모니터에서 열기</span></button>
        </span>`);
    button.setAttribute('aria-expanded', 'true');
}

async function shareLink(postId, kind) {
    const { url, title } = sharePostInfo(postId, kind);
    closeShareMenus();
    if (navigator.share) {
        try { await navigator.share({ title, url }); } catch (e) { /* 공유 창을 닫음 */ }
        return;
    }
    showToast(await copyText(title ? `${title}\n${url}` : url) ? '링크를 복사했습니다' : '복사하지 못했습니다');
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
    if (app.searchQuery) {
        const scope = searchScope();
        const period = SEARCH_PERIODS.find(p => p.days === app.searchDays);
        return `${scope ? `'${esc(scope.name)}'에서` : '모든 게시판에서'} ${total}건`
            + (period && period.days ? ` · 최근 ${period.label}` : '') + (isPopular() ? ` · ${currentSort().label}` : '');
    }
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
    const search = `search:${app.searchQuery}|${searchScope() ? app.activeKey : ''}|${app.searchDays}`;
    return (app.searchQuery ? search : app.activeKey + '|' + app.filter) + '|' + currentSort().key;
}

// 지금 화면에 쓰는 정렬: 안 읽은 글(읽는 중 순서가 밀리지 않게)·새 댓글(최근 댓글 순) 보기는 항상 그 보기의 순서
function sortable() { return !!app.searchQuery || !['unread', 'comments', 'popular'].includes(app.filter); }
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
    if (!searching && app.filter === 'popular') return loadPopularBoards();
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
        // 범위를 지금 게시판·묶음으로 좁혔으면 그 안에서만, 기간을 골랐으면 최근 그 기간에 수집한 글만
        if (searchScope() && group) params.set('group', group.id);
        else if (searchScope()) params.set('folder', findFolder(app.activeKey).id);
        if (app.searchDays) params.set('sdays', app.searchDays);
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

// ==========================================
// 인기글 보기: 게시판마다 최근 하루·일주일·한 달 동안 추천+댓글이 많은 글 몇 개씩 (사이드바 순서, 글 없는 게시판은 뺌).
// 전체·묶음은 게시판마다 5개, 게시판 하나를 고르면 10개. 제목을 누르면 그 글로 가고 '인기글 모아보기로'로 돌아옴
// ==========================================
const POPULAR_PERIODS = [{ days: 1, label: '오늘' }, { days: 7, label: '일주일' }, { days: 30, label: '한 달' }];
const POPULAR_DAYS_KEY = 'popular_days';
function popularDays() {
    const days = Number(storageGet(localStorage, POPULAR_DAYS_KEY, '1'));
    return POPULAR_PERIODS.some(p => p.days === days) ? days : 1;
}
function setPopularDays(days) {
    if (!POPULAR_PERIODS.some(p => p.days === days)) return;
    storageSet(localStorage, POPULAR_DAYS_KEY, String(days));
    loadPosts();
}

async function loadPopularBoards() {
    const feed = document.getElementById('feed');
    const group = findGroup(app.activeKey);
    const folder = findFolder(app.activeKey);
    const viewKey = currentViewKey();
    const days = popularDays();
    const params = new URLSearchParams({ days, limit: group ? 10 : 5 });
    if (group) params.set('group', group.id);
    else if (folder) params.set('folder', folder.id);
    let data;
    try {
        await flushReads();
        data = await withProgress(getJSON('/api/popular?' + params.toString()));
    } catch (e) {
        feed.innerHTML = '<div class="empty-card">인기글을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>';
        return;
    }
    if (viewKey !== currentViewKey() || days !== popularDays()) return false;
    renderPopularBoards(data, group, folder);
    return false;
}

function renderPopularBoards(data, group, folder) {
    const feed = document.getElementById('feed');
    feed.removeAttribute('aria-busy');
    // 글 목록 화면의 상태(페이지·새 글 배너·모아보기)는 쓰지 않음
    app.page = 1;
    app.totalPages = 1;
    app.renderedTotal = null;
    app.renderedPostTotal = 0;
    app.renderedUnreadIds = null;
    app.galleryRange = null;
    app.openPostIds = new Set();
    document.body.classList.remove('gallery-mode');
    storageSet(sessionStorage, 'last_active_tab', app.activeKey);
    storageSet(sessionStorage, 'last_active_filter', app.filter);

    const days = popularDays();
    const period = POPULAR_PERIODS.find(p => p.days === days);
    const scope = group ? (multiSite() ? groupTag(group) : '') + esc(group.name) : folder ? esc(folder.name) : '전체';
    const periodButtons = POPULAR_PERIODS.map(p => `
        <button class="popular-period" data-action="popular-days" data-days="${p.days}" aria-pressed="${p.days === days}">${p.label}</button>`).join('');
    const row = (post, i) => `
        <button class="popular-row${post.is_read ? ' is-read' : ''}" data-action="goto-post" data-post-id="${esc(post.id)}">
            <span class="popular-rank">${i + 1}</span>
            <span class="popular-title">${esc(post.title)}</span>
            <span class="popular-stats">
                <span class="popular-stat" title="추천">${ICONS.thumb}<span class="sr-only">추천</span>${statNumber(post.votes).toLocaleString('ko-KR')}</span>
                <span class="popular-stat" title="댓글">${ICONS.comment}<span class="sr-only">댓글</span>${statNumber(post.comment_count).toLocaleString('ko-KR')}</span>
            </span>
        </button>`;
    const card = g => `
        <section class="popular-card" aria-label="${esc(g.name)} 인기글">
            <div class="popular-card-head">
                <h2 class="popular-board">${multiSite() ? groupTag(g) : ''}${esc(g.name)}</h2>
                <button class="link-btn popular-more" data-action="open-board-popular" data-group-id="${g.id}">게시판 인기순${ICONS.next}</button>
            </div>
            ${g.posts.map(row).join('')}
        </section>`;
    const body = data.groups.length
        ? `<div class="popular-grid${group ? ' is-single' : ''}">${data.groups.map(card).join('')}</div>`
        : `<div class="empty-card">최근 ${period.label === '오늘' ? '하루' : period.label} 동안 모은 글이 없습니다.</div>`;
    feed.innerHTML = `
        <div class="feed-head">
            <div class="feed-head-text">
                <div class="feed-title-row"><h1 class="feed-title">${scope} · 인기글</h1></div>
                <span class="feed-sub">최근 ${period.label === '오늘' ? '24시간' : period.label} 동안 모은 글 · 추천+댓글이 많은 순${group ? '' : ` · 게시판 ${data.groups.length}개`}</span>
            </div>
            <div class="feed-tools popular-tools">
                <div class="popular-periods" role="group" aria-label="기간">${periodButtons}</div>
                ${renderFontSizeControl()}
            </div>
        </div>
        ${body}`;
    window.scrollTo({ top: 0 });
    document.querySelector('.fab-next').hidden = true;
    updateShortcutGuide();
}

// 인기글 카드의 '게시판 인기순': 그 게시판을 같은 기간의 인기순으로 엶
function openBoardPopular(groupId) {
    const sort = { 1: 'popular-1', 7: 'popular-7', 30: 'popular-30' }[popularDays()];
    app.sort = sort;
    storageSet(localStorage, SORT_STORAGE_KEY, sort);
    app.filter = 'all';
    app.galleryReturn = null;
    openView('group:' + groupId, 1);
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
    app.bannerDismissedAt = 0;
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
    // 모바일은 정렬·페이지 이동 줄을 접어 두고, 제목 줄 오른쪽의 작은 버튼(예: '최신순 · 1/10')으로 펼침
    const toolsLabel = [sortable() ? currentSort().label : '', empty ? '' : `${data.page}/${data.total_pages}`].filter(Boolean).join(' · ');
    // (글자 크기도 이 목록에 있어 늘 보임. 정렬·페이지가 없는 화면은 '보기 설정')
    const toolsButton = `<button class="btn btn-outline btn-small feed-tools-btn mobile-only" data-action="toggle-feed-tools" aria-expanded="false" aria-label="정렬·페이지 이동·글자 크기">${esc(toolsLabel || '보기 설정')}${ICONS.chevronDown}</button>`;
    feed.innerHTML = `
        <div class="feed-head">
            <div class="feed-head-text">
                <div class="feed-title-row">
                    <h1 class="feed-title">${title}</h1>
                    ${headActions}
                    ${toolsButton}
                </div>
                <span class="feed-sub">${feedSubText(data.total)}</span>
                ${searching ? renderSearchOptions() : ''}
            </div>
            <div class="feed-tools">
                ${sortable() ? renderSortSelect() : ''}
                ${renderPagerMini(data.page, data.total_pages, empty)}
                ${renderFontSizeControl()}
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
    scheduleNewCommentJump();
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
    root.querySelectorAll('.post-card.has-comments > .comments').forEach(box => {
        fitOpeningCommentBox(box);
        anchorCommentBox(box);
        updateCommentsBottom(box);
    });
}

// 넓은 화면 댓글 칸 높이는 CSS로 '창 높이 − 위 메뉴'(칸이 위 메뉴 아래에 붙었을 때 기준)라, 게시판을 막 열어 게시판 제목 줄
// 아래에서 시작하는 첫 글은 칸 끝이 창 밖으로 나가 마지막 댓글이 안 보였음. 글 목록을 그릴 때 한 번만, 그렇게 아래에서
// 시작하는 칸은 창 아래 끝까지만 오도록 높이를 정해 둠 (스크롤 중에는 바꾸지 않아 스크롤이 걸리지 않음)
const COMMENT_BOX_BOTTOM_GAP = 24;
const COMMENT_BOX_MIN = 240;
function fitOpeningCommentBox(box) {
    box.style.maxHeight = '';
    if (!WIDE_QUERY.matches) return;
    const top = box.getBoundingClientRect().top;
    const stickyTop = parseFloat(getComputedStyle(box).top) || 0;
    if (top <= stickyTop + 4 || top >= window.innerHeight) return;   // 위 메뉴 아래에 붙어 있거나 화면 밖이면 CSS 높이 그대로
    box.style.maxHeight = Math.max(COMMENT_BOX_MIN, Math.round(window.innerHeight - top - COMMENT_BOX_BOTTOM_GAP)) + 'px';
}
// 위에서 줄여 둔 칸은 글을 올리면 위쪽이 올라온 만큼 다시 늘림 (위 메뉴 아래에 붙으면 CSS 높이로 되돌림).
// 늘리기만 하므로 칸 안의 스크롤 위치는 흔들리지 않음
let growCommentsQueued = false;
function growShrunkCommentBoxes() {
    growCommentsQueued = false;
    if (!WIDE_QUERY.matches) return;
    document.querySelectorAll('.post-card.has-comments > .comments[style*="max-height"]').forEach(box => {
        const top = box.getBoundingClientRect().top;
        if (top >= window.innerHeight || box.getBoundingClientRect().bottom <= 0) return;
        const stickyTop = parseFloat(getComputedStyle(box).top) || 0;
        if (top <= stickyTop + 4) { box.style.maxHeight = ''; updateCommentsBottom(box); return; }
        const want = Math.round(window.innerHeight - top - COMMENT_BOX_BOTTOM_GAP);
        if (want > parseFloat(box.style.maxHeight)) { box.style.maxHeight = want + 'px'; updateCommentsBottom(box); }
    });
}
function scheduleGrowCommentBoxes() {
    if (growCommentsQueued) return;
    growCommentsQueued = true;
    requestAnimationFrame(growShrunkCommentBoxes);
}

// 넓은 화면 댓글 칸의 떠 있는 버튼: 칸 위쪽보다 아래에 새 댓글이 남아 있으면 '다음 새 댓글'(남은 새 댓글 수),
// 없으면 '맨 아래'(아래에 남은 댓글 수). 누르면 다음 새 댓글을 칸 맨 위로, 없으면 맨 아래로.
// 맨 아래이고 남은 새 댓글도 없으면 숨김
const WIDE_QUERY = window.matchMedia('(min-width: 1360px)');
const COMMENT_TOP_GAP = 8;   // 새 댓글로 옮길 때 칸 위쪽과 띄울 간격
function newCommentsBelow(box) {
    const rect = box.getBoundingClientRect();
    const top = rect.top + COMMENT_TOP_GAP + 4;
    // 칸이 맨 아래까지 내려가 더 올릴 수 없으면, 이미 칸 안에 다 보이는 새 댓글은 남은 것으로 치지 않음
    const atBottom = box.scrollHeight - box.clientHeight - box.scrollTop < 2;
    return [...box.querySelectorAll('.comment.is-new-comment')].filter(c => {
        const r = c.getBoundingClientRect();
        return r.top > top && !(atBottom && r.bottom <= rect.bottom + 1);
    });
}
function updateCommentsBottom(box) {
    const btn = box.querySelector('.comments-bottom');
    if (!btn) return;
    const left = box.scrollHeight - box.clientHeight - box.scrollTop;
    const newBelow = WIDE_QUERY.matches ? newCommentsBelow(box) : [];
    // 보이고 숨길 때 칸 높이가 바뀌어 흔들리지 않도록 자리는 그대로 두고 보이기만 바꿈
    if (!WIDE_QUERY.matches || (left < 40 && !newBelow.length)) { btn.classList.remove('is-shown'); return; }
    if (newBelow.length) {
        btn.querySelector('.cb-label').textContent = '다음 새 댓글';
        btn.querySelector('.cb-count').textContent = ` · ${newBelow.length}`;
        btn.classList.add('is-new');
    } else {
        const edge = box.getBoundingClientRect().bottom - 8;
        const below = [...box.querySelectorAll('.comment')].filter(c => c.getBoundingClientRect().top > edge).length;
        btn.querySelector('.cb-label').textContent = '맨 아래';
        btn.querySelector('.cb-count').textContent = below ? ` · ${below}` : '';
        btn.classList.remove('is-new');
    }
    btn.classList.add('is-shown');
}
function scrollCommentsToBottom(btn) {
    const box = btn.closest('.comments');
    box.dataset.userScrolled = '1';   // 늦게 뜬 사진 때문에 시작 위치로 되돌리지 않게
    const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
    const next = newCommentsBelow(box)[0];
    const top = next ? box.scrollTop + next.getBoundingClientRect().top - box.getBoundingClientRect().top - COMMENT_TOP_GAP : box.scrollHeight;
    box.scrollTo({ top, behavior });
}
['wheel', 'touchstart', 'keydown', 'mousedown'].forEach(type => document.addEventListener(type, e => {
    const box = e.target.closest && e.target.closest('.post-card.has-comments > .comments');
    if (box) box.dataset.userScrolled = '1';
}, { passive: true, capture: true }));
document.addEventListener('load', e => {
    const box = e.target.closest && e.target.closest('.post-card.has-comments > .comments');
    if (box) { anchorCommentBox(box); updateCommentsBottom(box); }
    // 사진이 늦게 떠 글 위치가 바뀌면 모바일 '새 댓글' 버튼도 다시 확인
    scheduleNewCommentJump();
    // 본문 사진이 늦게 떠서 길어진 글은 긴 본문 접기를 다시 판단
    const card = e.target.closest && e.target.closest('#feed .post-card');
    if (card && e.target.closest('.post-content')) clampLongBodies(card);
}, true);
// 창을 넓혀 댓글 칸이 따로 스크롤되기 시작할 때도 같은 시작 위치로
WIDE_QUERY.addEventListener('change', () => anchorCommentBoxes());

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

function isMobile() { return window.matchMedia('(max-width: 899px)').matches; }
// 아래로 내려 이동한 뒤 화면 위쪽을 가리는 높이: 모바일은 아래로 내리면 위 메뉴가 통째로 숨으므로 0
function scrolledTopInset() { return isMobile() ? 0 : stickyHeight(); }
// 화면 아래쪽에서 보기 탭바·게시판 칩 줄(보일 때)이 가리는 높이를 뺀, 글이 실제로 보이는 아래 끝 (모바일)
function viewBottom() {
    if (!isMobile()) return window.innerHeight;
    const tabsTop = document.getElementById('view-tabs').getBoundingClientRect().top;
    const chipsTop = document.getElementById('chip-row').getBoundingClientRect().top;
    return Math.min(tabsTop, chipsTop);
}

function currentPostCard() {
    const headerBottom = document.querySelector('.topbar').getBoundingClientRect().bottom;
    return [...document.querySelectorAll('#feed .post-card')]
        .find(card => card.getBoundingClientRect().bottom > headerBottom + 8) || null;
}

// 모바일 '새 댓글' 보기: 다음 글 버튼이 글 단위가 아니라 마지막 댓글 단위로 이동
function lastCommentMode() {
    return !app.searchQuery && app.filter === 'comments' && isMobile();
}

// 떠 있는 버튼(맨 위로·다음 글)과 아래 보기 탭바에 가리지 않도록 화면 아래쪽에 남기는 여백
function fabRoom() {
    return window.innerHeight - document.querySelector('.floating').getBoundingClientRect().top + 8;
}
function scrollToLastComment(card) {
    const comments = shownComments(card, '.comments .comment');
    const target = comments[comments.length - 1] || card;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // 마지막 댓글의 아래 끝을 버튼 바로 위에 맞춤 (그 위로 앞의 새 댓글들이 보이게)
    window.scrollTo({ top: target.getBoundingClientRect().bottom + window.pageYOffset - window.innerHeight + fabRoom(),
                      behavior: reduceMotion ? 'auto' : 'smooth' });
}

// 첫 새 댓글을 맨 위 메뉴 바로 아래에 맞춤 (그 아래로 이어지는 댓글이 보이게).
// 모바일은 아래로 내리면 맨 위 제목 줄이 숨으므로, 숨은 뒤의 위 메뉴 높이 기준
function newCommentTop() {
    return scrolledTopInset() + 12;
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
    const limit = window.innerHeight - fabRoom() + 8;
    const stops = [...document.querySelectorAll('#feed .post-card')].flatMap(card => {
        const comments = shownComments(card, '.comments .comment');
        const last = comments[comments.length - 1];
        if (!last) return [{ card, el: card }];
        const firstNew = shownComments(card, '.comments .comment.is-new-comment')[0];
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
    // 모바일은 아래로 내리면 위 메뉴가 숨으므로, 숨은 뒤 기준으로 맞춤
    const offset = scrolledTopInset() + 12;
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
// 검색 조건: 범위(모든 게시판·지금 게시판), 기간, 작성자. 작성자는 검색어 안에 '작성자:닉네임'으로 적는 것과 같음
const SEARCH_PERIODS = [
    { days: 0, label: '전체 기간' }, { days: 1, label: '하루' }, { days: 7, label: '일주일' },
    { days: 30, label: '한 달' }, { days: 90, label: '석 달' }
];
const SEARCH_AUTHOR_RE = /^(?:작성자|author):(.*)$/i;

// 검색어에서 작성자 조건을 뺀 낱말들 (제목 강조용)
function searchWords() {
    return app.searchQuery.split(/\s+/).filter(t => t && !SEARCH_AUTHOR_RE.test(t));
}
function searchAuthor() {
    const found = app.searchQuery.split(/\s+/).map(t => SEARCH_AUTHOR_RE.exec(t)).find(m => m && m[1]);
    return found ? found[1] : '';
}
// 범위를 좁혀 찾는 중인 게시판·묶음 (모든 게시판에서 찾는 중이면 null)
function searchScope() {
    if (!app.searchQuery || !app.searchHere) return null;
    return findGroup(app.activeKey) || findFolder(app.activeKey) || null;
}

function renderSearchOptions() {
    const here = findGroup(app.activeKey) || findFolder(app.activeKey);
    const scopeBtn = (on, label, value) =>
        `<button class="search-opt-btn" data-action="search-scope" data-here="${value}" aria-pressed="${on}">${esc(label)}</button>`;
    return `<div class="search-opts">
        ${here ? `<div class="search-opt-group" role="group" aria-label="검색 범위">
            ${scopeBtn(!app.searchHere, '모든 게시판', 0)}${scopeBtn(app.searchHere, here.name, 1)}
        </div>` : ''}
        <select class="page-select search-days" data-action="search-days" aria-label="검색 기간">
            ${SEARCH_PERIODS.map(p => `<option value="${p.days}" ${p.days === app.searchDays ? 'selected' : ''}>${p.label}</option>`).join('')}
        </select>
        <input class="search-author" type="text" data-action="search-author" maxlength="30" autocomplete="off"
            placeholder="작성자" aria-label="작성자로 좁히기" value="${esc(searchAuthor())}">
    </div>`;
}

function setSearchScope(here) {
    app.searchHere = here;
    app.page = 1;
    loadPosts();
}

function setSearchDays(days) {
    if (!SEARCH_PERIODS.some(p => p.days === days)) return;
    app.searchDays = days;
    app.page = 1;
    loadPosts();
}

// 작성자 칸: 검색어 안의 '작성자:닉네임'을 바꿔 다시 찾음 (비우면 조건을 뺌)
function setSearchAuthor(name) {
    const author = (name || '').trim().split(/\s+/)[0] || '';
    if (author === searchAuthor()) return;
    const words = app.searchQuery.split(/\s+/).filter(t => t && !SEARCH_AUTHOR_RE.test(t));
    if (author) words.push('작성자:' + author);
    const query = words.join(' ').slice(0, 50);
    document.getElementById('search-input').value = query;
    runSearch(query);
}

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
    app.searchHere = false;
    app.searchDays = 0;
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
// × 로 닫은 배너: 닫을 때의 새 글 수를 기억해 두고 그보다 더 늘어날 때만 다시 표시 (화면을 새로 그리면 초기화)
function dismissNewBanner() {
    app.bannerDismissedAt = app.bannerShownCount || 0;
    hideNewBanner();
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
    if (added > (app.bannerDismissedAt || 0)) {
        const banner = document.getElementById('new-banner');
        app.bannerShownCount = added;
        const what = app.filter === 'comments' ? '새 댓글이 달린 글' : app.filter === 'deleted' ? '새로 삭제된 글'
            : app.filter === 'saved' ? '새로 보관한 글' : '새 글';
        banner.querySelector('.new-banner-open').innerHTML = `${ICONS.up}<span>${what} ${added}개 · 눌러서 보기</span>`;
        banner.querySelector('.new-banner-close').innerHTML = ICONS.close;
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
