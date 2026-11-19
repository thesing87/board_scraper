// 에펨코리아 바로가기 페이지: 게시판마다 등록한 에펨코리아 검색 링크를 모아 보여 줌 (/api/fm-links).
// 링크를 누르면 새 창에서 에펨코리아 검색 결과가 열림. 서버는 에펨코리아에 요청하지 않음
'use strict';

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const EXTERNAL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"></path><path d="M10 14L20 4"></path><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"></path></svg>';

// 그 게시판에서 제목+본문 검색 (board가 ''이면 사이트 전체 검색)
function fmSearchUrl(board, keyword) {
    const q = encodeURIComponent(keyword);
    return board
        ? `https://www.fmkorea.com/index.php?mid=${encodeURIComponent(board)}&search_target=title_content&search_keyword=${q}`
        : `https://www.fmkorea.com/search.php?act=IS&is_keyword=${q}`;
}

let groups = [];

function render() {
    const query = $('links-filter').value.trim().toLowerCase();
    const shown = groups.map(g => {
        const nameHit = !query || g.name.toLowerCase().includes(query);
        const links = nameHit ? g.links : g.links.filter(l => l.keyword.toLowerCase().includes(query) || l.board_name.toLowerCase().includes(query));
        return { ...g, links, all: g.links };
    }).filter(g => g.links.length);
    const total = groups.reduce((n, g) => n + g.links.length, 0);
    const count = shown.reduce((n, g) => n + g.links.length, 0);
    $('links-count').textContent = total ? (query ? `${count} / ${total}개` : `링크 ${total}개`) : '';
    if (!total) {
        $('links-body').innerHTML = '<div class="empty">아직 등록한 링크가 없습니다.<br>키워드 게시판의 \'게시판 편집\'에서 에펨코리아 바로가기를 추가하면 여기에 모입니다.</div>';
        return;
    }
    if (!shown.length) {
        $('links-body').innerHTML = '<div class="empty">맞는 링크가 없습니다.</div>';
        return;
    }
    $('links-body').innerHTML = `<div class="link-groups">${shown.map(g => {
        // 한 게시판 안에서 에펨코리아 게시판이 여러 개면 키워드마다 게시판 이름을 붙임 (거를 때도 같게, 전체 링크 기준)
        const boards = new Set(g.all.map(l => l.board));
        const note = boards.size === 1 ? g.all[0].board_name : `게시판 ${boards.size}곳`;
        return `
        <section class="link-group" aria-label="${esc(g.name)}">
            <div class="link-group-head">
                <a class="link-group-name" href="/board/#board-${g.id}">${esc(g.name)}</a>
                <span class="link-group-note">${esc(note)}</span>
            </div>
            <div class="link-chips">${g.links.map(l => `
                <a class="link-chip" href="${esc(fmSearchUrl(l.board, l.keyword))}" target="_blank" rel="noopener noreferrer"
                   title="에펨코리아 ${esc(l.board_name)}에서 '${esc(l.keyword)}' 검색">
                    ${boards.size > 1 ? `<small>${esc(l.board_name)}</small>` : ''}${esc(l.keyword)}${EXTERNAL}</a>`).join('')}
            </div>
        </section>`;
    }).join('')}</div>`;
}

async function load() {
    try {
        const res = await fetch('/api/fm-links', { cache: 'no-store' });
        if (!res.ok) throw new Error(res.status);
        groups = (await res.json()).groups;
        render();
    } catch (e) {
        $('links-body').innerHTML = '<div class="empty">링크를 불러오지 못했습니다. 잠시 후 다시 열어 주세요.</div>';
    }
}

$('links-filter').addEventListener('input', render);
load();
