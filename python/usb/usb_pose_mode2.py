"""EMP2 v1 stream decoder and serial client. Only serial access needs pyserial."""
import math
import struct
import time
import zlib
from collections import Counter, deque

HEADER = struct.Struct('<4sBBHHHIIIQQ')
PREFIX = struct.Struct('<QHBBHH')
ITEM = struct.Struct('<HBBIQIBBH7f')
ACK = struct.Struct('<HHBBHIIHHI')
DIAG_ITEM = struct.Struct('<HBBBBH')
MAX_DECODED = 2048
MAX_ENCODED = 2057


class ProtocolError(ValueError):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


def cobs_encode(data):
    out = bytearray([0]); at = 0; code = 1
    for b in data:
        if b == 0:
            out[at] = code; at = len(out); out.append(0); code = 1
        else:
            out.append(b); code += 1
            if code == 255:
                out[at] = code; at = len(out); out.append(0); code = 1
    out[at] = code
    return bytes(out)


def cobs_decode(data):
    out = bytearray(); i = 0
    while i < len(data):
        code = data[i]; i += 1
        if code == 0 or i + code - 1 > len(data):
            raise ProtocolError('cobs_errors')
        block = data[i:i + code - 1]
        if 0 in block:
            raise ProtocolError('cobs_errors')
        out.extend(block); i += code - 1
        if code != 255 and i < len(data):
            out.append(0)
    return bytes(out)


def parse_frame(data):
    if not 44 <= len(data) <= MAX_DECODED:
        raise ProtocolError('length_errors')
    h = HEADER.unpack_from(data)
    magic, version, kind, flags, size, hsize, seq, boot, stream, snap, submit = h
    if magic != b'EMP2' or version != 1:
        raise ProtocolError('header_errors')
    if hsize != 40 or len(data) != 44 + size:
        raise ProtocolError('length_errors')
    if zlib.crc32(data[:-4]) & 0xffffffff != struct.unpack_from('<I', data, len(data)-4)[0]:
        raise ProtocolError('crc_errors')
    if flags & ~3 or not stream:
        raise ProtocolError('field_errors')
    result = dict(type=kind, flags=flags, sequence=seq, boot_id=boot,
                  stream_id=stream, snapshot_mono_us=snap, submit_mono_us=submit)
    p = memoryview(data)[40:-4]
    if kind == 0x80:
        if size != ACK.size:
            raise ProtocolError('length_errors')
        keys = ('command', 'result', 'current_usb_mode', 'protocol_version',
                'nominal_rate_hz', 'capabilities', 'stale_threshold_us',
                'max_pose_count', 'max_decoded_frame_size', 'fixed')
        result['ack'] = dict(zip(keys, ACK.unpack(p)))
        a = result['ack']
        if a['protocol_version'] != 1 or a['fixed'] or a['max_pose_count'] > 38 or a['current_usb_mode'] > 2:
            raise ProtocolError('field_errors')
    elif kind == 1:
        if size < PREFIX.size:
            raise ProtocolError('length_errors')
        utc, frame_id, coord, profile, count, entry = PREFIX.unpack_from(p)
        if entry != 52 or count > 38 or size != 16 + count * entry:
            raise ProtocolError('length_errors')
        if coord > 1 or profile > 2 or bool(flags & 1) != bool(utc):
            raise ProtocolError('field_errors')
        result.update(snapshot_utc_ns=utc, frame_id=frame_id,
                      coordinate_frame=coord, output_profile=profile, poses=[])
        last_id = -1
        for i in range(count):
            v = ITEM.unpack_from(p, 16 + 52*i)
            sid, state, sf, measurement, rx, age, rf, source, source_id = v[:9]
            if sid <= last_id or state & ~3 or sf & ~15 or source > 3:
                raise ProtocolError('field_errors')
            last_id = sid
            if not all(math.isfinite(x) for x in v[9:]):
                raise ProtocolError('numeric_errors')
            if state & 2 and abs(sum(x*x for x in v[12:16])-1) > 0.001:
                raise ProtocolError('numeric_errors')
            if sf & 2 and state:
                raise ProtocolError('field_errors')
            if not sf & 1 and (measurement or rx or rf or age != 0xffffffff or sf & 4):
                raise ProtocolError('field_errors')
            result['poses'].append(dict(sensor_id=sid, tracking_state=state,
                sample_flags=sf, measurement_sequence=measurement, rx_mono_us=rx,
                data_age_us=age, rf_sequence=rf, source_kind=source, source_id=source_id,
                position=list(v[9:12]), quaternion_xyzw=list(v[12:16])))
    elif kind == 0x82:
        if size % DIAG_ITEM.size:
            raise ProtocolError('length_errors')
        result['diagnostics'] = []
        last_id = -1
        for off in range(0, size, DIAG_ITEM.size):
            sid, df, quality, battery, rf, reserved = DIAG_ITEM.unpack_from(p, off)
            if sid <= last_id or df & ~7 or quality > 3 or reserved:
                raise ProtocolError('field_errors')
            if not df & 2 and quality:
                raise ProtocolError('field_errors')
            if not df & 1 and battery != 0xFF:
                raise ProtocolError('field_errors')
            if df & 1 and battery > 100:
                raise ProtocolError('field_errors')
            if battery != 0xFF and battery > 100:
                raise ProtocolError('field_errors')
            last_id = sid
            result['diagnostics'].append(dict(sensor_id=sid, diagnostic_flags=df,
                field_quality=quality, battery_percent=battery, rf_sequence=rf))
    return result


