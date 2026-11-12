// 모든 페이지 공통 바로가기 메뉴. 페이지의 <nav class="site-nav" data-current="키"> 자리(제목 줄 바로 아래)에 그림.
// 페이지마다 모양이 다르지 않도록 화면 폭으로만 정함
//  - 넓은 화면: 작은 버튼 한 줄 (지금 페이지는 파랑)
//  - 휴대폰: 아이콘 + 짧은 이름 일곱 칸 한 줄
'use strict';

(function () {
    const svg = body => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
    const GRID = '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"></rect><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"></rect>'
        + '<rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"></rect><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"></rect>';
    const ITEMS = [
        { key: 'home', href: '/', label: '대시보드', short: '홈', color: '#374151', icon: GRID },
        { key: 'board', href: '/board/', label: '게시판', short: '게시판', color: '#185FA5', icon: '<circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.5-3.5"></path>' },
        { key: 'popular', href: '/board/#popular', label: '인기글', short: '인기글', color: '#C2410C', icon: '<path d="M12 3c.5 3 4 5.2 4 9.5a4 4 0 0 1-8 0c0-1.8.8-3 2-4 .2 1.7 1 2.6 2 2.8-.3-3 .2-5.6 0-8.3z"></path>' },
        { key: 'apt', href: '/apt/', label: '실거래가', short: '실거래', color: '#993556', icon: '<rect x="5" y="3" width="14" height="18" rx="1.5"></rect><path d="M9 7h1.5M13.5 7H15M9 11h1.5M13.5 11H15M9 15h1.5M13.5 15H15"></path>' },
        { key: 'card', href: '/card/', label: '카드', short: '카드', color: '#534AB7', icon: '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M3 10h18"></path>' },
        { key: 'ev', href: '/ev/', label: '유지비', short: '유지비', color: '#0F6E56', icon: '<path d="M13 3L5 14h6l-1 7 8-11h-6l1-7z"></path>' },
        { key: 'stats', href: '/stats/', label: '통계', short: '통계', color: '#5F5E5A', icon: '<path d="M5 20v-8M12 20V5M19 20v-5"></path>' },
    ];
    const narrow = window.matchMedia('(max-width: 820px)');

    function itemHtml(item, current) {
        const on = item.key === current;
        return `<a class="site-nav-item${on ? ' is-current' : ''}" href="${item.href}" data-nav="${item.key}"${on ? ' aria-current="page"' : ''} style="--nav-color:${item.color}">`
            + svg(item.icon)
            + `<span class="site-nav-long">${item.label}</span><span class="site-nav-short">${item.short}</span>`
            + `<span class="site-nav-badge" data-badge="${item.key}" hidden></span></a>`;
    }

    function render(nav) {
        const current = nav.dataset.current || '';
        const items = ITEMS.map(item => itemHtml(item, current)).join('');
        nav.setAttribute('aria-label', '바로가기');
        nav.innerHTML = items;
        const compact = () => nav.classList.toggle('is-compact', narrow.matches);
        compact();
        narrow.addEventListener('change', compact);
        // 같은 페이지 안의 다른 보기(게시판 → 인기글)는 주소의 # 부분만 바뀌어 페이지가 다시 읽히지 않으므로 새로 엶
        nav.addEventListener('click', e => {
            const link = e.target.closest('a[href*="#"]');
            if (!link) return;
            const url = new URL(link.href);
            if (url.pathname !== window.location.pathname) return;
            e.preventDefault();
            window.location.hash = url.hash;
            window.location.reload();
        });
    }

    document.querySelectorAll('.site-nav[data-current]').forEach(render);

    // 메뉴 숫자 표시 (예: 대시보드가 받아 온 안 읽은 새 글 수)
    window.siteNav = {
        setBadge(key, count) {
            document.querySelectorAll(`.site-nav [data-badge="${key}"]`).forEach(el => {
                el.hidden = !count;
                el.textContent = count > 99 ? '99+' : String(count || '');
            });
        }
    };
})();
