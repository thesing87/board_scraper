'use strict';

// 키워드 게시판 화면 (app-feed.js): 피드 그리기: 글·댓글, 모아보기, 접기, 모바일 읽기 편의.
// 한 화면의 스크립트를 순서대로 나눈 파일 중 하나 (app.js, app-feed.js, app-view.js, app-admin.js, app-main.js). 전역 이름을 함께 씀

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
        .replace(/<iframe\b/gi, '<iframe referrerpolicy="strict-origin-when-cross-origin"')
        // 인스타그램·X 게시물(iframe) 위의 손가락 움직임은 그 사이트로 가서 대시보드가 받지 못함 → 모바일에서는 투명 덮개를 씌워
        // 그 위에서도 게시판 넘기기·스크롤이 되게 하고, 덮개를 한 번 누르면 걷어 게시물을 직접 조작 (넓은 화면은 덮개 없음, CSS)
        .replace(/<iframe\b[^>]*\bsrc="[^"]*(?:instagram\.com|platform\.twitter\.com\/embed)[^"]*"[^>]*>\s*<\/iframe>/gi,
            m => `<div class="embed-wrap">${m}<button class="embed-shield" data-action="activate-embed" aria-label="게시물 직접 조작하기 (누르면 덮개를 걷음)"></button></div>`);
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

// 댓글 페이지: 댓글이 COMMENT_PAGE_SIZE개를 넘으면 그만큼씩 페이지로 나눔 (원댓글과 그 답글은 한 페이지에).
// 페이지마다 댓글에 data-cpage를 달아 두고, 지금 페이지가 아닌 댓글은 c-off로 숨김 (숨기는 건 넓은 2단 화면이 아닐 때만, CSS).
// 처음에는 첫 새 댓글이 있는 페이지, 새 댓글이 없으면 가장 최근 댓글이 있는 마지막 페이지
const COMMENT_PAGE_SIZE = 20;

function commentPages(comments) {
    const pages = [];
    let page = [];
    comments.forEach((c, i) => {
        // 원댓글에서만 페이지를 나눠, 답글이 원댓글과 다른 페이지로 갈라지지 않게
        if (!c.is_reply && page.length >= COMMENT_PAGE_SIZE) { pages.push(page); page = []; }
        page.push(i);
    });
    if (page.length) pages.push(page);
    const pageOf = [];
    pages.forEach((idxs, p) => idxs.forEach(i => { pageOf[i] = p + 1; }));
    return { count: pages.length, pageOf };
}

function renderCommentPager(current, total) {
    const options = Array.from({ length: total }, (_, i) => `<option value="${i + 1}" ${i + 1 === current ? 'selected' : ''}>${i + 1}</option>`).join('');
    return `<nav class="comment-pager" aria-label="댓글 페이지">
        <button class="icon-btn" data-action="comment-page" data-step="-1" aria-label="이전 댓글 페이지" ${current <= 1 ? 'disabled' : ''}>${ICONS.prev}</button>
        <span class="comment-pager-pos">댓글 <select class="page-select" data-action="go-comment-page" aria-label="댓글 페이지 선택">${options}</select> / ${total}</span>
        <button class="icon-btn" data-action="comment-page" data-step="1" aria-label="다음 댓글 페이지" ${current >= total ? 'disabled' : ''}>${ICONS.next}</button>
    </nav>`;
}

// 댓글 페이지 바꾸기: 그 페이지 댓글만 보이고, 댓글 맨 위(제목)로 이동
function setCommentPage(section, page) {
    const total = Number(section.dataset.pages);
    page = Math.min(Math.max(1, page), total);
    section.dataset.page = String(page);
    section.querySelectorAll('.comment').forEach(c => c.classList.toggle('c-off', Number(c.dataset.cpage) !== page));
    scheduleNewCommentJump();
    section.querySelectorAll('.comment-pager').forEach(nav => nav.outerHTML = renderCommentPager(page, total));
    const title = section.querySelector('.comments-title');
    window.scrollTo({ top: title.getBoundingClientRect().top + window.pageYOffset - scrolledTopInset() - 12 });
    scheduleReadCheck();
}

