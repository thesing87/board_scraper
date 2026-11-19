// ==UserScript==
// @name         FM키워드 줄 (키워드 모니터)
// @namespace    keyword-monitor
// @version      1.0.2
// @description  에펨코리아 화면에 키워드 모니터의 FM키워드 줄을 붙임. 키워드를 누르면 같은 탭에서 그 검색으로 (PC는 위, 휴대폰은 아래)
// @match        https://fmkorea.com/*
// @match        https://*.fmkorea.com/*
// @updateURL    __SITE__/fm-keywords.user.js
// @downloadURL  __SITE__/fm-keywords.user.js
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      __SITE_HOST__
// @run-at       document-end
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

    const host = document.createElement('div');
    host.id = 'keyword-monitor-fm-bar';
    const root = host.attachShadow({ mode: 'open' });
    document.body.appendChild(host);
    let groups = [];

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
        .side { margin-left: auto; display: flex; align-items: center; gap: 10px; flex: 0 0 auto; white-space: nowrap; }
        .side a, .side button { font: inherit; font-size: 12px; color: #993C1D; background: none; border: 0; padding: 0; cursor: pointer; text-decoration: none; }
        .mini { display: flex; justify-content: center; padding: 4px 0 calc(4px + env(safe-area-inset-bottom, 0px)); cursor: pointer; color: #993C1D; font-size: 12px; font-weight: 700; }
        .top.mini { justify-content: flex-start; padding: 3px 12px; }
        .msg { font-size: 12px; color: #993C1D; }
    `;

    const currentGroup = () => groups.find(g => g.links.some(isCurrent));
    const staleCount = g => g.links.filter(l => isStale(l.last_opened)).length;
    // PC: 펼친 묶음 = 기억한 묶음 + 지금 보는 검색이 들어 있는 묶음 (이 화면에서 직접 접고 폈으면 기억한 그대로만)
    let openTouched = false;
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
    const chipHtml = (g, l) => `
        <a class="chip${isCurrent(l) ? ' on' : ''}${isStale(l.last_opened) ? ' stale' : ''}" href="${esc(searchUrl(l.board, l.keyword))}"
           data-board="${esc(l.board)}" data-keyword="${esc(l.keyword)}" data-group="${g.id}">
            ${esc(l.keyword)}${MOBILE ? '' : `<small>${esc(agoText(l.last_opened))}</small>`}</a>`;
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
            const side = `<span class="side">${MOBILE ? '' : `<a href="${SITE}/board/#fm" target="_blank" rel="noopener">키워드 모니터 ↗</a>`}<button data-fold>${MOBILE ? '숨기기 ▾' : '접기 ▴'}</button></span>`;
            if (MOBILE) {
                // 윗줄: 묶음 이름 (누르면 아랫줄이 그 묶음으로, 같은 것을 다시 누르면 아랫줄 접힘), 아랫줄: 고른 묶음의 키워드
                const picked = groups.find(g => g.id === mobileGroupId());
                const names = groups.map(g => `<button class="gp${picked === g ? ' on' : ''}" data-mgroup="${g.id}">${esc(g.name)}<span class="cnt">${g.links.length}</span></button>`).join('');
                html = `<div class="bar bottom"><div class="head"><span class="title">FM키워드</span>${side}</div>
                    <div class="groups">${names}</div>${picked ? `<div class="chips">${picked.links.map(l => chipHtml(picked, l)).join('')}</div>` : ''}</div>`;
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
        // 에펨코리아 화면의 맨 위·맨 아래가 줄에 가리지 않게 그만큼 여백
        const bar = root.querySelector('.bar');
        const height = bar.getBoundingClientRect().height;
        document.documentElement.style.setProperty(MOBILE ? 'padding-bottom' : 'padding-top', height + 'px', 'important');
        const active = root.querySelector('a.chip.on');
        if (active && MOBILE) active.scrollIntoView({ block: 'nearest', inline: 'center' });
    }

    root.addEventListener('click', e => {
        const chip = e.target.closest('a.chip');
        if (chip) {
            // 누른 시각을 남기고 같은 탭에서 그 검색으로
            if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return;
            e.preventDefault();
            const go = () => { location.href = chip.href; };
            request('POST', '/api/fm-link', { action: 'open', group_id: Number(chip.dataset.group), board: chip.dataset.board, keyword: chip.dataset.keyword })
                .then(go, go);
            setTimeout(go, 800);
            return;
        }
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
    if (MOBILE) {
        let lastY = window.scrollY;
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

    request('GET', '/api/fm-links').then(data => {
        groups = (data.groups || []).filter(g => g.links.length);
        if (!groups.length) render('등록한 키워드가 없습니다');
        else render();
    }, () => render('키워드 모니터에 연결하지 못했습니다'));
})();
