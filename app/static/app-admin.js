'use strict';

// 키워드 게시판 화면 (app-admin.js): 관리 패널: 알림, 게시판·묶음·카테고리, 수집 상태, 로그인.
// 한 화면의 스크립트를 순서대로 나눈 파일 중 하나 (app.js, app-feed.js, app-view.js, app-admin.js, app-main.js). 전역 이름을 함께 씀

// ==========================================
// 관리 패널
// ==========================================
function alertSwitch(groupId, type, on, label) {
    return `
        <label class="switch">
            <input type="checkbox" data-action="toggle-alert" data-group-id="${groupId}" data-type="${type}" aria-label="${esc(label)}" ${on ? 'checked' : ''}>
            <span class="slider"></span>
        </label>`;
}

function renderSettings() {
    renderBoardChecks();
    renderGroupSettings();
    renderSiteSettings();
    renderCategorySettings();

    const groups = app.state.groups || [];
    document.getElementById('settings-alerts').innerHTML = (groups.length ? groups.map(g => `
        <div class="alert-row">
            <span class="alert-row-name">${multiSite() ? groupTag(g) : ''}${esc(g.name)}</span>
            <span class="alert-switches">
                ${alertSwitch(g.id, 'alert', g.alert, g.name + ' 전체 알림')}
                ${alertSwitch(g.id, 'video_alert', g.video_alert, g.name + ' 동영상 알림')}
                ${alertSwitch(g.id, 'digest', g.digest, g.name + ' 하루 요약')}
                <input class="popular-min" type="number" inputmode="numeric" min="0" max="100000" step="1" placeholder="끔"
                    data-action="set-popular-min" data-group-id="${g.id}" value="${g.popular_min || ''}" aria-label="${esc(g.name)} 인기 글 알림 기준 (추천+댓글 수)">
            </span>
        </div>`).join('') : '<span class="settings-hint">게시판을 만들면 게시판별로 알림을 설정할 수 있습니다.</span>') + `
        <span class="settings-hint alert-hint">하루 요약: 매일 ${app.state.digest_hour}시에 최근 24시간 새 글 중 추천·댓글이 많은 글 5개를 한 번에 보냅니다. 글이 많아 전체 알림을 꺼 둔 게시판에 알맞습니다.<br>인기: 적어 둔 숫자만큼 추천+댓글이 쌓인 글을 한 번 알립니다 (기준을 정한 뒤에 모은 글만). 비워 두면 끕니다.</span>
        <div class="alert-row alert-row-saved">
            <span class="alert-row-name">⭐ 보관한 글에 새 댓글</span>
            <span class="alert-switches">${alertSwitch('', 'saved_comment', app.state.saved_comment_alert, '보관한 글 새 댓글 알림')}</span>
        </div>`;
}

