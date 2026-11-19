// ==UserScript==
// @name         FM키워드 줄 (키워드 모니터)
// @namespace    keyword-monitor
// @version      1.0.0
// @description  에펨코리아 화면에 키워드 모니터의 FM키워드 줄을 붙임. 키워드를 누르면 같은 탭에서 그 검색으로 (PC는 위, 휴대폰은 아래)
// @match        https://www.fmkorea.com/*
// @match        https://m.fmkorea.com/*
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
    // 휴대폰: 좁은 화면이거나 손가락으로 누르는 기기 (휴대폰에서 PC용 화면을 열면 화면 폭이 넓게 잡혀도 휴대폰으로)
    const MOBILE = window.matchMedia('(max-width: 899px)').matches || window.matchMedia('(pointer: coarse)').matches;
    const KEY_GROUP = 'fm_bar_group', KEY_FOLDED = 'fm_bar_folded';

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
        select { font: inherit; font-size: 12px; padding: 2px 6px; border-radius: 6px; border: 1px solid #D85A30; background: #fff; color: #712B13; max-width: 140px; }
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

    let chosenId = null;   // 이 화면에서 상자로 고른 게시판
    function pickGroup() {
        const saved = Number(GM_getValue(KEY_GROUP, 0));
        // 방금 고른 게시판 → 지금 보는 검색이 들어 있는 게시판 → 지난번에 고른 게시판 → 첫 게시판
        return groups.find(g => g.id === chosenId) || groups.find(g => g.links.some(isCurrent))
            || groups.find(g => g.id === saved) || groups[0];
    }

    function render(message) {
        const folded = GM_getValue(KEY_FOLDED, false);
        const place = MOBILE ? 'bottom' : 'top';
        let html;
        if (message) {
            html = `<div class="bar ${place}"><span class="title">FM키워드</span> <span class="msg">${esc(message)}</span></div>`;
        } else if (folded) {
            html = `<div class="bar ${place} mini" data-unfold>FM키워드 ${MOBILE ? '▴' : '▾'}</div>`;
        } else {
            const group = pickGroup();
            const options = groups.map(g => `<option value="${g.id}" ${g === group ? 'selected' : ''}>${esc(g.name)}</option>`).join('');
            const chips = group.links.map(l => `
                <a class="chip${isCurrent(l) ? ' on' : ''}${isStale(l.last_opened) ? ' stale' : ''}" href="${esc(searchUrl(l.board, l.keyword))}"
                   data-board="${esc(l.board)}" data-keyword="${esc(l.keyword)}" data-group="${group.id}">
                    ${esc(l.keyword)}${MOBILE ? '' : `<small>${esc(agoText(l.last_opened))}</small>`}</a>`).join('');
            const side = `<span class="side">${MOBILE ? '' : `<a href="${SITE}/board/#fm" target="_blank" rel="noopener">키워드 모니터 ↗</a>`}<button data-fold>${MOBILE ? '숨기기 ▾' : '접기 ▴'}</button></span>`;
            html = MOBILE
                ? `<div class="bar bottom"><div class="head"><span class="title">FM키워드</span><select aria-label="게시판">${options}</select>${side}</div><div class="chips">${chips}</div></div>`
                : `<div class="bar top"><div class="head"><span class="title">FM키워드</span><select aria-label="게시판">${options}</select></div><div class="chips">${chips}</div>${side}</div>`;
        }
        root.innerHTML = `<style>${CSS}</style>${html}`;
        // 에펨코리아 화면의 맨 위·맨 아래가 줄에 가리지 않게 그만큼 여백
        const bar = root.querySelector('.bar');
        const height = bar.getBoundingClientRect().height;
        document.documentElement.style.setProperty(MOBILE ? 'padding-bottom' : 'padding-top', height + 'px', 'important');
        const active = root.querySelector('a.chip.on');
        if (active && MOBILE) active.scrollIntoView({ block: 'nearest', inline: 'center' });
    }

    root.addEventListener('change', e => {
        if (e.target.tagName !== 'SELECT') return;
        chosenId = Number(e.target.value);
        GM_setValue(KEY_GROUP, chosenId);
        render();
    });
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
