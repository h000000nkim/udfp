"""HWP OLE2 인플레이스 패처 — BodyText 섹션 스트림만 교체.

PE-generation/modules/hwp_ole_patch.py 알고리즘을 UDF StreamPath(list[str]) 인터페이스로
재작성. OLE 구조(헤더, DIFAT, FAT, 디렉토리, 다른 스트림)를 전부 보존하고
지정된 스트림의 데이터만 교체한다. mini stream(<4096B)과 regular stream 모두 지원.

함정 8 주의: _alloc_sector()를 통해서만 새 섹터 확보할 것.
"""

from __future__ import annotations

import struct

StreamPath = list[str]

_FREESECT = 0xFFFFFFFF
_ENDOFCHAIN = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_DIFSECT = 0xFFFFFFFC
_NOSTREAM = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# FAT 읽기
# ---------------------------------------------------------------------------


def _read_fat(raw: bytes, sector_size: int) -> list[int]:
    """Read and reconstruct the full FAT from header + DIFAT sectors."""
    n_fat = struct.unpack_from("<I", raw, 44)[0]
    difat_start = struct.unpack_from("<I", raw, 68)[0]
    fat_sids: list[int] = []
    for i in range(109):
        sid = struct.unpack_from("<I", raw, 76 + i * 4)[0]
        if sid >= _DIFSECT:
            break
        fat_sids.append(sid)
    curr = difat_start
    while curr < _DIFSECT and len(fat_sids) < n_fat:
        off = 512 + curr * sector_size
        for j in range((sector_size // 4) - 1):
            sid = struct.unpack_from("<I", raw, off + j * 4)[0]
            if sid >= _DIFSECT:
                break
            fat_sids.append(sid)
        curr = struct.unpack_from("<I", raw, off + sector_size - 4)[0]
    fat: list[int] = []
    for sid in fat_sids:
        off = 512 + sid * sector_size
        count = sector_size // 4
        fat.extend(struct.unpack_from(f"<{count}I", raw, off))
    return fat


def _read_chain(fat: list[int], start: int) -> list[int]:
    """Follow a FAT chain from start sector to end-of-chain."""
    chain: list[int] = []
    curr = start
    while curr < _ENDOFCHAIN:
        chain.append(curr)
        if curr >= len(fat):
            break
        curr = fat[curr]
    return chain


# ---------------------------------------------------------------------------
# 디렉토리
# ---------------------------------------------------------------------------


def _dir_entries(
    raw: bytes, fat: list[int], dir_start: int, sector_size: int
) -> list[bytearray]:
    """Parse the directory stream into a list of 128-byte entry bytearrays."""
    buf = bytearray()
    for sid in _read_chain(fat, dir_start):
        off = 512 + sid * sector_size
        buf += raw[off : off + sector_size]
    return [bytearray(buf[i : i + 128]) for i in range(0, len(buf), 128)]


def _entry_name(entry: bytearray) -> str:
    """Extract the UTF-16LE name from a directory entry."""
    sz = struct.unpack_from("<H", entry, 64)[0]
    return entry[0:sz].decode("utf-16-le", errors="ignore").rstrip("\x00")


def _find_stream(entries: list[bytearray], path: StreamPath) -> int | None:
    """list[str] 경로로 스트림 디렉토리 항목 인덱스를 반환."""

    def _search(root_idx: int, target: str) -> int | None:
        """Recursively search the red-black tree for target name."""
        if root_idx == _NOSTREAM or root_idx >= len(entries):
            return None
        entry = entries[root_idx]
        if _entry_name(entry).lower() == target.lower() and entry[66] != 0:
            return root_idx
        left = struct.unpack_from("<I", entry, 68)[0]
        right = struct.unpack_from("<I", entry, 72)[0]
        found = _search(left, target)
        if found is not None:
            return found
        return _search(right, target)

    curr_idx = 0
    for part in path:
        child = struct.unpack_from("<I", entries[curr_idx], 76)[0]
        found = _search(child, part)
        if found is None:
            return None
        curr_idx = found
    return curr_idx


# ---------------------------------------------------------------------------
# Mini FAT
# ---------------------------------------------------------------------------


def _read_minifat(
    raw: bytes, fat: list[int], minifat_start: int, sector_size: int
) -> list[int]:
    """Read and reconstruct the mini FAT from its sector chain."""
    mfat: list[int] = []
    for sid in _read_chain(fat, minifat_start):
        off = 512 + sid * sector_size
        mfat.extend(struct.unpack_from(f"<{sector_size // 4}I", raw, off))
    return mfat


def _normalize_mfat(mfat: list[int], entries: list[bytearray], mini_cutoff: int) -> None:
    """mfat에서 실제 사용 중이지 않은 항목을 FREESECT로 정규화한다.

    일부 HWP 파일은 unused miniFAT 슬롯에 0 대신 FREESECT를 쓰지 않아
    'mini sector 0 pointed to twice' 오류가 발생한다. 이를 방지하기 위해
    모든 스트림의 체인을 순회해 사용 중인 미니섹터를 파악하고 나머지를 FREESECT로 설정.
    """
    used: set[int] = set()
    for entry in entries:
        typ = entry[66]
        sz = struct.unpack_from("<I", entry, 120)[0]
        st = struct.unpack_from("<I", entry, 116)[0]
        if typ == 2 and 0 < sz < mini_cutoff and st < _ENDOFCHAIN:
            curr = st
            visited: set[int] = set()
            while curr < _ENDOFCHAIN and curr < len(mfat) and curr not in visited:
                visited.add(curr)
                used.add(curr)
                curr = mfat[curr]
    for i in range(len(mfat)):
        if i not in used and mfat[i] != _FREESECT:
            mfat[i] = _FREESECT


def _mini_offset(
    mini_sid: int, root_chain: list[int], sector_size: int, mini_sector_size: int
) -> int:
    """Calculate byte offset of a mini sector within the raw file."""
    mspb = sector_size // mini_sector_size
    return (
        512
        + root_chain[mini_sid // mspb] * sector_size
        + (mini_sid % mspb) * mini_sector_size
    )


# ---------------------------------------------------------------------------
# FAT 쓰기 헬퍼
# ---------------------------------------------------------------------------


def _alloc_sector(raw: bytearray, fat: list[int], sector_size: int = 512) -> int:
    """파일 끝에 새 섹터를 추가하고 인덱스 반환. 반드시 이 함수로만 섹터 확보 (함정 8)."""
    new_sid = (len(raw) - 512) // sector_size
    raw += b"\x00" * sector_size
    fat.append(_FREESECT)
    return new_sid


def _write_minifat(
    raw: bytearray,
    fat: list[int],
    minifat_start: int,
    mfat: list[int],
    sector_size: int,
) -> None:
    """Write the mini FAT back to its sector chain."""
    count = sector_size // 4
    needed = max(1, -(-len(mfat) // count))
    current_chain = _read_chain(fat, minifat_start)
    while len(current_chain) < needed:
        new_sid = _alloc_sector(raw, fat)
        fat[current_chain[-1]] = new_sid
        fat[new_sid] = _ENDOFCHAIN
        current_chain.append(new_sid)
        n_mf = struct.unpack_from("<I", raw, 64)[0]
        struct.pack_into("<I", raw, 64, n_mf + 1)
    for chunk_i, sid in enumerate(current_chain):
        off = 512 + sid * sector_size
        for j in range(count):
            fidx = chunk_i * count + j
            val = mfat[fidx] if fidx < len(mfat) else _FREESECT
            struct.pack_into("<I", raw, off + j * 4, val)


def _write_fat(raw: bytearray, fat: list[int], sector_size: int) -> None:
    """Write the FAT back to all FAT sectors in the raw file.

    Reads existing FAT sector IDs from both the header DIFAT (109 slots)
    and any DIFAT extension sectors, so large files (>~7MB) are handled.
    """
    n_fat_existing = struct.unpack_from("<I", raw, 44)[0]
    difat_start = struct.unpack_from("<I", raw, 68)[0]

    fat_sids: list[int] = []
    for i in range(min(109, n_fat_existing)):
        sid = struct.unpack_from("<I", raw, 76 + i * 4)[0]
        if sid >= _DIFSECT:
            break
        fat_sids.append(sid)

    difat_chain: list[int] = []
    curr = difat_start
    while curr < _DIFSECT and len(fat_sids) < n_fat_existing:
        difat_chain.append(curr)
        off = 512 + curr * sector_size
        for j in range((sector_size // 4) - 1):
            sid = struct.unpack_from("<I", raw, off + j * 4)[0]
            if sid >= _DIFSECT:
                break
            fat_sids.append(sid)
        curr = struct.unpack_from("<I", raw, off + sector_size - 4)[0]

    count = sector_size // 4
    needed = max(1, -(-len(fat) // count))
    while len(fat_sids) < needed:
        needed = max(1, -(-len(fat) // count))
        new_sid = (len(raw) - 512) // sector_size
        raw += b"\x00" * sector_size
        fat.append(_FATSECT)
        fat_sids.append(new_sid)
        n_fat = len(fat_sids)
        struct.pack_into("<I", raw, 44, n_fat)
        if n_fat <= 109:
            struct.pack_into("<I", raw, 76 + (n_fat - 1) * 4, new_sid)
        else:
            difat_slot = n_fat - 110
            slots_per_difat = (sector_size // 4) - 1
            difat_idx = difat_slot // slots_per_difat
            slot_in_page = difat_slot % slots_per_difat
            while len(difat_chain) <= difat_idx:
                ds = (len(raw) - 512) // sector_size
                raw += b"\xff" * sector_size
                fat.append(_DIFSECT)
                if difat_chain:
                    prev_off = 512 + difat_chain[-1] * sector_size
                    struct.pack_into("<I", raw, prev_off + sector_size - 4, ds)
                else:
                    struct.pack_into("<I", raw, 68, ds)
                difat_chain.append(ds)
                ds_off = 512 + ds * sector_size
                struct.pack_into("<I", raw, ds_off + sector_size - 4, _ENDOFCHAIN)
                n_difat = struct.unpack_from("<I", raw, 72)[0]
                struct.pack_into("<I", raw, 72, n_difat + 1)
            ds_off = 512 + difat_chain[difat_idx] * sector_size
            struct.pack_into("<I", raw, ds_off + slot_in_page * 4, new_sid)

    for chunk_i, sid in enumerate(fat_sids):
        off = 512 + sid * sector_size
        for j in range(count):
            fidx = chunk_i * count + j
            val = fat[fidx] if fidx < len(fat) else _FREESECT
            struct.pack_into("<I", raw, off + j * 4, val)


def _write_dir(
    raw: bytearray,
    fat: list[int],
    entries: list[bytearray],
    dir_start: int,
    sector_size: int,
) -> None:
    """Write directory entries back to the directory sector chain."""
    dir_data = b"".join(bytes(e) for e in entries)
    for chunk_i, sid in enumerate(_read_chain(fat, dir_start)):
        off = 512 + sid * sector_size
        chunk = dir_data[chunk_i * sector_size : (chunk_i + 1) * sector_size]
        raw[off : off + sector_size] = chunk.ljust(sector_size, b"\x00")


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def patch_hwp_stream(
    original_path: str,
    output_path: str,
    stream_path: StreamPath,
    new_content: bytes,
) -> None:
    """Replace a single OLE stream in an HWP file, preserving all others.

    Handles mini-stream, regular-stream, and promotion/demotion between
    them automatically based on the mini-stream cutoff size.

    Parameters
    ----------
    original_path : str
        Path to the source HWP file.
    output_path : str
        Destination path (may be the same as original_path for in-place).
    stream_path : StreamPath
        OLE stream path as a list of strings (e.g. ["BodyText", "Section0"]).
    new_content : bytes
        New stream content (compressed bytes).

    Raises
    ------
    ValueError
        If the specified stream does not exist.
    """
    with open(original_path, "rb") as f:
        raw = bytearray(f.read())

    sector_size = 1 << struct.unpack_from("<H", raw, 30)[0]
    mini_sector_size = 1 << struct.unpack_from("<H", raw, 32)[0]
    mini_cutoff = struct.unpack_from("<I", raw, 56)[0]
    dir_start = struct.unpack_from("<I", raw, 48)[0]
    minifat_start = struct.unpack_from("<I", raw, 60)[0]

    fat = _read_fat(bytes(raw), sector_size)
    entries = _dir_entries(bytes(raw), fat, dir_start, sector_size)

    idx = _find_stream(entries, stream_path)
    if idx is None:
        raise ValueError(f"스트림 없음: {stream_path!r}")

    entry = entries[idx]
    old_start = struct.unpack_from("<I", entry, 116)[0]
    old_size = struct.unpack_from("<I", entry, 120)[0]

    if old_size < mini_cutoff and len(new_content) >= mini_cutoff:
        # mini → regular 승격
        mfat = _read_minifat(bytes(raw), fat, minifat_start, sector_size)
        _normalize_mfat(mfat, entries, mini_cutoff)
        old_mini_chain = _read_chain(mfat, old_start)
        for ms in old_mini_chain:
            if ms < len(mfat):
                mfat[ms] = _FREESECT
        _write_minifat(raw, fat, minifat_start, mfat, sector_size)

        n_new = max(1, -(-len(new_content) // sector_size))
        used: list[int] = []
        for _ in range(n_new):
            used.append(_alloc_sector(raw, fat))
        for i, sid in enumerate(used):
            fat[sid] = used[i + 1] if i < len(used) - 1 else _ENDOFCHAIN
        for i, sid in enumerate(used):
            chunk = new_content[i * sector_size : (i + 1) * sector_size]
            off = 512 + sid * sector_size
            raw[off : off + sector_size] = chunk.ljust(sector_size, b"\x00")
        struct.pack_into("<I", entry, 116, used[0])
        struct.pack_into("<I", entry, 120, len(new_content))

    elif old_size >= mini_cutoff and len(new_content) < mini_cutoff:
        # regular → mini 강등
        old_chain = _read_chain(fat, old_start)
        for sid in old_chain:
            if sid < len(fat):
                fat[sid] = _FREESECT

        mfat = _read_minifat(bytes(raw), fat, minifat_start, sector_size)
        _normalize_mfat(mfat, entries, mini_cutoff)
        root_entry = entries[0]
        root_start = struct.unpack_from("<I", root_entry, 116)[0]
        root_size = struct.unpack_from("<I", root_entry, 120)[0]
        root_chain = _read_chain(fat, root_start)

        n_new = max(1, -(-len(new_content) // mini_sector_size))
        free_ms = [i for i, v in enumerate(mfat) if v == _FREESECT]
        while len(free_ms) < n_new:
            new_ms = len(mfat)
            mfat.append(_FREESECT)
            free_ms.append(new_ms)
            needed_root_sectors = -(
                -((new_ms + 1) * mini_sector_size) // sector_size
            )
            while len(root_chain) < needed_root_sectors:
                new_sid = _alloc_sector(raw, fat)
                fat[root_chain[-1]] = new_sid
                fat[new_sid] = _ENDOFCHAIN
                root_chain.append(new_sid)
            needed_root_size = (new_ms + 1) * mini_sector_size
            if needed_root_size > root_size:
                root_size = needed_root_size
                struct.pack_into("<I", root_entry, 120, root_size)

        used_ms = free_ms[:n_new]
        if used_ms:
            max_used_ms = max(used_ms)
            needed_root_size = (max_used_ms + 1) * mini_sector_size
            if needed_root_size > root_size:
                root_size = needed_root_size
                struct.pack_into("<I", root_entry, 120, root_size)
            needed_root_sectors = -(-needed_root_size // sector_size)
            while len(root_chain) < needed_root_sectors:
                new_sid = _alloc_sector(raw, fat)
                fat[root_chain[-1]] = new_sid
                fat[new_sid] = _ENDOFCHAIN
                root_chain.append(new_sid)

        while len(mfat) <= max(used_ms, default=0):
            mfat.append(_FREESECT)
        for i, ms in enumerate(used_ms):
            mfat[ms] = used_ms[i + 1] if i < len(used_ms) - 1 else _ENDOFCHAIN
        for i, ms in enumerate(used_ms):
            chunk = new_content[i * mini_sector_size : (i + 1) * mini_sector_size]
            off = _mini_offset(ms, root_chain, sector_size, mini_sector_size)
            if off + mini_sector_size > len(raw):
                raw += b"\x00" * (off + mini_sector_size - len(raw))
            raw[off : off + mini_sector_size] = chunk.ljust(
                mini_sector_size, b"\x00"
            )
        struct.pack_into("<I", entry, 116, used_ms[0])
        struct.pack_into("<I", entry, 120, len(new_content))
        _write_minifat(raw, fat, minifat_start, mfat, sector_size)

    elif old_size < mini_cutoff:
        # mini stream
        mfat = _read_minifat(bytes(raw), fat, minifat_start, sector_size)
        _normalize_mfat(mfat, entries, mini_cutoff)
        root_entry = entries[0]
        root_start = struct.unpack_from("<I", root_entry, 116)[0]
        root_size = struct.unpack_from("<I", root_entry, 120)[0]
        root_chain = _read_chain(fat, root_start)

        old_mini_chain = _read_chain(mfat, old_start)
        n_old = len(old_mini_chain)
        n_new = max(1, -(-len(new_content) // mini_sector_size))

        if n_new <= n_old:
            # 줄인 경우: 기존 체인 전체를 유지하고 나머지는 0-패딩.
            # 중간 섹터를 FREESECT로 해제하면 다른 스트림과의 사이에 "홀"이
            # 생겨 한컴이 손상으로 판정하므로 절대 해제하지 않는다.
            used_ms = list(old_mini_chain)
            freed_ms = []
        else:
            used_ms = list(old_mini_chain)
            needed = n_new - n_old
            free_ms = [i for i, v in enumerate(mfat) if v == _FREESECT]
            while len(free_ms) < needed:
                new_ms = len(mfat)
                mfat.append(_FREESECT)
                free_ms.append(new_ms)
                needed_root_sectors = -(
                    -((new_ms + 1) * mini_sector_size) // sector_size
                )
                while len(root_chain) < needed_root_sectors:
                    new_sid = _alloc_sector(raw, fat)
                    fat[root_chain[-1]] = new_sid
                    fat[new_sid] = _ENDOFCHAIN
                    root_chain.append(new_sid)
                needed_root_size = (new_ms + 1) * mini_sector_size
                if needed_root_size > root_size:
                    root_size = needed_root_size
                    struct.pack_into("<I", root_entry, 120, root_size)
            used_ms.extend(free_ms[:needed])
            freed_ms = []
            if used_ms:
                max_used_ms = max(used_ms)
                needed_root_size = (max_used_ms + 1) * mini_sector_size
                if needed_root_size > root_size:
                    root_size = needed_root_size
                    struct.pack_into("<I", root_entry, 120, root_size)
                needed_root_sectors = -(-needed_root_size // sector_size)
                while len(root_chain) < needed_root_sectors:
                    new_sid = _alloc_sector(raw, fat)
                    fat[root_chain[-1]] = new_sid
                    fat[new_sid] = _ENDOFCHAIN
                    root_chain.append(new_sid)

        max_ms = max(max(used_ms, default=0), max(freed_ms, default=0))
        while len(mfat) <= max_ms:
            mfat.append(_FREESECT)
        for i, ms in enumerate(used_ms):
            mfat[ms] = used_ms[i + 1] if i < len(used_ms) - 1 else _ENDOFCHAIN
        for ms in freed_ms:
            mfat[ms] = _FREESECT
        for i, ms in enumerate(used_ms):
            chunk = new_content[i * mini_sector_size : (i + 1) * mini_sector_size]
            off = _mini_offset(ms, root_chain, sector_size, mini_sector_size)
            if off + mini_sector_size > len(raw):
                raw += b"\x00" * (off + mini_sector_size - len(raw))
            raw[off : off + mini_sector_size] = chunk.ljust(mini_sector_size, b"\x00")
        struct.pack_into("<I", entry, 116, used_ms[0])
        struct.pack_into("<I", entry, 120, len(new_content))
        _write_minifat(raw, fat, minifat_start, mfat, sector_size)

    else:
        # regular stream
        old_chain = _read_chain(fat, old_start)
        n_old = len(old_chain)
        n_new = max(1, -(-len(new_content) // sector_size))

        if n_new <= n_old:
            used = old_chain[:n_new]
            freed = old_chain[n_new:]
        else:
            used = list(old_chain)
            needed = n_new - n_old
            free_sids = [i for i, v in enumerate(fat) if v == _FREESECT]
            while len(free_sids) < needed:
                free_sids.append(_alloc_sector(raw, fat))
            used.extend(free_sids[:needed])
            freed = []

        max_sid = max(max(used, default=0), max(freed, default=0))
        while len(fat) <= max_sid:
            fat.append(_FREESECT)
        for i, sid in enumerate(used):
            fat[sid] = used[i + 1] if i < len(used) - 1 else _ENDOFCHAIN
        for sid in freed:
            fat[sid] = _FREESECT
        for i, sid in enumerate(used):
            chunk = new_content[i * sector_size : (i + 1) * sector_size]
            off = 512 + sid * sector_size
            if off + sector_size > len(raw):
                raw += b"\x00" * (off + sector_size - len(raw))
            raw[off : off + sector_size] = chunk.ljust(sector_size, b"\x00")
        struct.pack_into("<I", entry, 116, used[0])
        struct.pack_into("<I", entry, 120, len(new_content))

    _write_fat(raw, fat, sector_size)
    _write_dir(raw, fat, entries, dir_start, sector_size)

    with open(output_path, "wb") as f:
        f.write(raw)


# ---------------------------------------------------------------------------
# 스트림 추가 API
# ---------------------------------------------------------------------------


def _create_dir_entry(name: str, obj_type: int, start: int, size: int) -> bytearray:
    """128-byte OLE 디렉토리 엔트리 생성."""
    entry = bytearray(128)
    name_bytes = name.encode("utf-16-le") + b"\x00\x00"
    entry[0:len(name_bytes)] = name_bytes
    struct.pack_into("<H", entry, 64, len(name_bytes))  # name_size (includes null)
    entry[66] = obj_type  # 1=storage, 2=stream
    entry[67] = 1  # color: black
    struct.pack_into("<I", entry, 68, _NOSTREAM)  # left_sibling
    struct.pack_into("<I", entry, 72, _NOSTREAM)  # right_sibling
    struct.pack_into("<I", entry, 76, _NOSTREAM)  # child (for storages)
    struct.pack_into("<I", entry, 116, start)
    struct.pack_into("<I", entry, 120, size)
    return entry


def _find_or_create_storage(
    entries: list[bytearray], parent_idx: int, name: str
) -> int:
    """parent 하위에 name storage를 찾거나 생성한다."""
    child_id = struct.unpack_from("<I", entries[parent_idx], 76)[0]
    if child_id != _NOSTREAM and child_id < len(entries):
        found = _search_siblings(entries, child_id, name)
        if found is not None:
            return found

    new_idx = len(entries)
    new_entry = _create_dir_entry(name, 1, _ENDOFCHAIN, 0)
    entries.append(new_entry)

    if child_id == _NOSTREAM or child_id >= len(entries) - 1:
        struct.pack_into("<I", entries[parent_idx], 76, new_idx)
    else:
        _insert_sibling(entries, child_id, new_idx)
    return new_idx


def _search_siblings(entries: list[bytearray], root_idx: int, target: str) -> int | None:
    """red-black tree를 순회하여 target name 엔트리를 찾는다."""
    if root_idx == _NOSTREAM or root_idx >= len(entries):
        return None
    entry = entries[root_idx]
    if _entry_name(entry).lower() == target.lower():
        return root_idx
    left = struct.unpack_from("<I", entry, 68)[0]
    right = struct.unpack_from("<I", entry, 72)[0]
    found = _search_siblings(entries, left, target)
    if found is not None:
        return found
    return _search_siblings(entries, right, target)


def _insert_sibling(entries: list[bytearray], root_idx: int, new_idx: int) -> None:
    """새 엔트리를 sibling tree에 삽입 (단순 right-append)."""
    curr = root_idx
    while True:
        right = struct.unpack_from("<I", entries[curr], 72)[0]
        if right == _NOSTREAM or right >= len(entries):
            struct.pack_into("<I", entries[curr], 72, new_idx)
            return
        curr = right


def add_hwp_stream(
    file_path: str,
    stream_path: StreamPath,
    content: bytes,
) -> None:
    """Add a new stream to an OLE2 HWP file.

    Creates intermediate storage entries if they do not exist. If the
    stream already exists, delegates to ``patch_hwp_stream`` instead.

    Parameters
    ----------
    file_path : str
        Path to the HWP file (modified in-place).
    stream_path : StreamPath
        Stream path as a list of strings (e.g. ["BinData", "BIN0001.jpg"]).
    content : bytes
        Raw stream content (uncompressed bytes).
    """
    with open(file_path, "rb") as f:
        raw = bytearray(f.read())

    sector_size = 1 << struct.unpack_from("<H", raw, 30)[0]
    mini_sector_size = 1 << struct.unpack_from("<H", raw, 32)[0]
    mini_cutoff = struct.unpack_from("<I", raw, 56)[0]
    dir_start = struct.unpack_from("<I", raw, 48)[0]
    minifat_start = struct.unpack_from("<I", raw, 60)[0]

    fat = _read_fat(bytes(raw), sector_size)
    entries = _dir_entries(bytes(raw), fat, dir_start, sector_size)

    # 이미 존재하면 patch로 대체
    existing = _find_stream(entries, stream_path)
    if existing is not None:
        with open(file_path, "wb") as f:
            f.write(raw)
        patch_hwp_stream(file_path, file_path, stream_path, content)
        return

    # 중간 storage 확보
    parent_idx = 0  # root
    for part in stream_path[:-1]:
        parent_idx = _find_or_create_storage(entries, parent_idx, part)

    stream_name = stream_path[-1]

    # 새 스트림 데이터 할당
    if len(content) < mini_cutoff:
        # mini stream 할당
        mfat = _read_minifat(bytes(raw), fat, minifat_start, sector_size)
        _normalize_mfat(mfat, entries, mini_cutoff)
        root_entry = entries[0]
        root_start = struct.unpack_from("<I", root_entry, 116)[0]
        root_size = struct.unpack_from("<I", root_entry, 120)[0]
        root_chain = _read_chain(fat, root_start)

        n_mini = max(1, -(-len(content) // mini_sector_size))
        free_ms = [i for i, v in enumerate(mfat) if v == _FREESECT]
        while len(free_ms) < n_mini:
            new_ms = len(mfat)
            mfat.append(_FREESECT)
            free_ms.append(new_ms)
            needed_root_sectors = -(
                -((new_ms + 1) * mini_sector_size) // sector_size
            )
            while len(root_chain) < needed_root_sectors:
                new_sid = _alloc_sector(raw, fat)
                fat[root_chain[-1]] = new_sid
                fat[new_sid] = _ENDOFCHAIN
                root_chain.append(new_sid)
            needed_root_size = (new_ms + 1) * mini_sector_size
            if needed_root_size > root_size:
                root_size = needed_root_size
                struct.pack_into("<I", root_entry, 120, root_size)

        used_ms = free_ms[:n_mini]
        if used_ms:
            max_used_ms = max(used_ms)
            needed_root_size = (max_used_ms + 1) * mini_sector_size
            if needed_root_size > root_size:
                root_size = needed_root_size
                struct.pack_into("<I", root_entry, 120, root_size)
            needed_root_sectors = -(-needed_root_size // sector_size)
            while len(root_chain) < needed_root_sectors:
                new_sid = _alloc_sector(raw, fat)
                fat[root_chain[-1]] = new_sid
                fat[new_sid] = _ENDOFCHAIN
                root_chain.append(new_sid)

        while len(mfat) <= max(used_ms, default=0):
            mfat.append(_FREESECT)
        for i, ms in enumerate(used_ms):
            mfat[ms] = used_ms[i + 1] if i < len(used_ms) - 1 else _ENDOFCHAIN
        for i, ms in enumerate(used_ms):
            chunk = content[i * mini_sector_size : (i + 1) * mini_sector_size]
            off = _mini_offset(ms, root_chain, sector_size, mini_sector_size)
            if off + mini_sector_size > len(raw):
                raw += b"\x00" * (off + mini_sector_size - len(raw))
            raw[off : off + mini_sector_size] = chunk.ljust(mini_sector_size, b"\x00")

        start_sector = used_ms[0]
        _write_minifat(raw, fat, minifat_start, mfat, sector_size)
    else:
        # regular stream 할당
        n_sectors = max(1, -(-len(content) // sector_size))
        used: list[int] = []
        for _ in range(n_sectors):
            used.append(_alloc_sector(raw, fat))
        for i, sid in enumerate(used):
            fat[sid] = used[i + 1] if i < len(used) - 1 else _ENDOFCHAIN
        for i, sid in enumerate(used):
            chunk = content[i * sector_size : (i + 1) * sector_size]
            off = 512 + sid * sector_size
            if off + sector_size > len(raw):
                raw += b"\x00" * (off + sector_size - len(raw))
            raw[off : off + sector_size] = chunk.ljust(sector_size, b"\x00")
        start_sector = used[0]

    # 새 스트림 디렉토리 엔트리 생성
    new_idx = len(entries)
    new_entry = _create_dir_entry(stream_name, 2, start_sector, len(content))
    entries.append(new_entry)

    # parent의 child tree에 삽입
    child_id = struct.unpack_from("<I", entries[parent_idx], 76)[0]
    if child_id == _NOSTREAM or child_id >= len(entries) - 1:
        struct.pack_into("<I", entries[parent_idx], 76, new_idx)
    else:
        _insert_sibling(entries, child_id, new_idx)

    # 디렉토리 섹터 확장 (필요 시)
    dir_data_needed = len(entries) * 128
    dir_chain = _read_chain(fat, dir_start)
    dir_capacity = len(dir_chain) * sector_size
    while dir_data_needed > dir_capacity:
        new_sid = _alloc_sector(raw, fat)
        fat[dir_chain[-1]] = new_sid
        fat[new_sid] = _ENDOFCHAIN
        dir_chain.append(new_sid)
        dir_capacity += sector_size

    _write_fat(raw, fat, sector_size)
    _write_dir(raw, fat, entries, dir_start, sector_size)

    with open(file_path, "wb") as f:
        f.write(raw)