// ---------- 게시판 만들기·수정·삭제 (키워드는 게시판에 등록) ----------
function renderGroupSettings() {
    const editing = (app.state.groups || []).find(g => g.id === app.editingGroupId) || null;
    if (!editing) app.editingGroupId = null;
    if (app.groupDraft === undefined) {
        app.groupDraft = editing
            ? editing.members.map(m => ({ board: m.board, keyword: m.keyword, paused: !!m.paused, ignores: m.ignores.slice() })) : [];
        // 이 게시판이 수집할 카테고리: 수정이면 등록된 키워드의 카테고리, 새 게시판이면 첫 카테고리
        const first = app.state.boards.find(b => b.status !== 'invalid');
        app.draftBoards = editing ? [...new Set(app.groupDraft.map(m => m.board))] : (first ? [first.key] : []);
        // 새로 연 양식은 찾을 곳을 처음 값(카테고리가 둘 이상이면 '공통')으로
        document.getElementById('group-kw-target').innerHTML = '';
    }
    renderBoardChecks();

    // 편집 양식은 '새 게시판'이나 '수정'을 눌렀을 때만 펼침. 무시할 표현·합치기는 '고급 설정'에 접어 둠 (게시판 합치기는 수정할 때만)
    const form = document.getElementById('group-form');
    const wasHidden = form.hidden;
    form.hidden = !(editing || app.groupFormOpen);
    if (wasHidden && !form.hidden) {
        document.getElementById('group-advanced').open = app.groupDraft.some(m => m.ignores.length);
    }
    document.getElementById('group-advanced-merge').hidden = !editing;
    document.getElementById('group-form-title').textContent = editing ? `'${editing.name}' 게시판 수정` : '새 게시판';
    // 새 게시판을 넣을 묶음 (수정할 때는 아래 게시판 목록의 묶음 고르기로 옮김)
    const folderSelect = document.getElementById('group-folder-select');
    const prevFolder = folderSelect.value;
    folderSelect.innerHTML = '<option value="">묶음 없음</option>'
        + (app.state.folders || []).map(f => `<option value="${f.id}">${esc(f.name)}</option>`).join('');
    if ((app.state.folders || []).some(f => String(f.id) === prevFolder)) folderSelect.value = prevFolder;
    folderSelect.hidden = !!editing;
    document.getElementById('group-save-btn').textContent = editing ? '저장' : '만들기';
    const nameInput = document.getElementById('group-name-input');
    if (app.groupNameDraft !== undefined) nameInput.value = app.groupNameDraft;
    else nameInput.value = editing ? editing.name : '';

    // 이 게시판에 등록할 키워드: 고른 카테고리 모두에서 찾는 '공통' 키워드를 먼저, 카테고리별 키워드는 사이트·카테고리와 함께
    const entries = app.draftEntries = draftEntries();
    const entryBadge = e => e.common
        ? '<span class="site-tag site-multi" title="고른 카테고리 모두에서 찾음">공통</span>'
        : `${siteTag(boardSite(e.members[0].board))}<span class="kw-tag-board">${esc(boardName(e.members[0].board))}</span>`;
    const entryName = e => (e.common ? '공통 ' : boardName(e.members[0].board) + ' ') + e.keyword;
    document.getElementById('group-keywords').innerHTML = entries.length ? entries.map((e, idx) => {
        const paused = e.members.every(m => m.paused);
        return `
        <span class="kw-tag${paused ? ' is-paused' : ''}">
            ${entryBadge(e)}${esc(e.keyword)}${paused ? '<span class="kw-tag-paused">일시정지</span>' : ''}
            <button data-action="toggle-draft-pause" data-index="${idx}" aria-pressed="${paused}"
                aria-label="${esc(entryName(e))} 키워드 ${paused ? '다시 수집' : '일시정지'}" title="${paused ? '다시 수집' : '일시정지 (모은 글은 그대로, 수집만 멈춤)'}">${paused ? ICONS.play : ICONS.pause}</button>
            <button data-action="remove-draft-keyword" data-index="${idx}" aria-label="${esc(entryName(e))} 키워드 빼기">${ICONS.close}</button>
        </span>`;
    }).join('') : '<span class="settings-hint">아직 등록한 키워드가 없습니다.</span>';

    // 무시할 표현: 붙일 키워드를 고르는 상자(고른 키워드 유지)와 키워드별 표현 (공통 키워드는 모든 카테고리의 그 키워드에 함께)
    const ignoreSelect = document.getElementById('group-ignore-keyword');
    const selected = ignoreSelect.value;
    ignoreSelect.innerHTML = entries.map((e, idx) => `<option value="${idx}">${esc(entryName(e))}</option>`).join('');
    if (selected && Number(selected) < entries.length) ignoreSelect.value = selected;
    document.getElementById('group-ignores').innerHTML = entries.flatMap((e, idx) => entryIgnores(e).map((phrase, pIdx) => `
        <span class="kw-tag">
            ${entryBadge(e)}<span class="kw-tag-board">${esc(e.keyword)} 무시</span>${esc(phrase)}
            <button data-action="remove-draft-ignore" data-index="${idx}" data-phrase-index="${pIdx}" aria-label="${esc(entryName(e))} 키워드의 무시할 표현 ${esc(phrase)} 빼기">${ICONS.close}</button>
        </span>`)).join('');

    // 다른 게시판 합치기 (수정 중일 때만): 고른 게시판의 키워드를 이 게시판으로 옮기고, 저장하면 그 게시판은 지움
    const mergeRow = document.getElementById('group-merge-row');
    mergeRow.hidden = !editing;
    if (editing) {
        const others = (app.state.groups || []).filter(g => g.id !== editing.id && !app.mergeDraft.includes(g.id));
        const mergeSelect = document.getElementById('group-merge-select');
        mergeSelect.innerHTML = others.length
            ? others.map(g => `<option value="${g.id}">${esc(groupShort(g))} ${esc(g.name)}</option>`).join('')
            : '<option value="">합칠 게시판 없음</option>';
        mergeSelect.disabled = !others.length;
        const merging = app.mergeDraft.map(id => (app.state.groups || []).find(g => g.id === id)).filter(Boolean);
        document.getElementById('group-merge-note').textContent = merging.length
            ? `저장하면 ${merging.map(g => `'${groupShort(g)} ${g.name}'`).join(', ')} 게시판을 이 게시판에 합치고 지웁니다. (알림 설정은 이 게시판 것을 씀)`
            : '';
    }

    const groups = app.state.groups || [];
    const memberText = (m, g) => (isMultiGroup(g) ? esc(siteLabel(boardSite(m.board)).short) + ' ' : '') + esc(m.keyword) + (m.paused ? ' (일시정지)' : '') + (m.ignores.length ? ` (무시: ${m.ignores.map(esc).join(', ')})` : '');
    // 게시판 목록: 사이드바 순서대로. 묶음 고르기와 순서 옮기기 (묶음 안 게시판은 그 묶음 안에서, 묶음 없는 게시판은 묶음들 사이로도)
    const folders = app.state.folders || [];
    const folderOptions = g => `<option value="" ${folders.some(f => f.id === g.folder_id) ? '' : 'selected'}>묶음 없음</option>`
        + folders.map(f => `<option value="${f.id}" ${f.id === g.folder_id ? 'selected' : ''}>${esc(f.name)}</option>`).join('');
    const ordered = topItems().flatMap(t => t.kind === 'group' ? [t.item] : groups.filter(g => g.folder_id === t.item.id));
    document.getElementById('settings-groups').innerHTML = ordered.length ? ordered.map(g => `
        <div class="group-row">
            <div class="group-row-main">
                <span class="group-row-name">${multiSite() ? groupTag(g) : ''}${esc(g.name)}</span>
                <span class="group-row-members">${g.members.map(m => memberText(m, g)).join(' · ') || '(키워드 없음)'} · ${g.total}개 글</span>
                <span class="group-row-arrange">
                    <select class="input select select-small" data-action="set-group-folder" data-group-id="${g.id}" aria-label="${esc(g.name)} 게시판의 묶음">${folderOptions(g)}</select>
                    <button class="icon-btn small" data-action="move-group" data-group-id="${g.id}" data-direction="up" aria-label="${esc(g.name)} 위로">${ICONS.up}</button>
                    <button class="icon-btn small" data-action="move-group" data-group-id="${g.id}" data-direction="down" aria-label="${esc(g.name)} 아래로">${ICONS.down}</button>
                </span>
            </div>
            <button class="btn btn-outline btn-small" data-action="edit-group" data-group-id="${g.id}">수정</button>
            <button class="btn btn-outline btn-small btn-danger" data-action="delete-group" data-group-id="${g.id}">삭제</button>
        </div>`).join('') : '<span class="settings-hint">만든 게시판이 없습니다.</span>';
    renderFolderSettings();
}

