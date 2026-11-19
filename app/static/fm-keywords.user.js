// ==UserScript==
// @name         FM키워드 줄 (키워드 모니터)
// @namespace    keyword-monitor
// @version      1.2.0
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
    const STALE_DAYS = 7;
    // 휴대폰: 좁은 화면이거나 브라우저가 휴대폰이라고 알려 줄 때 (휴대폰에서 PC용 화면을 열어 폭이 넓게 잡혀도 휴대폰으로).
    // 터치 화면 노트북·PC용 삼성 인터넷은 PC로
    const MOBILE = window.matchMedia('(max-width: 899px)').matches
        || !!(navigator.userAgentData && navigator.userAgentData.mobile) || /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
    // 기기마다 기억: 줄 전체 접힘, PC에서 펼친 묶음 ID들, 휴대폰에서 고른 묶음 ID (0이면 아랫줄 접힘)
    const KEY_FOLDED = 'fm_bar_folded', KEY_OPEN = 'fm_bar_open', KEY_MOBILE = 'fm_bar_mobile_group';
    // 마지막으로 받은 키워드 목록: 새 화면이 열리면 서버를 기다리지 않고 이것으로 바로 그린 뒤, 새 목록이 다르면 다시 그림
    const KEY_CACHE = 'fm_bar_cache';

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
        .newb { position: absolute; top: -7px; right: -7px; background: #185FA5; color: #fff; font-size: 10px; font-weight: 700; border-radius: 999px; padding: 0 5px; line-height: 15px; }
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
    `;

    const currentGroup = () => groups.find(g => g.links.some(isCurrent));
    const staleCount = g => g.links.filter(l => isStale(l.last_opened)).length;
    // PC: 펼친 묶음 = 기억한 묶음 + 지금 보는 검색이 들어 있는 묶음 (이 화면에서 직접 접고 폈으면 기억한 그대로만)
    let openTouched = false;
    // PC: 아래로 스크롤하면 얇은 한 줄(묶음 이름만)로, 위로 올리거나 맨 위로 가면 원래대로 (줄 상태는 기억하지 않음)
    let compact = false;
    let lastY = window.scrollY;
    function openIds() {
        const saved = new Set(GM_getValue(KEY_OPEN, []));
        if (currentGroup() && !openTouched) saved.add(currentGroup().id);
        return saved;
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
    // 다음 키워드: 오늘 아직 안 본 것 중 가장 오래 안 본 것 (안 본 것 먼저, 같으면 등록 순). 지금 보는 것은 빼고
    function nextLink() {
        const key = x => (x.l.last_opened ? new Date(x.l.last_opened.replace(' ', 'T')).getTime() : -1);
        return allLinks().map((x, i) => ({ ...x, i })).filter(x => !openedToday(x.l) && !isCurrent(x.l))
            .sort((a, b) => key(a) - key(b) || a.i - b.i)[0] || null;
    }
    let newCount = 0;   // 지금 보는 검색 결과에서 지난번 이후 새 글 수 (지금 보는 칩에 표시)
    const chipHtml = (g, l) => `
        <a class="chip${isCurrent(l) ? ' on' : ''}${isStale(l.last_opened) ? ' stale' : ''}${openedToday(l) ? ' done' : ''}" href="${esc(searchUrl(l.board, l.keyword))}"
           data-board="${esc(l.board)}" data-keyword="${esc(l.keyword)}" data-group="${g.id}">
            ${esc(l.keyword)}${MOBILE ? '' : `<small>${esc(isCurrent(l) ? '지금 보는 중' : agoText(l.last_opened))}</small>`}${isCurrent(l) && newCount ? `<span class="newb">${MOBILE ? '' : '새 '}${newCount}</span>` : ''}</a>`;
    function progressHtml() {
        const all = allLinks(), done = all.filter(x => openedToday(x.l)).length;
        const next = nextLink();
        const nextBtn = next
            ? `<button class="next" data-next title="오늘 아직 안 본 키워드 중 가장 오래 안 본 것 (단축키 ])">다음 ▶${MOBILE ? '' : `<small>${esc(next.l.keyword)}</small>`}</button>`
            : `<span class="next alldone">오늘 모두 확인 ✓</span>`;
        return `<span class="prog" title="오늘 연 키워드">오늘 ${done}/${all.length}${MOBILE ? '' : `<span class="pbar"><i style="width:${all.length ? Math.round(done / all.length * 100) : 0}%"></i></span>`}</span>${nextBtn}`;
    }
    const countHtml = g => `<span class="cnt">${g.links.length}${staleCount(g) ? ` · 오래 안 봄 <b>${staleCount(g)}</b>` : ''}</span>`;

    function render(message) {
        const folded = GM_getValue(KEY_FOLDED, false);
        const place = MOBILE ? 'bottom' : 'top';
        let html;
        if (message) {
            html = `<div class="bar ${place}"><span class="title">FM키워드</span> <span class="msg">${esc(message)}</span></div>`;
        } else if (folded) {
            html = `<div class="bar ${place} mini" data-unfold>FM키워드 ${MOBILE ? '▴' : '▾'}</div>`;
        } else {
            const side = `<span class="side">${progressHtml()}${MOBILE ? '' : `<a href="${SITE}/board/#fm" target="_blank" rel="noopener">키워드 모니터 ↗</a>`}<button data-fold>${MOBILE ? '숨기기 ▾' : '접기 ▴'}</button></span>`;
            if (MOBILE) {
                // 윗줄: 묶음 이름 (누르면 아랫줄이 그 묶음으로, 같은 것을 다시 누르면 아랫줄 접힘), 아랫줄: 고른 묶음의 키워드
                const picked = groups.find(g => g.id === mobileGroupId());
                const names = groups.map(g => `<button class="gp${picked === g ? ' on' : ''}" data-mgroup="${g.id}">${esc(g.name)}<span class="cnt">${g.links.length}</span></button>`).join('');
                html = `<div class="bar bottom"><div class="head"><span class="title">FM키워드</span>${side}</div>
                    <div class="groups">${names}</div>${picked ? `<div class="chips">${picked.links.map(l => chipHtml(picked, l)).join('')}</div>` : ''}</div>`;
            } else if (compact) {
                // 얇은 줄: 묶음 이름만 (누르면 그 묶음을 펼친 원래 줄로)
                const cur = currentGroup();
                const names = groups.map(g => `<button class="gh${cur === g ? ' cur' : ''}" data-cgroup="${g.id}">▸ ${esc(g.name)}</button>`).join('');
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

    // 누른 시각을 남기고 같은 탭에서 그 검색으로 (새 화면에서 바로 '방금 전'으로 보이게 기억해 둔 목록에도 반영)
    function openLink(group, link) {
        link.last_opened = nowText();
        GM_setValue(KEY_CACHE, JSON.stringify(groups));
        const href = searchUrl(link.board, link.keyword);
        let gone = false;
        const go = () => { if (!gone) { gone = true; location.href = href; } };
        request('POST', '/api/fm-link', { action: 'open', group_id: group.id, board: link.board, keyword: link.keyword }).then(go, go);
        setTimeout(go, 800);
    }
    function goNext() { const next = nextLink(); if (next) openLink(next.g, next.l); }

    // 단축키 (PC): ] 다음 키워드, [ 방금 보던 화면으로, \ 줄 펼치기·접기. 글을 쓰는 중이거나 Ctrl·Alt 등과 함께 누르면 무시
    if (!MOBILE) {
        document.addEventListener('keydown', e => {
            if (e.ctrlKey || e.metaKey || e.altKey || !groups.length) return;
            const t = e.target;
            if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
            if (e.key === ']') { e.preventDefault(); goNext(); }
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
        const toggle = e.target.closest('[data-toggle]');
        if (toggle) {
            const open = openIds();
            const id = Number(toggle.dataset.toggle);
            if (open.has(id)) open.delete(id); else open.add(id);
            openTouched = true;
            GM_setValue(KEY_OPEN, [...open]);
            render();
            return;
        }
        const cgroup = e.target.closest('[data-cgroup]');
        if (cgroup) {
            const open = openIds();
            open.add(Number(cgroup.dataset.cgroup));
            openTouched = true;
            GM_setValue(KEY_OPEN, [...open]);
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
        newCount = 0;
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
        if (since.length) {
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
            note.innerHTML = unread.length
                ? `<span>안 읽은 새 글 ${unread.length}개</span><button type="button" data-kmfm-readall>모두 읽음</button>`
                : '<span>새 글을 모두 읽었습니다</span><button type="button" data-kmfm-readall>모두 읽음</button>';
            const list = rows[0].row.closest('table, ul, ol') || rows[0].row;
            list.parentNode.insertBefore(note, list);
            note.querySelector('[data-kmfm-readall]').addEventListener('click', () => readAll(link, Math.max(...rows.map(x => x.no))));
        }
        newCount = unread.length;
        render();
    }
    // '모두 읽음': 기준을 이 화면의 가장 큰 글 번호로
    function readAll(link, top) {
        link.seen_max = Math.max(link.seen_max || 0, top);
        link.read_ids = (link.read_ids || []).filter(no => no > link.seen_max);
        saveCache();
        request('POST', '/api/fm-link', { action: 'read_all', board: link.board, keyword: link.keyword, max: top }).catch(() => {});
        markNewPosts();
    }
    // 글 하나를 읽음으로: 그 글이 새 글인 모든 키워드에서 (같은 글이 여러 키워드에 걸려도 함께)
    function markRead(no) {
        let changed = false;
        allLinks().forEach(({ l }) => {
            if (l.seen_max == null || no <= l.seen_max || (l.read_ids || []).includes(no)) return;
            l.read_ids = [...(l.read_ids || []), no];
            changed = true;
        });
        if (changed) saveCache();
        request('POST', '/api/fm-link', { action: 'read', post: no }).catch(() => {});
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
    // 다른 경로로 글을 열어도 읽음 (글 화면 주소의 번호)
    const pagePost = !currentKeyword ? postNumber(location.pathname + location.search) : 0;
    if (pagePost) markRead(pagePost);

    // 화면이 다 그려지고 키워드 목록이 있을 때 (처음 설치해 목록이 없으면 서버에서 받은 뒤). 새 목록을 받으면 다시 (다른 기기에서 읽은 글 반영)
    let marked = false;
    function tryMark() {
        if (marked || !groups.length || document.readyState === 'loading') return;
        marked = true;
        markNewPosts();
    }
    document.addEventListener('DOMContentLoaded', tryMark, { once: true });
    tryMark();

    // 기억해 둔 목록이 있으면 바로 그리고, 서버의 새 목록이 다를 때만 다시 그림 (처음 설치했을 때만 받을 때까지 기다림)
    if (groups.length) render();
    request('GET', '/api/fm-links').then(data => {
        const fresh = (data.groups || []).filter(g => g.links.length);
        const json = JSON.stringify(fresh);
        if (json === cachedJson && groups.length) return;
        cachedJson = json;
        GM_setValue(KEY_CACHE, json);
        groups = fresh;
        if (!groups.length) render('등록한 키워드가 없습니다');
        else { render(); if (marked) markNewPosts(); else tryMark(); }
    }, () => { if (!groups.length) render('키워드 모니터에 연결하지 못했습니다'); });
})();
