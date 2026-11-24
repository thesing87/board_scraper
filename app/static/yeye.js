// YeYe홈 앱의 홈 탭 (/yeye/): 근무표·가계부 요약 (서버 /api/ledger/home, 가계부 로그인)
// - 근무표: 사람마다 오늘·내일, '처음 보일 사람'(근무표 설정 > 이 휴대폰, localStorage duty_home_person)의 오늘부터 7일
// - 가계부: 이번 달 지출·수입, 내 확인 대기함 건수, 최근 기록 3건
// - 카드를 누르면 그 페이지로 (앱은 그 탭으로 바꿈). 앱이 홈 탭을 다시 보일 때 window.homeRefresh()로 새로
// - 전체 설정(#settings, 앱 홈 탭의 위쪽 '설정' = window.appOpenSettings): 앱 파일(관리자는 APK 올리기, 앱 밖에서는 앱 받기),
//   이 휴대폰 앱(버전·새 버전 확인, 앱 안에서만), 로그아웃
'use strict';

(function () {
    const $ = id => document.getElementById(id);
    const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const storageGet = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } };
    const WD = '일월화수목금토';
    const pad = n => String(n).padStart(2, '0');
    const parse = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
    const won = n => Math.round(n).toLocaleString('ko-KR');
    function mix(hex, toWhite, f) {
        const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
        const t = toWhite ? 255 : 0;
        return '#' + c.map(v => Math.round(v + (t - v) * f).toString(16).padStart(2, '0')).join('');
    }
    const badgeStyle = h => `background:${mix(h, true, 0.8)};color:${mix(h, false, 0.5)}`;
    const inApp = !!window.LedgerApp;
    if (inApp) document.documentElement.classList.add('in-app');
    const st = { me: null, app: null, ordering: false };
    // 카드 순서 (이 기기, localStorage home_cards: 'duty,spend,inbox,recent')
    const CARDS = ['duty', 'spend', 'inbox', 'recent'], ORDER_KEY = 'home_cards';
    function cardOrder() {
        const saved = storageGet(ORDER_KEY, '').split(',').filter(k => CARDS.includes(k));
        return [...new Set([...saved, ...CARDS])];
    }
    function applyOrder() {
        const box = $('cards');
        cardOrder().forEach(k => box.appendChild(box.querySelector(`[data-card="${k}"]`)));
    }
    function saveOrder() {
        const keys = [...$('cards').querySelectorAll('[data-card]')].map(c => c.dataset.card);
        try { localStorage.setItem(ORDER_KEY, keys.join(',')); } catch (e) { /* 저장 불가 */ }
    }
    // 분류 아이콘 (가계부와 같은 규칙: 고른 이모지, 없으면 이름으로 짐작)
    const GUESS = [[/식|밥|외식|배달/, '🍚'], [/카페|커피/, '☕'], [/교통|버스|지하철|택시/, '🚌'], [/생활|마트|장보/, '🧺'], [/쇼핑|옷/, '🛍️'],
        [/의료|병원|약|건강/, '💊'], [/주거|월세|관리비|집/, '🏠'], [/통신|휴대폰|폰/, '📱'], [/경조|선물/, '🎁'], [/문화|여가|취미|영화/, '🎬'],
        [/교육|학원|책/, '📚'], [/반려|강아지|고양이|펫/, '🐶'], [/여행/, '✈️'], [/차|주유|주차/, '🚗'], [/공과|전기|가스|수도/, '💡'], [/술/, '🍺'],
        [/미용|화장/, '💄'], [/육아|아이/, '👶'], [/급여|월급/, '💰'], [/부수입/, '💵'], [/용돈/, '🎉'], [/이자|환급/, '🏦']];
    const iconOf = (icon, name) => icon || (GUESS.find(([re]) => re.test(name || '')) || [0, [...(name || '?')][0]])[1];
    const kb = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;

    async function req(url, body) {
        const res = await fetch(url, body ? { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
            : { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        let data = {};
        try { data = await res.json(); } catch (e) { /* 본문 없음 */ }
        return { status: res.status, data };
    }

    // ---- 로그인 (가계부 계정)
    $('login-form').addEventListener('submit', async e => {
        e.preventDefault();
        const name = $('login-name').value.trim(), password = $('login-pw').value;
        if (!name || !password) { $('auth-msg').textContent = '이름과 비밀번호를 넣어 주세요.'; return; }
        const { status, data } = await req('/api/ledger/session', { action: 'login', name, password });
        if (status !== 200) { $('auth-msg').textContent = String(data.message || '로그인하지 못했어요.').replace(/^❌\s*/, ''); return; }
        $('login-pw').value = '';
        try { localStorage.setItem('ledger_user', data.user.name); } catch (err) { /* 저장 불가 */ }
        try { if (window.LedgerApp && window.LedgerApp.loggedIn) window.LedgerApp.loggedIn(); } catch (err) { /* 예전 앱 */ }
        load();
    });

    async function load() {
        const person = storageGet('duty_home_person', '');
        const { status, data } = await req('/api/ledger/home' + (person ? `?person=${encodeURIComponent(person)}` : ''));
        if (status === 401) {
            // 관리자 기기: 대시보드 로그인 키로 자동 로그인
            const token = storageGet('admin_token', '');
            if (token && !load.triedToken) {
                load.triedToken = true;
                if ((await req('/api/ledger/session', { action: 'login', password: token })).status === 200) { load(); return; }
            }
            st.me = null;
            $('app').hidden = $('set-view').hidden = $('hnav').hidden = true;
            $('auth').hidden = false;
            return;
        }
        if (status !== 200) { $('msg').textContent = '불러오지 못했어요. 잠시 뒤 다시 해 주세요.'; return; }
        $('msg').textContent = '';
        $('auth').hidden = true;
        st.me = data.user;
        st.app = data.app;
        $('hnav').hidden = false;
        showSettings(location.hash === '#settings');
        const now = new Date();
        $('greet-date').textContent = `${now.getMonth() + 1}월 ${now.getDate()}일 ${WD[now.getDay()]}요일`;
        $('greet-name').textContent = `안녕하세요, ${st.me.name}님`;
        applyOrder();
        renderDuty(data.duty);
        renderLedger(data.ledger);
        renderOrdering();
        renderSettings();
    }
    window.homeRefresh = load;

    function renderDuty(d) {
        const types = {};
        d.types.forEach(t => { types[t.id] = t; });
        const badge = id => types[id] ? `<span class="badge" style="${badgeStyle(types[id].color)}">${esc(types[id].code)}</span>` : '<span class="badge blank">–</span>';
        $('duty-title').textContent = '오늘 근무';
        if (!d.people.length) { $('duty-body').innerHTML = '<p class="none">아직 근무표가 없어요</p>'; return; }
        // 처음 보일 사람은 크게 (가계부의 이번 달 지출처럼), 다른 사람은 한 줄씩
        const who = d.people.find(p => p.id === d.person_id) || d.people[0];
        const big = p => {
            const t = types[p.today], n = types[p.tomorrow];
            return `<div class="big-duty"><span class="lbl">${esc(p.name)}</span><span class="v"${t ? ` style="color:${mix(t.color, false, 0.4)}"` : ''}>${t ? esc(t.name) : '근무 없음'}</span>
                ${t && t.start_time ? `<span class="tm">${t.start_time}–${t.end_time}</span>` : ''}<span class="nx">내일 ${n ? esc(n.name) : '–'}</span></div>`;
        };
        const rows = d.people.filter(p => p !== who).map(p => {
            const t = types[p.today], n = types[p.tomorrow];
            const desc = (t ? `${t.name}${t.start_time ? ` ${t.start_time}–${t.end_time}` : ''}` : '근무 없음') + ` · 내일 ${n ? n.code : '–'}`;
            return `<div class="who"><span class="n">${esc(p.name)}</span>${badge(p.today)}<span class="t">${esc(desc)}</span></div>`;
        }).join('');
        const week = d.week.map((w, i) => {
            const day = parse(w.day);
            return `<div><div class="d${i === 0 ? ' today' : ''}">${i === 0 ? '오늘' : WD[day.getDay()]}</div>${badge(w.type_id)}</div>`;
        }).join('');
        $('duty-body').innerHTML = big(who) + (d.person_id === who.id ? `<div class="week"><div class="row">${week}</div></div>` : '') + (rows ? `<div class="others">${rows}</div>` : '');
    }

    function renderLedger(l) {
        $('ledger-title').textContent = '이번 달 지출';
        const pct = l.income ? Math.min(100, Math.round(l.expense / l.income * 100)) : l.expense ? 100 : 0;
        $('ledger-body').innerHTML = `<div class="spend">${won(l.expense)}<small>원</small></div>
            <div class="bar"><i style="width:${pct}%"></i></div><div class="sub">수입 <b class="in">${won(l.income)}원</b> · 남음 <b>${won(l.income - l.expense)}원</b></div>`;
        $('inbox-n').textContent = l.inbox || '';
        st.inboxN = l.inbox;
        $('recent-body').innerHTML = l.recent.length ? l.recent.map(r => `<div class="rc"><span class="ci" style="background:${mix(r.color || '#888780', true, 0.84)}">${esc(iconOf(r.icon, r.category))}</span>
                <span class="m">${esc(r.memo)}</span><span class="a${r.kind === 'income' ? ' in' : ''}">${r.kind === 'income' ? '+' : '−'}${won(r.amount)}</span></div>`).join('')
            : '<p class="none">이번 달 기록이 아직 없어요</p>';
    }

    // ==========================================
    // 카드 순서 바꾸기: ⋮⋮를 끌어 옮기고 '완료' (놓을 때마다 이 기기에 저장)
    // ==========================================
    function renderOrdering() {
        $('app').classList.toggle('ordering', st.ordering);
        $('order-bar').hidden = !st.ordering;
        $('order-btn').hidden = st.ordering;
        $('inbox-card').hidden = !st.ordering && !st.inboxN;   // 확인할 결제가 없으면 숨김 (순서 바꿀 때는 보임)
    }
    $('order-btn').addEventListener('click', () => { st.ordering = true; renderOrdering(); });
    $('order-done').addEventListener('click', () => { saveOrder(); st.ordering = false; renderOrdering(); });
    let drag = null;
    $('cards').addEventListener('pointerdown', e => {
        if (!st.ordering) return;
        const card = e.target.closest('[data-card]');
        if (!card) return;
        e.preventDefault();
        drag = { card, id: e.pointerId };
        card.setPointerCapture(e.pointerId);
        card.classList.add('dragging');
    });
    $('cards').addEventListener('pointermove', e => {
        if (!drag || e.pointerId !== drag.id) return;
        const rest = [...$('cards').querySelectorAll('[data-card]')].filter(c => c !== drag.card && !c.hidden);
        const before = rest.find(c => { const b = c.getBoundingClientRect(); return e.clientY < b.top + b.height / 2; });
        if (before) { if (before !== drag.card.nextElementSibling) $('cards').insertBefore(drag.card, before); }
        else if (rest.length) rest[rest.length - 1].after(drag.card);
    });
    const endDrag = e => { if (!drag || e.pointerId !== drag.id) return; drag.card.classList.remove('dragging'); drag = null; saveOrder(); };
    $('cards').addEventListener('pointerup', endDrag);
    $('cards').addEventListener('pointercancel', endDrag);
    window.homeMoveCard = (key, to) => {   // 시험용: 카드를 to번째로 옮기고 저장
        const card = $('cards').querySelector(`[data-card="${key}"]`), rest = [...$('cards').querySelectorAll('[data-card]')].filter(c => c !== card);
        if (rest[to]) $('cards').insertBefore(card, rest[to]); else $('cards').appendChild(card);
        saveOrder();
    };

    // 아래 메뉴: 홈 · 설정
    function renderNav() {
        const v = $('set-view').hidden ? 'home' : 'set';
        document.querySelectorAll('#hnav [data-hv]').forEach(b => {
            b.classList.toggle('on', b.dataset.hv === v);
            if (b.dataset.hv === v) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
        });
    }
    $('hnav').addEventListener('click', e => {
        const b = e.target.closest('[data-hv]');
        if (!b) return;
        if (b.dataset.hv === 'set') { if ($('set-view').hidden) openSettings(); }
        else if (!$('set-view').hidden) closeSettings();
    });

    // ==========================================
    // 전체 설정 (#settings)
    // ==========================================
    function showSettings(on) {
        $('app').hidden = on;
        $('set-view').hidden = !on;
        if (on) window.scrollTo(0, 0);
        if (on && st.ordering) { saveOrder(); st.ordering = false; renderOrdering(); }
        renderNav();
    }
    function openSettings() {
        if (location.hash !== '#settings') history.pushState({ homeSettings: 1 }, '', '#settings');
        showSettings(true);
        renderSettings();
    }
    function closeSettings() {
        if (location.hash === '#settings' && (history.state || {}).homeSettings) history.back();
        else {
            if (location.hash === '#settings') history.replaceState(null, '', location.pathname + location.search);
            showSettings(false);
        }
    }
    window.addEventListener('popstate', () => { if (st.me) showSettings(location.hash === '#settings'); });
    $('set-back').addEventListener('click', closeSettings);
    // 앱이 부름: 홈 탭 위쪽 '설정' → 전체 설정 (로그인 전이면 false → 앱이 자기 설정을 엶), 뒤로가기 → 설정부터 닫음
    window.appOpenSettings = () => { if (!st.me) return false; openSettings(); return true; };
    window.ledgerBack = () => {
        if (!$('set-view').hidden) { closeSettings(); return true; }
        if (st.ordering) { saveOrder(); st.ordering = false; renderOrdering(); return true; }
        return false;
    };

    function renderSettings() {
        if (!st.me) return;
        const admin = !!st.me.admin, app = st.app;
        const text = app ? `YeYe홈 ${app.versionName} · ${kb(app.size)} · ${String(app.uploaded_at).slice(5, 10).replace('-', '/')} 올림` : '';
        // 앱 파일: 관리자는 올리기, 앱 밖의 멤버는 받기, 앱 안의 멤버에게는 칸을 숨김 (앱은 저절로 새 버전으로)
        $('appfile-card').hidden = !admin && inApp;
        $('appfile-tag').hidden = !admin;
        $('app-state').textContent = app ? `서버에 올라간 앱: ${text}${admin && app.uploaded_by ? ` (${app.uploaded_by})` : ''}` : '아직 올라간 앱이 없어요.';
        $('app-up').hidden = !admin;
        $('app-get').hidden = !app || inApp;
        $('who').textContent = `${st.me.name}${admin ? ' (관리자)' : ''}로 로그인했어요.`;
        if (inApp) {
            let v = '';
            try { v = window.LedgerApp.version(); } catch (e) { /* 예전 앱 */ }
            const newer = app && v && app.versionName !== v;
            $('phone-state').textContent = `YeYe홈 ${v || '?'}` + (app ? (newer ? ` · 새 버전 ${app.versionName}이 있어요` : ' · 최신 버전이에요') : '');
            renderPhone();
        }
    }
    // 결제 알림 (이 휴대폰): 앱이 알려 준 상태 (1.11부터, 예전 앱이면 칸을 숨김)
    function renderPhone() {
        let s = null;
        try { s = window.LedgerApp.phoneState ? JSON.parse(window.LedgerApp.phoneState()) : null; } catch (e) { s = null; }
        $('notify-card').hidden = !s || s.access == null;
        // 근무표 변경 알림 (1.12부터, Firebase 설정이 든 앱만)
        $('duty-push-card').hidden = !s || s.dutyPush == null;
        if (!$('duty-push-card').hidden) {
            $('ph-duty').checked = !!s.dutyPush;
            const off = s.dutyPush && !s.notifyAllowed;
            $('ph-duty-s').textContent = off ? '휴대폰 알림 권한이 꺼져 있어요 · 껐다 켜면 물어봐요' : '다른 사람이 근무표를 고치면 바로 알려 줘요';
            $('ph-duty-s').className = off ? 'bad' : '';
        }
        if ($('notify-card').hidden) return;
        $('ph-access-s').textContent = s.access ? `켜짐${s.battery ? ' · 배터리 제한 없음' : ' · 배터리 절약이 켜져 있어요'}` : '꺼짐 · 눌러서 켜 주세요';
        $('ph-access-s').className = s.access ? 'ok' : 'bad';
        $('ph-alert').checked = !!s.alertOn;
        $('ph-ignore-n').textContent = s.ignores ? String(s.ignores) : '';
    }
    $('ph-alert').addEventListener('change', e => {
        try { window.LedgerApp.setAlertOn(e.target.checked); } catch (err) { /* 예전 앱 */ }
    });
    $('ph-duty').addEventListener('change', e => {
        try { window.LedgerApp.setDutyPushOn(e.target.checked); } catch (err) { /* 예전 앱 */ }
    });
    // 휴대폰에서 해야 하는 것(권한·무시할 알림 고르기·최근 알림)은 앱의 결제 알림 화면에서
    $('notify-card').addEventListener('click', e => {
        if (!e.target.closest('[data-phone]')) return;
        try { window.LedgerApp.openPhoneSettings(); } catch (err) { /* 예전 앱 */ }
    });
    $('app-file').addEventListener('change', () => { $('app-upload').disabled = !$('app-file').files.length; $('app-msg').textContent = ''; });
    $('app-upload').addEventListener('click', async () => {
        const file = $('app-file').files[0];
        if (!file) return;
        $('app-upload').disabled = true;
        $('app-msg').classList.remove('ok');
        $('app-msg').textContent = '올리는 중…';
        let status = 0, data = {};
        try {
            const res = await fetch('/api/ledger/app-upload', { method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/octet-stream' }, body: file });
            status = res.status;
            data = await res.json().catch(() => ({}));
        } catch (e) { data = { message: '연결이 끊겼어요.' }; }
        if (status !== 200) {
            $('app-upload').disabled = false;
            $('app-msg').textContent = String(data.message || '올리지 못했어요.').replace(/^❌\s*/, '');
            return;
        }
        $('app-msg').classList.add('ok');
        $('app-msg').textContent = `올렸어요: ${data.app.versionName}`;
        $('app-file').value = '';
        st.app = data.app;
        renderSettings();
    });
    $('update-check').addEventListener('click', () => {
        try { window.LedgerApp.checkUpdate(); } catch (e) { $('phone-state').textContent = '이 앱 버전에서는 새 버전을 확인할 수 없어요.'; return; }
        $('phone-state').textContent = '새 버전 확인 중…';
        // 확인 결과는 앱이 알려 줌 (몇 번 물어봄)
        let n = 0;
        const t = setInterval(() => {
            let s = '';
            try { s = window.LedgerApp.updateText(); } catch (e) { /* 예전 앱 */ }
            if (s) $('phone-state').textContent = s;
            if (++n > 20 || (s && !/확인 중|받는 중/.test(s))) clearInterval(t);
        }, 700);
    });
    $('logout').addEventListener('click', async () => {
        await req('/api/ledger/session', { action: 'logout' });
        try { localStorage.removeItem('ledger_user'); } catch (e) { /* 저장 불가 */ }
        // 앱 안이면 가계부·근무표 탭도 다시 읽음
        try { if (window.LedgerApp && window.LedgerApp.loggedOut) window.LedgerApp.loggedOut(); } catch (e) { /* 예전 앱 */ }
        if (location.hash === '#settings') history.replaceState(null, '', location.pathname);
        load.triedToken = true;     // 관리자 기기여도 방금 로그아웃했으면 자동으로 다시 로그인하지 않음
        load();
    });

    // 카드·대기함을 누르면 그 페이지로 (앱은 탭을 바꿈)
    document.addEventListener('click', e => {
        if (st.ordering) return;   // 순서 바꾸는 중엔 카드를 눌러도 가지 않음
        const go = e.target.closest('[data-go]');
        if (go) location.href = go.dataset.go;
    });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') load(); });
    load();
})();