// 무시할 표현 비교 기준 (서버와 같이 대소문자 무시, 연속 공백은 하나로)
function normPhrase(text) { return text.split(/\s+/).filter(Boolean).join(' ').toLowerCase(); }

// 키워드 태그 단위: 고른 카테고리가 둘 이상이고 모든 카테고리에 있는 키워드는 '공통' 하나로 묶고, 나머지는 카테고리별로 하나씩
// (고른 카테고리 순서대로). 공통 키워드의 일시정지·무시할 표현·빼기는 묶인 모든 카테고리에 함께 적용
function draftEntries() {
    const boards = app.draftBoards;
    const has = (board, keyword) => app.groupDraft.some(m => m.board === board && m.keyword === keyword);
    const common = boards.length > 1
        ? [...new Set(app.groupDraft.map(m => m.keyword))].filter(k => boards.every(b => has(b, k))) : [];
    return [
        ...common.map(k => ({ common: true, keyword: k, members: app.groupDraft.filter(m => m.keyword === k) })),
        ...boards.flatMap(b => app.groupDraft.filter(m => m.board === b && !common.includes(m.keyword))
            .map(m => ({ common: false, keyword: m.keyword, members: [m] })))
    ];
}

// 키워드 태그의 무시할 표현 (공통 키워드는 카테고리마다 다를 수 있어 모두 합쳐 한 번씩)
function entryIgnores(entry) {
    const seen = new Set();
    return entry.members.flatMap(m => m.ignores).filter(p => !seen.has(normPhrase(p)) && seen.add(normPhrase(p)));
}

// 키워드를 찾을 곳: '공통'(고른 카테고리 모두) 또는 카테고리 하나
function addDraftKeyword() {
    const input = document.getElementById('group-kw-input');
    const keyword = input.value.trim();
    const target = document.getElementById('group-kw-target').value;
    const boards = target === '*' ? app.draftBoards : app.draftBoards.filter(b => b === target);
    if (!boards.length) { alert('수집할 카테고리를 먼저 골라 주세요.'); return; }
    if (!keyword) { input.focus(); return; }
    const added = boards.filter(b => !app.groupDraft.some(m => m.board === b && m.keyword === keyword));
    if (!added.length) {
        alert('이미 등록한 키워드입니다.');
        return;
    }
    added.forEach(b => app.groupDraft.push({ board: b, keyword: keyword, paused: false, ignores: [] }));
    input.value = '';
    renderGroupSettings();
    input.focus();
}

function addDraftIgnore() {
    const input = document.getElementById('group-ignore-input');
    const phrase = input.value.trim();
    const entry = (app.draftEntries || [])[Number(document.getElementById('group-ignore-keyword').value)];
    if (!entry) { alert('키워드를 먼저 등록해 주세요.'); return; }
    if (!phrase) { input.focus(); return; }
    if (entry.members.every(m => m.ignores.some(p => normPhrase(p) === normPhrase(phrase)))) {
        alert('이미 등록한 무시할 표현입니다.');
        return;
    }
    entry.members.forEach(m => { if (!m.ignores.some(p => normPhrase(p) === normPhrase(phrase))) m.ignores.push(phrase); });
    input.value = '';
    renderGroupSettings();
    input.focus();
}

