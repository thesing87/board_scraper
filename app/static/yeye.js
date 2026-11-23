// YeYe홈 앱의 홈 탭 (/yeye/): 근무표·가계부 요약 (서버 /api/ledger/home, 가계부 로그인)
// - 근무표: 사람마다 오늘·내일, '처음 보일 사람'(근무표 설정 > 이 휴대폰, localStorage duty_home_person)의 오늘부터 7일
// - 가계부: 이번 달 지출·수입, 내 확인 대기함 건수, 최근 기록 3건
// - 카드를 누르면 그 페이지로 (앱은 그 탭으로 바꿈). 앱이 홈 탭을 다시 보일 때 window.homeRefresh()로 새로
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
    if (window.LedgerApp) document.documentElement.classList.add('in-app');

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
            $('app').hidden = true;
            $('auth').hidden = false;
            return;
        }
        if (status !== 200) { $('msg').textContent = '불러오지 못했어요. 잠시 뒤 다시 해 주세요.'; return; }
        $('msg').textContent = '';
        $('auth').hidden = true;
        $('app').hidden = false;
        renderDuty(data.duty);
        renderLedger(data.ledger);
    }
    window.homeRefresh = load;

    function renderDuty(d) {
        const types = {};
        d.types.forEach(t => { types[t.id] = t; });
        const badge = id => types[id] ? `<span class="badge" style="${badgeStyle(types[id].color)}">${esc(types[id].code)}</span>` : '<span class="badge blank">–</span>';
        const t0 = parse(d.today);
        $('duty-title').textContent = `근무표 · 오늘 ${t0.getMonth() + 1}/${t0.getDate()} (${WD[t0.getDay()]})`;
        if (!d.people.length) { $('duty-body').innerHTML = '<p class="none">아직 근무표가 없어요. 눌러서 사람을 더해 주세요.</p>'; return; }
        const rows = d.people.map(p => {
            const t = types[p.today], n = types[p.tomorrow];
            const desc = (t ? `${t.name}${t.start_time ? ` ${t.start_time}–${t.end_time}` : ''}` : '근무 없음') + ` · 내일 ${n ? n.code : '–'}`;
            return `<div class="who"><span class="n">${esc(p.name)}</span>${badge(p.today)}<span class="t">${esc(desc)}</span></div>`;
        }).join('');
        const who = d.people.find(p => p.id === d.person_id);
        const week = d.week.map((w, i) => {
            const day = parse(w.day);
            return `<div><div class="d${i === 0 ? ' today' : ''}">${i === 0 ? '오늘' : WD[day.getDay()]}</div>${badge(w.type_id)}</div>`;
        }).join('');
        $('duty-body').innerHTML = rows + (who ? `<div class="week"><div class="lbl">${esc(who.name)}의 이번 주</div><div class="row">${week}</div></div>` : '');
    }

    function renderLedger(l) {
        $('ledger-title').textContent = `가계부 · ${Number(l.month.slice(5))}월`;
        $('ledger-body').innerHTML = `<div class="sums"><div><div class="l">지출</div><div class="v ex">-${won(l.expense)}</div></div>
            <div><div class="l">수입</div><div class="v in">+${won(l.income)}</div></div></div>`
            + (l.inbox ? `<div class="inbox" data-go="/ledger/#inbox" role="link">확인 대기함 ${l.inbox}건 ›</div>` : '')
            + (l.recent.length ? `<div class="recent">${l.recent.map(r => `<div class="rc"><span class="dot" style="background:${esc(r.color)}"></span>
                <span class="m">${esc(r.memo)}</span><span class="a${r.kind === 'income' ? ' in' : ''}">${r.kind === 'income' ? '+' : '-'}${won(r.amount)}</span></div>`).join('')}</div>`
                : '<p class="none" style="margin:10px 0 0">이번 달 기록이 아직 없어요.</p>');
    }

    // 카드·대기함을 누르면 그 페이지로 (앱은 탭을 바꿈)
    document.addEventListener('click', e => {
        const go = e.target.closest('[data-go]');
        if (go) location.href = go.dataset.go;
    });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') load(); });
    load();
})();
