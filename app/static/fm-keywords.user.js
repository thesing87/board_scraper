// ==UserScript==
// @name         FM키워드 줄 (키워드 모니터)
// @namespace    keyword-monitor
// @version      1.5.1
// @description  에펨코리아 화면에 키워드 모니터의 FM키워드 줄을 붙임. 키워드를 누르면 같은 탭에서 그 검색으로 (PC는 위, 휴대폰은 아래)
// @match        https://fmkorea.com/*
// @match        https://*.fmkorea.com/*
// @updateURL    __SITE__/fm-keywords.user.js
// @downloadURL  __SITE__/fm-keywords.user.js
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      __SITE_HOST__
// @run-at       document-start
// @noframes
// ==/UserScript==
// 키워드 모니터 서버가 설치 주소(/fm-keywords.user.js)로 내려줄 때 __SITE__ 자리에 사이트 주소를 넣음.
// 키워드 목록은 키워드 모니터에서 가져오고(누구나 볼 수 있는 FM키워드 목록), 누른 시각을 기록함.
// 에펨코리아 화면은 보고 있는 탭 그대로이며, 키워드 모니터 서버는 에펨코리아에 요청하지 않음
(function () {
    'use strict';
    const SITE = '__SITE__';
    const VERSION = '1.5.1';
    // 오류로 멈추면 키워드 모니터 서버 기록에 한 줄 남김 (화면마다 한 번, 원인을 찾으려고. 에펨코리아 화면 내용은 보내지 않음)
    let reported = false;
    function reportError(where, err) {
        try { console.error('[FM키워드 줄]', where, err); } catch (e) { /* 콘솔 없음 */ }
        if (reported) return;
        reported = true;
        try {
            GM_xmlhttpRequest({ method: 'POST', url: SITE + '/api/fm-link', headers: { 'Content-Type': 'application/json' }, timeout: 10000,
                data: JSON.stringify({ action: 'client_error', where, version: VERSION,
                                       message: String((err && (err.stack || err.message)) || err).slice(0, 300) }) });
        } catch (e) { /* 보내지 못함 */ }
    }
    try {
    const STALE_DAYS = 7;
    // 휴대폰: 좁은 화면이거나 브라우저가 휴대폰이라고 알려 줄 때 (휴대폰에서 PC용 화면을 열어 폭이 넓게 잡혀도 휴대폰으로).
    // 터치 화면 노트북·PC용 삼성 인터넷은 PC로
    const MOBILE = window.matchMedia('(max-width: 899px)').matches
        || !!(navigator.userAgentData && navigator.userAgentData.mobile) || /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
    // 기기마다 기억: 줄 전체 접힘, PC에서 펼친 묶음 ID들, 휴대폰에서 고른 묶음 ID (0이면 아랫줄 접힘)
    const KEY_FOLDED = 'fm_bar_folded', KEY_OPEN = 'fm_bar_open', KEY_MOBILE = 'fm_bar_mobile_group';
    // 마지막으로 받은 키워드 목록: 새 화면이 열리면 서버를 기다리지 않고 이것으로 바로 그린 뒤, 새 목록이 다르면 다시 그림
    const KEY_CACHE = 'fm_bar_cache';
    // 키워드 줄에서 바로 추가할 때 쓰는 관리자 비밀번호 (처음 한 번 넣으면 Tampermonkey 저장소에만 둠. 에펨코리아 페이지는 읽을 수 없음)
    const KEY_PWD = 'fm_admin_password';
    // 아직 서버에 못 보낸 '누른 시각' [{group_id, board, keyword, at}]: 누르면 기다리지 않고 바로 넘어가므로, 넘어가는 사이 끊긴 기록은 다음 화면에서 다시 보냄
    const KEY_PENDING = 'fm_bar_pending_opens';
    // 아직 서버에 못 보낸 읽은 글 번호: 글을 누르면 바로 넘어가므로, 넘어가는 사이 끊긴 기록은 다음 화면에서 다시 보내고 받은 목록에도 반영
    const KEY_PENDING_READS = 'fm_bar_pending_reads';
    // 마지막으로 본 검색 결과 목록 {board, keyword, url, page, at, posts: [{no, href, title}]} (글 화면에서 이전·다음 글로 넘어가려고)
    const KEY_TRAIL = 'fm_bar_trail';
    // 이보다 오래된 검색 결과 목록은 쓰지 않음 (하루)
    const TRAIL_MAX_AGE = 86400000;

    // 응답 코드와 내용을 그대로 (실패 이유를 보여 줄 때)
    function requestRaw(method, path, body) {
        return new Promise(resolve => {
            GM_xmlhttpRequest({
                method, url: SITE + path, data: body ? JSON.stringify(body) : undefined,
                headers: body ? { 'Content-Type': 'application/json' } : {}, timeout: 15000,
                onload: res => { let data = {}; try { data = JSON.parse(res.responseText); } catch (e) { /* 내용 없음 */ } resolve({ status: res.status, data }); },
                onerror: () => resolve({ status: 0, data: {} }), ontimeout: () => resolve({ status: 0, data: {} }),
            });
        });
    }
    function request(method, path, body) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method, url: SITE + path, data: body ? JSON.stringify(body) : undefined,
                headers: body ? { 'Content-Type': 'application/json' } : {}, timeout: 15000,
                onload: res => {
                    if (res.status !== 200) { reject(new Error(res.status)); return; }
                    try { resolve(JSON.parse(res.responseText)); } catch (e) { reject(e); }
                },
                onerror: reject, ontimeout: reject,
            });
        });
    }
    const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    function searchUrl(board, keyword) {
        const q = encodeURIComponent(keyword);
        return board
            ? `https://www.fmkorea.com/search.php?mid=${encodeURIComponent(board)}&search_target=title_content&search_keyword=${q}`
            : `https://www.fmkorea.com/search.php?act=IS&is_keyword=${q}`;
    }
    function agoText(at) {
        if (!at) return '아직 안 봄';
        const minutes = Math.max(0, Math.floor((Date.now() - new Date(at.replace(' ', 'T'))) / 60000));
        if (minutes < 1) return '방금 전';
        if (minutes < 60) return `${minutes}분 전`;
        if (minutes < 1440) return `${Math.floor(minutes / 60)}시간 전`;
        const days = Math.floor(minutes / 1440);
        return days === 1 ? '어제' : `${days}일 전`;
    }
    const isStale = at => !!at && Date.now() - new Date(at.replace(' ', 'T')) >= STALE_DAYS * 86400000;
    // 지금 보는 검색 (주소의 게시판·검색어)
    const params = new URLSearchParams(location.search);
    const currentBoard = params.get('act') === 'IS' ? '' : (params.get('mid') || '');
    const currentKeyword = (params.get('search_keyword') || params.get('is_keyword') || '').trim();
    const isCurrent = l => !!currentKeyword && l.keyword === currentKeyword && l.board === currentBoard;
    // 지금 보는 글 번호 (글 화면이 아니면 0). 검색 결과에서 연 글은 주소에 검색어가 붙어 있어도
    const postNumberOf = href => {
        const m = /document_srl=(\d+)/.exec(href || '') || /^\/(\d{5,})(?:[?#]|$)/.exec((href || '').replace(/^https?:\/\/[^/]+/, ''));
        return m ? Number(m[1]) : 0;
    };
    const pagePostNo = postNumberOf(location.pathname + location.search) || Number(params.get('document_srl')) || 0;

    // 페이지가 막 열릴 때(본문이 생기기 전) 실행되므로 문서 맨 바깥에 붙임: 에펨코리아 화면이 나타날 때부터 줄·여백이 함께 있어 화면이 밀리지 않음
    const host = document.createElement('div');
    host.id = 'keyword-monitor-fm-bar';
    const root = host.attachShadow({ mode: 'open' });
    // 아주 이르면 문서 뼈대(html)도 아직 없을 수 있어, 생기는 즉시 붙이고 다시 그림
    function mount() {
        if (!document.documentElement) return false;
        if (!host.isConnected) document.documentElement.appendChild(host);
        return true;
    }
    if (!mount()) {
        new MutationObserver((_, observer) => {
            if (mount()) { observer.disconnect(); if (groups.length) render(); }
        }).observe(document, { childList: true });
    }
    let groups = [];
    let cachedJson = GM_getValue(KEY_CACHE, '');
    try { groups = cachedJson ? JSON.parse(cachedJson) : []; } catch (e) { groups = []; cachedJson = ''; }

    const CSS = `
        :host { all: initial; }
        .bar { position: fixed; left: 0; right: 0; z-index: 2147483000; background: #FAECE7; color: #4A1B0C;
            font: 13px/1.4 -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
            box-sizing: border-box; transition: transform .2s ease; }
        .bar * { box-sizing: border-box; font-family: inherit; }
        .top { top: 0; border-bottom: 1px solid #F0997B; padding: 6px 12px; display: flex; align-items: center; gap: 8px; }
        .bottom { bottom: 0; border-top: 1px solid #F0997B; padding: 6px 10px calc(8px + env(safe-area-inset-bottom, 0px)); }
        .bottom.gone { transform: translateY(100%); }
        .head { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
        .bottom .head { margin-bottom: 6px; }
        .title { font-weight: 700; color: #712B13; white-space: nowrap; }
        button { font: inherit; }
        .boxes { display: flex; flex-wrap: wrap; gap: 6px; flex: 1 1 auto; min-width: 0; align-items: flex-start; }
        .box { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 5px; border: 1px solid #F0997B; border-radius: 10px; padding: 3px 6px; background: #fff; max-width: 100%; }
        .box.open { border-color: #993C1D; background: #FFF6F2; }
        .gh { border: 0; background: none; padding: 1px 2px; cursor: pointer; color: #712B13; font-size: 12px; font-weight: 700; white-space: nowrap; display: inline-flex; align-items: center; gap: 4px; }
        .cnt { font-size: 11px; color: #993C1D; font-weight: 400; }
        .cnt b { color: #854F0B; font-weight: 700; }
        .groups { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; margin-bottom: 6px; }
        .groups::-webkit-scrollbar { display: none; }
        .gp { flex: 0 0 auto; border: 1px solid #F0997B; background: #fff; color: #712B13; border-radius: 999px; padding: 4px 11px; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }
        .gp.on { background: #712B13; border-color: #712B13; color: #fff; }
        .gp .cnt { margin-left: 3px; }
        .gp.on .cnt { color: #F5C4B3; }
        .chips { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; flex: 1 1 auto; min-width: 0; }
        .chips::-webkit-scrollbar { display: none; }
        .top .chips { flex-wrap: wrap; overflow: visible; }
        a.chip { flex: 0 0 auto; display: inline-flex; flex-direction: column; justify-content: center; padding: 3px 10px; border-radius: 12px;
            border: 1px solid #F0997B; background: #fff; color: #4A1B0C; text-decoration: none; line-height: 1.25; white-space: nowrap; }
        .bottom a.chip { border-radius: 999px; padding: 5px 12px; }
        a.chip small { font-size: 10px; color: #993C1D; }
        a.chip.stale { border-color: #EF9F27; }
        a.chip.on { background: #993C1D; border-color: #993C1D; color: #fff; }
        a.chip.on small { color: #F5C4B3; }
        a.chip { position: relative; }
        a.chip.done { opacity: .55; }
        a.chip.on.done { opacity: 1; }
        /* 새 글 뱃지: 키워드 글자 바로 옆 (칩 밖으로 튀어나오면 휴대폰의 옆으로 밀리는 칩 줄에서 잘리고, PC에서는 글자를 가림) */
        .kw { display: inline-flex; align-items: center; gap: 4px; }
        .newb { display: inline-block; background: #185FA5; color: #fff; font-size: 10px; font-weight: 700; border-radius: 999px; padding: 0 5px; line-height: 15px; }
        a.chip.on .newb { background: #fff; color: #185FA5; }
        .newg { color: #185FA5; font-weight: 700; }
        .gp .newg { margin-left: 4px; }
        .gp.on .newg { color: #B5D4F4; }
        .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #185FA5; margin-left: 4px; vertical-align: 1px; }
        .prog { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: #712B13; white-space: nowrap; }
        .pbar { width: 56px; height: 5px; border-radius: 3px; background: #F5C4B3; overflow: hidden; }
        .pbar i { display: block; height: 100%; background: #993C1D; }
        .side .next { border: 0; border-radius: 8px; background: #993C1D; color: #fff; font-size: 12px; font-weight: 700; padding: 4px 10px; cursor: pointer; white-space: nowrap; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
        .side .next small { font-weight: 400; opacity: .85; margin-left: 2px; }
        .side .next.alldone { background: #fff; color: #3B6D11; border: 1px solid #97C459; cursor: default; }
        .side { margin-left: auto; display: flex; align-items: center; gap: 10px; flex: 0 0 auto; white-space: nowrap; }
        .side a, .side button { font: inherit; font-size: 12px; color: #993C1D; background: none; border: 0; padding: 0; cursor: pointer; text-decoration: none; }
        .mini { display: flex; justify-content: center; padding: 4px 0 calc(4px + env(safe-area-inset-bottom, 0px)); cursor: pointer; color: #993C1D; font-size: 12px; font-weight: 700; }
        .top.mini { justify-content: flex-start; padding: 3px 12px; }
        .msg { font-size: 12px; color: #993C1D; }
        .top.compact { padding: 3px 12px; align-items: center; }
        .names { display: flex; gap: 4px; flex: 1 1 auto; min-width: 0; overflow-x: auto; scrollbar-width: none; white-space: nowrap; }
        .names::-webkit-scrollbar { display: none; }
        .compact .gh { padding: 2px 6px; border-radius: 6px; }
        .compact .gh:hover, .compact .gh.cur { background: #fff; }
        .side .add { border: 1px solid #185FA5; border-radius: 8px; background: #fff; color: #185FA5; font-weight: 700; padding: 3px 9px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
        .picker { position: absolute; right: 12px; width: 280px; max-width: calc(100vw - 24px); background: #fff; color: #4A1B0C; border: 1px solid #F0997B; border-radius: 10px;
            padding: 10px; box-shadow: 0 6px 20px rgba(74, 27, 12, .18); display: flex; flex-direction: column; gap: 6px; }
        .top .picker { top: calc(100% + 4px); }
        .bottom .picker { bottom: calc(100% + 4px); right: 10px; }
        .picker .ph { font-size: 12px; color: #993C1D; }
        .picker .ph b { color: #4A1B0C; }
        .picker input { font: inherit; font-size: 13px; border: 1px solid #F0997B; border-radius: 6px; padding: 5px 8px; outline-color: #993C1D; }
        .picker .to { text-align: left; border: 1px solid #F5C4B3; background: #fff; color: #4A1B0C; border-radius: 7px; padding: 6px 9px; cursor: pointer; font-size: 13px; }
        .picker .to.best { border-color: #185FA5; color: #0C447C; background: #E6F1FB; }
        .picker .to small { font-size: 11px; color: #993C1D; margin-left: 4px; }
        .picker .to:disabled { opacity: .5; cursor: default; }
        .picker .err { font-size: 12px; color: #A32D2D; }
        .pnav { display: inline-flex; align-items: center; gap: 4px; padding-right: 10px; margin-right: 2px; border-right: 1px solid #F0997B; }
        .bottom .pnav { border-right: 0; padding-right: 0; }
        .side .pnav button, .side .pnav a { border: 1px solid #F0997B; border-radius: 7px; background: #fff; color: #712B13; font-weight: 700; padding: 3px 8px; line-height: 1.2; }
        .side .pnav button:disabled { opacity: .4; cursor: default; }
        .side .pnav .pnew { border-color: #185FA5; color: #185FA5; }
        .pnav .ppos { font-size: 12px; color: #712B13; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .pnav .ppos b { font-variant-numeric: tabular-nums; }
        .picker .x { position: absolute; top: 6px; right: 8px; border: 0; background: none; color: #993C1D; cursor: pointer; font-size: 14px; }
    `;

    const currentGroup = () => groups.find(g => g.links.some(isCurrent));
    const staleCount = g => g.links.filter(l => isStale(l.last_opened)).length;
    // PC: 펼친 묶음 = 기억한 묶음 + 지금 보는 검색이 들어 있는 묶음 (이 화면에서 직접 접고 폈으면 기억한 그대로만)
    let openTouched = false;
    // PC: 아래로 스크롤하면 얇은 한 줄(묶음 이름만)로, 위로 올리거나 맨 위로 가면 원래대로 (줄 상태는 기억하지 않음)
    let compact = false;
    let lastY = window.scrollY;
    // 펼친 묶음은 하나만: 지금 보는 검색이 들어 있는 묶음 → 마지막으로 펼친 묶음 (이 화면에서 직접 고쳤으면 그대로)
    function openIds() {
        const saved = GM_getValue(KEY_OPEN, []).filter(id => groups.some(g => g.id === id)).slice(0, 1);
        if (currentGroup() && !openTouched) return new Set([currentGroup().id]);
        return new Set(saved);
    }
    // 휴대폰: 아랫줄에 보일 묶음 = 지금 보는 검색의 묶음 → 기억한 묶음 → 첫 묶음 (0이면 아랫줄 접힘)
    let mobileTouched = false;
    function mobileGroupId() {
        const saved = GM_getValue(KEY_MOBILE, null);
        if (saved === 0) return 0;
        if (!mobileTouched && currentGroup()) return currentGroup().id;
        return groups.some(g => g.id === saved) ? saved : groups[0].id;
    }
    // 오늘 연 키워드 (날짜가 바뀌면 처음부터)
    const pad2 = n => String(n).padStart(2, '0');
    const nowText = () => { const d = new Date(); return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`; };
    const openedToday = l => !!l.last_opened && l.last_opened.slice(0, 10) === nowText().slice(0, 10);
    const allLinks = () => groups.flatMap(g => g.links.map(l => ({ g, l })));
    // 안 읽은 새 글 수: 검색 결과에서 확인한 새 글 중 아직 열지 않은 글 (열어 본 키워드만 알 수 있음)
    function unreadOf(l) {
        if (l.seen_max == null) return 0;
        const read = new Set(l.read_ids || []);
        return (l.found_ids || []).filter(no => no > l.seen_max && !read.has(no)).length;
    }
    const groupUnread = g => g.links.reduce((n, l) => n + unreadOf(l), 0);
    // 다음 키워드: 안 읽은 새 글이 남은 키워드 먼저(많은 순), 그다음 오늘 아직 안 본 것 중 가장 오래 안 본 것 (같으면 등록 순). 지금 보는 것은 빼고
    function nextLink() {
        const key = x => (x.l.last_opened ? new Date(x.l.last_opened.replace(' ', 'T')).getTime() : -1);
        const list = allLinks().map((x, i) => ({ ...x, i })).filter(x => !isCurrent(x.l));
        const withNew = list.filter(x => unreadOf(x.l)).sort((a, b) => unreadOf(b.l) - unreadOf(a.l) || a.i - b.i);
        if (withNew.length) return withNew[0];
        return list.filter(x => !openedToday(x.l)).sort((a, b) => key(a) - key(b) || a.i - b.i)[0] || null;
    }
    const chipHtml = (g, l) => {
        const unread = unreadOf(l);
        return `
        <a class="chip${isCurrent(l) ? ' on' : ''}${isStale(l.last_opened) ? ' stale' : ''}${openedToday(l) && !unread ? ' done' : ''}" href="${esc(searchUrl(l.board, l.keyword))}"
           data-board="${esc(l.board)}" data-keyword="${esc(l.keyword)}" data-group="${g.id}">
            <span class="kw">${esc(l.keyword)}${unread ? `<span class="newb">${MOBILE ? '' : '새 '}${unread}</span>` : ''}</span>${MOBILE ? '' : `<small>${esc(isCurrent(l) ? '지금 보는 중' : agoText(l.last_opened))}</small>`}</a>`;
    };
    function progressHtml() {
        const all = allLinks(), done = all.filter(x => openedToday(x.l)).length;
        const next = nextLink();
        const nextBtn = next
            ? `<button class="next" data-next title="안 읽은 새 글이 남은 키워드 → 오늘 아직 안 본 키워드 중 가장 오래 안 본 것 (단축키 ])">다음 ▶${MOBILE ? '' : `<small>${esc(next.l.keyword)}</small>`}</button>`
            : `<span class="next alldone">오늘 모두 확인 ✓</span>`;
        return `<span class="prog" title="오늘 연 키워드">오늘 ${done}/${all.length}${MOBILE ? '' : `<span class="pbar"><i style="width:${all.length ? Math.round(done / all.length * 100) : 0}%"></i></span>`}</span>${nextBtn}`;
    }
    // ---------- 키워드 줄에서 바로 추가 ----------
    // 목록에 없는 검색을 직접 보고 있으면 '+ 추가' 단추. 누르면 넣을 카드를 고름 (이 게시판을 가장 많이 쓰는 카드가 맨 위)
    let addOpen = false, addBusy = false, addError = '', typedPwd = '';
    const canAdd = () => !!currentKeyword && groups.length > 0 && !allLinks().some(x => isCurrent(x.l))
        && (currentBoard === '' || /^[a-z][a-z0-9_]{0,39}$/i.test(currentBoard));
    function addCandidates() {
        const uses = g => g.links.filter(l => l.board === currentBoard).length;
        return groups.map((g, i) => ({ g, i, n: uses(g) })).sort((a, b) => b.n - a.n || a.i - b.i);
    }
    function pickerHtml() {
        if (!addOpen) return '';
        const list = addCandidates();
        const where = currentBoard ? '이 게시판' : '전체 검색';
        const full = g => g.links.length >= 30;
        return `<div class="picker" role="dialog" aria-label="FM키워드에 추가">
            <button class="x" data-addclose aria-label="닫기">✕</button>
            <div class="ph">${esc(where)} · <b>'${esc(currentKeyword)}'</b>를 넣을 카드</div>
            ${GM_getValue(KEY_PWD, '') ? '' : `<input type="password" data-addpwd placeholder="관리자 비밀번호 (처음 한 번만)" autocomplete="off" value="${esc(typedPwd)}">`}
            ${list.map((x, k) => `<button class="to${k === 0 && x.n ? ' best' : ''}" data-addto="${x.g.id}" ${addBusy || full(x.g) ? 'disabled' : ''}>${esc(x.g.name)}${
                full(x.g) ? '<small>30개가 다 찼음</small>' : k === 0 && x.n ? `<small>${currentBoard ? "이 게시판을" : "전체 검색을"} 가장 많이 씀</small>` : ''}</button>`).join('')}
            ${addError ? `<div class="err">${esc(addError)}</div>` : ''}
        </div>`;
    }
    async function addTo(groupId) {
        const group = groups.find(g => g.id === groupId);
        const password = GM_getValue(KEY_PWD, '') || typedPwd.trim();
        if (!group || addBusy) return;
        if (!password) { addError = '관리자 비밀번호를 넣어 주세요'; render(); return; }
        addBusy = true; addError = ''; render();
        const { status, data } = await requestRaw('POST', '/api/fm-link', { action: 'add', group_id: groupId, board: currentBoard, keyword: currentKeyword, password });
        addBusy = false;
        if (status !== 200 || !data.success) {
            if (status === 401) { GM_setValue(KEY_PWD, ''); addError = '비밀번호가 맞지 않습니다'; }
            else addError = (data.message || (status ? `추가하지 못했습니다 (${status})` : '키워드 모니터에 연결하지 못했습니다')).replace(/^❌\s*/, '');
            render();
            return;
        }
        GM_setValue(KEY_PWD, password);
        typedPwd = '';
        // 받은 목록으로 바꾸되 새 글 기록은 이어 감. 지금 보는 검색이므로 '방금 전'으로
        const old = new Map(group.links.map(l => [l.board + '\u001f' + l.keyword, l]));
        group.links = data.links.map(l => ({ seen_max: null, read_ids: [], found_ids: [], ...(old.get(l.board + '\u001f' + l.keyword) || {}), ...l }));
        const link = group.links.find(isCurrent);
        if (link) {
            link.last_opened = nowText();
            request('POST', '/api/fm-link', { action: 'open', group_id: group.id, board: link.board, keyword: link.keyword }).catch(() => {});
        }
        addOpen = false; openTouched = false; mobileTouched = false;
        saveCache();
        markNewPosts();
    }
    // ---------- 검색 결과 이전·다음 글 ----------
    // 검색 결과 화면에서 본 목록(이미 화면에 떠 있는 것)을 순서대로 기억해 두고, 그 목록의 글을 열면 줄에 ◀ 이전 · n/전체 · 다음 ▶ ·
    // 다음 새 글 · 목록. 마지막 글에서는 다음 쪽 검색 결과로. 에펨코리아에는 내가 누른 화면만 열림 (미리 받아 오지 않음)
    function loadTrail() {
        try {
            const t = GM_getValue(KEY_TRAIL, null);
            return t && Array.isArray(t.posts) && Date.now() - (t.at || 0) < TRAIL_MAX_AGE ? t : null;
        } catch (err) { reportError('trail-load', err); return null; }
    }
    const trail = loadTrail();
    const trailIndex = () => (trail && pagePostNo ? trail.posts.findIndex(p => p.no === pagePostNo) : -1);
    function trailLink() {
        return trail ? allLinks().map(x => x.l).find(l => l.board === trail.board && l.keyword === trail.keyword) : null;
    }
    // 이 글 뒤로(없으면 앞에서부터) 아직 안 읽은 새 글
    function nextNewPost() {
        const i = trailIndex(), l = trailLink();
        if (i < 0 || !l || l.seen_max == null) return null;
        const read = new Set(l.read_ids || []);
        const isNew = p => p.no > l.seen_max && !read.has(p.no) && p.no !== pagePostNo;
        return trail.posts.slice(i + 1).find(isNew) || trail.posts.slice(0, i).find(isNew) || null;
    }
    function pageUrl(delta) {
        try {
            const u = new URL(trail.url);
            const page = Math.max(1, (Number(u.searchParams.get('page')) || 1) + delta);
            if (page === 1) u.searchParams.delete('page'); else u.searchParams.set('page', String(page));
            return u.href;
        } catch (e) { return ''; }
    }
    function postNavHtml() {
        try { return postNavInner(); } catch (err) { reportError('trail-nav', err); return ''; }
    }
    function postNavInner() {
        const i = trailIndex();
        if (i < 0) return '';
        const n = trail.posts.length, prev = trail.posts[i - 1], next = trail.posts[i + 1], fresh = nextNewPost();
        const tip = (p, key) => p ? ` title="${esc(p.title)}${MOBILE ? '' : ` (단축키 ${key})`}"` : '';
        const nextBtn = next
            ? `<button data-pnav="next"${tip(next, 'j')}>다음 ▶</button>`
            : `<button data-pnav="nextpage" title="다음 쪽 검색 결과${MOBILE ? '' : ' (단축키 j)'}">다음 쪽 ▶</button>`;
        return `<span class="pnav">
            <button data-pnav="prev"${tip(prev, 'k')} ${prev ? '' : 'disabled'}>◀${MOBILE ? '' : ' 이전'}</button>
            <span class="ppos" title="'${esc(trail.keyword)}' 검색 결과"><b>${i + 1}/${n}</b>${MOBILE ? '' : ` · ${esc(trail.keyword)}`}</span>
            ${nextBtn}
            ${fresh ? `<button class="pnew" data-pnav="new"${tip(fresh, 'n')}>새 글 ▶▶</button>` : ''}
            <button data-pnav="list" title="검색 결과로${MOBILE ? '' : ' (단축키 u)'}">목록</button></span>`;
    }
    function goTrail(action) {
        const i = trailIndex();
        if (i < 0) return false;
        let url = '';
        if (action === 'prev' && trail.posts[i - 1]) url = trail.posts[i - 1].href;
        else if (action === 'next') url = trail.posts[i + 1] ? trail.posts[i + 1].href : pageUrl(1);
        else if (action === 'nextpage') url = pageUrl(1);
        else if (action === 'new') { const p = nextNewPost(); url = p ? p.href : ''; }
        else if (action === 'list') url = trail.url;
        if (!url) return false;
        location.href = url;
        return true;
    }
    // 검색 결과 화면이면 목록을 기억 (글 화면에 붙은 목록은 기억하지 않음: 그 글을 연 검색 결과가 기준)
    function saveTrail() {
        if (!currentKeyword || pagePostNo) return;
        const rows = resultRows();
        if (!rows.length) return;
        const posts = rows.map(x => ({ no: x.no, href: new URL(x.title.getAttribute('href'), location.href).href,
                                       title: x.title.textContent.replace(/\s+/g, ' ').trim().slice(0, 120) }));
        GM_setValue(KEY_TRAIL, { board: currentBoard, keyword: currentKeyword, url: location.href, at: Date.now(), posts });
    }

    const countHtml = g => `<span class="cnt">${g.links.length}${groupUnread(g) ? ` · <span class="newg">새 ${groupUnread(g)}</span>` : ''}${staleCount(g) ? ` · 오래 안 봄 <b>${staleCount(g)}</b>` : ''}</span>`;

    function render(message) {
        try { renderBar(message); } catch (err) { reportError('render', err); }
    }
    function renderBar(message) {
        const folded = GM_getValue(KEY_FOLDED, false);
        const place = MOBILE ? 'bottom' : 'top';
        let html;
        if (message) {
            html = `<div class="bar ${place}"><span class="title">FM키워드</span> <span class="msg">${esc(message)}</span></div>`;
        } else if (folded) {
            html = `<div class="bar ${place} mini" data-unfold>FM키워드 ${MOBILE ? '▴' : '▾'}</div>`;
        } else {
            const addBtn = canAdd() && !(compact && !MOBILE)
                ? `<button class="add" data-add title="지금 보는 검색을 FM키워드에 추가">+ ${MOBILE ? '추가' : `'${esc(currentKeyword)}' 추가`}</button>` : '';
            const side = `<span class="side">${postNavHtml()}${addBtn}${progressHtml()}${MOBILE ? '' : `<a href="${SITE}/board/#fm" target="_blank" rel="noopener">키워드 모니터 ↗</a>`}<button data-fold>${MOBILE ? '숨기기 ▾' : '접기 ▴'}</button></span>`;
            if (MOBILE) {
                // 윗줄: 묶음 이름 (누르면 아랫줄이 그 묶음으로, 같은 것을 다시 누르면 아랫줄 접힘), 아랫줄: 고른 묶음의 키워드
                const picked = groups.find(g => g.id === mobileGroupId());
                const names = groups.map(g => `<button class="gp${picked === g ? ' on' : ''}" data-mgroup="${g.id}">${esc(g.name)}${groupUnread(g) ? `<span class="newg">새 ${groupUnread(g)}</span>` : `<span class="cnt">${g.links.length}</span>`}</button>`).join('');
                html = `<div class="bar bottom"><div class="head"><span class="title">FM키워드</span>${side}</div>
                    <div class="groups">${names}</div>${picked ? `<div class="chips">${picked.links.map(l => chipHtml(picked, l)).join('')}</div>` : ''}</div>`;
            } else if (compact) {
                // 얇은 줄: 묶음 이름만 (누르면 그 묶음을 펼친 원래 줄로)
                const cur = currentGroup();
                const names = groups.map(g => `<button class="gh${cur === g ? ' cur' : ''}" data-cgroup="${g.id}">▸ ${esc(g.name)}${groupUnread(g) ? '<span class="dot" title="안 읽은 새 글"></span>' : ''}</button>`).join('');
                html = `<div class="bar top compact"><span class="title">FM키워드</span><div class="names">${names}</div>${side}</div>`;
            } else {
                // 묶음 상자: 접히면 이름·개수, 펼치면 그 자리에 키워드 칩 (여러 개 함께 펼침)
                const open = openIds();
                const boxes = groups.map(g => open.has(g.id)
                    ? `<span class="box open"><button class="gh" data-toggle="${g.id}" aria-expanded="true">▾ ${esc(g.name)}</button>${g.links.map(l => chipHtml(g, l)).join('')}</span>`
                    : `<span class="box"><button class="gh" data-toggle="${g.id}" aria-expanded="false">▸ ${esc(g.name)} ${countHtml(g)}</button></span>`).join('');
                html = `<div class="bar top"><div class="head"><span class="title">FM키워드</span></div><div class="boxes">${boxes}</div>${side}</div>`;
            }
        }
        if (!message && !folded && !(compact && !MOBILE) && canAdd()) html = html.replace(/<\/div>$/, pickerHtml() + '</div>');
        root.innerHTML = `<style>${CSS}</style>${html}`;
        if (!host.isConnected) return;
        // 에펨코리아 화면의 맨 위·맨 아래가 줄에 가리지 않게 그만큼 여백.
        // 얇은 줄일 때는 여백을 그대로 둠: 스크롤 중에 여백이 바뀌면 보고 있던 글이 위아래로 덜컹거림 (맨 위는 원래 줄이 덮음)
        if (compact && !MOBILE && !message) return;
        const bar = root.querySelector('.bar');
        const height = bar.getBoundingClientRect().height;
        document.documentElement.style.setProperty(MOBILE ? 'padding-bottom' : 'padding-top', height + 'px', 'important');
        const active = root.querySelector('a.chip.on');
        if (active && MOBILE) active.scrollIntoView({ block: 'nearest', inline: 'center' });
    }

    // 누른 시각을 서버에 보냄. 보내기 전에 '보낼 기록'에 적어 두고, 보내지면 지움 (같은 기록이 두 번 가도 시각만 다시 적힘)
    const pendingKey = x => `${x.group_id}|${x.board}|${x.keyword}`;
    function sendOpen(item) {
        return request('POST', '/api/fm-link', { action: 'open', group_id: item.group_id, board: item.board, keyword: item.keyword }).then(() => {
            GM_setValue(KEY_PENDING, GM_getValue(KEY_PENDING, []).filter(x => !(pendingKey(x) === pendingKey(item) && x.at <= item.at)));
        }, err => {
            // 없는 바로가기(그사이 지워짐)면 버림, 연결이 안 되면 다음 화면에서 다시
            if (String(err && err.message) === '404') GM_setValue(KEY_PENDING, GM_getValue(KEY_PENDING, []).filter(x => pendingKey(x) !== pendingKey(item)));
        });
    }
    // 같은 탭에서 그 검색으로 바로 넘어감 (서버 답을 기다리지 않음). 새 화면에서 바로 '방금 전'으로 보이게 기억해 둔 목록에도 반영
    function openLink(group, link) {
        link.last_opened = nowText();
        GM_setValue(KEY_CACHE, JSON.stringify(groups));
        const item = { group_id: group.id, board: link.board, keyword: link.keyword, at: link.last_opened };
        GM_setValue(KEY_PENDING, [...GM_getValue(KEY_PENDING, []).filter(x => pendingKey(x) !== pendingKey(item)), item].slice(-50));
        sendOpen(item);
        location.href = searchUrl(link.board, link.keyword);
    }
    function goNext() { const next = nextLink(); if (next) openLink(next.g, next.l); }

    // 단축키 (PC): ] 다음 키워드, [ 방금 보던 화면으로, \ 줄 펼치기·접기. 글을 쓰는 중이거나 Ctrl·Alt 등과 함께 누르면 무시
    if (!MOBILE) {
        document.addEventListener('keydown', e => {
            if (e.ctrlKey || e.metaKey || e.altKey || !groups.length) return;
            const t = (e.composedPath && e.composedPath()[0]) || e.target;
            if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
            if (e.key === ']') { e.preventDefault(); goNext(); }
            else if ('jknu'.includes(e.key) && e.key.length === 1 && trailIndex() >= 0) {
                if (goTrail({ j: 'next', k: 'prev', n: 'new', u: 'list' }[e.key])) e.preventDefault();
            }
            else if (e.key === '[') { e.preventDefault(); history.back(); }
            else if (e.key === '\\') { e.preventDefault(); GM_setValue(KEY_FOLDED, !GM_getValue(KEY_FOLDED, false)); render(); }
        }, true);
    }

    root.addEventListener('click', e => {
        const chip = e.target.closest('a.chip');
        if (chip) {
            // 누른 시각을 남기고 같은 탭에서 그 검색으로
            if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return;
            e.preventDefault();
            const group = groups.find(g => g.id === Number(chip.dataset.group));
            const link = group && group.links.find(l => l.board === chip.dataset.board && l.keyword === chip.dataset.keyword);
            if (link) openLink(group, link);
            return;
        }
        if (e.target.closest('[data-next]')) { goNext(); return; }
        const pnav = e.target.closest('[data-pnav]');
        if (pnav) { goTrail(pnav.dataset.pnav); return; }
        if (e.target.closest('[data-add]')) { addOpen = !addOpen; addError = ''; render(); const pwd = root.querySelector('[data-addpwd]'); if (pwd) pwd.focus(); return; }
        if (e.target.closest('[data-addclose]')) { addOpen = false; render(); return; }
        const addto = e.target.closest('[data-addto]');
        if (addto) { addTo(Number(addto.dataset.addto)); return; }
        const toggle = e.target.closest('[data-toggle]');
        if (toggle) {
            // 다른 묶음을 펼치면 펼쳐져 있던 묶음은 접힘, 펼친 묶음을 다시 누르면 모두 접힘
            const id = Number(toggle.dataset.toggle);
            const open = openIds().has(id) ? [] : [id];
            openTouched = true;
            GM_setValue(KEY_OPEN, open);
            render();
            return;
        }
        const cgroup = e.target.closest('[data-cgroup]');
        if (cgroup) {
            openTouched = true;
            GM_setValue(KEY_OPEN, [Number(cgroup.dataset.cgroup)]);
            compact = false;
            lastY = window.scrollY;
            render();
            return;
        }
        const mgroup = e.target.closest('[data-mgroup]');
        if (mgroup) {
            const id = Number(mgroup.dataset.mgroup);
            const shown = mobileGroupId();
            mobileTouched = true;
            GM_setValue(KEY_MOBILE, shown === id ? 0 : id);
            render();
            const on = root.querySelector('.gp.on');
            if (on) on.scrollIntoView({ block: 'nearest', inline: 'center' });
            return;
        }
        if (e.target.closest('[data-fold]')) { GM_setValue(KEY_FOLDED, true); render(); return; }
        if (e.target.closest('[data-unfold]')) { GM_setValue(KEY_FOLDED, false); render(); }
    });

    root.addEventListener('input', e => { if (e.target.matches('[data-addpwd]')) typedPwd = e.target.value; });

    // 휴대폰: 아래로 스크롤하면 줄이 내려가 숨고, 위로 올리거나 맨 위·맨 아래에 닿으면 다시 보임 (10px 안의 떨림은 무시)
    if (!MOBILE) {
        window.addEventListener('scroll', () => {
            if (!groups.length || GM_getValue(KEY_FOLDED, false)) return;
            const y = window.scrollY;
            let next = compact;
            if (y <= 0) next = false;
            else if (y - lastY > 10) next = true;
            else if (lastY - y > 10) next = false;
            else return;
            lastY = y;
            if (next !== compact) { compact = next; render(); }
        }, { passive: true });
    }
    if (MOBILE) {
        window.addEventListener('scroll', () => {
            const bar = root.querySelector('.bar');
            if (!bar) return;
            const y = window.scrollY;
            const atEdge = y <= 0 || window.innerHeight + y >= document.documentElement.scrollHeight - 2;
            if (atEdge) bar.classList.remove('gone');
            else if (y - lastY > 10) bar.classList.add('gone');
            else if (lastY - y > 10) bar.classList.remove('gone');
            else return;
            lastY = y;
        }, { passive: true });
    }

    // ---------- 새 글 표시 (기기끼리 공유) ----------
    // 지금 보는 검색 결과(이미 브라우저에 떠 있는 화면)에서 글 번호만 읽음. 키워드마다 기준 글 번호(seen_max)보다 큰 글이 새 글이고,
    // 그 글을 직접 열기 전까지 계속 새 글(NEW). '모두 읽음'을 누르면 기준이 그 화면의 가장 큰 번호로.
    // 기준과 읽은 글 번호는 키워드 모니터 서버에 두어 PC·휴대폰이 같게 봄 (서버는 에펨코리아에 요청하지 않음)
    const postNumber = href => {
        const m = /document_srl=(\d+)/.exec(href || '') || /^\/(\d{5,})(?:[?#]|$)/.exec((href || '').replace(/^https?:\/\/[^/]+/, ''));
        return m ? Number(m[1]) : 0;
    };
    function resultRows() {
        let rows = [...document.querySelectorAll('table.bd_lst tbody tr:not(.notice)')];
        let titleOf = row => row.querySelector('td.title a.hx') || row.querySelector('td.title a');
        if (!rows.length) {   // 휴대폰 화면 등 표가 아닌 목록: 글로 가는 링크를 담은 줄
            const seen = new Set();
            rows = [];
            document.querySelectorAll('a[href]').forEach(a => {
                if (!postNumber(a.getAttribute('href')) || a.closest('#keyword-monitor-fm-bar, header, nav, .notice')) return;
                const row = a.closest('li, tr');
                if (row && !seen.has(row)) { seen.add(row); rows.push(row); }
            });
            titleOf = row => [...row.querySelectorAll('a[href]')].find(a => postNumber(a.getAttribute('href')));
        }
        return rows.map(row => ({ row, title: titleOf(row) })).filter(x => x.title)
            .map(x => ({ ...x, no: postNumber(x.title.getAttribute('href')) })).filter(x => x.no);
    }
    function saveCache() {
        cachedJson = JSON.stringify(groups);
        GM_setValue(KEY_CACHE, cachedJson);
    }
    let styled = false;
    function addStyle() {
        if (styled) return;
        styled = true;
        const style = document.createElement('style');
        style.textContent = `.kmfm-new { background: #E6F1FB !important; box-shadow: inset 3px 0 0 #185FA5; }
            .kmfm-tag { display: inline-block; margin-right: 6px; padding: 0 5px; border-radius: 4px; background: #185FA5; color: #fff; font-size: 11px; font-weight: 700; line-height: 17px; vertical-align: 1px; }
            .kmfm-line td, li.kmfm-line { padding: 4px !important; text-align: center; color: #185FA5; font-size: 12px; border-bottom: 1px dashed #85B7EB; list-style: none; }
            .kmfm-note { display: flex; align-items: center; gap: 10px; margin: 6px 0; padding: 6px 10px; border-radius: 8px; background: #E6F1FB; color: #0C447C; font-size: 13px; }
            .kmfm-note button { margin-left: auto; border: 1px solid #185FA5; background: #fff; color: #185FA5; border-radius: 6px; padding: 3px 10px; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }`;
        (document.head || document.documentElement).appendChild(style);
    }
    function clearMarks() {
        document.querySelectorAll('.kmfm-new').forEach(row => row.classList.remove('kmfm-new'));
        document.querySelectorAll('.kmfm-tag, .kmfm-line, .kmfm-note').forEach(el => el.remove());
    }
    function markNewPosts() {
        clearMarks();
        const cur = allLinks().find(x => isCurrent(x.l));
        const rows = cur ? resultRows() : [];
        if (!rows.length) { render(); return; }
        const link = cur.l;
        if (link.seen_max == null) {
            // 처음 여는 키워드: 지금 화면의 가장 최근 글을 기준으로 (예전 버전이 이 브라우저에 기억한 기준이 있으면 그것을 이어 씀)
            const old = GM_getValue(`fm_seen:${link.board}|${link.keyword}`, null);
            link.seen_max = old && old.max ? old.max : Math.max(...rows.map(x => x.no));
            link.read_ids = [];
            saveCache();
            request('POST', '/api/fm-link', { action: 'seen_init', board: link.board, keyword: link.keyword, max: link.seen_max }).then(data => {
                // 다른 기기가 먼저 정한 기준이 있으면 그것을 따름
                if (data.seen_max !== link.seen_max) { link.seen_max = data.seen_max; link.read_ids = data.read_ids; saveCache(); markNewPosts(); }
            }, () => {});
        }
        const read = new Set(link.read_ids || []);
        const since = rows.filter(x => x.no > link.seen_max);
        const unread = since.filter(x => !read.has(x.no));
        // 이 화면에서 확인한 새 글 번호를 기억 (키워드 줄에 '새 N'을 계속 보이게, 서버에도 두어 기기끼리 같게)
        const found = new Set(link.found_ids || []);
        const added = since.map(x => x.no).filter(no => !found.has(no));
        if (added.length) {
            link.found_ids = [...found, ...added].sort((a, b) => a - b);
            saveCache();
            request('POST', '/api/fm-link', { action: 'found', board: link.board, keyword: link.keyword, max: link.seen_max, ids: added.slice(0, 100) }).catch(() => {});
        }
        // 안 읽은 새 글이 남았을 때만 안내 줄·구분선 (다 읽었으면 '모두 읽음'을 누르지 않아도 없음)
        if (unread.length) {
            addStyle();
            unread.forEach(x => {
                x.row.classList.add('kmfm-new');
                const tag = document.createElement('span');
                tag.className = 'kmfm-tag';
                tag.textContent = 'NEW';
                x.title.prepend(tag);
            });
            const last = since[since.length - 1].row;
            if (since.length < rows.length) {
                const line = document.createElement(last.tagName === 'TR' ? 'tr' : 'li');
                line.className = 'kmfm-line';
                const text = '여기까지 마지막으로 모두 읽은 뒤 올라온 글';
                line.innerHTML = last.tagName === 'TR' ? `<td colspan="20">${text}</td>` : text;
                last.after(line);
            }
            const note = document.createElement('div');
            note.className = 'kmfm-note';
            note.innerHTML = `<span>안 읽은 새 글 ${unread.length}개</span><button type="button" data-kmfm-readall>모두 읽음</button>`;
            const list = rows[0].row.closest('table, ul, ol') || rows[0].row;
            list.parentNode.insertBefore(note, list);
            note.querySelector('[data-kmfm-readall]').addEventListener('click', () => readAll(link, Math.max(...rows.map(x => x.no))));
        }
        render();
    }
    // '모두 읽음': 기준을 이 화면의 가장 큰 글 번호로
    function readAll(link, top) {
        link.seen_max = Math.max(link.seen_max || 0, top);
        link.read_ids = (link.read_ids || []).filter(no => no > link.seen_max);
        link.found_ids = (link.found_ids || []).filter(no => no > link.seen_max);
        saveCache();
        request('POST', '/api/fm-link', { action: 'read_all', board: link.board, keyword: link.keyword, max: top }).catch(() => {});
        markNewPosts();
    }
    // 글 하나를 읽음으로 표시 (목록 안에서만): 그 글이 새 글인 모든 키워드에서. 바뀌었으면 true
    function applyRead(list, no) {
        let changed = false;
        list.forEach(g => g.links.forEach(l => {
            if (l.seen_max == null || no <= l.seen_max || (l.read_ids || []).includes(no)) return;
            l.read_ids = [...(l.read_ids || []), no];
            changed = true;
        }));
        return changed;
    }
    // 읽음을 서버에 보냄. 보내기 전에 '보낼 기록'에 적어 두고, 보내지면 지움 (같은 글을 두 번 보내도 그대로)
    function sendRead(no) {
        return request('POST', '/api/fm-link', { action: 'read', post: no }).then(() => {
            GM_setValue(KEY_PENDING_READS, GM_getValue(KEY_PENDING_READS, []).filter(x => x !== no));
        }, () => {});
    }
    // 글 하나를 읽음으로: 그 글이 새 글인 모든 키워드에서 (같은 글이 여러 키워드에 걸려도 함께)
    function markRead(no) {
        GM_setValue(KEY_PENDING_READS, [...GM_getValue(KEY_PENDING_READS, []).filter(x => x !== no), no].slice(-200));
        if (applyRead(groups, no)) { saveCache(); render(); }
        sendRead(no);
    }
    // 검색 결과에서 글을 누르면(가운데 버튼·새 탭 포함) 읽음
    ['click', 'auxclick'].forEach(type => document.addEventListener(type, e => {
        const a = e.target.closest && e.target.closest('a[href]');
        if (!a || a.closest('#keyword-monitor-fm-bar')) return;
        const no = postNumber(a.getAttribute('href'));
        if (!no || !a.closest('.kmfm-new')) return;
        markRead(no);
        const row = a.closest('.kmfm-new');
        if (row) { row.classList.remove('kmfm-new'); const tag = row.querySelector('.kmfm-tag'); if (tag) tag.remove(); }
    }, true));
    // 다른 경로로 글을 열어도 읽음 (글 화면 주소의 번호. 검색 결과에서 연 글은 주소에 검색어가 붙어 있어도)
    const pagePost = pagePostNo;
    if (pagePost) markRead(pagePost);

    // 화면이 다 그려지고 키워드 목록이 있을 때 (처음 설치해 목록이 없으면 서버에서 받은 뒤). 새 목록을 받으면 다시 (다른 기기에서 읽은 글 반영)
    let marked = false;
    // 검색 결과 목록은 키워드 목록과 상관없이 화면이 다 그려지면 기억 (FM키워드에 없는 검색도 이전·다음 글로)
    function trySaveTrail() {
        if (document.readyState === 'loading') return;
        try { saveTrail(); } catch (err) { reportError('trail-save', err); }
    }
    document.addEventListener('DOMContentLoaded', trySaveTrail, { once: true });
    trySaveTrail();
    function tryMark() {
        if (marked || !groups.length || document.readyState === 'loading') return;
        marked = true;
        markNewPosts();
    }
    document.addEventListener('DOMContentLoaded', tryMark, { once: true });
    tryMark();

    applyPending(groups);
    // 기억해 둔 목록이 있으면 바로 그리고, 서버의 새 목록이 다를 때만 다시 그림 (처음 설치했을 때만 받을 때까지 기다림)
    if (groups.length) render();
    // 아직 서버에 닿지 않은 누른 시각·읽음은 목록에도 반영 ('방금 전'이 예전 시각으로, 읽은 글이 다시 새 글로 돌아가지 않게)
    function applyPending(list) {
        GM_getValue(KEY_PENDING, []).forEach(x => {
            const g = list.find(f => f.id === x.group_id);
            const l = g && g.links.find(y => y.board === x.board && y.keyword === x.keyword);
            if (l && (!l.last_opened || l.last_opened < x.at)) l.last_opened = x.at;
        });
        GM_getValue(KEY_PENDING_READS, []).forEach(no => applyRead(list, no));
    }
    // 앞 화면에서 못 보낸 기록을 다시 보냄
    function flushPending() {
        GM_getValue(KEY_PENDING, []).forEach(sendOpen);
        GM_getValue(KEY_PENDING_READS, []).forEach(sendRead);
    }
    function refresh() {
        request('GET', '/api/fm-links').then(data => {
            const fresh = (data.groups || []).filter(g => g.links.length);
            applyPending(fresh);
            const json = JSON.stringify(fresh);
            if (json === cachedJson && groups.length) return;
            cachedJson = json;
            GM_setValue(KEY_CACHE, json);
            groups = fresh;
            if (!groups.length) render('등록한 키워드가 없습니다');
            else { render(); if (marked) markNewPosts(); else tryMark(); }
        }, () => { if (!groups.length) render('키워드 모니터에 연결하지 못했습니다'); });
    }
    flushPending();
    refresh();
    // 뒤로 가기 등으로 브라우저가 앞 화면을 그대로 되살리면 스크립트가 다시 돌지 않으므로, 다른 화면에서 바뀐 목록(읽은 글 등)으로 다시 그림
    window.addEventListener('pageshow', e => {
        if (!e.persisted) return;
        try {
            const json = GM_getValue(KEY_CACHE, '');
            if (json) { groups = JSON.parse(json); cachedJson = json; }
        } catch (err) { /* 기억한 목록이 깨졌으면 서버에서 받은 것으로 */ }
        applyPending(groups);
        compact = false;
        lastY = window.scrollY;
        if (groups.length) { render(); if (marked) markNewPosts(); else tryMark(); }
        flushPending();
        refresh();
    });
    } catch (err) {
        reportError('start', err);
    }
})();