// 수집할 카테고리 고르기 (게시판 만들기·수정): 누를 때마다 넣고 빼기. 뺄 때 그 카테고리의 키워드도 함께 빠짐.
// 이미 고른 카테고리가 둘 이상이면 새로 넣는 카테고리에도 공통 키워드를 등록
function toggleDraftBoard(board) {
    if (app.draftBoards.includes(board)) {
        const members = app.groupDraft.filter(m => m.board === board);
        if (members.length && !confirm(`'${boardName(board)}' 카테고리의 키워드 ${members.length}개도 함께 뺍니다. 뺄까요?`)) return;
        app.groupDraft = app.groupDraft.filter(m => m.board !== board);
        app.draftBoards = app.draftBoards.filter(b => b !== board);
    } else {
        const common = draftEntries().filter(e => e.common);
        app.draftBoards.push(board);
        common.forEach(e => app.groupDraft.push({
            board: board, keyword: e.keyword, paused: e.members.every(m => m.paused), ignores: entryIgnores(e)
        }));
    }
    renderGroupSettings();
}

// 카테고리 고르기 칩과 키워드를 찾을 곳 상자 (확인을 통과하지 못한 카테고리는 뺌)
function renderBoardChecks() {
    if (!app.draftBoards) return;
    const boards = app.state.boards.filter(b => b.status !== 'invalid');
    app.draftBoards = app.draftBoards.filter(key => boards.some(b => b.key === key) || app.groupDraft.some(m => m.board === key));
    document.getElementById('group-board-checks').innerHTML = boards.map(b => `
        <button type="button" class="board-check" data-action="toggle-draft-board" data-board="${esc(b.key)}" aria-pressed="${app.draftBoards.includes(b.key)}">
            ${siteTag(b.site)}${esc(b.name)}${b.status === 'pending' ? ' (확인 대기)' : ''}
        </button>`).join('');
    const target = document.getElementById('group-kw-target');
    const prev = target.value;
    const options = (app.draftBoards.length > 1 ? [['*', '공통']] : [])
        .concat(app.draftBoards.map(key => [key, `${siteLabel(boardSite(key)).short} ${boardName(key)}`]));
    target.innerHTML = options.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join('');
    if (options.some(([value]) => value === prev)) target.value = prev;
    target.disabled = !options.length;
}

// 고른 게시판의 키워드를 지금 수정 중인 게시판에 넣고, 저장할 때 그 게시판을 지우도록 기억
function addDraftMerge() {
    const id = Number(document.getElementById('group-merge-select').value);
    const source = (app.state.groups || []).find(g => g.id === id);
    if (!source) return;
    source.members.forEach(m => {
        if (!app.groupDraft.some(d => d.board === m.board && d.keyword === m.keyword)) {
            app.groupDraft.push({ board: m.board, keyword: m.keyword, paused: !!m.paused, ignores: m.ignores.slice() });
        }
    });
    source.members.forEach(m => { if (!app.draftBoards.includes(m.board)) app.draftBoards.push(m.board); });
    app.mergeDraft.push(id);
    renderGroupSettings();
}

function resetGroupForm() {
    app.groupFormOpen = false;
    app.mergeDraft = [];
    app.draftBoards = undefined;
    app.editingGroupId = null;
    app.groupDraft = undefined;
    app.groupNameDraft = undefined;
    document.getElementById('group-kw-input').value = '';
    document.getElementById('group-ignore-input').value = '';
    renderGroupSettings();
}

// 다른 게시판에 없는 키워드는 게시판에서 빠지면 수집을 멈추고 모은 글도 삭제됨 (합쳐서 지울 게시판의 키워드도 포함)
function droppedKeywords(groupId, keepMembers, mergeIds = []) {
    const keep = new Set(keepMembers.map(memberKey));
    const leaving = new Set([groupId, ...mergeIds]);
    const others = new Set((app.state.groups || []).filter(g => !leaving.has(g.id)).flatMap(g => g.members.map(memberKey)));
    const seen = new Set();
    return (app.state.groups || []).filter(g => leaving.has(g.id)).flatMap(g => g.members)
        .filter(m => !keep.has(memberKey(m)) && !others.has(memberKey(m)) && !seen.has(memberKey(m)) && seen.add(memberKey(m)));
}

