"""
표시 순서표(ctts)가 빠진 MP4를 재생할 때만 바로잡아 내보냄

일부 MP4는 B프레임(뒤 장면을 먼저 풀어 두는 프레임)이 있는데도 프레임마다 '언제 보여 줄지'(ctts)가
빠져 있어, 모든 프레임의 표시 시각이 푸는 순서 그대로 매겨져 있음. 그러면 브라우저는 푼 프레임을
시각 순서대로 보여 주다가 시각이 뒤로 가는 프레임을 늦었다고 버려(B프레임 3장마다 1장꼴, 약 25%)
화면이 뚝뚝 끊기고, 남은 프레임도 순서가 섞여 보임. (VLC 같은 재생기는 스스로 순서를 다시 계산해 멀쩡함)

고치는 법: 각 프레임의 슬라이스 머리에서 표시 순서 번호(POC)를 읽어 실제 표시 순서를 구하고,
그에 맞는 ctts를 moov에 넣은 '새 moov'를 만듦. 원본 파일은 건드리지 않고(읽기 전용 마운트),
보낼 때 [moov 앞 원본][새 moov][moov 뒤 원본]을 이어 붙인 가상의 파일로 보냄.
새 moov는 output/video_fix에 저장해 두고 파일이 바뀌면(크기·수정 시각) 다시 만듦.

다루지 않는 것(그대로 원본을 보냄): ctts가 이미 있음, H.264가 아님, 조각난 MP4(moof),
POC 방식 0이 아님(방식 2는 애초에 순서가 바뀌지 않음), 필드(인터레이스) 부호화
"""
import hashlib
import json
import os
import struct
import threading

from config import OUTPUT_DIR

FIX_DIR = os.path.join(OUTPUT_DIR, 'video_fix')
# 이 확장자만 살펴봄 (MP4 계열)
MP4_TYPES = ('mp4', 'm4v', 'mov')
# 앞쪽 이만큼의 프레임에서 순서가 한 번도 안 바뀌면 고칠 것이 없다고 봄 (전체를 읽지 않으려고)
PROBE_SAMPLES = 150
# 표시 순서가 푸는 순서와 이보다 많이 벌어지면 잘못 읽은 것으로 보고 고치지 않음
MAX_REORDER = 16
# 슬라이스 머리를 읽으려고 NAL마다 앞부분만 읽는 양
HEAD_READ = 48
CACHE_VERSION = 1

_locks = {}
_locks_guard = threading.Lock()
# 최근에 보낸 결과 {키: (전체 크기, 조각들) 또는 None} — 건너뛸 때마다 오는 Range 요청에서 디스크를 다시 읽지 않으려고
_memo = {}
MEMO_SIZE = 16


class Unsupported(Exception):
    """고칠 수 없거나 고칠 필요가 없는 파일"""


# ==========================================
# MP4 상자(box) 읽고 쓰기
# ==========================================
# 안에 다른 상자를 담는 상자 (moov 안에서 ctts를 넣으려면 stbl까지 내려가야 함)
CONTAINERS = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts'}