// 숨긴 댓글(다른 페이지)을 뺀, 지금 보이는 댓글 (새 댓글 읽음 판정·'마지막 댓글로' 이동에 씀)
function shownComments(root, selector = '.comment') {
    return [...root.querySelectorAll(selector)].filter(c => c.offsetParent !== null);
}

function renderComments(post) {
    if (!post.comments || post.comments.length === 0) {
        // 넓은 화면의 2단 배치에서 오른쪽 댓글 자리를 유지하기 위한 빈 댓글 칸 (좁은 화면에서는 CSS로 숨김)
        return '<section class="comments is-empty"><h3 class="comments-title">댓글 0</h3><p class="comments-empty">아직 댓글이 없습니다.</p></section>';
    }
    const pages = commentPages(post.comments);
    const firstNew = post.comments.findIndex(c => isNewComment(c, post));
    const startPage = firstNew >= 0 ? pages.pageOf[firstNew] : pages.count;
    const items = post.comments.map((c, i) => {
        const body = (c.content || []).map(t => t ? `<p class="comment-line">${t}</p>` : '<br>').join('');
        const isAuthor = c.author === post.author;
        const isNew = isNewComment(c, post);
        const classes = ['comment'];
        const depth = replyDepth(c);
        if (c.is_reply) classes.push('reply');
        if (isNew) classes.push('is-new-comment');
        if (isAuthor) classes.push('is-author');
        if (pages.count > 1 && pages.pageOf[i] !== startPage) classes.push('c-off');
        const pageAttr = pages.count > 1 ? ` data-cpage="${pages.pageOf[i]}"` : '';
        return `
            <div class="${classes.join(' ')}"${pageAttr}${depth ? ` style="--depth: ${depth}"` : ''}>
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
    // 넓은 화면 댓글 칸의 '다음 새 댓글'·'맨 아래' 버튼 (updateCommentsBottom이 보일지·글자를 정함)
    const bottomButton = `<button class="comments-bottom" data-action="comments-to-bottom">${ICONS.chevronDown}<span class="cb-label">맨 아래</span><span class="cb-count"></span></button>`;
    if (pages.count <= 1) return `<section class="comments"><h3 class="comments-title">댓글 ${count}</h3>${items}${bottomButton}</section>`;
    return `<section class="comments is-paged" data-pages="${pages.count}" data-page="${startPage}">
        <h3 class="comments-title">댓글 ${count}</h3>${items}${renderCommentPager(startPage, pages.count)}${bottomButton}</section>`;
}

function safeLink(url) {
    return /^https?:\/\//i.test(url || '') ? url : '#';
}

function highlightTerms(text) {
    // 검색어를 제목에서 강조 (이스케이프한 뒤 표시용 태그만 추가)
    const escaped = esc(text);
    if (!app.searchQuery) return escaped;
    const terms = searchWords().map(t => esc(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
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
    if (window.location.hash) history.replaceState(history.state, '', window.location.pathname);
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
    // 긴 본문 접기 (전부 접기로 숨은 본문은 높이가 0이라, 펼쳐 보일 때 판단)
    clampLongBodies();
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
// 모바일 읽기 편의: 긴 본문 접기, 많은 댓글 접기(renderComments), 본문 사진 크게 보기, 글자 크기
// ==========================================
// 본문이 화면 높이의 BODY_CLAMP_RATIO배보다 길면 화면 70% 높이까지만 보이고 '본문 펼치기'로 엶.
// 사진이 늦게 떠서 길어지면 그때 다시 확인 (아래 load 이벤트). 한 번 펼친 본문은 다시 접지 않음
const BODY_CLAMP_RATIO = 1.3;
function clampLongBodies(root = document) {
    if (!isMobile()) return;
    root.querySelectorAll('#feed .post-card .post-content:not([data-expanded])').forEach(content => {
        if (content.classList.contains('is-clamped') || content.scrollHeight <= window.innerHeight * BODY_CLAMP_RATIO) return;
        content.classList.add('is-clamped');
        content.insertAdjacentHTML('afterend', `<button class="body-more" data-action="expand-body">${ICONS.chevronDown} 본문 펼치기</button>`);
    });
}
function expandBody(button) {
    const content = button.previousElementSibling;
    content.classList.remove('is-clamped');
    content.dataset.expanded = '1';
    button.remove();
    scheduleReadCheck();
}

// 본문 사진을 누르면 그 글의 사진·동영상을 모아 크게 보기. 에펨코리아 사진은 원본 사진으로 가는 링크(a.highslide)로
// 감싸여 있어 그 링크는 크게 보기로 대신하고, 다른 곳으로 가는 링크로 감싼 사진·작은 그림(이모티콘)은 그대로
function isImageLink(a) {
    return a.classList.contains('highslide') || /\.(jpe?g|png|gif|webp|bmp)([?#].*)?$/i.test(a.getAttribute('href') || '');
}
function openBodyImage(img) {
    const link = img.closest('a');
    if (link && !isImageLink(link) || img.naturalWidth && img.naturalWidth < 80) return false;
    const card = img.closest('.post-card');
    const postId = card.id.replace(/^post-/, '');
    const src = img.getAttribute('src') || '';
    const full = src.startsWith('//') ? 'https:' + src : src;
    const media = app.previewMedia[postId] || [];
    const index = media.findIndex(m => m.src === full);
    if (index >= 0) {
        app.galleryItems = media;
        openMedia(index);
    } else {
        const title = card.querySelector('.post-title').textContent.trim();
        app.galleryItems = [{ type: 'image', src: full, index: 1, of: 1, post: { id: postId, title, link: '', keywords: [] } }];
        openMedia(0);
    }
    return true;
}

// 크게 보기에서 좌우로 밀면 이전·다음 (모바일)
let viewerSwipe = null;
document.addEventListener('touchstart', e => {
    viewerSwipe = e.target.closest('.mv-stage') && e.touches.length === 1
        ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
}, { passive: true });
document.addEventListener('touchend', e => {
    if (!viewerSwipe) return;
    const dx = e.changedTouches[0].clientX - viewerSwipe.x;
    const dy = e.changedTouches[0].clientY - viewerSwipe.y;
    viewerSwipe = null;
    // 확대한 상태(두 손가락으로 키운 화면)에서는 밀어도 넘기지 않음
    if (window.visualViewport && window.visualViewport.scale > 1.05) return;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) openMedia(app.mediaIndex + (dx < 0 ? 1 : -1));
}, { passive: true });

// 모바일: 글 목록을 좌우로 밀면 게시판 칩 순서대로 이전·다음 게시판 (왼쪽으로 밀면 다음).
// 미는 동안 목록이 손가락을 따라 움직이고, 충분히 밀었다 놓으면 지금 목록이 밀려 나가고 다음 게시판 목록이 반대쪽에서 들어옴.
// 덜 밀었으면 제자리로 돌아오고, 끝 게시판에서는 조금만 끌려오다 돌아옴.
// 세로 스크롤과 헷갈리지 않도록 처음 움직임이 가로일 때만, 가로로 스크롤되는 곳(넓은 표·칩 줄)·동영상·입력칸 위는 제외.
// 링크·사진·버튼 위에서 시작해도 끌 수 있음 (끌면 브라우저가 누름으로 치지 않아 링크가 열리지 않음)
const BOARD_SWIPE_DECIDE = 12;     // 이만큼(px) 움직인 뒤 가로인지 세로인지 정함
const BOARD_SWIPE_RATIO = 0.25;    // 화면 폭의 이 비율 넘게 밀면 넘김
const BOARD_SWIPE_FLICK = 60;      // 또는 빠르게(BOARD_SWIPE_MS 안에) 이만큼 밀면 넘김
const BOARD_SWIPE_MS = 300;
const BOARD_SLIDE_MS = 200;        // 밀려 나가고 들어오는 시간
let boardSwipe = null;
function scrollsSideways(el) {
    for (; el && el !== document.body; el = el.parentElement) {
        if (el.scrollWidth > el.clientWidth + 4 && /(auto|scroll)/.test(getComputedStyle(el).overflowX)) return true;
    }
    return false;
}
// 게시판 칩 줄의 순서(전체 → 게시판·묶음)에서 지금 칩의 앞·뒤 칩
function neighborBoardChip(step) {
    const chips = [...document.querySelectorAll('#chip-row [data-action="open-all"], #chip-row [data-action="open-group"], #chip-row [data-action="open-folder"]')];
    const current = chips.findIndex(c => c.getAttribute('aria-current') === 'true');
    return current < 0 ? null : chips[current + step] || null;
}
function setFeedSlide(x, opacity, transition) {
    const feed = document.getElementById('feed');
    feed.style.transition = transition || 'none';
    feed.style.transform = x ? `translateX(${x})` : '';
    feed.style.opacity = opacity === 1 ? '' : String(opacity);
}
document.addEventListener('touchstart', e => {
    const t = e.target;
    boardSwipe = isMobile() && e.touches.length === 1 && t.closest('#feed') && !isGalleryView() && !document.body.classList.contains('board-sliding')
        && !t.closest('input, select, textarea, video, iframe, .chip-row, .feed-tools') && !scrollsSideways(t)
        && document.getElementById('settings').hidden && !document.body.classList.contains('viewer-open')
        // 두 손가락으로 확대한 상태에서는 화면을 옮기는 동작이므로 넘기지 않음
        && !(window.visualViewport && window.visualViewport.scale > 1.05)
        ? { x: e.touches[0].clientX, y: e.touches[0].clientY, at: Date.now(), dragging: false, dx: 0 } : null;
}, { passive: true });
// 가로로 끄는 동안에는 세로 스크롤을 막아야 하므로 passive가 아닌 리스너 (끄는 중이 아니면 바로 돌아감)
document.addEventListener('touchmove', e => {
    if (!boardSwipe) return;
    const dx = e.touches[0].clientX - boardSwipe.x;
    const dy = e.touches[0].clientY - boardSwipe.y;
    if (!boardSwipe.dragging) {
        if (Math.abs(dx) < BOARD_SWIPE_DECIDE && Math.abs(dy) < BOARD_SWIPE_DECIDE) return;
        if (Math.abs(dx) <= Math.abs(dy) * 1.5) { boardSwipe = null; return; }   // 세로 스크롤
        boardSwipe.dragging = true;
        boardSwipe.prev = neighborBoardChip(-1);
        boardSwipe.next = neighborBoardChip(1);
        // 맨 위에서 당겨서 새로고침이 같이 시작됐으면 취소
        if (pull) { pull = null; resetPull(document.getElementById('pull-refresh')); }
    }
    e.preventDefault();
    boardSwipe.dx = dx;
    // 넘어갈 게시판이 없는 쪽으로는 조금만 끌려옴
    const target = dx < 0 ? boardSwipe.next : boardSwipe.prev;
    const shown = target ? dx : dx * 0.25;
    setFeedSlide(`${shown}px`, 1 - Math.min(0.4, Math.abs(shown) / window.innerWidth * 0.6));
}, { passive: false });
document.addEventListener('touchend', e => {
    if (!boardSwipe) return;
    const swipe = boardSwipe;
    boardSwipe = null;
    if (!swipe.dragging) return;
    const dx = swipe.dx;
    const step = dx < 0 ? 1 : -1;
    const target = step > 0 ? swipe.next : swipe.prev;
    const far = Math.abs(dx) > window.innerWidth * BOARD_SWIPE_RATIO;
    const flick = Date.now() - swipe.at < BOARD_SWIPE_MS && Math.abs(dx) >= BOARD_SWIPE_FLICK;
    if (target && (far || flick)) {
        slideToBoard(target, step);
        return;
    }
    if (!target && (far || flick)) showToast(step > 0 ? '마지막 게시판입니다' : '첫 게시판입니다');
    // 덜 밀었으면 제자리로
    setFeedSlide('', 1, `transform ${BOARD_SLIDE_MS}ms ease-out, opacity ${BOARD_SLIDE_MS}ms ease-out`);
}, { passive: true });

// 지금 목록을 민 쪽으로 밀어 내보내고, 다음 게시판 목록을 받아 반대쪽에서 들여옴
async function slideToBoard(chip, step) {
    document.body.classList.add('board-sliding');
    const out = step > 0 ? '-100vw' : '100vw';
    setFeedSlide(out, 0, `transform ${BOARD_SLIDE_MS}ms ease-in, opacity ${BOARD_SLIDE_MS}ms ease-in`);
    await new Promise(r => setTimeout(r, BOARD_SLIDE_MS));
    const d = chip.dataset;
    const key = d.groupId ? 'group:' + d.groupId : d.folderId ? 'folder:' + d.folderId : ALL_KEY;
    const name = d.groupId ? (findGroup(key) || {}).name : d.folderId ? (findFolder(key) || {}).name : '전체';
    try {
        await openBoard(key);
    } finally {
        setFeedSlide(step > 0 ? '40vw' : '-40vw', 0);
        document.getElementById('feed').getBoundingClientRect();   // 들어올 위치를 먼저 그린 뒤 움직이게
        setFeedSlide('', 1, `transform ${BOARD_SLIDE_MS + 60}ms ease-out, opacity ${BOARD_SLIDE_MS + 60}ms ease-out`);
        setTimeout(() => { setFeedSlide('', 1); document.body.classList.remove('board-sliding'); }, BOARD_SLIDE_MS + 80);
        showToast(name || '');
    }
}

// 모바일 '새 댓글' 버튼: 지금 보는 글에서 화면 가운데보다 아래에 남은 새 댓글(보이는 댓글 페이지의)이 있으면 '새 댓글 · N',
// 지금 글은 다 봤고 아래 다른 글에 새 댓글이 있으면 '다음 글 새 댓글'. 누르면 그 새 댓글을 보이는 화면 가운데로
// (아래로 내리면 위 메뉴가 숨으므로 그 기준, 아래 보기 탭바에 가린 부분은 뺌). 다음을 남은 것으로 치지 않음:
// - 이미 가운데 근처(NEW_COMMENT_JUMP_SLACK 안)까지 온 새 댓글: 위쪽 사진이 늦게 떠 몇 px 밀려도 다시 세지 않게
// - 페이지가 끝까지 내려가 더 올릴 수 없는데 이미 화면에 다 보이는 새 댓글: 눌러도 움직이지 않는 버튼이 남지 않게
const NEW_COMMENT_JUMP_SLACK = 40;
// 위 메뉴(숨은 뒤 기준)와 아래 보기 탭바 사이, 글이 실제로 보이는 곳의 가운데
function visibleCenter() {
    return (scrolledTopInset() + viewBottom()) / 2;
}
function newCommentJump() {
    const line = visibleCenter() + NEW_COMMENT_JUMP_SLACK;
    const pageEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
    const bottom = viewBottom();
    const remaining = c => {
        const r = c.getBoundingClientRect();
        return (r.top + r.bottom) / 2 > line && !(pageEnd && r.bottom <= bottom + 1);
    };
    const current = currentPostCard();
    const here = current ? shownComments(current, '.comment.is-new-comment').filter(remaining) : [];
    if (here.length) return { targets: here, nextPost: false };
    const later = shownComments(document.getElementById('feed'), '.comment.is-new-comment')
        .filter(c => c.closest('.post-card') !== current && remaining(c));
    return { targets: later, nextPost: later.length > 0 };
}
let newCommentJumpScheduled = false;
function updateNewCommentJump() {
    newCommentJumpScheduled = false;
    const btn = document.getElementById('new-comment-jump');
    const jump = isMobile() && !isGalleryView() ? newCommentJump() : { targets: [] };
    btn.hidden = !jump.targets.length;
    if (!jump.targets.length) return;
    btn.classList.toggle('is-next-post', jump.nextPost);
    btn.innerHTML = jump.nextPost ? `${ICONS.chevronDown}다음 글 새 댓글` : `${ICONS.chevronDown}새 댓글 · ${jump.targets.length}`;
}
function scheduleNewCommentJump() {
    if (newCommentJumpScheduled) return;
    newCommentJumpScheduled = true;
    requestAnimationFrame(updateNewCommentJump);
}
function jumpToNextNewComment() {
    const next = newCommentJump().targets[0];
    if (!next) return;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // 새 댓글의 가운데를 보이는 화면 가운데에 (화면보다 긴 댓글은 위 끝이 위 메뉴 아래에 오게)
    const r = next.getBoundingClientRect();
    const offset = r.height > viewBottom() - scrolledTopInset() - 24
        ? r.top - scrolledTopInset() - 12
        : (r.top + r.bottom) / 2 - visibleCenter();
    window.scrollTo({ top: window.pageYOffset + offset, behavior: reduceMotion ? 'auto' : 'smooth' });
}

// 글자 크기 (본문·댓글): 작게·보통·크게. 기기마다 기억하고 body 클래스(font-s·font-l)로 적용
const FONT_SIZES = [{ key: 's', label: '작게' }, { key: 'm', label: '보통' }, { key: 'l', label: '크게' }];
const FONT_SIZE_KEY = 'font_size';
function applyFontSize() {
    const size = storageGet(localStorage, FONT_SIZE_KEY, 'm');
    document.body.classList.toggle('font-s', size === 's');
    document.body.classList.toggle('font-l', size === 'l');
}
function renderFontSizeControl() {
    const current = storageGet(localStorage, FONT_SIZE_KEY, 'm');
    const theme = storageGet(localStorage, THEME_KEY, 'auto');
    return `<div class="font-size-control" role="group" aria-label="글자 크기">
        <span class="font-size-label">글자</span>
        ${FONT_SIZES.map(f => `<button class="font-size-btn fs-${f.key}" data-action="set-font-size" data-size="${f.key}" aria-pressed="${f.key === current}">${f.label}</button>`).join('')}
    </div>
    <div class="font-size-control" role="group" aria-label="화면 밝기">
        <span class="font-size-label">화면</span>
        ${THEMES.map(t => `<button class="font-size-btn theme-btn" data-action="set-theme" data-theme="${t.key}" aria-pressed="${t.key === theme}">${t.label}</button>`).join('')}
    </div>`;
}

// 다크 모드 (모바일): 자동(휴대폰 설정을 따름)·밝게·어둡게. 기기마다 기억하고 body.theme-dark로 적용,
// 휴대폰 위 상태 표시줄 색(theme-color)도 화면 색에 맞춤
const THEMES = [{ key: 'auto', label: '자동' }, { key: 'light', label: '밝게' }, { key: 'dark', label: '어둡게' }];
const THEME_KEY = 'theme';
const DARK_QUERY = window.matchMedia('(prefers-color-scheme: dark)');
function applyTheme() {
    const theme = storageGet(localStorage, THEME_KEY, 'auto');
    const dark = isMobile() && (theme === 'dark' || (theme === 'auto' && DARK_QUERY.matches));
    document.body.classList.toggle('theme-dark', dark);
    document.getElementById('theme-color').setAttribute('content', dark ? '#181B21' : '#FFFFFF');
}
function setTheme(theme) {
    if (!THEMES.some(t => t.key === theme)) return;
    storageSet(localStorage, THEME_KEY, theme);
    applyTheme();
    document.querySelectorAll('.theme-btn').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.theme === theme)));
}
DARK_QUERY.addEventListener('change', applyTheme);
window.matchMedia('(max-width: 899px)').addEventListener('change', applyTheme);
function setFontSize(size) {
    if (!FONT_SIZES.some(f => f.key === size)) return;
    storageSet(localStorage, FONT_SIZE_KEY, size);
    applyFontSize();
    document.querySelectorAll('.font-size-btn').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.size === size)));
    // 글자 크기가 바뀌면 본문 길이도 달라지므로 접기를 다시 판단
    clampLongBodies();
}