async function saveGroup(button) {
    const pwd = adminPassword();
    const name = document.getElementById('group-name-input').value.trim();
    // 입력만 하고 '추가'를 누르지 않은 키워드도 함께 등록
    if (document.getElementById('group-kw-input').value.trim()) addDraftKeyword();
    if (document.getElementById('group-ignore-input').value.trim()) addDraftIgnore();
    const members = app.groupDraft.map(m => ({ board: m.board, keyword: m.keyword, paused: !!m.paused, ignores: m.ignores.slice() }));
    if (!name) { alert('게시판 이름을 입력해 주세요.'); document.getElementById('group-name-input').focus(); return; }
    if (members.length === 0) { alert('키워드를 하나 이상 등록해 주세요.'); document.getElementById('group-kw-input').focus(); return; }
    if (!pwd) { needPassword(); return; }

    const editingId = app.editingGroupId;
    const mergeIds = editingId ? app.mergeDraft.slice() : [];
    const dropped = editingId ? droppedKeywords(editingId, members, mergeIds) : [];
    if (dropped.length && !confirm(`뺀 키워드 ${dropped.map(m => m.keyword).join(', ')}는 수집을 멈추고 모은 글도 삭제됩니다. 저장할까요?`)) return;
    button.disabled = true;
    try {
        const data = await postJSON('/api/group', {
            action: editingId ? 'update' : 'create', id: editingId, name: name, members: members, merge_ids: mergeIds, password: pwd,
            folder_id: editingId || !document.getElementById('group-folder-select').value
                ? null : Number(document.getElementById('group-folder-select').value)
        });
        if (!data.success) { if (data.message) alert(data.message); return; }
        resetGroupForm();
        // 만들거나 고친 게시판을 바로 열어서 보여줌
        app.activeKey = 'group:' + data.id;
        app.searchQuery = ''; app.searchHere = false; app.searchDays = 0;
        app.page = 1;
        setSettingsOpen(false);
        await loadState();
        window.scrollTo({ top: 0 });
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
    } finally {
        button.disabled = false;
    }
}

async function deleteGroup(groupId, button) {
    const group = (app.state.groups || []).find(g => g.id === groupId);
    if (!group) return;
    const pwd = adminPassword();
    if (!pwd) { needPassword(); return; }
    const dropped = droppedKeywords(groupId, []);
    const note = dropped.length ? `\n(키워드 ${dropped.map(m => m.keyword).join(', ')}는 수집을 멈추고 모은 글도 삭제됩니다)` : '';
    if (!confirm(`'${group.name}' 게시판을 삭제할까요?${note}`)) return;
    button.disabled = true;
    try {
        const data = await postJSON('/api/group', { action: 'delete', id: groupId, password: pwd });
        if (!data.success) { if (data.message) alert(data.message); return; }
        if (app.activeKey === 'group:' + groupId) { app.activeKey = ALL_KEY; app.page = 1; }
        if (app.editingGroupId === groupId) resetGroupForm();
        await loadState();
        renderSettings();
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
    } finally {
        button.disabled = false;
    }
}

// ---------- 카테고리 (수집할 에펨코리아 게시판. 추가하면 수집기가 다음 주기에 확인) ----------
const CATEGORY_STATUS = {
    pending: { label: '확인 대기', cls: 'cat-pending' },
    ok: { label: '수집 중', cls: 'cat-ok' },
    invalid: { label: '수집 불가', cls: 'cat-invalid' }
};

// 키워드 등록용 카테고리 선택: 수집할 수 없는 카테고리는 빼고, 확인 전인 카테고리는 표시해서 보여줌
// 사이트 이름·짧은 표시 편집 (저장하면 사이드바·FM·DC 표시·텔레그램 알림에 바로 반영)
function renderSiteSettings() {
    document.getElementById('settings-sites').innerHTML = Object.entries(SITES).map(([site, label]) => `
        <div class="group-row site-row">
            ${siteTag(site)}
            <input class="input site-name-input" data-site="${site}" value="${esc(label.name)}" maxlength="20" aria-label="${esc(label.name)} 이름" autocomplete="off">
            <input class="input site-short-input" data-site="${site}" value="${esc(label.short)}" maxlength="4" aria-label="${esc(label.name)} 짧은 표시" autocomplete="off">
            <button class="btn btn-outline btn-small" data-action="save-site" data-site="${site}">저장</button>
        </div>`).join('');
}

async function saveSite(site, button) {
    const row = button.closest('.site-row');
    const name = row.querySelector('.site-name-input').value.trim();
    const short = row.querySelector('.site-short-input').value.trim();
    if (!name || !short) { alert('이름과 짧은 표시를 모두 입력해 주세요.'); return; }
    const pwd = adminPassword();
    if (!pwd) { needPassword(); return; }
    button.disabled = true;
    try {
        const data = await postJSON('/api/site', { site: site, name: name, short: short, password: pwd });
        if (!data.success) { if (data.message) alert(data.message); return; }
        await loadState();
        renderSettings();
        alert(data.message);
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
    } finally {
        button.disabled = false;
    }
}

function renderCategorySettings() {
    const boards = app.state.boards || [];
    document.getElementById('settings-categories').innerHTML = boards.length ? boards.map(b => {
        const status = CATEGORY_STATUS[b.status] || CATEGORY_STATUS.pending;
        // 확인은 됐지만 등록한 키워드가 없으면 실제로 수집하는 글은 없음
        const label = b.status === 'ok' && !b.keyword_count ? '확인됨' : status.label;
        const usage = b.keyword_count
            ? `키워드 ${b.keyword_count}개${b.groups.length ? ` (${b.groups.map(esc).join(', ')})` : ''}`
            : '키워드 없음';
        return `
        <div class="group-row">
            <div class="group-row-main">
                <span class="group-row-name">${siteTag(b.site)}${esc(b.name)} <span class="cat-status ${status.cls}">${label}</span></span>
                <span class="group-row-members">${esc(b.key)} · ${usage}</span>
                ${b.status === 'invalid' && b.message ? `<span class="cat-message">${esc(b.message)}</span>` : ''}
            </div>
            ${b.status === 'invalid' ? `<button class="btn btn-outline btn-small" data-action="recheck-category" data-key="${esc(b.key)}">다시 확인</button>` : ''}
            <button class="btn btn-outline btn-small" data-action="rename-category" data-key="${esc(b.key)}">이름</button>
            <button class="btn btn-outline btn-small btn-danger" data-action="delete-category" data-key="${esc(b.key)}">삭제</button>
        </div>`;
    }).join('') : '<span class="settings-hint">등록된 카테고리가 없습니다.</span>';
}

