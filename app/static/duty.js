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
        pending: {},          // 저장 전 바뀐 날 {날짜: 종류 id|null}
        undo: [],             // [{person, day, prev}]
        saveTimer: null, adding: false, newType: null,
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
        for (const [d, t] of Object.entries(st.pending)) {
            if (d.startsWith(st.month)) { if (t == null) delete data.days[d]; else data.days[d] = t; }
            if (d >= data.today && d <= addDays(data.today, 3)) { if (t == null) delete data.near[d]; else data.near[d] = t; }
        }
        if (st.brush && st.brush !== 'clear' && !data.types.some(t => t.id === st.brush)) st.brush = null;
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
    }

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
        const first = new Date(y, m - 1, 1).getDay(), last = new Date(y, m, 0).getDate();
        let html = [...WD].map((w, i) => `<div class="wd${i === 0 ? ' sun' : i === 6 ? ' sat' : ''}">${w}</div>`).join('');
        html += '<div class="pad"></div>'.repeat(first);
        const counts = {};
        for (let day = 1; day <= last; day++) {
            const key = `${st.month}-${pad(day)}`, wd = (first + day - 1) % 7, tid = d.days[key];
            if (tid != null) counts[tid] = (counts[tid] || 0) + 1;
            const t = typeOf(tid);
            html += `<div class="day${wd === 0 ? ' sun' : wd === 6 ? ' sat' : ''}${key === d.today ? ' today' : ''}" data-day="${key}" role="button" aria-label="${m}월 ${day}일${t ? ' ' + esc(t.name) : ''}">
                <span class="n">${day}</span>${t ? `<span class="badge" style="${badgeStyle(t.color)}">${esc(t.code)}</span>` : ''}</div>`;
        }
        $('cal').innerHTML = html;
        $('counts').innerHTML = d.types.filter(t => counts[t.id]).map(t => `<span>${esc(t.name)}<b>${counts[t.id]}</b></span>`).join('')
            || '<span>이 달은 아직 넣은 근무가 없어요</span>';
    }

    function renderBrush() {
        const person = (st.data.people || []).find(p => p.id === st.personId);
        $('cal-sec').classList.toggle('editing', st.editing);
        $('brush-sec').hidden = !st.editing;
        $('edit-btn').textContent = st.editing ? '완료' : '고치기';
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
        $('changes-sec').hidden = !list.length;
        $('changes').innerHTML = list.map(c => `<div class="ch">${c.type_id == null ? '<span class="badge blank">지움</span>' : badge(c.type_id)}
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
        st.pending[day] = tid;
        clearTimeout(st.saveTimer);
        st.saveTimer = setTimeout(flush, SAVE_DELAY);
        renderToday(); renderCal(); renderBrush();
    }
    async function flush() {
        clearTimeout(st.saveTimer);
        const days = st.pending, person = st.personId;
        if (!Object.keys(days).length || !person) return;
        st.pending = {};
        const { status, data } = await act({ action: 'set', person_id: person, days });
        if (status !== 200) { $('cal-msg').textContent = msgOf(data); load(); return; }
        $('cal-msg').textContent = '';
        tellApp();
        // 최근 고친 것만 새로 (칠하는 중에 달력을 다시 그리지 않음)
        if (!Object.keys(st.pending).length) refreshChanges();
    }
    async function refreshChanges() {
        const { status, data } = await get(`/api/ledger/duty?month=${st.month}&person=${st.personId}`);
        if (status === 200 && st.data && data.person_id === st.personId) { st.data.changes = data.changes; renderChanges(); }
    }

    $('cal').addEventListener('click', e => {
        const cell = e.target.closest('[data-day]');
        if (!cell) return;
        if (!st.editing) { $('cal-msg').textContent = "근무를 바꾸려면 위의 '고치기'를 눌러 주세요."; return; }
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
    }
    $('edit-btn').addEventListener('click', () => setEditing(!st.editing));

    // 달 넘기기
    async function goMonth(n) {
        await flush();
        const [y, m] = st.month.split('-').map(Number);
        st.month = ymd(new Date(y, m - 1 + n, 1)).slice(0, 7);
        load();
    }
    $('prev').addEventListener('click', () => goMonth(-1));
    $('next').addEventListener('click', () => goMonth(1));
    $('month-label').addEventListener('click', async () => { await flush(); st.month = ymd(new Date()).slice(0, 7); load(); });

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
    }
    function openSettings() {
        if (location.hash !== '#settings') history.pushState({ dutySettings: 1 }, '', '#settings');
        showSettings(true);
        renderSettings();
    }
    function closeSettings() {
        if (location.hash === '#settings' && (history.state || {}).dutySettings) history.back();
        else {
            if (location.hash === '#settings') history.replaceState(null, '', location.pathname + location.search);
            showSettings(false);
        }
        load();
    }
    window.addEventListener('popstate', () => { if (st.me) { showSettings(location.hash === '#settings'); if (location.hash !== '#settings') load(); } });
    $('set-open').addEventListener('click', async () => { await flush(); openSettings(); });
    $('set-back').addEventListener('click', closeSettings);

    function typeRow(t, isNew) {
        const color = t.color || PRESET[5];
        return `<div class="trow" data-type="${isNew ? 'new' : t.id}">
            <input class="code" data-f="code" maxlength="4" placeholder="글자" value="${esc(t.code || '')}" aria-label="짧은 글자">
            <input data-f="name" maxlength="10" placeholder="이름 (예: 데이)" value="${esc(t.name || '')}" aria-label="이름">
            <div class="times"><span>시간</span><input data-f="start_time" type="time" value="${esc(t.start_time || '')}" aria-label="시작 시간">
                <span>~</span><input data-f="end_time" type="time" value="${esc(t.end_time || '')}" aria-label="끝 시간"></div>
            <div class="acts"><button type="button" class="small primary" data-type-save>${isNew ? '더하기' : '저장'}</button>
                <button type="button" class="small ${isNew ? '' : 'danger'}" data-type-del>${isNew ? '취소' : '지우기'}</button></div>
            <div class="colors"><span class="badge prev" style="${badgeStyle(color)}">${esc(t.code || '글자')}</span>
                ${PRESET.map(c => `<button type="button" class="sw${c === color.toUpperCase() ? ' on' : ''}" data-color="${c}" style="background:${c}" aria-label="색 ${c}"></button>`).join('')}</div>
        </div>`;
    }
    function renderSettings() {
        if (!st.data) return;
        const hp = Number(storageGet(HOME_PERSON_KEY, 0));
        $('home-person').innerHTML = st.data.people.length
            ? st.data.people.map((p, i) => `<option value="${p.id}"${p.id === hp || (!hp && i === 0) ? ' selected' : ''}>${esc(p.name)}</option>`).join('')
            : '<option value="">(사람이 없어요)</option>';
        $('types').innerHTML = st.data.types.map(t => typeRow(t, false)).join('') + (st.newType ? typeRow(st.newType, true) : '');
        $('type-add').hidden = !!st.newType;
        $('people-edit').innerHTML = st.data.people.map(p => `<div class="prow" data-pe="${p.id}">
            <input maxlength="20" value="${esc(p.name)}" aria-label="이름"><button type="button" class="small" data-pe-save>이름 바꾸기</button>
            <button type="button" class="small danger" data-pe-del>지우기</button></div>`).join('')
            || '<p class="hint">아직 사람이 없어요. 근무표 화면에서 더할 수 있어요.</p>';
    }
    function rowValues(row) {
        const v = {};
        row.querySelectorAll('[data-f]').forEach(i => { v[i.dataset.f] = i.value.trim(); });
        v.color = (row.querySelector('.sw.on') || {}).dataset?.color || PRESET[5];
        return v;
    }
    $('types').addEventListener('click', async e => {
        const row = e.target.closest('.trow');
        if (!row) return;
        const sw = e.target.closest('[data-color]');
        if (sw) {
            row.querySelectorAll('.sw').forEach(b => b.classList.toggle('on', b === sw));
            row.querySelector('.prev').setAttribute('style', badgeStyle(sw.dataset.color));
            return;
        }
        const isNew = row.dataset.type === 'new';
        if (e.target.closest('[data-type-save]')) {
            const v = rowValues(row);
            const { status, data } = await act(isNew ? { action: 'type-add', ...v } : { action: 'type-edit', id: Number(row.dataset.type), ...v });
            if (status !== 200) { $('type-msg').classList.remove('ok'); $('type-msg').textContent = msgOf(data); return; }
            if (isNew) st.newType = null;
            $('type-msg').classList.add('ok');
            $('type-msg').textContent = isNew ? '더했어요.' : '저장했어요.';
            tellApp();
            load();
        } else if (e.target.closest('[data-type-del]')) {
            if (isNew) { st.newType = null; renderSettings(); return; }
            const t = typeOf(Number(row.dataset.type));
            if (!confirm(`'${t ? t.name : ''}' 근무 종류를 지울까요?`)) return;
            const { status, data } = await act({ action: 'type-delete', id: Number(row.dataset.type) });
            $('type-msg').classList.toggle('ok', status === 200);
            $('type-msg').textContent = status === 200 ? '지웠어요.' : msgOf(data);
            if (status === 200) { tellApp(); load(); }
        }
    });
    $('types').addEventListener('input', e => {
        if (e.target.dataset.f !== 'code') return;
        const row = e.target.closest('.trow');
        row.querySelector('.prev').textContent = e.target.value.trim() || '글자';
    });
    $('type-add').addEventListener('click', () => {
        const used = new Set(st.data.types.map(t => t.color.toUpperCase()));
        st.newType = { code: '', name: '', start_time: '', end_time: '', color: PRESET.find(c => !used.has(c)) || PRESET[5] };
        $('type-msg').textContent = '';
        renderSettings();
        $('types').querySelector('[data-type="new"] [data-f="code"]').focus();
    });
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
    window.ledgerBack = () => {
        if (!$('set-view').hidden) { closeSettings(); return true; }
        if (st.adding) { openAdd(false); return true; }
        if (st.editing) { setEditing(false); return true; }
        return false;
    };
    // 앱(YeYe홈)이 부름: 위쪽 '설정' → 근무표 설정, 다른 탭으로 감 → 고치기 끝
    window.appOpenSettings = () => { if (!st.me) return false; flush(); openSettings(); return true; };
    window.appTabHidden = () => { if (st.editing) setEditing(false); else flush(); };
    if (window.LedgerApp) document.documentElement.classList.add('in-app');

    // 다른 화면에 갔다 오면 새로 (다른 멤버가 고쳤을 수 있음). 떠날 때는 칠한 것을 바로 저장
    document.addEventListener('visibilitychange', () => {
        if (!st.me) return;
        if (document.visibilityState === 'hidden') flush();
        else if (!Object.keys(st.pending).length && $('set-view').hidden) load();
    });
    window.addEventListener('pagehide', () => {
        const days = st.pending;
        if (!Object.keys(days).length || !st.personId) return;
        st.pending = {};
        try {
            fetch('/api/ledger/duty', { method: 'POST', keepalive: true, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'set', person_id: st.personId, days }) });
        } catch (e) { /* 보내지 못함 */ }
    });

    boot();
})();
