import struct


def make_packet(seq: int, payload: bytes) -> bytes:
    return struct.pack("<I", len(payload))[:3] + bytes([seq & 0xFF]) + payload


def lenenc(s) -> bytes:
    """Length-encoded string for MySQL result-set row data."""
    if s is None:
        return b'\xfb'
    if isinstance(s, str):
        s = s.encode("utf-8", errors="replace")
    n = len(s)
    if n < 251:
        return bytes([n]) + s
    if n < 65536:
        return b'\xfc' + struct.pack("<H", n) + s
    if n < 16777216:
        return b'\xfd' + struct.pack("<I", n)[:3] + s
    return b'\xfe' + struct.pack("<Q", n) + s


def col_def_packet(seq: int, name: str) -> bytes:
    """MySQL column definition packet (Protocol::ColumnDefinition41)."""
    payload = (
        lenenc("def") +            # catalog
        lenenc("") +               # schema
        lenenc("") +               # table alias
        lenenc("") +               # table
        lenenc(name) +             # name alias
        lenenc(name) +             # org_name
        b'\x0c' +                  # fixed-length fields (always 12)
        struct.pack("<H", 0x21) +  # charset: utf8_general_ci
        struct.pack("<I", 0xFF) +  # column display length
        b'\xfd' +                  # type: VAR_STRING
        struct.pack("<H", 0x00) +  # flags
        b'\x00' +                  # decimals
        b'\x00\x00'                # filler
    )
    return make_packet(seq, payload)


def result_set(seq: int, columns: list, rows: list) -> bytes:
    """Build a complete MySQL text result-set response."""
    pkts = [make_packet(seq, bytes([len(columns)]))]
    seq += 1
    for col in columns:
        pkts.append(col_def_packet(seq, col))
        seq += 1
    pkts.append(make_packet(seq, b'\xfe\x00\x00\x02\x00'))  # EOF
    seq += 1
    for row in rows:
        pkts.append(make_packet(seq, b''.join(lenenc(v) for v in row)))
        seq += 1
    pkts.append(make_packet(seq, b'\xfe\x00\x00\x02\x00'))  # EOF
    return b''.join(pkts)


def ok_packet(seq: int) -> bytes:
    # OK marker, affected=0, insert_id=0, status=AUTO_COMMIT, warnings=0
    return make_packet(seq, b'\x00\x00\x00\x02\x00\x00\x00')