async function categoryRequest(body, button) {
    const pwd = adminPassword();
    if (!pwd) { needPassword(); return false; }
    button.disabled = true;
    try {
        const data = await postJSON('/api/category', { ...body, password: pwd });
        if (!data.success) { if (data.message) alert(data.message); return false; }
        await loadState();
        renderSettings();
        return data;
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
        return false;
    } finally {
        button.disabled = false;
    }
}

async function addCategory(button) {
    const input = document.getElementById('category-input');
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    const data = await categoryRequest({ action: 'create', input: value }, button);
    if (data) {
        input.value = '';
        alert(data.message);
    }
}

// ---------- 묶음 (사이드바에서 게시판을 묶어 보여 줌) ----------
function renderFolderSettings() {
    const folders = app.state.folders || [];
    const groups = app.state.groups || [];
    // 묶음은 묶음 없는 게시판과 함께 한 줄 순서에서 옮김 (맨 앞·맨 뒤면 그쪽 화살표를 끔)
    const top = topItems();
    const first = top[0], last = top[top.length - 1];
    const isTop = (t, f) => t && t.kind === 'folder' && t.item.id === f.id;
    document.getElementById('settings-folders').innerHTML = folders.length ? folders.map(f => {
        const names = groups.filter(g => g.folder_id === f.id).map(g => esc(g.name));
        return `
        <div class="group-row">
            <div class="group-row-main">
                <span class="group-row-name">${esc(f.name)}</span>
                <span class="group-row-members">${names.length ? names.join(' · ') : '(비어 있음 · 사이드바에 보이지 않음)'}</span>
            </div>
            <button class="icon-btn small" data-action="move-folder" data-folder-id="${f.id}" data-direction="up" aria-label="${esc(f.name)} 묶음 위로" ${isTop(first, f) ? 'disabled' : ''}>${ICONS.up}</button>
            <button class="icon-btn small" data-action="move-folder" data-folder-id="${f.id}" data-direction="down" aria-label="${esc(f.name)} 묶음 아래로" ${isTop(last, f) ? 'disabled' : ''}>${ICONS.down}</button>
            <button class="btn btn-outline btn-small" data-action="rename-folder" data-folder-id="${f.id}">이름</button>
            <button class="btn btn-outline btn-small btn-danger" data-action="delete-folder" data-folder-id="${f.id}">삭제</button>
        </div>`;
    }).join('') : '<span class="settings-hint">만든 묶음이 없습니다. 게시판은 사이드바에 묶음 없이 보입니다.</span>';
}

// 묶음·게시판 배치 요청 (관리자 암호 필요). 성공하면 상태를 다시 받아 사이드바와 관리 화면을 그림
async function adminRequest(url, body, button) {
    const pwd = adminPassword();
    if (!pwd) { needPassword(); return null; }
    if (button) button.disabled = true;
    try {
        const data = await postJSON(url, { ...body, password: pwd });
        if (!data.success) { if (data.message) alert(data.message); return null; }
        await loadState();
        renderSettings();
        return data;
    } catch (e) {
        alert('요청 중 오류가 발생했습니다.');
        return null;
    } finally {
        if (button) button.disabled = false;
    }
}
function folderRequest(body, button) { return adminRequest('/api/folder', body, button); }
function arrangeGroup(body, control) { return adminRequest('/api/group', { action: 'arrange', ...body }, control); }

async function addFolder(button) {
    const input = document.getElementById('folder-name-input');
    const name = input.value.trim();
    if (!name) { input.focus(); return; }
    if (await folderRequest({ action: 'create', name: name }, button)) input.value = '';
}

async function renameFolder(folderId, button) {
    const folder = (app.state.folders || []).find(f => f.id === folderId);
    if (!folder) return;
    const name = prompt(`'${folder.name}' 묶음의 새 이름`, folder.name);
    if (name === null || !name.trim() || name.trim() === folder.name) return;
    await folderRequest({ action: 'rename', id: folderId, name: name.trim() }, button);
}

async function deleteFolder(folderId, button) {
    const folder = (app.state.folders || []).find(f => f.id === folderId);
    if (!folder || !confirm(`'${folder.name}' 묶음을 삭제할까요? 안에 있던 게시판은 지워지지 않고 묶음 없이 남습니다.`)) return;
    await folderRequest({ action: 'delete', id: folderId }, button);
}

