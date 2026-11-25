// 근무표: 사람마다 날짜별 근무(D·E·N·OFF 등)를 넣고 함께 보기 (서버 duty.py, API /api/ledger/duty)
// - 로그인은 가계부 계정 (관리자 기기는 대시보드 로그인 키로 자동 로그인). 허락받은 멤버 누구나 고침
// - 평소엔 보기만. '고치기'를 누르면 아래 '근무 칠하기'가 나오고, 근무를 고르고 날짜를 누르면 바로 들어감
//   (같은 근무를 다시 누르면 지움, 잠깐 모았다가 한 번에 저장). 완료·뒤로가기·앱의 다른 탭으로 가면 끝
// - 설정(#settings): 근무 종류(글자·이름·시간·색)와 사람(근무표 주인) 고치기
'use strict';

(function () {
    const $ = id => document.getElementById(id);
    const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const storageGet = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } };
    const storageSet = (k, v) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (e) { /* 저장 불가 */ } };
    const LEDGER_FLAG = 'ledger_user';        // 메뉴(nav.js)가 가계부·근무표를 보이게 하는 표시 (가계부와 같음)
    const ADMIN_TOKEN_KEY = 'admin_token';
    const PERSON_KEY = 'duty_person';         // 이 기기에서 마지막으로 본 사람
    const HOME_PERSON_KEY = 'duty_home_person';   // YeYe홈 앱의 홈 탭·위젯에 처음 보일 사람 (설정 > 이 휴대폰)
    const PRESET = ['#EF9F27', '#D4537E', '#534AB7', '#888780', '#1D9E75', '#378ADD', '#E24B4A', '#D85A30', '#639922', '#2BA7B8', '#9B5DE5', '#5F5E5A'];
    const WD = '일월화수목금토';
    const SAVE_DELAY = 500;
    const RETRY_DELAY = 10000;   // 저장 실패(연결 끊김 등) 뒤 다시 보낼 때까지
    const hasPending = () => Object.values(st.pending).some(d => Object.keys(d).length);

    const pad = n => String(n).padStart(2, '0');
    const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const parse = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
    const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return ymd(d); };
    const short = s => { const d = parse(s); return `${d.getMonth() + 1}/${d.getDate()} (${WD[d.getDay()]})`; };
    function mix(hex, toWhite, f) {
        const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
        const t = toWhite ? 255 : 0;
        return '#' + c.map(v => Math.round(v + (t - v) * f).toString(16).padStart(2, '0')).join('');
    }
    const badgeStyle = h => `background:${mix(h, true, 0.8)};color:${mix(h, false, 0.5)}`;

    const st = {
        me: null, data: null, month: ymd(new Date()).slice(0, 7), personId: Number(storageGet(PERSON_KEY, 0)) || null,
        editing: false,       // '고치기'를 누른 동안만 날짜를 눌러 근무를 넣음
        brush: null,          // 고른 근무 종류 id, 'clear'(지우기), null(안 고름)
        pending: {},          // 저장 전 바뀐 날 {사람 id: {날짜: 종류 id|null}} — 저장에 실패하면 남겨 두고 다시 보냄
        undo: [],             // [{person, day, prev}]
        saveTimer: null, adding: false,
        typeDraft: null,      // 설정에서 고치는 중인 근무 종류 (모두 저장 전)
        dview: 'cal',         // 아래 메뉴: cal(오늘·달력) · history(고친 기록)
        cal: null,            // 휴대폰 캘린더 일정 {날짜: [일정]} (YeYe홈 앱 1.16부터, 근무표 설정에서 켰을 때만. 아니면 null)
        sel: null,            // 달력에서 누른 날 (아래 일정 칸, 없으면 오늘)
    };

    // ==========================================
    // 서버
    // ==========================================
    async function get(url) {
        const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        let data = {};
        try { data = await res.json(); } catch (e) { /* 본문 없음 */ }
        return { status: res.status, data };
    }
    async function post(url, body) {
        const res = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        let data = {};
        try { data = await res.json(); } catch (e) { /* 본문 없음 */ }
        return { status: res.status, data };
    }
    const msgOf = d => String((d && d.message) || '처리하지 못했어요.').replace(/^❌\s*/, '');
    const act = body => post('/api/ledger/duty', body);
    // YeYe홈 앱 안이면: 근무표를 고쳐 저장했다고 알려 홈 화면 위젯을 새로
    function tellApp() { try { if (window.LedgerApp && window.LedgerApp.dutyChanged) window.LedgerApp.dutyChanged(); } catch (e) { /* 예전 앱 */ } }

    // ==========================================
    // 로그인 (가계부 계정)
    // ==========================================
    function showAuth() {
        st.me = null;
        storageSet(LEDGER_FLAG, '');
        $('app').hidden = true;
        $('who-me').hidden = $('logout').hidden = $('set-open').hidden = true;
        $('auth').hidden = false;
    }
    $('login-form').addEventListener('submit', async e => {
        e.preventDefault();
        const name = $('login-name').value.trim(), password = $('login-pw').value;
        if (!name || !password) { $('auth-msg').textContent = '이름과 비밀번호를 넣어 주세요.'; return; }
        const { status, data } = await post('/api/ledger/session', { action: 'login', name, password });
        if (status !== 200) { $('auth-msg').textContent = msgOf(data); return; }
        $('login-pw').value = '';
        start(data.user);
    });
    $('logout').addEventListener('click', async () => {
        await flush();
        await post('/api/ledger/session', { action: 'logout' });
        showAuth();
    });

    function start(user) {
        st.me = user;
        storageSet(LEDGER_FLAG, user.name);
        $('auth').hidden = true;
        $('app').hidden = false;
        $('who-me').textContent = user.name;
        $('who-me').hidden = $('logout').hidden = $('set-open').hidden = false;
        showSettings(location.hash === '#settings');
        load();
        try { if (window.LedgerApp && window.LedgerApp.loggedIn) window.LedgerApp.loggedIn(); } catch (e) { /* 예전 앱 */ }
    }

    async function boot() {
        let { status, data } = await get('/api/ledger/me');
        if (status === 200) { start(data.user); return; }
        const token = storageGet(ADMIN_TOKEN_KEY, '');
        if (token) {
            ({ status, data } = await post('/api/ledger/session', { action: 'login', password: token }));
            if (status === 200) { start(data.user); return; }
        }
        showAuth();
    }

    async function load() {
        const q = `month=${st.month}` + (st.personId ? `&person=${st.personId}` : '');
        const { status, data } = await get(`/api/ledger/duty?${q}`);
        if (status === 401) { showAuth(); return; }
        if (status !== 200) { $('cal-msg').textContent = '불러오지 못했어요. 잠시 뒤 다시 해 주세요.'; return; }
        st.data = data;
        st.personId = data.person_id;
        storageSet(PERSON_KEY, data.person_id ? String(data.person_id) : '');
        // 저장 전 칠한 것은 화면에 그대로
        for (const [d, t] of Object.entries(st.pending[data.person_id] || {})) {
            if (d.startsWith(st.month)) { if (t == null) delete data.days[d]; else data.days[d] = t; }
            if (d >= data.today && d <= addDays(data.today, 3)) { if (t == null) delete data.near[d]; else data.near[d] = t; }
        }
        if (st.brush && st.brush !== 'clear' && !data.types.some(t => t.id === st.brush)) st.brush = null;
        // 저장하지 못하고 남은 것이 있으면 (다시 로그인한 뒤 등) 곧 다시 보냄
        if (hasPending() && !st.saving) { clearTimeout(st.saveTimer); st.saveTimer = setTimeout(flush, SAVE_DELAY); }
        loadEvents();
        render();
        renderSettings();
    }

    // ==========================================
    // 그리기
    // ==========================================
    const typeOf = id => (st.data.types || []).find(t => t.id === id);
    function badge(id) {
        const t = id != null && typeOf(id);
        return t ? `<span class="badge" style="${badgeStyle(t.color)}">${esc(t.code)}</span>` : '<span class="badge blank">–</span>';
    }
    const timeOf = t => (t.start_time ? `${t.start_time}–${t.end_time}` : '');

    function render() {
        const d = st.data;
        const people = d.people || [];
        $('people').innerHTML = people.map(p => `<button type="button" data-person="${p.id}" class="${p.id === st.personId ? 'on' : ''}">${esc(p.name)}</button>`).join('')
            + (people.length ? '<button type="button" class="add" data-add-person>＋ 사람</button>' : '');
        $('add-person').hidden = !st.adding;
        $('no-person').hidden = !!people.length || st.adding;
        $('roster').hidden = !people.length;
        if (!people.length) return;
        renderToday();
        renderCal();
        renderBrush();
        renderChanges();
        renderDView();
    }
    // 아래 메뉴 (설정이 열려 있으면 '설정'), 달력에서만 ✎
    function renderDView() {
        const set = !$('set-view').hidden, v = set ? 'set' : st.dview, cal = st.dview === 'cal';
        document.querySelectorAll('#dnav [data-dv]').forEach(b => {
            b.classList.toggle('on', b.dataset.dv === v);
            if (b.dataset.dv === v) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
        });
        $('today').hidden = $('cal-sec').hidden = !cal;
        $('changes-sec').hidden = cal;
        $('edit-fab').hidden = !cal || set || !st.data || !(st.data.people || []).length;
        if (!cal) $('brush-sec').hidden = true;
        if (st.data) renderDay();
    }
    $('dnav').addEventListener('click', async e => {
        const b = e.target.closest('[data-dv]');
        if (!b) return;
        if (b.dataset.dv === 'set') { if ($('set-view').hidden) { await flush(); openSettings(); } return; }
        if (!$('set-view').hidden && !okToLeave()) return;
        if (st.editing) setEditing(false);
        if (!$('set-view').hidden) closeSettings();
        if (st.dview !== b.dataset.dv) window.scrollTo(0, 0);
        st.dview = b.dataset.dv;
        if (st.data) { renderBrush(); renderDView(); }
    });
    $('edit-fab').addEventListener('click', () => setEditing(!st.editing));

    function renderToday() {
        const d = st.data, person = d.people.find(p => p.id === st.personId);
        const t = typeOf(d.near[d.today]);
        const big = t ? `${esc(t.name)}${timeOf(t) ? `<span class="time">${timeOf(t)}</span>` : ''}` : '<span class="none">아직 안 넣었어요</span>';
        const next = [1, 2, 3].map(n => {
            const day = addDays(d.today, n);
            return `<div>${n === 1 ? '내일' : WD[parse(day).getDay()]}${badge(d.near[day])}</div>`;
        }).join('');
        $('today').innerHTML = `<div class="main"><div class="lbl">${esc(person ? person.name : '')} · 오늘 ${short(d.today)}</div>
            <div class="big" ${t ? `style="color:${mix(t.color, false, 0.4)}"` : ''}>${big}</div></div><div class="next">${next}</div>`;
    }

    function renderCal() {
        const d = st.data;
        const [y, m] = st.month.split('-').map(Number);
        $('month-label').textContent = `${y}년 ${m}월`;
        $('today-btn').classList.toggle('away', st.month !== ymd(new Date()).slice(0, 7));   // 다른 달을 볼 때는 눈에 띄게
        const first = new Date(y, m - 1, 1).getDay(), last = new Date(y, m, 0).getDate();
        let html = [...WD].map((w, i) => `<div class="wd${i === 0 ? ' sun' : i === 6 ? ' sat' : ''}">${w}</div>`).join('');
        html += '<div class="pad"></div>'.repeat(first);
        const counts = {};
        // 여러 날 일정: 주마다 띠 조각과 줄(lane). 칸에는 그 줄 자리만 비워 두고 띠는 그린 뒤 위에 얹음 (placeBars)
        const max = evMax();
        st.segs = st.cal ? weekSegments(first, last) : null;
        st.segMax = max;
        // 이름이 잘려 두 줄이 된 띠 줄 {'주-줄': true} — 달·폭이 바뀌면 다시 잼 (placeBars가 재서 넣고 다시 그림)
        const twoKey = `${st.month}|${Math.round($('cal').clientWidth)}`;
        if (st.twoKey !== twoKey) { st.twoKey = twoKey; st.two = {}; }
        for (let day = 1; day <= last; day++) {
            const key = `${st.month}-${pad(day)}`, wd = (first + day - 1) % 7, tid = d.days[key];
            if (tid != null) counts[tid] = (counts[tid] || 0) + 1;
            const t = typeOf(tid);
            const evs = (st.cal && st.cal[key]) || [];
            html += `<div class="day${wd === 0 ? ' sun' : wd === 6 ? ' sat' : ''}${key === d.today ? ' today' : ''}${st.cal && key === selDay() ? ' sel' : ''}" data-day="${key}" role="button" aria-label="${m}월 ${day}일${t ? ' ' + esc(t.name) : ''}${evs.length ? ` 일정 ${evs.length}개` : ''}">
                <span class="n">${day}</span>${t ? `<span class="badge" style="${badgeStyle(t.color)}">${esc(t.code)}</span>` : st.cal ? '<span class="badge ph">&nbsp;</span>' : ''}${st.cal ? evCell(key, day, max, Math.floor((first + day - 1) / 7)) : ''}</div>`;
        }
        $('cal').innerHTML = html;
        $('cal').classList.toggle('has-ev', !!st.cal);   // 캘린더 일정 이름 서너 줄 자리만큼 칸을 높게
        fitCells();
        placeBars();
        $('counts').innerHTML = d.types.filter(t => counts[t.id]).map(t => `<span>${esc(t.name)}<b>${counts[t.id]}</b></span>`).join('')
            || '<span>이 달은 아직 넣은 근무가 없어요</span>';
    }

    // ==========================================
    // 휴대폰 캘린더 일정 (YeYe홈 앱 1.16부터): 휴대폰에 연결된 구글 계정 캘린더를 앱이 읽어 줌, 서버로는 안 보냄
    // ==========================================
    const appHas = f => { try { return !!(window.LedgerApp && window.LedgerApp[f]); } catch (e) { return false; } };
    function loadEvents() {
        st.cal = null;
        if (!appHas('calendarEvents')) return;
        const [y, m] = st.month.split('-').map(Number);
        const from = `${st.month}-01`, to = `${st.month}-${pad(new Date(y, m, 0).getDate())}`;
        let list = null;
        try { list = JSON.parse(window.LedgerApp.calendarEvents(from, to)); } catch (e) { list = null; }
        if (!Array.isArray(list)) return;
        const map = {};
        for (const ev of list) {
            // 여러 날 일정은 날마다 (이 달 안만)
            let day = ev.day < from ? from : ev.day;
            const last = ev.endDay > to ? to : ev.endDay;
            for (let i = 0; day <= last && i < 62; i++, day = addDays(day, 1)) (map[day] = map[day] || []).push(ev);
        }
        for (const k of Object.keys(map)) map[k].sort((a, b) => (b.allDay - a.allDay) || String(a.start || '').localeCompare(String(b.start || '')));
        st.cal = map;
    }
    // 칸 안 일정 줄 수: 휴대폰 3줄, 넓은 화면 4줄 (여러 날 일정 띠도 한 줄씩 차지)
    const evMax = () => (window.matchMedia('(max-width: 560px)').matches ? 3 : 4);

    /**
     * 여러 날 일정을 주마다 조각 내어 줄(lane)을 정함 (삼성 달력처럼): 먼저 시작한 것, 같으면 긴 것부터 위 줄.
     * 같은 일정은 그 주 안에서 늘 같은 줄. 반환: [{e, a, b, lane, head, tail}] (a~b는 이 달의 날짜 숫자)
     */
    function weekSegments(first, last) {
        const from = `${st.month}-01`, to = `${st.month}-${pad(last)}`;
        const seen = new Set(), multi = [];
        for (const k of Object.keys(st.cal)) for (const e of st.cal[k]) if (e.day !== e.endDay && !seen.has(e)) { seen.add(e); multi.push(e); }
        multi.sort((x, y) => (x.day < y.day ? -1 : x.day > y.day ? 1 : 0) || (x.endDay > y.endDay ? -1 : x.endDay < y.endDay ? 1 : 0));
        const num = v => Number(v.slice(8)), used = {}, segs = [];
        for (const e of multi) {
            const a0 = e.day < from ? 1 : num(e.day), z = e.endDay > to ? last : num(e.endDay);
            for (let a = a0; a <= z;) {
                const b = Math.min(z, a + 6 - (first + a - 1) % 7);   // 이 주 토요일까지
                let lane = 0;
                while ([...Array(b - a + 1).keys()].some(i => (used[a + i] || []).includes(lane))) lane++;
                for (let d = a; d <= b; d++) (used[d] = used[d] || []).push(lane);
                segs.push({ e, a, b, lane, week: Math.floor((first + a - 1) / 7), head: a === a0 && e.day >= from, tail: b === z && e.endDay <= to });
                a = b + 1;
            }
        }
        return segs;
    }

    // 칸 안 일정: 여러 날 일정 띠 자리(빈 줄, 이름이 두 줄인 띠는 두 줄) 다음에 하루 일정 이름 (캘린더 색 띠), 넘치면 +n.
    // 줄 수(max)는 한 줄짜리 기준 — 두 줄짜리 띠는 두 칸을 씀. 시간 있는 일정은 시작 시각을 앞에 (휴대폰처럼 칸이 좁으면 CSS가 시각을 숨김)
    function evCell(key, day, max, week) {
        const singles = (st.cal[key] || []).filter(e => e.day === e.endDay);
        const over = (st.segs || []).filter(g => g.a <= day && day <= g.b);
        const lanes = over.reduce((n, g) => Math.max(n, g.lane + 1), 0);
        let used = 0, spacers = '', shownLanes = 0;
        for (let l = 0; l < lanes; l++) {
            const two = !!(st.two && st.two[`${week}-${l}`]), h = two ? 2 : 1;
            if (used + h > max) break;
            spacers += `<span class="evc sp${two ? ' two' : ''}"></span>`;
            used += h;
            shownLanes++;
        }
        const room = max - used;
        const hidden = Math.max(0, singles.length - room) + over.filter(g => g.lane >= shownLanes).length;
        const chip = e => `<span class="evc" style="--c:${esc(e.color)}">${!e.allDay ? `<span class="tm">${esc(e.start)}</span>` : ''}${esc(e.title)}</span>`;
        const html = spacers + singles.slice(0, room).map(chip).join('');
        return html || hidden ? `<span class="evs" data-hidden="${hidden}">${html}${hidden ? `<b>+${hidden}</b>` : ''}</span>` : '';
    }

    // 일정 이름은 잘리면 두 줄까지 이어 씀 → 칸에 다 안 들어가면 아래 것부터 숨기고 +n에 더함 (칸 크기가 바뀌면 다시)
    function fitCells() {
        if (!st.cal) return;
        for (const evs of $('cal').querySelectorAll('.day .evs')) {
            const day = evs.parentElement, chips = [...evs.querySelectorAll('.evc:not(.sp)')];
            chips.forEach(c => { c.hidden = false; });
            const bottom = day.getBoundingClientRect().bottom - 1;
            if (bottom < 2) return;   // 안 보이는 중
            let more = evs.querySelector('b'), extra = 0;
            const base = Number(evs.dataset.hidden || 0);
            const over = () => (more || evs).getBoundingClientRect().bottom > bottom + 0.5
                || (chips.filter(c => !c.hidden).pop() || evs).getBoundingClientRect().bottom > bottom + 0.5;
            while (over() && chips.some(c => !c.hidden)) {
                chips.filter(c => !c.hidden).pop().hidden = true;
                extra++;
                if (!more) { more = document.createElement('b'); evs.appendChild(more); }
                more.textContent = `+${base + extra}`;
            }
            if (!extra && more) more.textContent = base ? `+${base}` : '';
        }
    }

    // 여러 날 일정 띠: 칸 사이 틈까지 덮게 달력 위에 얹음 (칸 크기가 바뀌면 다시)
    function placeBars() {
        const cal = $('cal');
        cal.querySelectorAll('.evbar').forEach(el => el.remove());
        if (!st.cal || !st.segs || !st.segs.length) return;
        const rc = cal.getBoundingClientRect();
        if (!rc.width) return;   // 안 보이는 중 (보이면 ResizeObserver가 다시 부름)
        let grew = false;
        for (const g of st.segs) {
            const c0 = cal.querySelector(`[data-day="${st.month}-${pad(g.a)}"]`), c1 = cal.querySelector(`[data-day="${st.month}-${pad(g.b)}"]`);
            const sp = c0 && c0.querySelectorAll('.evc.sp')[g.lane];
            if (!sp || !c1) continue;
            const r0 = c0.getBoundingClientRect(), r1 = c1.getBoundingClientRect(), rs = sp.getBoundingClientRect();
            const el = document.createElement('span');
            const two = sp.classList.contains('two');
            el.className = `evbar${two ? ' two' : ''}${g.head ? ' head' : ''}${g.tail ? ' tail' : ''}`;
            el.style.cssText = `left:${r0.left - rc.left + 2}px;width:${r1.right - r0.left - 4}px;top:${rs.top - rc.top}px;height:${rs.height}px;--c:${g.e.color}`;
            el.textContent = g.e.title;
            cal.appendChild(el);
            // 한 줄에 이름이 다 안 들어가면 그 주의 그 줄을 두 줄로 (다시 그림)
            if (!two && el.scrollWidth > el.clientWidth + 1) { st.two[`${g.week}-${g.lane}`] = true; grew = true; }
        }
        if (grew) renderCal();
    }
    let resizeWait = 0;
    if (window.ResizeObserver) new ResizeObserver(() => {
        if (!st.cal || !st.data) return;
        // 크기가 다 바뀐 뒤에 한 번 (바뀌는 도중의 폭으로 두 줄 띠를 정하지 않게).
        // 휴대폰↔넓은 화면이 바뀌거나 폭이 바뀌면 줄 수·두 줄 띠부터 다시
        clearTimeout(resizeWait);
        resizeWait = setTimeout(() => {
            if (evMax() !== st.segMax || `${st.month}|${Math.round($('cal').clientWidth)}` !== st.twoKey) renderCal();
            else { fitCells(); placeBars(); }
        }, 150);
    }).observe($('cal'));
    function evTime(e, day) {
        if (e.allDay) return '종일';
        if (day === e.day && day === e.endDay) return `${e.start}–${e.end}`;
        if (day === e.day) return `${e.start}부터`;
        if (day === e.endDay) return `${e.end}까지`;
        return '종일';
    }
    // 아래 일정 칸에 보일 날: 누른 날, 없으면 오늘 (오늘이 이 달일 때)
    const selDay = () => (st.sel && st.sel.startsWith(st.month) ? st.sel : st.data.today.startsWith(st.month) ? st.data.today : null);
    function renderDay() {
        const sec = $('day-sec'), day = selDay();
        sec.hidden = !st.cal || !day || st.editing || st.dview !== 'cal' || !(st.data.people || []).length;
        if (sec.hidden) return;
        const t = typeOf(st.data.days[day]), list = st.cal[day] || [];
        sec.innerHTML = `<div class="day-head"><b>${short(day)}${day === st.data.today ? ' · 오늘' : ''}</b>`
            + (t ? `<span class="badge" style="${badgeStyle(t.color)}">${esc(t.code)}</span><span class="tn">${esc(t.name)}${timeOf(t) ? ' ' + timeOf(t) : ''}</span>` : '')
            + '</div>'
            + (list.length ? list.map(e => `<div class="ev"><i style="background:${esc(e.color)}"></i><span class="tm">${evTime(e, day)}</span><span class="tt">${esc(e.title)}</span></div>`).join('')
                : '<p class="hint">캘린더 일정이 없어요</p>');
    }
    // 근무표 설정 > 구글 캘린더 (앱 안에서만)
    function renderGcal() {
        const inApp = !!window.LedgerApp;
        $('gcal-set').hidden = !inApp;
        if (!inApp) return;
        let s = null;
        try { if (appHas('calendarState')) s = JSON.parse(window.LedgerApp.calendarState()); } catch (e) { s = null; }
        if (!s || s.on == null) { $('gcal-body').innerHTML = '<p class="hint">YeYe홈 앱을 1.16 이상으로 올리면 쓸 수 있어요. (홈 &gt; 설정 &gt; 새 버전 확인)</p>'; return; }
        let html = `<label class="gcal-on"><input type="checkbox" id="gcal-on"${s.on ? ' checked' : ''}> 달력에 캘린더 일정 보이기</label>`;
        if (s.on && !s.allowed) {
            html += '<p class="hint gcal-warn">캘린더를 읽을 권한이 없어 일정을 못 보여요. <button type="button" class="small" id="gcal-ask">권한 허용하기</button></p>';
        } else if (s.on) {
            const cals = s.calendars || [];
            if (!cals.length) html += '<p class="hint">이 휴대폰에 캘린더가 없어요. 휴대폰 설정 &gt; 계정 &gt; 구글에서 캘린더 동기화를 켜 주세요.</p>';
            let acc = null;
            html += cals.map(c => {
                const head = c.account !== acc ? `<div class="gcal-acc">${esc(c.account)}</div>` : '';
                acc = c.account;
                return `${head}<label class="gcal-row"><input type="checkbox" data-gcal="${esc(c.id)}"${c.shown ? ' checked' : ''}><i style="background:${esc(c.color)}"></i>${esc(c.name)}</label>`;
            }).join('');
        }
        html += '<p class="hint">휴대폰에 연결된 계정의 캘린더를 읽기만 하고 서버로 보내지 않아요. 그래서 이 휴대폰에서만 보여요.</p>';
        $('gcal-body').innerHTML = html;
    }
    $('gcal-body').addEventListener('change', e => {
        try {
            if (e.target.id === 'gcal-on') window.LedgerApp.setCalendarOn(e.target.checked);
            else if (e.target.dataset.gcal) { window.LedgerApp.setCalendarShown(e.target.dataset.gcal, e.target.checked); window.appCalendarChanged(); }
        } catch (err) { /* 예전 앱 */ }
    });
    $('gcal-body').addEventListener('click', e => {
        if (e.target.id === 'gcal-ask') { try { window.LedgerApp.askCalendar(); } catch (err) { /* 예전 앱 */ } }
    });
    // 앱이 부름: 캘린더 켜고 끔·권한이 바뀜·앱으로 돌아옴 → 일정을 새로 읽음
    window.appCalendarChanged = () => {
        if (!st.data) return;
        loadEvents();
        if ((st.data.people || []).length) { renderCal(); renderDay(); }
        renderGcal();
    };

    function renderBrush() {
        const person = (st.data.people || []).find(p => p.id === st.personId);
        $('cal-sec').classList.toggle('editing', st.editing);
        $('brush-sec').hidden = !st.editing || st.dview !== 'cal';
        $('edit-btn').textContent = st.editing ? '완료' : '고치기';
        $('edit-fab').innerHTML = st.editing ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>' : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>';
        $('edit-fab').setAttribute('aria-label', st.editing ? '고치기 끝' : '고치기');
        $('edit-fab').classList.toggle('editing', st.editing);
        $('edit-label').textContent = st.editing ? `고치는 중 · ${person ? person.name : ''}` : '달력';
        $('brush').innerHTML = st.data.types.map(t => `<button type="button" data-brush="${t.id}" class="${st.brush === t.id ? 'on' : ''}" style="${badgeStyle(t.color)}" title="${esc(t.name)} ${timeOf(t)}">${esc(t.code)}</button>`).join('')
            + `<button type="button" data-brush="clear" class="clear${st.brush === 'clear' ? ' on' : ''}">지우기</button>`;
        const t = st.brush && st.brush !== 'clear' && typeOf(st.brush);
        $('brush-hint').textContent = st.brush === 'clear' ? '누르는 날의 근무를 지워요'
            : t ? `${t.name}${timeOf(t) ? ` ${timeOf(t)}` : ''} · 날짜를 누르면 들어가요 (다시 누르면 지움)` : '근무를 고르고 날짜를 누르면 들어가요';
        $('undo').hidden = !st.undo.length;
    }

    function renderChanges() {
        const list = st.data.changes || [];
        $('changes').innerHTML = (list.length ? '' : '<p class="hint">아직 고친 게 없어요</p>') + list.map(c => `<div class="ch">${c.type_id == null ? '<span class="badge blank">지움</span>' : badge(c.type_id)}
            <span class="d">${short(c.day)}</span><span class="w">${esc(c.who || '누군가')} · ${ago(c.changed_at)}</span></div>`).join('');
    }
    function ago(at) {
        const t = new Date(at.replace(' ', 'T')), s = (Date.now() - t) / 1000;
        if (s < 90) return '방금';
        if (s < 3600) return `${Math.round(s / 60)}분 전`;
        if (s < 86400) return `${Math.round(s / 3600)}시간 전`;
        if (s < 86400 * 2) return '어제';
        return `${t.getMonth() + 1}/${t.getDate()}`;
    }

    // ==========================================
    // 근무 칠하기: 화면은 바로 바꾸고 잠깐 모았다가 저장
    // ==========================================
    function apply(day, tid, recordUndo) {
        const d = st.data, prev = d.days[day] ?? null;
        if (prev === tid) return;
        if (recordUndo) st.undo.push({ person: st.personId, day, prev });
        if (tid == null) delete d.days[day]; else d.days[day] = tid;
        if (day >= d.today && day <= addDays(d.today, 3)) { if (tid == null) delete d.near[day]; else d.near[day] = tid; }
        (st.pending[st.personId] = st.pending[st.personId] || {})[day] = tid;
        clearTimeout(st.saveTimer);
        st.saveTimer = setTimeout(flush, SAVE_DELAY);
        renderToday(); renderCal(); renderBrush();
    }
    // 사람마다 모아 둔 것을 보냄. 연결이 끊겼거나 서버가 잠깐 안 되면(응답 없음·5xx·429) 칠한 것을 그대로 남겨 두고
    // 잠시 뒤·온라인이 되면·화면에 돌아오면 다시 보냄 (예전에는 보내기 전에 비워서 실패하면 조용히 사라졌음).
    // 서버가 거절한 것(없는 사람·근무 종류 등)만 버리고 서버 것으로 다시 그림
    async function flush() {
        clearTimeout(st.saveTimer);
        if (st.saving) { await st.saving; if (hasPending()) return flush(); return; }
        const jobs = Object.entries(st.pending).filter(([, d]) => Object.keys(d).length);
        if (!jobs.length) return;
        st.pending = {};
        let failed = false, rejected = null, auth = false;
        st.saving = (async () => {
            for (const [person, days] of jobs) {
                let status = 0, data = {};
                try { ({ status, data } = await act({ action: 'set', person_id: Number(person), days })); } catch (e) { status = 0; }
                if (status === 200) continue;
                if (status === 0 || status >= 500 || status === 429 || status === 401) {
                    // 남겨 둠 (그 사이 다시 칠한 날은 새로 칠한 것이 이김)
                    st.pending[person] = { ...days, ...(st.pending[person] || {}) };
                    failed = true;
                    if (status === 401) auth = true;
                } else rejected = data;
            }
        })();
        try { await st.saving; } finally { st.saving = null; }
        if (auth) { showAuth(); return; }
        if (failed) {
            $('cal-msg').textContent = '저장하지 못했어요 · 연결되면 다시 저장할게요 (칠한 것은 그대로 있어요)';
            clearTimeout(st.saveTimer);
            st.saveTimer = setTimeout(flush, RETRY_DELAY);
        }
        if (rejected) { $('cal-msg').textContent = msgOf(rejected); load(); return; }
        if (failed) return;
        $('cal-msg').textContent = '';
        tellApp();
        // 최근 고친 것만 새로 (칠하는 중에 달력을 다시 그리지 않음)
        if (!hasPending()) refreshChanges();
    }
    window.addEventListener('online', () => { if (hasPending()) flush(); });
    async function refreshChanges() {
        const { status, data } = await get(`/api/ledger/duty?month=${st.month}&person=${st.personId}`);
        if (status === 200 && st.data && data.person_id === st.personId) { st.data.changes = data.changes; renderChanges(); }
    }

    $('cal').addEventListener('click', e => {
        const cell = e.target.closest('[data-day]');
        if (!cell) return;
        if (!st.editing) {
            // 캘린더를 켰으면 그날 일정을 아래에 (근무를 바꾸려면 연필 단추)
            if (st.cal) { st.sel = cell.dataset.day; $('cal-msg').textContent = ''; renderCal(); renderDay(); return; }
            $('cal-msg').textContent = '근무를 바꾸려면 오른쪽 아래 연필 단추를 눌러 주세요.';
            return;
        }
        if (!st.brush) { $('cal-msg').textContent = '아래에서 넣을 근무를 먼저 골라 주세요.'; return; }
        $('cal-msg').textContent = '';
        const day = cell.dataset.day, cur = st.data.days[day] ?? null;
        apply(day, st.brush === 'clear' || cur === st.brush ? null : st.brush, true);
    });
    $('brush').addEventListener('click', e => {
        const b = e.target.closest('[data-brush]');
        if (!b) return;
        const v = b.dataset.brush === 'clear' ? 'clear' : Number(b.dataset.brush);
        st.brush = st.brush === v ? null : v;
        $('cal-msg').textContent = '';
        renderBrush();
    });
    $('undo').addEventListener('click', async () => {
        const u = st.undo.pop();
        if (!u) return;
        if (u.person !== st.personId) { await switchPerson(u.person); }
        if (!u.day.startsWith(st.month)) { await flush(); st.month = u.day.slice(0, 7); await load(); }
        apply(u.day, u.prev, false);
    });

    // 고치기 시작·끝 (끝낼 때 칠한 것을 바로 저장하고 되돌리기 목록도 비움)
    function setEditing(on) {
        st.editing = on;
        if (!on) { st.brush = null; st.undo = []; flush(); }
        $('cal-msg').textContent = '';
        renderBrush();
        if (st.data && (st.data.people || []).length) renderDay();
    }
    $('edit-btn').addEventListener('click', () => setEditing(!st.editing));

    // 달 넘기기
    async function goMonth(n) {
        await flush();
        const [y, m] = st.month.split('-').map(Number);
        st.month = ymd(new Date(y, m - 1 + n, 1)).slice(0, 7);
        st.sel = null;
        load();
    }
    $('prev').addEventListener('click', () => goMonth(-1));
    $('next').addEventListener('click', () => goMonth(1));
    // 오늘로: 이번 달로 가서 오늘 날짜를 고름 (아래에 오늘 일정). 달 이름을 눌러도 같음
    async function goToday() {
        await flush();
        const month = ymd(new Date()).slice(0, 7);
        st.sel = null;
        if (st.month === month && st.data) { renderCal(); renderDay(); return; }
        st.month = month;
        load();
    }
    $('month-label').addEventListener('click', goToday);
    $('today-btn').addEventListener('click', goToday);

    // ==========================================
    // 사람 고르기·더하기
    // ==========================================
    async function switchPerson(id) {
        await flush();
        st.personId = id;
        await load();
    }
    function openAdd(on) {
        st.adding = on;
        $('ap-msg').textContent = '';
        render();
        if (on) { $('ap-name').value = ''; $('ap-name').focus(); }
    }
    $('people').addEventListener('click', e => {
        const b = e.target.closest('[data-person]');
        if (b) { switchPerson(Number(b.dataset.person)); return; }
        if (e.target.closest('[data-add-person]')) openAdd(true);
    });
    $('first-person').addEventListener('click', () => openAdd(true));
    $('ap-cancel').addEventListener('click', () => openAdd(false));
    async function addPerson() {
        const name = $('ap-name').value.trim();
        if (!name) { $('ap-msg').textContent = '이름을 넣어 주세요.'; return; }
        const { status, data } = await act({ action: 'person-add', name });
        if (status !== 200) { $('ap-msg').textContent = msgOf(data); return; }
        st.adding = false;
        tellApp();
        await switchPerson(data.id);
    }
    $('ap-save').addEventListener('click', addPerson);
    $('ap-name').addEventListener('keydown', e => { if (e.key === 'Enter') addPerson(); });

    // ==========================================
    // 설정 (#settings): 근무 종류 · 사람
    // ==========================================
    function showSettings(on) {
        $('main-view').hidden = on;
        $('set-view').hidden = !on;
        if (on) window.scrollTo(0, 0);
        renderDView();
    }
    function openSettings() {
        if (location.hash !== '#settings') history.pushState({ dutySettings: 1 }, '', '#settings');
        showSettings(true);
        renderSettings();
    }
    function closeSettings() {
        st.typeDraft = null;
        if (location.hash === '#settings' && (history.state || {}).dutySettings) history.back();
        else {
            if (location.hash === '#settings') history.replaceState(null, '', location.pathname + location.search);
            showSettings(false);
        }
        load();
    }
    window.addEventListener('popstate', () => { if (st.me) { showSettings(location.hash === '#settings'); if (location.hash !== '#settings') load(); } });
    $('set-open').addEventListener('click', async () => { await flush(); openSettings(); });
    $('set-back').addEventListener('click', () => { if (okToLeave()) closeSettings(); });

    // ==========================================
    // 근무 종류: 고친 것을 모아 두었다가 '모두 저장'으로 한 번에 (고친 줄은 노랗게). 지우기(✕)만 바로.
    // 시간 칸: 휴대폰은 휴대폰의 시간 고르기 그대로, PC는 글자 칸 + 30분 간격 목록 (숫자로 치기·↑↓·휠로 10분씩)
    // ==========================================
    const touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    const F = ['code', 'name', 'start_time', 'end_time', 'color'];
    let rowKey = 0;
    const draftOf = t => ({ key: ++rowKey, id: t.id ?? null, code: t.code || '', name: t.name || '', start_time: t.start_time || '', end_time: t.end_time || '', color: (t.color || PRESET[5]).toUpperCase() });
    const origOf = r => r.id != null && (st.data.types || []).find(t => t.id === r.id);
    function rowChanged(r) {
        const o = origOf(r);
        if (!o) return true;   // 새 줄
        return F.some(f => String(r[f] || '').trim() !== String((f === 'color' ? (o.color || '').toUpperCase() : o[f]) || '').trim());
    }
    const changedCount = () => (st.typeDraft || []).filter(rowChanged).length;
    function timeField(r, f, label) {
        if (touch) return `<input data-f="${f}" type="time" value="${esc(r[f])}" aria-label="${label}">`;
        return `<span class="tpick"><input data-f="${f}" class="tinput" value="${esc(r[f])}" placeholder="--:--" maxlength="5" autocomplete="off" aria-label="${label}"><span class="tlist" hidden></span></span>`;
    }
    function typeRow(r, bad) {
        return `<div class="trow${rowChanged(r) ? ' changed' : ''}${bad ? ' bad' : ''}" data-key="${r.key}">
            <input class="code" data-f="code" maxlength="4" placeholder="글자" value="${esc(r.code)}" aria-label="짧은 글자">
            <input data-f="name" maxlength="10" placeholder="이름 (예: 데이)" value="${esc(r.name)}" aria-label="이름">
            <div class="times"><span>시간</span>${timeField(r, 'start_time', '시작 시간')}<span>~</span>${timeField(r, 'end_time', '끝 시간')}</div>
            <div class="acts"><button type="button" class="small ${r.id != null ? 'danger' : ''}" data-type-del aria-label="${r.id != null ? '이 근무 종류 지우기' : '이 줄 빼기'}">✕</button></div>
            <div class="colors"><span class="badge prev" style="${badgeStyle(r.color)}">${esc(r.code || '글자')}</span>
                ${PRESET.map(c => `<button type="button" class="sw${c === r.color ? ' on' : ''}" data-color="${c}" style="background:${c}" aria-label="색 ${c}"></button>`).join('')}</div>
        </div>`;
    }
    function renderTypes(badKey) {
        if (!st.typeDraft) st.typeDraft = (st.data.types || []).map(draftOf);
        $('types').innerHTML = st.typeDraft.map(r => typeRow(r, r.key === badKey)).join('');
        renderSaveBtn();
    }
    function renderSaveBtn() {
        const n = changedCount();
        $('type-save').textContent = n ? `모두 저장 (${n}개 바뀜)` : '바뀐 것 없음';
        $('type-save').classList.toggle('primary', !!n);
        document.querySelectorAll('#types .trow').forEach(el => {
            const r = st.typeDraft.find(x => String(x.key) === el.dataset.key);
            if (r) el.classList.toggle('changed', rowChanged(r));
        });
    }
    const rowOf = el => st.typeDraft.find(x => String(x.key) === el.closest('.trow').dataset.key);
    $('types').addEventListener('input', e => {
        const f = e.target.dataset.f;
        if (!f) return;
        const r = rowOf(e.target);
        r[f] = e.target.value;
        if (f === 'code') e.target.closest('.trow').querySelector('.prev').textContent = e.target.value.trim() || '글자';
        if (e.target.classList.contains('tinput')) showTimes(e.target);
        renderSaveBtn();
    });
    $('types').addEventListener('click', async e => {
        const row = e.target.closest('.trow');
        if (!row) return;
        const r = rowOf(row);
        const sw = e.target.closest('[data-color]');
        if (sw) {
            r.color = sw.dataset.color;
            row.querySelectorAll('.sw').forEach(b => b.classList.toggle('on', b === sw));
            row.querySelector('.prev').setAttribute('style', badgeStyle(r.color));
            renderSaveBtn();
            return;
        }
        const pick = e.target.closest('[data-time]');
        if (pick) { e.preventDefault(); const input = pick.closest('.tpick').querySelector('input'); setTime(input, pick.dataset.time); hideTimes(input); return; }
        if (!e.target.closest('[data-type-del]')) return;
        if (r.id == null) { st.typeDraft = st.typeDraft.filter(x => x !== r); renderTypes(); return; }
        const t = typeOf(r.id);
        if (!confirm(`'${t ? t.name : r.name}' 근무 종류를 지울까요?`)) return;
        const { status, data } = await act({ action: 'type-delete', id: r.id });
        $('type-msg').classList.toggle('ok', status === 200);
        $('type-msg').textContent = status === 200 ? '지웠어요.' : msgOf(data);
        if (status !== 200) return;
        st.typeDraft = st.typeDraft.filter(x => x !== r);   // 다른 줄의 고친 것은 그대로
        st.data.types = st.data.types.filter(x => x.id !== r.id);
        renderTypes();
        tellApp();
        load();
    });
    $('type-add').addEventListener('click', () => {
        const used = new Set(st.typeDraft.map(t => t.color));
        st.typeDraft.push(draftOf({ color: PRESET.find(c => !used.has(c)) || PRESET[5] }));
        $('type-msg').textContent = '';
        renderTypes();
        $('types').querySelector('.trow:last-child [data-f="code"]').focus();
    });
    $('type-save').addEventListener('click', async () => {
        if (!changedCount()) return;
        const rows = st.typeDraft;
        const types = rows.map(r => ({ ...(r.id != null ? { id: r.id } : {}), code: r.code, name: r.name, start_time: normTime(r.start_time) ?? r.start_time, end_time: normTime(r.end_time) ?? r.end_time, color: r.color }));
        $('type-save').disabled = true;
        const { status, data } = await act({ action: 'type-save', types });
        $('type-save').disabled = false;
        $('type-msg').classList.toggle('ok', status === 200);
        if (status !== 200) {
            const bad = rows[data.row];
            $('type-msg').textContent = (bad ? `${bad.code || '새'} 줄: ` : '') + msgOf(data);
            renderTypes(bad && bad.key);
            return;
        }
        $('type-msg').textContent = '저장했어요.';
        st.typeDraft = null;
        tellApp();
        await load();
        renderTypes();
    });
    const typesDirty = () => !!st.typeDraft && changedCount() > 0;
    const okToLeave = () => !typesDirty() || confirm('저장하지 않은 근무 종류 변경이 있어요. 버리고 나갈까요?');

    // ---- PC 시간 칸: '7' → 07:00, '1530' → 15:30, '9:15' → 09:15, 빈 칸은 시간 없음 (틀리면 null)
    function normTime(v) {
        const s = String(v || '').trim();
        if (!s) return '';
        let m = s.match(/^(\d{1,2}):?(\d{2})?$/);
        if (!m && /^\d{3,4}$/.test(s)) m = [s, s.slice(0, s.length - 2), s.slice(-2)];
        if (!m) return null;
        const h = Number(m[1]), mi = Number(m[2] || 0);
        return h < 24 && mi < 60 ? `${pad(h)}:${pad(mi)}` : null;
    }
    const toMin = t => { const [h, m] = t.split(':').map(Number); return h * 60 + m; };
    const fromMin = n => { n = ((n % 1440) + 1440) % 1440; return `${pad(Math.floor(n / 60))}:${pad(n % 60)}`; };
    function setTime(input, v) {
        input.value = v;
        rowOf(input)[input.dataset.f] = v;
        input.classList.remove('bad');
        renderSaveBtn();
    }
    function showTimes(input) {
        const list = input.parentElement.querySelector('.tlist'), r = rowOf(input);
        const start = input.dataset.f === 'end_time' && normTime(r.start_time);
        const cur = normTime(input.value);
        list.innerHTML = Array.from({ length: 48 }, (_, i) => {
            const t = fromMin(i * 30);
            const len = start ? ((toMin(t) - toMin(start) + 1440) % 1440) / 60 : null;
            return `<button type="button" data-time="${t}" class="${t === cur ? 'sel' : ''}" tabindex="-1">${t}${len ? `<small>${len}시간</small>` : ''}</button>`;
        }).join('');
        list.hidden = false;
        const near = cur ? list.querySelector(`[data-time="${fromMin(Math.round(toMin(cur) / 30) * 30)}"]`) : list.querySelector('[data-time="07:00"]');
        if (near) list.scrollTop = near.offsetTop - 60;
    }
    function hideTimes(input) { input.parentElement.querySelector('.tlist').hidden = true; }
    $('types').addEventListener('focusin', e => { if (e.target.classList.contains('tinput')) showTimes(e.target); });
    $('types').addEventListener('mousedown', e => { if (e.target.closest('[data-time]')) e.preventDefault(); });   // 목록을 누를 때 칸에서 커서가 빠지지 않게
    $('types').addEventListener('focusout', e => {
        if (!e.target.classList.contains('tinput')) return;
        const v = normTime(e.target.value);
        if (v == null) e.target.classList.add('bad'); else setTime(e.target, v);
        hideTimes(e.target);
    });
    function stepTime(input, d) {
        const cur = normTime(input.value) || '07:00';
        setTime(input, fromMin(toMin(cur) + d));
        showTimes(input);
    }
    $('types').addEventListener('keydown', e => {
        if (!e.target.classList.contains('tinput')) return;
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); stepTime(e.target, e.key === 'ArrowUp' ? 10 : -10); }
        else if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); }
        else if (e.key === 'Escape') hideTimes(e.target);
    });
    $('types').addEventListener('wheel', e => {
        if (!e.target.classList.contains('tinput') || document.activeElement !== e.target) return;
        e.preventDefault();
        stepTime(e.target, e.deltaY < 0 ? 10 : -10);
    }, { passive: false });

    function renderSettings() {
        if (!st.data) return;
        const hp = Number(storageGet(HOME_PERSON_KEY, 0));
        $('home-person').innerHTML = st.data.people.length
            ? st.data.people.map((p, i) => `<option value="${p.id}"${p.id === hp || (!hp && i === 0) ? ' selected' : ''}>${esc(p.name)}</option>`).join('')
            : '<option value="">(사람이 없어요)</option>';
        renderGcal();
        if (!st.typeDraft) renderTypes();   // 고치는 중이면 칸을 다시 그리지 않음 (친 글자·커서 그대로)
        $('people-edit').innerHTML = st.data.people.map(p => `<div class="prow" data-pe="${p.id}">
            <input maxlength="20" value="${esc(p.name)}" aria-label="이름"><button type="button" class="small" data-pe-save>이름 바꾸기</button>
            <button type="button" class="small danger" data-pe-del>지우기</button></div>`).join('')
            || '<p class="hint">아직 사람이 없어요. 근무표 화면에서 더할 수 있어요.</p>';
    }
    $('home-person').addEventListener('change', e => {
        storageSet(HOME_PERSON_KEY, e.target.value);
        try { if (window.LedgerApp && window.LedgerApp.setDutyPerson) window.LedgerApp.setDutyPerson(Number(e.target.value) || 0); } catch (err) { /* 예전 앱 */ }
    });
    $('people-edit').addEventListener('click', async e => {
        const row = e.target.closest('[data-pe]');
        if (!row) return;
        const id = Number(row.dataset.pe), person = st.data.people.find(p => p.id === id);
        let res;
        if (e.target.closest('[data-pe-save]')) {
            res = await act({ action: 'person-rename', id, name: row.querySelector('input').value.trim() });
            if (res.status === 200) res.ok = '이름을 바꿨어요.';
        } else if (e.target.closest('[data-pe-del]')) {
            if (!confirm(`'${person.name}'의 근무표를 지울까요? 넣은 근무도 모두 지워지고 되돌릴 수 없어요.`)) return;
            res = await act({ action: 'person-delete', id });
            if (res.status === 200) { res.ok = '지웠어요.'; if (st.personId === id) st.personId = null; }
        } else return;
        $('pe-msg').classList.toggle('ok', res.status === 200);
        $('pe-msg').textContent = res.status === 200 ? res.ok : msgOf(res.data);
        if (res.status === 200) { tellApp(); load(); }
    });

    // ==========================================
    // 앱의 뒤로가기 (YeYe홈 앱이 부름): 열린 것을 하나씩 닫고, 닫을 게 없으면 false
    // ==========================================
    window.appBusy = () => !$('set-view').hidden || !!st.adding || !!st.editing;   // 앱(1.30부터)의 좌우 밀기·새로고침을 막음
    window.ledgerBack = () => {
        if (!$('set-view').hidden) { if (okToLeave()) closeSettings(); return true; }
        if (st.adding) { openAdd(false); return true; }
        if (st.editing) { setEditing(false); return true; }
        return false;
    };
    // 앱(YeYe홈)이 부름: 위쪽 '설정' → 근무표 설정, 다른 탭으로 감 → 고치기 끝
    window.appOpenSettings = () => { if (!st.me) return false; flush(); openSettings(); return true; };
    window.appTabHidden = () => { if (st.editing) setEditing(false); else flush(); };
    // 앱(1.25부터)이 부름: 한 달 위젯에서 날짜를 누름 → 그 사람·그 달로 가서 그날을 고름 (아래에 그날 근무·일정)
    window.appOpenDay = async (day, person) => {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
        // 앱을 막 열었으면 로그인·처음 읽기가 끝날 때까지 잠깐 기다림 (그 뒤에 그 날짜로)
        for (let i = 0; i < 40 && !(st.me && st.data); i++) await new Promise(r => setTimeout(r, 250));
        if (!st.me || !st.data) return false;
        if (!$('set-view').hidden) closeSettings();
        if (st.editing) setEditing(false);
        await flush();
        st.dview = 'cal';
        st.sel = day;
        const samePerson = !person || person === st.personId;
        if (st.data && samePerson && st.month === day.slice(0, 7)) { render(); }
        else {
            st.month = day.slice(0, 7);
            if (person) st.personId = person;
            await load();
        }
        const sec = $('day-sec');
        if (sec && !sec.hidden) sec.scrollIntoView({ block: 'center' });
        return true;
    };
    if (window.LedgerApp) document.documentElement.classList.add('in-app');

    // 다른 화면에 갔다 오면 새로 (다른 멤버가 고쳤을 수 있음). 떠날 때는 칠한 것을 바로 저장
    document.addEventListener('visibilitychange', () => {
        if (!st.me) return;
        if (document.visibilityState === 'hidden') flush();
        else if (hasPending()) flush();
        else if ($('set-view').hidden) load();
    });
    window.addEventListener('pagehide', () => {
        // 떠날 때는 남은 것을 한 번 더 보내 봄 (못 보내면 다음에 열 때는 없음 — 이 페이지 안에만 모아 둠)
        for (const [person, days] of Object.entries(st.pending)) {
            if (!Object.keys(days).length) continue;
            try {
                fetch('/api/ledger/duty', { method: 'POST', keepalive: true, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'set', person_id: Number(person), days }) });
            } catch (e) { /* 보내지 못함 */ }
        }
    });

    boot();
})();
