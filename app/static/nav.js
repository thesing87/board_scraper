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
        { key: 'board', href: '/board/#home', label: '게시판', short: '게시판', color: '#185FA5', icon: '<circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.5-3.5"></path>' },
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
        // 같은 페이지 안의 다른 보기(게시판 ↔ 인기글): 페이지가 정한 처리(onSamePage)가 있으면 그것으로 보기만 바꾸고,
        // 없으면 # 부분만 바뀌어서는 페이지가 다시 읽히지 않으므로 새로 엶
        nav.addEventListener('click', e => {
            const link = e.target.closest('a[data-nav]');
            if (!link) return;
            const url = new URL(link.href);
            if (url.pathname !== window.location.pathname) return;
            if (typeof window.siteNav.onSamePage === 'function') {
                e.preventDefault();
                window.siteNav.onSamePage(link.dataset.nav);
            } else if (url.hash) {
                e.preventDefault();
                window.location.hash = url.hash;
                window.location.reload();
            }
        });
    }

    window.siteNav = {
        // 같은 페이지 안의 메뉴를 눌렀을 때 페이지가 직접 처리 (키워드 게시판: 게시판·인기글 보기 바꾸기)
        onSamePage: null,
        // 지금 위치 표시 바꾸기 (키워드 게시판에서 인기글 보기면 '인기글')
        setCurrent(key) {
            document.querySelectorAll('.site-nav [data-nav]').forEach(a => {
                const on = a.dataset.nav === key;
                a.classList.toggle('is-current', on);
                if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
            });
        },
        // 메뉴 숫자 표시 (예: 대시보드가 받아 온 안 읽은 새 글 수)
        setBadge(key, count) {
            document.querySelectorAll(`.site-nav [data-badge="${key}"]`).forEach(el => {
                el.hidden = !count;
                el.textContent = count > 99 ? '99+' : String(count || '');
            });
        }
    };

    document.querySelectorAll('.site-nav[data-current]').forEach(render);

    // ==========================================
    // 공유 버튼 (공통 상단 바의 오른쪽): 지금 페이지 주소를 휴대폰 공유 창으로, 공유 창이 없으면 주소 복사.
    // 페이지 안의 위치(실거래가 단지 상세 #w-… 등)도 주소에 그대로 들어감. 키워드 게시판은 제목 줄에 따로 있음
    // ==========================================
    const SHARE_ICON = svg('<circle cx="18" cy="5" r="2.5"></circle><circle cx="6" cy="12" r="2.5"></circle><circle cx="18" cy="19" r="2.5"></circle>'
        + '<path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"></path>');
    function navToast(message) {
        let toast = document.querySelector('.nav-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.className = 'nav-exit-toast nav-toast';
            toast.setAttribute('role', 'status');
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add('is-shown');
        clearTimeout(toast.hideTimer);
        toast.hideTimer = setTimeout(() => toast.classList.remove('is-shown'), 1800);
    }
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
    async function sharePage() {
        const heading = document.querySelector('.site-top h1');
        const title = `${heading ? heading.textContent.trim() : document.title} · 키워드 모니터`;
        const url = window.location.href;
        if (navigator.share) {
            try { await navigator.share({ title, url }); } catch (e) { /* 공유 창을 닫음 */ }
            return;
        }
        navToast(await copyText(url) ? '주소를 복사했습니다' : '복사하지 못했습니다');
    }
    document.querySelectorAll('.site-top .site-top-row').forEach(row => {
        let tools = row.querySelector('.site-top-tools');
        if (!tools) {
            tools = document.createElement('div');
            tools.className = 'site-top-tools';
            row.appendChild(tools);
        }
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'site-share-btn';
        button.title = '이 페이지 주소 공유';
        button.setAttribute('aria-label', '이 페이지 주소 공유');
        button.innerHTML = SHARE_ICON + '<span>공유</span>';
        button.addEventListener('click', sharePage);
        tools.appendChild(button);
    });

    // 공통 상단 바(.site-top): 휴대폰에서 아래로 내리면 숨기고 위로 올리면 다시 보임 (키워드 게시판 상단 바와 같은 동작).
    // 보이는 높이를 --site-top-offset으로 알려, 그 아래에 붙는 요소(유지비 요약 등)가 가려지지 않게 함
    const top = document.querySelector('.site-top');
    if (top) {
        const mobile = window.matchMedia('(max-width: 899px)');
        let lastY = window.scrollY;
        const update = () => {
            const y = window.scrollY;
            const hide = mobile.matches && y > top.offsetHeight && y > lastY;
            const show = !mobile.matches || y <= top.offsetHeight || y < lastY - 4;
            if (hide) top.classList.add('is-hidden');
            else if (show) top.classList.remove('is-hidden');
            if (Math.abs(y - lastY) > 4 || hide || show) lastY = y;
            document.documentElement.style.setProperty('--site-top-offset', (top.classList.contains('is-hidden') ? 0 : top.offsetHeight) + 'px');
        };
        window.addEventListener('scroll', update, { passive: true });
        mobile.addEventListener('change', update);
        new ResizeObserver(update).observe(top);
        update();
    }

    // ==========================================
    // 휴대폰: 페이지(탭)를 옮겨도 뒤로 가기 기록이 쌓이지 않게 하고, 뒤로 가기를 두 번 연달아 누르면 앱 종료
    // ==========================================
    // 방문 기록을 [이 페이지(기준) → 지키는 칸] 두 칸으로 유지함
    //  - 다른 페이지로 갈 때: 기준 칸까지 돌아간 뒤 그 칸을 새 페이지로 바꿔 씀 (기록이 늘지 않음)
    //  - 뒤로 가기 1번: 지키는 칸이 빠지며 기준 칸에 닿으면 안내를 띄우고 지키는 칸을 다시 넣음
    //  - 2초 안에 한 번 더: 기준 칸에서 한 칸 더 뒤로 → 앱의 첫 기록이므로 앱이 닫힘 (브라우저에서는 이전 사이트로)
    // 게시판의 글 링크(#post-)·실거래가 단지(#w-)처럼 페이지 안에서 쌓는 기록은 지키는 칸 뒤에 쌓여 지금처럼 동작함
    const EXIT_WINDOW_MS = 2000;
    const PENDING_KEY = 'nav_pending_url';
    const appLike = window.matchMedia('(max-width: 899px)').matches || window.matchMedia('(display-mode: standalone)').matches;
    if (!appLike) return;

    const isBase = state => !!(state && state.navBase);
    const pending = () => { try { return sessionStorage.getItem(PENDING_KEY); } catch (e) { return null; } };
    const setPending = url => { try { if (url) sessionStorage.setItem(PENDING_KEY, url); else sessionStorage.removeItem(PENDING_KEY); } catch (e) { /* 저장 불가: 바로 이동 */ } };

    // 새로 연 페이지면 두 칸을 만듦. 새로고침·앞뒤 이동으로 다시 열린 페이지는 이미 칸이 있음
    const navType = (performance.getEntriesByType('navigation')[0] || {}).type;
    if (isBase(history.state)) {
        history.pushState({ navGuard: 1 }, '', window.location.href);
    } else if (navType !== 'reload' && navType !== 'back_forward') {
        history.replaceState({ navBase: 1 }, '', window.location.href);
        history.pushState({ navGuard: 1 }, '', window.location.href);
    }
    setPending(null);

    function goTo(url) {
        if (isBase(history.state)) { window.location.replace(url); return; }
        setPending(url);
        history.back();
    }

    let toast = null, toastTimer = 0, lastBackAt = 0, hops = 0;
    function showExitHint() {
        if (!toast) {
            toast = document.createElement('div');
            toast.className = 'nav-exit-toast';
            toast.setAttribute('role', 'status');
            toast.textContent = '뒤로 버튼을 한 번 더 누르면 종료됩니다';
            document.body.appendChild(toast);
        }
        toast.classList.add('is-shown');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('is-shown'), EXIT_WINDOW_MS);
    }

    window.addEventListener('popstate', e => {
        const url = pending();
        if (url) {
            // 다른 페이지로 가는 중: 기준 칸까지 계속 뒤로 간 뒤 그 칸을 새 페이지로 바꿈 (칸을 못 찾으면 그냥 이동)
            if (isBase(e.state) || ++hops > 20) { setPending(null); window.location.replace(url); }
            else history.back();
            return;
        }
        if (!isBase(e.state)) return;
        const now = Date.now();
        if (now - lastBackAt < EXIT_WINDOW_MS) {
            history.back();
            return;
        }
        lastBackAt = now;
        history.pushState({ navGuard: 1 }, '', window.location.href);
        showExitHint();
    });

    // 다른 페이지로 가는 링크(바로가기 메뉴·대시보드 카드 등)는 기록을 쌓지 않고 이동
    document.addEventListener('click', e => {
        if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        const link = e.target.closest('a[href]');
        if (!link || (link.target && link.target !== '_self') || link.hasAttribute('download')) return;
        const url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin || url.pathname === window.location.pathname) return;
        e.preventDefault();
        goTo(url.href);
    });
})();