async function renameCategory(key, button) {
    const board = app.state.boards.find(b => b.key === key);
    if (!board) return;
    const name = prompt(`'${board.name}' 카테고리의 새 이름`, board.name);
    if (name === null || !name.trim() || name.trim() === board.name) return;
    await categoryRequest({ action: 'rename', key: key, name: name.trim() }, button);
}

async function deleteCategory(key, button) {
    const board = app.state.boards.find(b => b.key === key);
    if (!board) return;
    // 키워드가 등록된 카테고리는 서버에서도 거부함 (지우면 그 키워드를 쓰는 게시판을 고칠 수 없게 됨)
    if (board.keyword_count) {
        alert(`키워드가 등록되어 있어 삭제할 수 없습니다.${board.groups.length ? `\n(${board.groups.join(', ')} 게시판에서 이 카테고리 키워드를 먼저 빼 주세요)` : ''}`);
        return;
    }
    if (!confirm(`'${board.name}' 카테고리를 삭제할까요?`)) return;
    await categoryRequest({ action: 'delete', key: key }, button);
}

// ---------- 수집 상태 (수집 주기·차단 의심·크롬·백업·최근 경고) ----------
function parseServerTime(ts) {
    return ts ? new Date(ts.replace(' ', 'T')) : null;
}

function agoText(ts, now) {
    const t = parseServerTime(ts);
    if (!t) return '';
    const minutes = Math.floor((parseServerTime(now) - t) / 60000);
    if (minutes < 1) return '방금';
    if (minutes < 60) return `${minutes}분 전`;
    if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}시간 전`;
    return `${Math.floor(minutes / 60 / 24)}일 전`;
}

function renderRuntimeStatus(s) {
    const hm = ts => esc((ts || '').slice(11, 16));
    const row = (label, value) => `<div class="status-row"><span class="status-label">${label}</span><span class="status-value">${value}</span></div>`;
    const c = s.last_cycle;
    const rows = [
        // started_at이 없으면 웹서버가 수집기 상태를 받지 못한 것 (수집기 컨테이너가 시작 전이거나 멈춤)
        row('상태', !s.started_at
            ? '<span class="status-warn">수집기 상태 없음</span> (수집기가 시작 중이거나 멈춤)'
            : s.stalled_minutes
            ? `<span class="status-warn">멈춤 의심 · ${s.stalled_minutes}분째 진행 없음</span> (텔레그램으로 알림)`
            : s.block_streak
            ? `<span class="status-warn">차단 의심 · 연속 ${s.block_streak}회</span> (다음 확인 ${hm(s.next_check_at)})`
            : '<span class="status-ok">정상 수집 중</span>'),
        row('마지막 수집', c
            ? `${hm(c.finished_at)} (${agoText(c.finished_at, s.now)}) · ${c.seconds}초 · 새 글 ${c.new}, 갱신 ${c.updated}, 오류 ${c.errors}`
            : '아직 없음 (시작 직후)'),
        row('실행', s.started_at ? `${hm(s.started_at)}부터 (${agoText(s.started_at, s.now)}) · 주기 ${s.cycles}회` : '-'),
        row('크롬', s.chrome_started_at ? `${hm(s.chrome_started_at)} 시작 · 재시작 ${s.chrome_restarts}회` : '-'),
        row('DB 백업', s.last_backup ? `${esc(s.last_backup.file)} (${hm(s.last_backup.at)})` : '오늘 백업 있음 또는 아직 안 함'),
        row('오래된 글 정리', s.last_prune ? `${s.last_prune.deleted}건 정리 (${hm(s.last_prune.at)})` : '-')
    ];
    const problems = (s.recent_problems || []).slice(0, 5);
    const problemList = problems.length
        ? `<ul class="status-problems">${problems.map(p => `<li><span class="status-time">${esc(p.time.slice(5, 16))}</span>${esc(p.message)}</li>`).join('')}</ul>`
        : '<span class="settings-hint">최근 경고·오류 없음</span>';
    document.getElementById('settings-status').innerHTML = rows.join('') +
        `<div class="status-row status-row-block"><span class="status-label">최근 경고·오류</span>${problemList}</div>`;
}

async function loadRuntimeStatus() {
    const box = document.getElementById('settings-status');
    try {
        renderRuntimeStatus(await getJSON('/api/status'));
    } catch (e) {
        box.innerHTML = '<span class="settings-hint">수집 상태를 불러오지 못했습니다.</span>';
    }
}

function setSettingsOpen(open) {
    const panel = document.getElementById('settings');
    panel.hidden = !open;
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
        // 관리 화면은 관리자로 로그인한 기기에서만
        if (!adminPassword()) { panel.hidden = true; document.body.style.overflow = ''; openLogin(); return; }
        renderSettings();
        setSettingsTab(app.settingsTab || 'groups');
    }
}

// 관리 화면 탭: 고른 칸만 보여 주고, 수집 상태는 그 탭을 열 때 새로 받아 옴
function setSettingsTab(tab) {
    app.settingsTab = tab;
    document.querySelectorAll('.settings-tab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
    document.querySelectorAll('.settings-pane').forEach(p => { p.hidden = p.dataset.pane !== tab; });
    document.querySelector('.settings-body').scrollTop = 0;
    if (tab === 'status') loadRuntimeStatus();
}

// 게시판 탭의 편집 양식 열기 (새 게시판). 사이드바 '+'에서 부르면 관리 화면부터 엶
function openNewGroupForm() {
    if (!adminPassword()) { openLogin(); return; }
    if (document.getElementById('settings').hidden) setSettingsOpen(true);
    setSettingsTab('groups');
    resetGroupForm();
    app.groupFormOpen = true;
    renderGroupSettings();
    document.getElementById('group-name-input').focus();
}

// ---------- 관리자 로그인 ----------
// 암호로 한 번 로그인하면 서버가 준 로그인 키를 이 기기(localStorage)에 기억해 다시 묻지 않고, 관리 요청에 암호 대신 보냄.
// 로그인 전에는 관리 버튼·게시판 만들기(+) 대신 자물쇠 버튼만 보임 (body.is-admin)
const ADMIN_TOKEN_KEY = 'admin_token';
function adminPassword() {
    return storageGet(localStorage, ADMIN_TOKEN_KEY, '');
}

function updateAdminUI() {
    document.body.classList.toggle('is-admin', !!adminPassword());
}

function openLogin(message) {
    const box = document.getElementById('login');
    box.hidden = false;
    const error = document.getElementById('login-error');
    error.textContent = message || '';
    error.hidden = !message;
    const input = document.getElementById('admin-pwd-input');
    input.value = '';
    input.focus();
}

function closeLogin() {
    document.getElementById('login').hidden = true;
}

async function submitLogin() {
    const input = document.getElementById('admin-pwd-input');
    const error = document.getElementById('login-error');
    const button = document.getElementById('login-submit');
    if (!input.value.trim()) { input.focus(); return; }
    button.disabled = true;
    try {
        const res = await fetch('/api/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify({ password: input.value })
        });
        const data = await res.json();
        if (!data.success) {
            error.textContent = data.message.replace(/^❌\s*/, '');
            error.hidden = false;
            input.select();
            return;
        }
        storageSet(localStorage, ADMIN_TOKEN_KEY, data.token);
        input.value = '';
        closeLogin();
        updateAdminUI();
        setSettingsOpen(true);
    } catch (e) {
        error.textContent = '요청 중 오류가 발생했습니다.';
        error.hidden = false;
    } finally {
        button.disabled = false;
    }
}

function logout() {
    storageRemove(localStorage, ADMIN_TOKEN_KEY);
    setSettingsOpen(false);
    updateAdminUI();
}

// 기억한 로그인 키가 없거나 더는 맞지 않을 때(서버 암호를 바꿈 등): 로그아웃하고 로그인 창을 띄움
function needPassword(message) {
    logout();
    openLogin(message || '관리자 암호를 입력해 주세요.');
}

async function toggleGroupAlert(checkbox) {
    const pwd = adminPassword();
    const target = checkbox.checked;
    if (!pwd) {
        checkbox.checked = !target;
        needPassword();
        return;
    }
    const groupId = Number(checkbox.dataset.groupId);
    const type = checkbox.dataset.type;
    try {
        const data = await postJSON('/api/toggle-alert', { group: groupId, type: type, enabled: target, password: pwd });
        const group = (app.state.groups || []).find(g => g.id === groupId);
        if (data.success) {
            if (type === 'saved_comment') app.state.saved_comment_alert = target;
            else if (group) group[type] = target;
            renderNavigation();
        } else {
            if (data.message) alert(data.message);
            checkbox.checked = !target;
        }
    } catch (e) {
        alert('알림 상태 요청 중 오류가 발생했습니다.');
        checkbox.checked = !target;
    }
}

// 인기 글 알림 기준 (추천+댓글 수, 비우거나 0이면 끔)
async function setPopularMin(input) {
    const groupId = Number(input.dataset.groupId);
    const group = (app.state.groups || []).find(g => g.id === groupId);
    const restore = () => { input.value = group && group.popular_min ? group.popular_min : ''; };
    const pwd = adminPassword();
    if (!pwd) { restore(); needPassword(); return; }
    const min = input.value.trim() === '' ? 0 : Number(input.value);
    if (!Number.isInteger(min) || min < 0 || min > 100000) {
        alert('인기 글 기준은 0~100,000 사이 숫자로 입력해 주세요.');
        restore();
        return;
    }
    try {
        const data = await postJSON('/api/toggle-alert', { group: groupId, type: 'popular', min, password: pwd });
        if (data.relogin) { restore(); return; }
        if (!data.success) throw new Error(data.message);
        if (group) group.popular_min = min;
        if (!min) input.value = '';
        showToast(min ? `추천+댓글 ${min.toLocaleString()} 이상이면 알립니다` : '인기 글 알림을 껐습니다');
    } catch (e) {
        alert(e.message || '알림 상태 요청 중 오류가 발생했습니다.');
        restore();
    }
}