def _parse_boxes(data, start=0, end=None):
    """[[종류, 내용 bytes 또는 자식 목록], ...]"""
    end = len(data) if end is None else end
    out = []
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from('>I4s', data, pos)
        head = 8
        if size == 1:
            size = struct.unpack_from('>Q', data, pos + 8)[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            raise Unsupported('broken box')
        if kind in CONTAINERS:
            out.append([kind, _parse_boxes(data, pos + head, pos + size)])
        else:
            out.append([kind, data[pos + head:pos + size]])
        pos += size
    return out


def _build_boxes(boxes):
    parts = []
    for kind, body in boxes:
        if isinstance(body, list):
            body = _build_boxes(body)
        parts.append(struct.pack('>I4s', 8 + len(body), kind) + body)
    return b''.join(parts)


def _child(boxes, kind):
    for box in boxes:
        if box[0] == kind:
            return box
    return None


def _top_boxes(f, size):
    """파일 맨 위 상자들의 (종류, 시작, 크기)"""
    out = []
    pos = 0
    while pos + 8 <= size:
        f.seek(pos)
        head = f.read(16)
        box_size, kind = struct.unpack_from('>I4s', head, 0)
        if box_size == 1:
            box_size = struct.unpack_from('>Q', head, 8)[0]
        elif box_size == 0:
            box_size = size - pos
        if box_size < 8:
            raise Unsupported('broken top box')
        out.append((kind, pos, box_size))
        pos += box_size
    return out


# ==========================================
# H.264 비트 읽기 (SPS·PPS·슬라이스 머리에 필요한 만큼만)
# ==========================================
def _unescape(data):
    """00 00 03 의 03(에뮬레이션 방지 바이트)을 뺌"""
    if b'\x00\x00\x03' not in data:
        return data
    out = bytearray()
    zeros = 0
    for b in data:
        if zeros >= 2 and b == 3:
            zeros = 0
            continue
        out.append(b)
        zeros = zeros + 1 if b == 0 else 0
    return bytes(out)


class _Bits:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def u(self, n):
        v = 0
        for _ in range(n):
            byte = self.pos >> 3
            if byte >= len(self.data):
                raise Unsupported('short bitstream')
            v = (v << 1) | ((self.data[byte] >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def ue(self):
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
            if zeros > 31:
                raise Unsupported('bad exp-golomb')
        return (1 << zeros) - 1 + self.u(zeros)

    def se(self):
        v = self.ue()
        return (v + 1) // 2 if v & 1 else -(v // 2)


HIGH_PROFILES = {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}


def _parse_sps(nal):
    b = _Bits(_unescape(nal[1:]))
    profile = b.u(8)
    b.u(16)  # 제약 플래그·레벨
    sps_id = b.ue()
    separate_colour = 0
    if profile in HIGH_PROFILES:
        chroma = b.ue()
        if chroma == 3:
            separate_colour = b.u(1)
        b.ue()
        b.ue()
        b.u(1)
        if b.u(1):  # seq_scaling_matrix_present
            for i in range(8 if chroma != 3 else 12):
                if b.u(1):
                    last = nxt = 8
                    for _ in range(16 if i < 6 else 64):
                        if nxt:
                            nxt = (last + b.se() + 256) % 256
                        last = nxt or last
    log2_frame_num = b.ue() + 4
    poc_type = b.ue()
    if poc_type != 0:
        raise Unsupported(f'poc type {poc_type}')
    log2_poc_lsb = b.ue() + 4
    b.ue()  # max_num_ref_frames
    b.u(1)
    b.ue()
    b.ue()
    frame_mbs_only = b.u(1)
    if not frame_mbs_only:
        raise Unsupported('interlaced')
    return sps_id, {'frame_num_bits': log2_frame_num, 'poc_lsb_bits': log2_poc_lsb, 'separate_colour': separate_colour}


def _parse_pps(nal):
    b = _Bits(_unescape(nal[1:]))
    pps_id = b.ue()
    sps_id = b.ue()
    b.u(1)  # entropy_coding_mode
    bottom_poc = b.u(1)
    return pps_id, {'sps': sps_id, 'bottom_poc': bottom_poc}


def _parse_avcc(avcc):
    """avcC → (NAL 길이 바이트 수, {sps_id: ...}, {pps_id: ...})"""
    if len(avcc) < 7:
        raise Unsupported('short avcC')
    length_size = (avcc[4] & 3) + 1
    pos = 6
    sps, pps = {}, {}
    for _ in range(avcc[5] & 31):
        n = struct.unpack_from('>H', avcc, pos)[0]
        key, val = _parse_sps(avcc[pos + 2:pos + 2 + n])
        sps[key] = val
        pos += 2 + n
    count = avcc[pos]
    pos += 1
    for _ in range(count):
        n = struct.unpack_from('>H', avcc, pos)[0]
        key, val = _parse_pps(avcc[pos + 2:pos + 2 + n])
        pps[key] = val
        pos += 2 + n
    if not sps or not pps:
        raise Unsupported('no sps/pps')
    return length_size, sps, pps


def _slice_info(nal, sps, pps):
    """슬라이스 NAL → (IDR인지, 참조 프레임인지, poc_lsb)"""
    kind = nal[0] & 31
    b = _Bits(_unescape(nal[1:]))
    b.ue()  # first_mb_in_slice
    b.ue()  # slice_type
    p = pps.get(b.ue())
    if p is None or p['sps'] not in sps:
        raise Unsupported('unknown pps')
    s = sps[p['sps']]
    if s['separate_colour']:
        b.u(2)
    b.u(s['frame_num_bits'])
    if kind == 5:
        b.ue()  # idr_pic_id
    return kind == 5, (nal[0] >> 5) & 3 != 0, b.u(s['poc_lsb_bits']), s['poc_lsb_bits']


# ==========================================
# 표 읽기: 프레임마다 파일 속 위치·푸는 시각
# ==========================================
def _full_box(body):
    return body[0], body[4:]


def _sample_offsets(stbl):
    stsz = _child(stbl, b'stsz')
    stsc = _child(stbl, b'stsc')
    stco = _child(stbl, b'stco') or _child(stbl, b'co64')
    if not stsz or not stsc or not stco:
        raise Unsupported('no sample table')
    _, body = _full_box(stsz[1])
    fixed, count = struct.unpack_from('>II', body, 0)
    sizes = [fixed] * count if fixed else list(struct.unpack_from(f'>{count}I', body, 8))
    _, body = _full_box(stco[1])
    n = struct.unpack_from('>I', body, 0)[0]
    chunks = list(struct.unpack_from(f'>{n}{"Q" if stco[0] == b"co64" else "I"}', body, 4))
    _, body = _full_box(stsc[1])
    n = struct.unpack_from('>I', body, 0)[0]
    runs = [struct.unpack_from('>III', body, 4 + 12 * i) for i in range(n)]
    offsets = []
    for r, (first, per_chunk, _desc) in enumerate(runs):
        last = runs[r + 1][0] - 1 if r + 1 < len(runs) else len(chunks)
        for chunk in range(first, last + 1):
            pos = chunks[chunk - 1]
            for _ in range(per_chunk):
                if len(offsets) >= count:
                    break
                offsets.append(pos)
                pos += sizes[len(offsets) - 1]
    if len(offsets) != count:
        raise Unsupported('sample table mismatch')
    return offsets, sizes


def _decode_times(stbl, count):
    stts = _child(stbl, b'stts')
    if not stts:
        raise Unsupported('no stts')
    _, body = _full_box(stts[1])
    n = struct.unpack_from('>I', body, 0)[0]
    times, t = [], 0
    for i in range(n):
        run, delta = struct.unpack_from('>II', body, 4 + 8 * i)
        for _ in range(run):
            times.append(t)
            t += delta
    if len(times) < count:
        raise Unsupported('stts too short')
    return times[:count]


def _sample_pocs(f, offsets, sizes, length_size, sps, pps, limit=None):
    """프레임마다 (IDR인지, 참조인지, poc_lsb, lsb 비트 수). 프레임 안 NAL을 앞에서부터 건너뛰며 첫 슬라이스를 찾음"""
    out = []
    for offset, size in zip(offsets[:limit] if limit else offsets, sizes):
        pos = 0
        found = None
        while pos + length_size < size:
            f.seek(offset + pos)
            head = f.read(length_size + HEAD_READ)
            n = int.from_bytes(head[:length_size], 'big')
            nal = head[length_size:length_size + min(n, HEAD_READ)]
            if not nal:
                break
            if nal[0] & 31 in (1, 5):
                found = _slice_info(nal, sps, pps)
                break
            pos += length_size + n
        if found is None:
            raise Unsupported('no slice')
        out.append(found)
    return out


def _display_ranks(infos):
    """POC로 표시 순서를 구해 프레임마다 '이 프레임이 IDR 묶음 안에서 몇 번째로 보이는지'(전체 번호)"""
    ranks = [0] * len(infos)
    group = []  # (poc, 번호)
    prev_msb = prev_lsb = 0

    def flush():
        for rank, (_, idx) in enumerate(sorted(group)):
            ranks[idx] = group[0][1] + rank
        group.clear()

    for i, (idr, ref, lsb, bits) in enumerate(infos):
        if idr:
            flush()
            prev_msb = prev_lsb = 0
        top = 1 << bits
        if lsb < prev_lsb and prev_lsb - lsb >= top // 2:
            msb = prev_msb + top
        elif lsb > prev_lsb and lsb - prev_lsb > top // 2:
            msb = prev_msb - top
        else:
            msb = prev_msb
        group.append((msb + lsb, i))
        if ref:
            prev_msb, prev_lsb = msb, lsb
    flush()
    return ranks


def _reordered(ranks):
    return any(r != i for i, r in enumerate(ranks))


# ==========================================
# 새 moov 만들기
# ==========================================
def _video_trak(moov):
    for box in moov:
        if box[0] != b'trak':
            continue
        mdia = _child(box[1], b'mdia')
        hdlr = mdia and _child(mdia[1], b'hdlr')
        if hdlr and hdlr[1][8:12] == b'vide':
            return box
    return None


def _avcc(stbl):
    stsd = _child(stbl, b'stsd')
    if not stsd:
        raise Unsupported('no stsd')
    body = stsd[1]
    entry_size, entry_kind = struct.unpack_from('>I4s', body, 8)
    if entry_kind not in (b'avc1', b'avc3'):
        raise Unsupported(f'codec {entry_kind!r}')
    entry = body[8:8 + entry_size]
    avcc = _child(_parse_boxes(entry, 8 + 78, len(entry)), b'avcC')
    if not avcc:
        raise Unsupported('no avcC')
    return avcc[1]


def _make_ctts(offsets):
    runs = []
    for v in offsets:
        if runs and runs[-1][1] == v:
            runs[-1][0] += 1
        else:
            runs.append([1, v])
    return b'\x00\x00\x00\x00' + struct.pack('>I', len(runs)) + b''.join(struct.pack('>II', n, v) for n, v in runs)


def _fix_edit_list(trak, delay, movie_duration):
    """표시 시각을 delay만큼 뒤로 민 만큼 편집 목록(elst)의 시작도 맞춤 → 첫 장면이 0초에 보임"""
    edts = _child(trak[1], b'edts')
    elst = edts and _child(edts[1], b'elst')
    if not elst:
        entry = struct.pack('>Ii', movie_duration, delay) + struct.pack('>hh', 1, 0)
        new = [b'elst', b'\x00\x00\x00\x00' + struct.pack('>I', 1) + entry]
        if edts:
            edts[1].append(new)
        else:
            idx = next(i for i, b in enumerate(trak[1]) if b[0] == b'tkhd') + 1
            trak[1].insert(idx, [b'edts', [new]])
        return
    body = bytearray(elst[1])
    version = body[0]
    n = struct.unpack_from('>I', body, 4)[0]
    fmt, step = ('>Qq', 20) if version == 1 else ('>Ii', 12)
    # 원래 시작점이 이미 delay 이상이면(앞부분을 숨긴 편집·원래 만든 프로그램이 맞춰 둔 값) 그대로 두고,
    # 모자라면 delay까지 늘림 → 첫 장면이 앞으로 당겨져 잘리거나 숨긴 앞부분이 드러나지 않음
    move = None
    for i in range(n):
        pos = 8 + step * i
        dur, media = struct.unpack_from(fmt, body, pos)
        if media == -1:
            continue
        if move is None:
            move = max(media, delay) - media
        struct.pack_into(fmt, body, pos, dur, media + move)
    elst[1] = bytes(body)


def _shift_chunks(moov, delta, after):
    """moov가 영상 데이터 앞에 있으면 moov가 커진 만큼 데이터 위치(stco)도 뒤로 밂"""
    for trak in moov:
        if trak[0] != b'trak':
            continue
        stbl = _child(_child(_child(trak[1], b'mdia')[1], b'minf')[1], b'stbl')[1]
        for box in stbl:
            if box[0] not in (b'stco', b'co64'):
                continue
            body = bytearray(box[1])
            n = struct.unpack_from('>I', body, 4)[0]
            fmt, step = ('>Q', 8) if box[0] == b'co64' else ('>I', 4)
            for i in range(n):
                pos = 8 + step * i
                v = struct.unpack_from(fmt, body, pos)[0]
                if v >= after:
                    v += delta
                    if step == 4 and v > 0xFFFFFFFF:
                        raise Unsupported('stco overflow')
                    struct.pack_into(fmt, body, pos, v)
            box[1] = bytes(body)


def build(full):
    """고친 moov와 그 자리 → {'moov_start', 'moov_end', 'moov'(bytes)}. 고칠 것이 없으면 Unsupported"""
    size = os.path.getsize(full)
    # 프레임마다 몇십 바이트만 읽으므로 버퍼 없이 (버퍼가 있으면 건너뛸 때마다 수 KB씩 더 읽음)
    with open(full, 'rb', buffering=0) as f:
        tops = _top_boxes(f, size)
        kinds = [k for k, _, _ in tops]
        if kinds.count(b'moov') != 1 or b'moof' in kinds:
            raise Unsupported('no single moov / fragmented')
        _, moov_start, moov_size = tops[kinds.index(b'moov')]
        if moov_size > 64 * 1024 * 1024:
            raise Unsupported('moov too large')
        f.seek(moov_start)
        raw = f.read(moov_size)
        moov_box = _parse_boxes(raw)[0]
        moov = moov_box[1]
        if _child(moov, b'mvex'):
            raise Unsupported('fragmented')
        trak = _video_trak(moov)
        if not trak:
            raise Unsupported('no video')
        stbl_box = _child(_child(_child(trak[1], b'mdia')[1], b'minf')[1], b'stbl')
        stbl = stbl_box[1]
        if _child(stbl, b'ctts'):
            raise Unsupported('has ctts')
        length_size, sps, pps = _parse_avcc(_avcc(stbl))
        offsets, sizes = _sample_offsets(stbl)
        if len(offsets) < 2:
            raise Unsupported('too few samples')
        # 앞부분만 보고 순서가 그대로면 끝 (대부분의 정상 파일)
        if not _reordered(_display_ranks(_sample_pocs(f, offsets, sizes, length_size, sps, pps, PROBE_SAMPLES))):
            raise Unsupported('no reorder')
        ranks = _display_ranks(_sample_pocs(f, offsets, sizes, length_size, sps, pps))
    if max(abs(r - i) for i, r in enumerate(ranks)) > MAX_REORDER:
        raise Unsupported('reorder too deep')
    dts = _decode_times(stbl, len(ranks))
    # rank번째로 보이는 프레임은 rank번째 프레임의 푸는 시각에 보여 줌 → 표시 시각 - 푸는 시각
    shift = [dts[r] - dts[i] for i, r in enumerate(ranks)]
    delay = max(0, -min(shift))
    idx = next(i for i, b in enumerate(stbl) if b[0] == b'stts') + 1
    stbl.insert(idx, [b'ctts', _make_ctts([s + delay for s in shift])])
    mvhd = _child(moov, b'mvhd')[1]
    movie_duration = struct.unpack_from('>Q' if mvhd[0] == 1 else '>I', mvhd, 24 if mvhd[0] == 1 else 16)[0]
    _fix_edit_list(trak, delay, min(movie_duration, 0xFFFFFFFF))
    new = _build_boxes([moov_box])
    if moov_start + moov_size < size:
        # moov 뒤에 데이터가 있으면(빠른 시작용 배치) 커진 만큼 위치를 밂
        _shift_chunks(moov, len(new) - moov_size, moov_start + moov_size)
        new = _build_boxes([moov_box])
    return {'moov_start': moov_start, 'moov_end': moov_start + moov_size, 'moov': new}


# ==========================================
# 저장해 두고 꺼내 쓰기
# ==========================================
def _lock_for(key):
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.Lock()
        return lock


def layout(full):
    """보낼 가상의 파일 → (전체 크기, [(원본 시작, 길이) 또는 bytes, ...]). 고칠 것이 없으면 None"""
    ext = full.rsplit('.', 1)[-1].lower() if '.' in full else ''
    if ext not in MP4_TYPES:
        return None
    try:
        st = os.stat(full)
    except OSError:
        return None
    key = hashlib.sha1(f'{CACHE_VERSION}|{full}|{st.st_size}|{st.st_mtime_ns}'.encode('utf-8')).hexdigest()
    meta_path = os.path.join(FIX_DIR, key[:2], key + '.json')
    moov_path = os.path.join(FIX_DIR, key[:2], key + '.moov')
    if key in _memo:
        return _memo[key]
    with _lock_for(key):
        if key in _memo:
            return _memo[key]
        meta = None
        try:
            with open(meta_path, encoding='utf-8') as f:
                meta = json.load(f)
        except (OSError, ValueError):
            pass
        if meta is None:
            try:
                result = build(full)
                meta = {'fix': True, 'moov_start': result['moov_start'], 'moov_end': result['moov_end']}
                os.makedirs(os.path.dirname(moov_path), exist_ok=True)
                with open(moov_path + '.tmp', 'wb') as f:
                    f.write(result['moov'])
                os.replace(moov_path + '.tmp', moov_path)
            except Unsupported as e:
                meta = {'fix': False, 'reason': str(e)}
            except (OSError, struct.error, IndexError, ValueError, TypeError, AttributeError) as e:
                # 예상 못 한 모양의 파일: 원본 그대로 보내고 다음에 다시 보지 않음
                meta = {'fix': False, 'reason': f'error: {type(e).__name__}'}
            try:
                os.makedirs(os.path.dirname(meta_path), exist_ok=True)
                with open(meta_path + '.tmp', 'w', encoding='utf-8') as f:
                    json.dump(meta, f)
                os.replace(meta_path + '.tmp', meta_path)
            except OSError:
                pass
        result = None
        if meta.get('fix'):
            try:
                with open(moov_path, 'rb') as f:
                    moov = f.read()
            except OSError:
                return None
            start, end = meta['moov_start'], meta['moov_end']
            result = (start + len(moov) + st.st_size - end, [(0, start), moov, (end, st.st_size - end)])
        _memo[key] = result
        while len(_memo) > MEMO_SIZE:
            _memo.pop(next(iter(_memo)))
        return result


# ==========================================
# 미리 고쳐 두기 (재생 중에 다음 영상): 한 번에 하나씩, 뒤에서 조용히
# ==========================================
_queue = []
_queue_cond = threading.Condition()
_worker = None
QUEUE_MAX = 8


def _work():
    while True:
        with _queue_cond:
            while not _queue:
                _queue_cond.wait()
            full = _queue.pop(0)
        try:
            layout(full)
        except Exception:  # noqa: BLE001 - 미리 고치기가 실패해도 재생할 때 다시 시도됨
            pass


def prepare(full):
    """나중에 재생할 영상을 미리 고쳐 둠 (기다리지 않음)"""
    global _worker
    with _queue_cond:
        if full in _queue:
            return
        _queue.append(full)
        del _queue[:-QUEUE_MAX]
        if _worker is None:
            _worker = threading.Thread(target=_work, name='video-fix', daemon=True)
            _worker.start()
        _queue_cond.notify()
