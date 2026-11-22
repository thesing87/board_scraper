// 가계부: 관리자가 허락한 사람끼리 지출을 함께 기록하고 보기 (서버 ledger.py, API /api/ledger/*)
// - 로그인: 이름·비밀번호 → 가계부 API에만 쓰는 쿠키. 관리자 기기(대시보드 로그인 키가 있는 기기)는 자동으로 관리자 로그인
// - 기록은 그 달 것을 받아 일별·사람별 거르기는 화면에서. 내가 쓴 기록(관리자는 모두)을 누르면 고치기
// - 소비형태는 모두 함께 쓰고 색은 직접 고름 (정해진 12색 또는 원하는 색)
'use strict';

(function () {
    const $ = id => document.getElementById(id);
    const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const storageGet = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } };
    const storageSet = (k, v) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (e) { /* 저장 불가 */ } };
    // 메뉴(nav.js)가 이 기기에서 가계부를 보이게 하는 표시
    const LEDGER_FLAG = 'ledger_user';
    const ADMIN_TOKEN_KEY = 'admin_token';
    const PRESET = ['#E24B4A', '#D85A30', '#EF9F27', '#C9B11A', '#639922', '#1D9E75', '#2BA7B8', '#378ADD', '#534AB7', '#9B5DE5', '#D4537E', '#888780'];
    // 사람마다 동그라미 색 (함께 쓰는 순서대로)
    const AVATAR = [['#EEEDFE', '#3C3489'], ['#E1F5EE', '#085041'], ['#FAEEDA', '#633806'], ['#E6F1FB', '#0C447C'], ['#FBEAF0', '#72243E'], ['#EAF3DE', '#27500A'], ['#FAECE7', '#712B13']];

    const won = n => `${Math.round(n).toLocaleString('ko-KR')}원`;
    const pad = n => String(n).padStart(2, '0');
    const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const ym = d => ymd(d).slice(0, 7);
    function mix(hex, toWhite, f) {
        const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
        const t = toWhite ? 255 : 0;
        return '#' + c.map(v => Math.round(v + (t - v) * f).toString(16).padStart(2, '0')).join('');
    }
    const chipBg = h => mix(h, true, 0.84), chipFg = h => mix(h, false, 0.45);

    const st = {
        me: null, data: null, mode: 'month', day: new Date(), who: 0, sel: null,
        catEditing: false, popFor: null, addColor: null, editId: null, ddIndex: -1,
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

    // ==========================================
    // 로그인
    // ==========================================
    function showAuth(tab) {
        st.me = null;
        storageSet(LEDGER_FLAG, '');
        $('app').hidden = true;
        $('who-me').hidden = $('logout').hidden = true;
        $('auth').hidden = false;
        setTab(tab || 'login');
    }
    function setTab(tab) {
        $('tab-login').setAttribute('aria-selected', String(tab === 'login'));
        $('tab-signup').setAttribute('aria-selected', String(tab === 'signup'));
        $('login-form').hidden = tab !== 'login';
        $('signup-form').hidden = tab !== 'signup';
        setAuthMsg('');
    }
    function setAuthMsg(text, ok) { $('auth-msg').textContent = text; $('auth-msg').classList.toggle('ok', !!ok); }
    $('tab-login').addEventListener('click', () => setTab('login'));
    $('tab-signup').addEventListener('click', () => setTab('signup'));

    $('login-form').addEventListener('submit', async e => {
        e.preventDefault();
        const name = $('login-name').value.trim(), password = $('login-pw').value;
        if (!name || !password) { setAuthMsg('이름과 비밀번호를 넣어 주세요.'); return; }
        const { status, data } = await post('/api/ledger/session', { action: 'login', name, password });
        if (status !== 200) { setAuthMsg(msgOf(data)); return; }
        $('login-pw').value = '';
        start(data.user);
    });
    $('signup-form').addEventListener('submit', async e => {
        e.preventDefault();
        const name = $('su-name').value.trim(), pw = $('su-pw').value, pw2 = $('su-pw2').value;
        if (!name) { setAuthMsg('이름을 넣어 주세요.'); return; }
        if (pw.length < 4) { setAuthMsg('비밀번호는 4자 이상으로 넣어 주세요.'); return; }
        if (pw !== pw2) { setAuthMsg('비밀번호 확인이 다릅니다.'); return; }
        const { status, data } = await post('/api/ledger/session', { action: 'signup', name, password: pw });
        if (status !== 200) { setAuthMsg(msgOf(data)); return; }
        $('su-pw').value = $('su-pw2').value = '';
        $('login-name').value = name;
        setTab('login');
        setAuthMsg('가입 요청을 보냈어요. 관리자가 허락하면 로그인할 수 있어요.', true);
    });
    $('logout').addEventListener('click', async () => {
        await post('/api/ledger/session', { action: 'logout' });
        showAuth('login');
    });

    // ==========================================
    // 시작
    // ==========================================
    function start(user) {
        st.me = user;
        storageSet(LEDGER_FLAG, user.name);
        $('auth').hidden = true;
        $('app').hidden = false;
        const av = avatarOf(user.id, user.name);
        $('who-me').innerHTML = `${av}<span>${esc(user.name)}</span>`;
        $('who-me').hidden = $('logout').hidden = false;
        $('used-on').value = ymd(new Date());
        $('admin').hidden = !user.admin;
        if (user.admin) loadPeople();
        load();
    }

    async function boot() {
        let { status, data } = await get('/api/ledger/me');
        if (status === 200) { start(data.user); return; }
        // 관리자 기기: 대시보드 로그인 키로 관리자 로그인
        const token = storageGet(ADMIN_TOKEN_KEY, '');
        if (token) {
            ({ status, data } = await post('/api/ledger/session', { action: 'login', password: token }));
            if (status === 200) { start(data.user); return; }
        }
        showAuth('login');
    }

    async function load() {
        const { status, data } = await get(`/api/ledger/state?month=${ym(st.day)}`);
        if (status === 401) { showAuth('login'); return; }
        if (status !== 200) { $('entry-msg').textContent = '불러오지 못했어요. 잠시 뒤 다시 해 주세요.'; return; }
        st.data = data;
        if (!data.categories.some(c => c.id === st.sel)) st.sel = data.categories.length ? data.categories[0].id : null;
        render();
    }

    // ==========================================
    // 사람
    // ==========================================
    function memberIndex(id) {
        const list = (st.data && st.data.members) || [];
        const i = list.findIndex(m => m.id === id);
        return i < 0 ? id : i;
    }
    function avatarOf(id, name) {
        const [bg, fg] = AVATAR[memberIndex(id) % AVATAR.length];
        const letter = (name || '?').trim().slice(-1);
        return `<span class="av" style="background:${bg};color:${fg}">${esc(letter)}</span>`;
    }
    const nameOf = id => ((st.data.members.find(m => m.id === id) || {}).name || '알 수 없음');
    const catOf = id => (st.data.categories.find(c => c.id === id) || { name: '알 수 없음', color: '#888780' });

    // ==========================================
    // 화면 그리기
    // ==========================================
    function inPeriod(e) { return st.mode === 'day' ? e.used_on === ymd(st.day) : e.used_on.slice(0, 7) === ym(st.day); }
    function shown() { return st.data.entries.filter(e => inPeriod(e) && (!st.who || e.user_id === st.who)); }

    function render() {
        if (st.me) $('who-me').innerHTML = `${avatarOf(st.me.id, st.me.name)}<span>${esc(st.me.name)}</span>`;
        renderEntryHead();
        renderCats();
        renderFilter();
        renderSummary();
    }

    function renderEntryHead() {
        const editing = st.editId != null;
        $('entry').classList.toggle('editing', editing);
        $('entry-title').textContent = editing ? '기록 고치기' : '지출 입력';
        $('entry-note').textContent = editing ? '고친 뒤 저장을 누르세요' : `${st.me.name} 이름으로 기록돼요`;
        $('save').textContent = editing ? '저장' : '입력';
        $('edit-row').hidden = !editing;
    }

    function chipHtml(c, extra) {
        return `<span class="dot" style="background:${c.color}"></span>${esc(c.name)}${extra || ''}`;
    }
    function renderCats() {
        const cats = st.data.categories;
        $('cats').classList.toggle('editing', st.catEditing);
        $('cat-hint').textContent = st.catEditing ? '바꿀 소비형태를 누르세요' : '소비형태 — 누르면 선택, 없으면 추가';
        $('cat-edit').textContent = st.catEditing ? '편집 끝' : '색·이름 편집';
        $('cats').innerHTML = cats.map(c => `<span class="chip${!st.catEditing && c.id === st.sel ? ' on' : ''}" data-cat="${c.id}" role="button" tabindex="0"
                style="background:${chipBg(c.color)};color:${chipFg(c.color)}">${chipHtml(c)}${st.popFor === c.id ? popHtml(c) : ''}</span>`).join('')
            + (st.catEditing ? '' : '<span class="chip add" id="cat-add" role="button" tabindex="0">＋ 추가</span>');
    }
    function palHtml(current, attr) {
        const cur = (current || '').toUpperCase();
        return PRESET.map(h => `<button type="button" class="sw${cur === h ? ' on' : ''}" ${attr}="${h}" style="background:${h}" aria-label="${h}">${cur === h ? '✓' : ''}</button>`).join('');
    }
    function popHtml(c) {
        return `<div class="pop" data-pop>
            <input id="pop-name" value="${esc(c.name)}" maxlength="12" aria-label="소비형태 이름">
            <div class="pal">${palHtml(c.color, 'data-pop-color')}</div>
            <label class="custom"><input type="color" id="pop-custom" value="${c.color.toLowerCase()}"> 직접 고르기</label>
            <div class="pop-actions"><button type="button" class="primary" data-pop-save>완료</button><button type="button" class="danger" data-pop-delete>지우기</button></div>
            <p class="msg" id="pop-msg"></p></div>`;
    }

    function renderAddBox() {
        $('add-pal').innerHTML = palHtml(st.addColor, 'data-add-color');
        const name = $('new-name').value.trim() || '새 소비형태';
        const pv = $('new-preview');
        if (st.addColor) {
            pv.setAttribute('style', `background:${chipBg(st.addColor)};color:${chipFg(st.addColor)};cursor:default`);
            pv.innerHTML = chipHtml({ name, color: st.addColor });
        } else {
            pv.setAttribute('style', 'border:1px dashed #B6BBC4;color:#8B919C;cursor:default');
            pv.textContent = name;
        }
    }

    function renderFilter() {
        $('mode-day').classList.toggle('on', st.mode === 'day');
        $('mode-month').classList.toggle('on', st.mode === 'month');
        const d = st.day;
        $('period').textContent = st.mode === 'day'
            ? `${d.getMonth() + 1}월 ${d.getDate()}일 (${'일월화수목금토'[d.getDay()]})`
            : `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
        const members = st.data.members;
        if (st.who && !members.some(m => m.id === st.who)) st.who = 0;
        $('people').innerHTML = `<button type="button" class="pp all${!st.who ? ' on' : ''}" data-who="0">모두</button>`
            + members.map(m => `<button type="button" class="pp${st.who === m.id ? ' on' : ''}" data-who="${m.id}">${avatarOf(m.id, m.name)}${esc(m.name)}</button>`).join('');
    }

    function renderSummary() {
        const list = shown();
        const sums = new Map();
        list.forEach(e => sums.set(e.category_id, (sums.get(e.category_id) || 0) + e.amount));
        const parts = [...sums.entries()].sort((a, b) => b[1] - a[1]);
        const total = parts.reduce((t, p) => t + p[1], 0);
        const whoName = st.who ? nameOf(st.who) : '';
        $('m1-label').textContent = `${st.mode === 'day' ? '이날' : '이 달'} 지출${whoName ? ` · ${whoName}` : ''}`;
        $('m1').textContent = won(total);
        $('m2').textContent = `${list.length}건`;
        $('m3').textContent = parts.length ? `${catOf(parts[0][0]).name} ${Math.round(parts[0][1] / total * 100)}%` : '–';
        renderDonut(parts, total, whoName);
        $('legend').innerHTML = parts.length ? parts.map(([id, v]) => {
            const c = catOf(id), pct = Math.round(v / total * 100);
            return `<div class="lg"><div class="lg-top"><span class="dot" style="background:${c.color}"></span><span class="n">${esc(c.name)}</span>
                <span class="p">${pct}%</span><span class="w">${won(v)}</span></div><div class="lg-bar"><i style="width:${pct}%;background:${c.color}"></i></div></div>`;
        }).join('') : '<p class="empty">이 기간에는 기록이 없어요</p>';
        renderList(list);
    }

    function renderDonut(parts, total, whoName) {
        const R = 70, r = 44, cx = 85, cy = 85;
        let svg = '';
        if (!total) svg = `<circle cx="85" cy="85" r="57" fill="none" stroke="#E5E7EB" stroke-width="26"/>`;
        else if (parts.length === 1) svg = `<circle cx="85" cy="85" r="57" fill="none" stroke="${catOf(parts[0][0]).color}" stroke-width="26"/>`;
        else {
            let a0 = -Math.PI / 2;
            const p = (g, rad) => [cx + rad * Math.cos(g), cy + rad * Math.sin(g)];
            parts.forEach(([id, v]) => {
                const a1 = a0 + v / total * Math.PI * 2, big = a1 - a0 > Math.PI ? 1 : 0;
                const [x1, y1] = p(a0, R), [x2, y2] = p(a1, R), [x3, y3] = p(a1, r), [x4, y4] = p(a0, r);
                svg += `<path d="M${x1} ${y1}A${R} ${R} 0 ${big} 1 ${x2} ${y2}L${x3} ${y3}A${r} ${r} 0 ${big} 0 ${x4} ${y4}Z" fill="${catOf(id).color}" stroke="#fff" stroke-width="2"><title>${esc(catOf(id).name)} ${won(v)}</title></path>`;
                a0 = a1;
            });
        }
        svg += `<text x="85" y="80" text-anchor="middle" font-size="12" fill="#5F6673">${esc(whoName || '모두')}</text>
            <text x="85" y="101" text-anchor="middle" font-size="15" font-weight="700" fill="#111827">${won(total)}</text>`;
        $('donut').innerHTML = svg;
    }

    function canEdit(e) { return st.me && (st.me.admin || e.user_id === st.me.id); }
    function renderList(list) {
        $('count').textContent = `${list.length}건`;
        if (!list.length) { $('list').innerHTML = '<p class="empty">이 기간에는 기록이 없어요</p>'; return; }
        const days = [...new Set(list.map(e => e.used_on))];
        $('list').innerHTML = days.map(day => {
            const items = list.filter(e => e.used_on === day);
            const head = `<div class="dayh"><span>${+day.slice(5, 7)}월 ${+day.slice(8)}일</span><span>${won(items.reduce((t, e) => t + e.amount, 0))}</span></div>`;
            return head + items.map(e => {
                const c = catOf(e.category_id), mine = canEdit(e);
                return `<button type="button" class="it${mine ? ' mine' : ''}${st.editId === e.id ? ' editing' : ''}" data-entry="${e.id}"${mine ? ' title="눌러서 고치기"' : ' tabindex="-1"'}>
                    ${avatarOf(e.user_id, nameOf(e.user_id))}
                    <span class="txt"><span class="cat" style="color:${chipFg(c.color)}"><span class="dot" style="background:${c.color}"></span>${esc(c.name)}</span>
                    <span class="sub">${esc(nameOf(e.user_id))}${e.memo ? ` · ${esc(e.memo)}` : ''}</span></span>
                    <span class="amt">${won(e.amount)}</span></button>`;
            }).join('');
        }).join('');
    }

    // ==========================================
    // 입력·고치기
    // ==========================================
    function amountValue() { return parseInt(($('amount').value || '').replace(/[^0-9]/g, ''), 10) || 0; }
    $('amount').addEventListener('input', () => {
        $('entry-msg').textContent = '';
        const v = $('amount').value.replace(/[^0-9]/g, '').slice(0, 10);
        $('amount').value = v ? Number(v).toLocaleString('ko-KR') : '';
    });

    function clearForm() {
        st.editId = null;
        $('amount').value = '';
        $('memo').value = '';
        $('entry-msg').textContent = '';
    }

    $('save').addEventListener('click', async () => {
        const amount = amountValue();
        if (!amount) { $('entry-msg').textContent = '금액을 넣어 주세요.'; $('amount').focus(); return; }
        if (st.sel == null) { $('entry-msg').textContent = '소비형태를 골라 주세요.'; return; }
        const body = { amount, used_on: $('used-on').value || ymd(new Date()), category_id: st.sel, memo: $('memo').value.trim() };
        const editing = st.editId != null;
        $('save').disabled = true;
        const { status, data } = await post('/api/ledger/entry', editing ? { action: 'edit', id: st.editId, ...body } : { action: 'add', ...body });
        $('save').disabled = false;
        if (status === 401) { showAuth('login'); return; }
        if (status !== 200) { $('entry-msg').textContent = msgOf(data); return; }
        clearForm();
        await load();
        $('amount').focus();
    });
    $('amount').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); $('save').click(); } });

    function startEdit(entry) {
        st.editId = entry.id;
        st.sel = entry.category_id;
        st.catEditing = false; st.popFor = null;
        $('addbox').hidden = true;
        $('amount').value = entry.amount.toLocaleString('ko-KR');
        $('used-on').value = entry.used_on;
        $('memo').value = entry.memo || '';
        $('entry-msg').textContent = '';
        render();
        $('entry').scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
    $('edit-cancel').addEventListener('click', () => { clearForm(); $('used-on').value = ymd(new Date()); render(); });
    $('edit-delete').addEventListener('click', async () => {
        if (st.editId == null || !window.confirm('이 기록을 지울까요?')) return;
        const { status, data } = await post('/api/ledger/entry', { action: 'delete', id: st.editId });
        if (status !== 200) { $('entry-msg').textContent = msgOf(data); return; }
        clearForm();
        $('used-on').value = ymd(new Date());
        load();
    });

    // ==========================================
    // 소비형태: 고르기·추가·색과 이름 바꾸기
    // ==========================================
    $('cat-edit').addEventListener('click', () => {
        st.catEditing = !st.catEditing;
        st.popFor = null;
        $('addbox').hidden = true;
        renderCats();
    });
    function openAddBox() {
        st.addColor = null;
        $('new-name').value = '';
        $('add-msg').textContent = '';
        $('addbox').hidden = false;
        renderAddBox();
        $('new-name').focus();
    }
    $('new-name').addEventListener('input', () => { $('add-msg').textContent = ''; renderAddBox(); });
    $('add-custom').addEventListener('input', e => { st.addColor = e.target.value.toUpperCase(); $('add-msg').textContent = ''; renderAddBox(); });
    $('add-cancel').addEventListener('click', () => { $('addbox').hidden = true; });
    $('add-ok').addEventListener('click', async () => {
        const name = $('new-name').value.trim();
        if (!name) { $('add-msg').textContent = '이름을 넣어 주세요.'; return; }
        if (!st.addColor) { $('add-msg').textContent = '색을 골라 주세요.'; return; }
        const { status, data } = await post('/api/ledger/category', { action: 'add', name, color: st.addColor });
        if (status !== 200) { $('add-msg').textContent = msgOf(data); return; }
        st.sel = data.id;
        $('addbox').hidden = true;
        load();
    });

    async function saveCategory(id, color) {
        const c = st.data.categories.find(x => x.id === id);
        const nameInput = $('pop-name');
        const name = nameInput ? nameInput.value.trim() : c.name;
        const { status, data } = await post('/api/ledger/category', { action: 'edit', id, name, color: color || c.color });
        if (status !== 200) { const m = $('pop-msg'); if (m) m.textContent = msgOf(data); return false; }
        c.name = name; if (color) c.color = color;
        return true;
    }

    // 소비형태 칸 안의 누르기 (선택·추가·편집 창)
    $('cats').addEventListener('click', async e => {
        const pop = e.target.closest('[data-pop]');
        if (pop) {
            e.stopPropagation();
            const id = st.popFor;
            const sw = e.target.closest('[data-pop-color]');
            if (sw) { if (await saveCategory(id, sw.dataset.popColor)) { render(); } return; }
            if (e.target.closest('[data-pop-save]')) { if (await saveCategory(id)) { st.popFor = null; render(); } return; }
            if (e.target.closest('[data-pop-delete]')) {
                if (!window.confirm('이 소비형태를 지울까요?')) return;
                const { status, data } = await post('/api/ledger/category', { action: 'delete', id });
                if (status !== 200) { $('pop-msg').textContent = msgOf(data); return; }
                st.popFor = null;
                load();
            }
            return;
        }
        if (e.target.closest('#cat-add')) { openAddBox(); return; }
        const chip = e.target.closest('[data-cat]');
        if (!chip) return;
        const id = Number(chip.dataset.cat);
        if (st.catEditing) { st.popFor = st.popFor === id ? null : id; renderCats(); const n = $('pop-name'); if (n) n.focus(); return; }
        st.sel = id;
        $('addbox').hidden = true;
        renderCats();
    });
    $('cats').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.chip')) { e.preventDefault(); e.target.click(); } });
    // 편집 창의 '직접 고르기': 고르는 동안 미리 보이고, 손을 떼면(change) 저장
    $('cats').addEventListener('input', e => {
        if (e.target.id !== 'pop-custom') return;
        const chip = e.target.closest('[data-cat]');
        const h = e.target.value;
        chip.style.background = chipBg(h); chip.style.color = chipFg(h);
        chip.querySelector('.dot').style.background = h;
    });
    $('cats').addEventListener('change', async e => {
        if (e.target.id === 'pop-custom' && await saveCategory(st.popFor, e.target.value.toUpperCase())) render();
    });
    $('addbox').addEventListener('click', e => {
        const sw = e.target.closest('[data-add-color]');
        if (sw) { st.addColor = sw.dataset.addColor; $('add-msg').textContent = ''; renderAddBox(); }
    });
    document.addEventListener('click', e => {
        if (st.popFor != null && !e.target.closest('[data-pop]') && !e.target.closest('[data-cat]')) { st.popFor = null; renderCats(); }
        if (!e.target.closest('.memo-wrap')) $('memo-dd').hidden = true;
    });

    // ==========================================
    // 메모: 최근 메모 드롭다운 (고르면 그 메모에 썼던 소비형태도 함께)
    // ==========================================
    function memoMatches() {
        const q = $('memo').value.trim();
        return ((st.data && st.data.memos) || []).filter(m => !q || m.memo.includes(q)).filter(m => m.memo !== q).slice(0, 6);
    }
    function renderMemoDd() {
        const list = memoMatches();
        if (!list.length) { $('memo-dd').hidden = true; return; }
        $('memo-dd').innerHTML = list.map((m, i) => {
            const c = catOf(m.category_id);
            return `<button type="button" class="${i === st.ddIndex ? 'act' : ''}" data-memo="${i}"><span class="m">${esc(m.memo)}</span>
                <span class="dot" style="background:${c.color}"></span><span class="k">${esc(c.name)}</span></button>`;
        }).join('');
        $('memo-dd').hidden = false;
    }
    function useMemo(i) {
        const m = memoMatches()[i];
        if (!m) return;
        $('memo').value = m.memo;
        if (st.data.categories.some(c => c.id === m.category_id)) { st.sel = m.category_id; renderCats(); }
        $('memo-dd').hidden = true;
        st.ddIndex = -1;
    }
    $('memo').addEventListener('focus', () => { st.ddIndex = -1; renderMemoDd(); });
    $('memo').addEventListener('input', () => { st.ddIndex = -1; renderMemoDd(); });
    $('memo').addEventListener('keydown', e => {
        const n = $('memo-dd').hidden ? 0 : memoMatches().length;
        if (e.key === 'ArrowDown' && n) { st.ddIndex = Math.min(n - 1, st.ddIndex + 1); renderMemoDd(); e.preventDefault(); }
        else if (e.key === 'ArrowUp' && n) { st.ddIndex = Math.max(0, st.ddIndex - 1); renderMemoDd(); e.preventDefault(); }
        else if (e.key === 'Enter') { e.preventDefault(); if (n && st.ddIndex >= 0) useMemo(st.ddIndex); else { $('memo-dd').hidden = true; $('save').click(); } }
        else if (e.key === 'Escape') { $('memo-dd').hidden = true; }
    });
    // 누르는 순간 메모 칸에서 포커스가 빠져 목록이 닫히지 않게 mousedown에서 고름
    $('memo-dd').addEventListener('mousedown', e => {
        const b = e.target.closest('[data-memo]');
        if (b) { e.preventDefault(); useMemo(Number(b.dataset.memo)); }
    });

    // ==========================================
    // 거르기·기록 누르기
    // ==========================================
    function moveDay(delta) {
        const before = ym(st.day);
        if (st.mode === 'day') st.day.setDate(st.day.getDate() + delta);
        else st.day = new Date(st.day.getFullYear(), st.day.getMonth() + delta, 1);
        if (ym(st.day) !== before) load(); else render();
    }
    $('prev').addEventListener('click', () => moveDay(-1));
    $('next').addEventListener('click', () => moveDay(1));
    $('mode-day').addEventListener('click', () => {
        if (st.mode === 'day') return;
        st.mode = 'day';
        // 이 달을 보다가 일별로 바꾸면: 오늘이 이 달이면 오늘, 아니면 그 달 1일
        const today = new Date();
        if (ym(today) === ym(st.day)) st.day = today;
        render();
    });
    $('mode-month').addEventListener('click', () => { st.mode = 'month'; render(); });
    $('people').addEventListener('click', e => {
        const b = e.target.closest('[data-who]');
        if (b) { st.who = Number(b.dataset.who); render(); }
    });
    $('list').addEventListener('click', e => {
        const b = e.target.closest('[data-entry]');
        if (!b) return;
        const entry = st.data.entries.find(x => x.id === Number(b.dataset.entry));
        if (entry && canEdit(entry)) startEdit(entry);
    });

    // ==========================================
    // 관리자: 사용자 허락
    // ==========================================
    async function loadPeople() {
        const { status, data } = await get('/api/ledger/admin');
        if (status === 200) renderPeople(data);
    }
    function renderPeople(data) {
        const n = data.pending.length;
        $('pending-count').hidden = !n;
        $('pending-count').textContent = n;
        if (n) $('admin').open = true;
        $('pending').innerHTML = n ? data.pending.map(p => `<div class="person"><span class="name">${esc(p.name)} <span class="hint">· ${esc((p.requested_at || '').slice(5, 16))} 요청</span></span>
            <button type="button" class="small primary" data-admin="approve" data-uid="${p.id}">허락</button>
            <button type="button" class="small" data-admin="reject" data-uid="${p.id}">거절</button></div>`).join('')
            : '<p class="hint">기다리는 사람 없음</p>';
        $('members').innerHTML = data.members.map(m => `<div class="person"><span class="name">${esc(m.name)}</span>
            ${m.admin ? '<span class="tag admin-tag">관리자</span>' : `<span class="tag">가계부만</span><button type="button" class="small" data-admin="revoke" data-uid="${m.id}">허락 취소</button>`}</div>`).join('');
    }
    $('admin').addEventListener('click', async e => {
        const b = e.target.closest('[data-admin]');
        if (!b) return;
        const action = b.dataset.admin;
        if (action === 'revoke' && !window.confirm('허락을 취소할까요? 그 사람의 로그인이 끊기고, 쓴 기록은 남아요.')) return;
        b.disabled = true;
        const { status, data } = await post('/api/ledger/admin', { action, user_id: Number(b.dataset.uid) });
        b.disabled = false;
        if (status !== 200) { window.alert(msgOf(data)); return; }
        renderPeople(data);
        load();
    });

    boot();
})();