class StreamDecoder:
    """Bounded framing; discard only the bad segment, never the following frame."""
    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False
        self.stats = Counter()

    def feed(self, data):
        frames = []
        self.stats['bytes'] += len(data)
        for b in data:
            if b == 0:
                if self.discarding:
                    self.discarding = False; self.buffer.clear(); continue
                if not self.buffer:
                    self.stats['empty_segments'] += 1; continue
                segment = bytes(self.buffer); self.buffer.clear()
                try:
                    frame = parse_frame(cobs_decode(segment))
                except ProtocolError as exc:
                    self.stats[exc.kind] += 1
                else:
                    self.stats['valid_frames'] += 1
                    frames.append(frame)
            elif not self.discarding:
                self.buffer.append(b)
                if len(self.buffer) > MAX_ENCODED:
                    self.stats['oversize_errors'] += 1
                    self.buffer.clear(); self.discarding = True
        return frames


class SerialClient:
    def __init__(self, port, baudrate=115200):
        import serial
        # Set control-line states BEFORE open: ESP USB Serial/JTAG uses RTS/DTR
        # for reset/download control. Opening with pyserial's asserted defaults
        # can cause unwanted transitions. OS/driver open glitches remain possible.
        self.serial = serial.Serial(port=None, baudrate=baudrate, timeout=0.1,
                                    write_timeout=2, rtscts=False, dsrdtr=False)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        self.decoder = StreamDecoder()
        self.pending = deque()
        self.raw_tail = bytearray()
        self.entry_ack = None
        self.entry_raw_tail = b''
        self.last_command_diagnostic = {}
        self.diagnostics = {}
        self.unmatched_diagnostics = 0

    def poll(self):
        if self.pending:
            return self.pending.popleft()
        deadline = time.monotonic() + 0.25
        while True:
            data = self.serial.read(min(max(self.serial.in_waiting, 1), 8192))
            self.raw_tail.extend(data)
            if len(self.raw_tail) > 65536:
                del self.raw_tail[:-65536]
            now = time.monotonic()
            for frame in self.decoder.feed(data):
                if frame["type"] == 0x82:
                    self.diagnostics[(frame["stream_id"], frame["sequence"])] = frame["diagnostics"]
                else:
                    self.pending.append((now, frame))
            while self.pending:
                stamp, frame = self.pending.popleft()
                if frame["type"] == 0x01:
                    key = (frame["stream_id"], frame["sequence"])
                    diag = self.diagnostics.pop(key, None)
                    if diag is None and time.monotonic() < deadline:
                        self.pending.appendleft((stamp, frame))
                        break
                    if diag is None:
                        self.unmatched_diagnostics += 1
                    else:
                        by_id = {x["sensor_id"]: x for x in diag}
                        for pose in frame["poses"]:
                            item = by_id.get(pose["sensor_id"])
                            if item is not None:
                                pose["field_quality"] = item["field_quality"]
                                pose["battery_percent"] = item["battery_percent"]
                                pose["diagnostic_flags"] = item["diagnostic_flags"]
                return stamp, frame
            if time.monotonic() >= deadline:
                return None

    def command(self, text, command_id, timeout=3, retry_interval=None):
        if retry_interval is not None and (command_id != 1 or text != 'mode wired2' or retry_interval <= 0):
            raise ValueError('Automatic retry is supported only for idempotent mode wired2 entry')
        self.last_command_diagnostic = {}
        # Terminate any abandoned partial CLI line from an interrupted client.
        # Empty lines are harmless, including while already in wired2.
        request = ('\n' + text + '\n').encode('ascii')
        self.serial.write(request)
        before = dict(self.decoder.stats)
        pose_frames = 0; ack_commands = []; transmissions = 1
        start = time.monotonic(); end = start + timeout
        next_retry = start + retry_interval if retry_interval is not None else None
        while time.monotonic() < end:
            if next_retry is not None and time.monotonic() >= next_retry:
                self.serial.write(request); transmissions += 1
                next_retry = time.monotonic() + retry_interval
            received = self.poll()
            if received and received[1]['type'] == 1:
                pose_frames += 1
            if received and received[1]['type'] == 0x80:
                a = received[1]['ack']
                ack_commands.append(a['command']); ack_commands = ack_commands[-16:]
                if a['command'] == command_id:
                    if a['result'] != 0:
                        raise RuntimeError('Command rejected: %r' % a)
                    if command_id == 1 and a['current_usb_mode'] != 2:
                        raise RuntimeError('Entry ACK did not enable wired2')
                    self.last_command_diagnostic = dict(command=text,command_id=command_id,
                                                       transmissions=transmissions,ack_received=True)
                    return received[1]
        delta = {k: v-before.get(k,0) for k,v in self.decoder.stats.items()
                 if v != before.get(k,0)}
        self.last_command_diagnostic = dict(command=text,command_id=command_id,
                                           transmissions=transmissions,ack_received=False,
                                           pose_frames=pose_frames,ack_commands=ack_commands,
                                           decoder_delta=delta)
        raise TimeoutError('No valid ACK for %s; rx_bytes=%d, pose_frames=%d, ACK commands=%r, decoder=%r' %
                           (text,delta.get('bytes',0),pose_frames,ack_commands,delta))

    def enter(self, timeout=10):
        try:
            # Early commands may arrive before boot initializes the USB CLI.
            # Entry is idempotent even if already active: retry without resetting.
            self.entry_ack = self.command('mode wired2', 1, timeout=timeout, retry_interval=1)
        finally:
            # Preserve entry evidence even when no ACK is received.
            self.entry_raw_tail = bytes(self.raw_tail)
        # Startup ASCII/old logs are expected before entry ACK, not link failures.
        self.decoder.stats.clear()
        self.raw_tail.clear()
        return self.entry_ack

    def close(self):
        try:
            if self.entry_ack:
                self.command('mode log', 2, timeout=1)
        finally:
            self.serial.close()
