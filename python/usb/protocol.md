# USB Mode 2 Binary Protocol (EMP2 v1)

English | [简体中文](protocol_zh.md)

## 1. Connection and mode switching

Connect to the base station ESP32 USB Serial/JTAG port, not a Tracker or coil MCU serial port.
The host serial API may use 115200; this is not the actual USB transfer rate. One application must exclusively own the port.

Send ASCII commands terminated by LF or CRLF:

| Command | Purpose |
|---|---|
| `mode wired2` | Enter Mode 2, nominally 100 Hz; wait for a successful binary ACK |
| `mode wired2 status` | Query the current mode and parameters; returns a binary ACK |
| `mode log` | Exit data mode; text logging resumes after the exit ACK |
| `mode wired` | Legacy JustFloat protocol, not Mode 2; this parser does not support it |

Reboot returns the device to log mode. Mode selection is not persisted to Flash.
Repeated entry while Mode 2 is already active returns its current state without resetting the session.
Ignore residual text until a complete, CRC-valid success ACK arrives. The protocol entry check reports failure if no success ACK arrives within 2 seconds; do not interpret the legacy protocol as Mode 2.
The exit ACK is the session's last Mode 2 frame.
Mode 2 must not echo text; leave data mode before issuing configuration commands.
Send only one control command at a time and wait for its ACK before sending the next.

## 2. Framing and COBS

```text
Wire frame = COBS(40-byte header + payload + 4-byte CRC32) + 00
```

Use standard COBS, not COBS/R. **Only the encoded COBS segment excludes 00. The original header, poses, and CRC may contain zero bytes.**
COBS restores original zeros during decoding; it does not restrict numeric values or discard zeros.

COBS-only example:

```text
Original: 11 00 22 00
Encoded:  02 11 02 22 01
Wire:     02 11 02 22 01 00
```

The final 00 is a delimiter, not part of the encoded segment.
Encode the entire frame, not each field separately.

### 2.1 Encoding and decoding rules

- Encoding: split original data into nonzero runs; prefix each with a code C = nonzero-byte count + 1. Do not copy original zeros into the encoded segment. Empty runs use code 01, so consecutive zeros are represented losslessly.
- A run contains at most 254 nonzero bytes. Code FF introduces such a run; an FF run does not imply an original zero after it.
- Decoding: read C and copy the next C−1 bytes. If C < 255 and more encoded data remains, append an original zero, then read the next code. Do not append an extra zero at the end.
- Code 00 is invalid. A run must not extend beyond the encoded segment. After encoding, append a separate 00 frame delimiter.

For example, original `00 00 00` encodes as `01 01 01 01`, or `01 01 01 01 00` on the wire.
**Codes delimit COBS runs inside a frame; only wire 00 delimits frames.**

### 2.2 Error handling and resynchronization

Serial is a byte stream: one read can return part of a frame or multiple frames.
Split at 00, COBS-decode each nonempty segment, then validate the header, length, CRC, and payload.
Discard invalid segments and continue with the next.
After consuming the terminating 00 of a bad segment, start collecting immediately after that delimiter:
**do not skip another delimiter or an additional frame.**
If a delimiter is lost/corrupted, adjacent frames can merge and be discarded.
Resume framing at a subsequent intact delimiter and validate the next candidate.
Maximum decoded frame size is 2048 bytes; maximum encoded segment size is 2057 bytes.
If an unterminated segment exceeds the bound, discard until the next 00 to prevent unbounded buffering.

All offsets below refer to decoded bytes, not wire offsets.
Multibyte integers and IEEE-754 float32 values are little-endian; no struct padding is allowed.

### 2.3 Pose and ACK structure

Both messages use the same outer framing: COBS-encode the complete decoded frame, then append 00.

```text
Decoded pose frame:
  Common header: 40 bytes, message_type=01
  Pose prefix:   16 bytes (UTC, frame_id, coordinate/profile, count, entry size)
  Device entries: 52 bytes each; none when n=0
  CRC32:          4 bytes
  Total: 60+52*n bytes; payload_length=16+52*n

Decoded command ACK:
  Common header: 40 bytes, message_type=80
  ACK payload:   24 bytes (command, result, mode, rate, capabilities, limits)
  CRC32:          4 bytes
  Total: 68 bytes; payload_length=24

Wire: COBS(complete frame above) + 00
```

See Section 3 for the common header, Section 5 for poses, and Section 6 for ACKs.
CRC covers the common header and all payload bytes.

## 3. Common header (40 bytes)

| Offset | Type | Field | Description |
|---:|---|---|---|
| 0 | bytes[4] | magic | `EMP2`: 45 4D 50 32 |
| 4 | uint8 | version | 1 |
| 5 | uint8 | message_type | 01 pose; 80 command ACK |
| 6 | uint16 | flags | Bit 0: payload UTC synchronized/valid; bit 1: pending snapshots discarded since the last successful submission; other bits zero |
| 8 | uint16 | payload_length | Payload bytes, excluding header and CRC |
| 10 | uint16 | header_length | 40 |
| 12 | uint32 | stream_sequence | Shared increasing sequence for all session frames, modulo 2³² |
| 16 | uint32 | boot_id | Base station boot identity |
| 20 | uint32 | stream_id | Nonzero Mode 2 session identity |
| 24 | uint64 | snapshot_mono_us | Monotonic microseconds since boot when the snapshot was created |
| 32 | uint64 | submit_mono_us | Monotonic microseconds immediately before submitting the complete frame; not PC arrival time |

Total decoded length must equal `40 + payload_length + 4`.
For a newly created session, the successful entry ACK has sequence 0; subsequent frames increment it.
Re-entering an already active Mode 2 returns a success ACK in the existing session, using its current sequence; it need not be 0.
Dropped pending frames can produce sequence gaps, so gaps alone do not establish physical USB loss.
Reset time/sequence baselines when boot_id changes; reset session sequence baselines when stream_id changes.
Within a boot, monotonic time is unaffected by NTP adjustments. Submission must not precede the snapshot.

## 4. CRC32

CRC-32/ISO-HDLC covers the complete decoded header and payload, excluding CRC bytes, COBS encoding, and delimiter.
poly=0x04C11DB7; reflected implementation poly=0xEDB88320; init=0xFFFFFFFF;
refin/refout=true; xorout=0xFFFFFFFF.
Append the uint32 result little-endian.
The CRC of `123456789` is 0xCBF43926, matching Python `zlib.crc32`.
CRC detects errors; it does not authenticate the sender.

## 5. Pose message (type=01)

### 5.1 Payload prefix (16 bytes)

| Payload offset | Type | Field | Description |
|---:|---|---|---|
| 0 | uint64 | snapshot_utc_ns | Snapshot Unix UTC nanoseconds; zero before synchronization, with header flags bit 0 cleared |
| 8 | uint16 | frame_id | Same as UDP under the same configuration; may be 0; not an incrementing sequence |
| 10 | uint8 | coordinate_frame | 0 non-VR base-reported coordinates; 1 VR-aligned output coordinates |
| 11 | uint8 | output_profile | 0 NON_VR; 1 VR; 2 RAW |
| 12 | uint16 | pose_count | Number of device entries; 0 allowed |
| 14 | uint16 | entry_size | 52 |

`payload_length = 16 + 52 * pose_count`.
IDs are sorted ascending and cannot repeat within a frame.
Associate devices by sensor_id, not entry index.
Count must not exceed the ACK's max_pose_count; the protocol size limit permits at most 38 entries.

### 5.2 Device entry (52 bytes)

| Entry offset | Type | Field | Description |
|---:|---|---|---|
| 0 | uint16 | sensor_id | Same output ID as UDP under the same configuration |
| 2 | uint8 | tracking_state | Bit 0 position valid; bit 1 orientation valid; other bits zero |
| 3 | uint8 | sample_flags | See below |
| 4 | uint32 | measurement_sequence | Base station's count of newly recognized RF WORLD_POSE receptions |
| 8 | uint64 | rx_mono_us | Monotonic RF reception time for this pose, in microseconds |
| 16 | uint32 | data_age_us | submit−rx; unknown=0xFFFFFFFF; overflow saturates at 0xFFFFFFFE |
| 20 | uint8 | rf_sequence | Wrapping 8-bit RF packet sequence |
| 21 | uint8 | source_kind | 0 RF Tracker; 1 external input; 2 derived pose; 3 static reference |
| 22 | uint16 | source_id | Physical RF Tracker ID; unknown for other sources=0xFFFF |
| 24 | float32[3] | position_xyz | XYZ, meters |
| 36 | float32[4] | quaternion_xyzw | Normalized quaternion, XYZW |

| sample_flags bit | Name | Description |
|---:|---|---|
| 0 | SOURCE_META_VALID | RF reception sequence, time, age, and rf_sequence are available |
| 1 | STALE | Age exceeds the ACK threshold or source is offline; tracking_state cleared |
| 2 | NEW_SOURCE_SAMPLE | Source sequence changed since the previous successfully submitted entry in this session; set for the first valid RF sample |
| 3 | SOURCE_LINK_ONLINE | Source link online; does not guarantee freshness or tracking correctness |

Other sample_flags bits are zero.
For external/derived sources without RF metadata, SOURCE_META_VALID and NEW_SOURCE_SAMPLE are cleared;
measurement_sequence, rx_mono_us, and rf_sequence are zero, and age is unknown.
Unknown age must not be interpreted as zero.

### 5.3 Pose processing and validity

The same configuration-dependent processing is used for UDP and USB: ID mapping, quaternion normalization, low-pass filtering, center offset, and VR coordinate conversion.
These are solved poses, not ADC samples. The RAW profile name does not mean Tracker fusion is disabled.
Do not apply the device center offset a second time.
The current default convention is `P_center=P_coil-R(q)*offset`, with offset `(-0.0125,-0.0075,-0.0029)` meters.

Positions must be finite. Valid quaternions must be finite and normalized; q and −q represent the same rotation.
Invalid numeric values clear the corresponding tracking_state bits; placeholders are position zero and quaternion `[0,0,0,1]`, not valid zero poses.
STALE entries may retain the last finite pose for diagnostics, but tracking_state is cleared and they must not be used as current measurements.

RF devices previously seen and applicable to the current profile retain STALE/invalid entries after going offline; unseen devices are not fabricated.
Frames with pose_count=0 provide a heartbeat when there are no devices.
The protocol does not assume three Trackers or invent default entries to pad packets.
VR device IDs do not necessarily represent independent RF Trackers; inspect source_kind/source_id.

## 6. ACK message (type=80, 24-byte payload)

ACKs use the common header and CRC and **have a 24-byte payload**:

```text
Decoded: 40-byte common header (message_type=80, payload_length=24)
         + 24-byte ACK payload + 4-byte CRC32 = 68 bytes
Wire:    COBS(those 68 bytes) + 00 = 70 bytes
```

ACK payload fields describe the command, result, and current parameters.
An ACK is a separate message, not an extra marker attached to a header.
It acknowledges mode-control commands, not reception of individual pose frames.

| Payload offset | Type | Field | Description |
|---:|---|---|---|
| 0 | uint16 | command | 1 enter; 2 exit; 3 status query; 0 unknown command |
| 2 | uint16 | result | 0 success; 1 unsupported; 2 invalid arguments; 3 busy; 4 internal error |
| 4 | uint8 | current_usb_mode | 0 log; 1 legacy wired; 2 wired2; exit ACK reports 0 |
| 5 | uint8 | protocol_version | 1 |
| 6 | uint16 | nominal_rate_hz | Default 100; not a guarantee of exact 10 ms intervals |
| 8 | uint32 | capabilities | Bit 0 poses; bit 1 RF freshness; bit 2 UTC capability; other bits zero |
| 12 | uint32 | stale_threshold_us | Default 500000 microseconds (500 ms) |
| 16 | uint16 | max_pose_count | Maximum entries supported by firmware, not number currently online |
| 18 | uint16 | max_decoded_frame_size | 2048 |
| 20 | uint32 | Fixed field | 0 |

UTC capability does not mean UTC is currently synchronized.
The exit ACK retains the session's boot_id/stream_id.
Report non-success ACKs as errors rather than treating subsequent data as valid tracking.

## 7. Identifying old poses and clock changes

### 7.1 Per-device freshness and sources

| Field/flag | Meaning |
|---|---|
| measurement_sequence | Increments for newly recognized RF poses at the base, not Tracker solver iterations |
| rx_mono_us | Monotonic time when the base received this RF pose |
| data_age_us | Submission time minus reception time: base cache age in microseconds |
| NEW_SOURCE_SAMPLE | A new RF sample is available compared with the previous successful output |
| STALE | Cache age expired or source offline; pose invalid; default age threshold 500 ms |
| SOURCE_LINK_ONLINE | Source link online; does not guarantee freshness or accuracy |
| SOURCE_META_VALID | Whether RF reception times/sequences are available |
| source_kind | RF Tracker, external input, derived pose, or static reference |
| source_id | Physical Tracker ID, possibly different from reported sensor_id |

A repeated sample need not be stale; unchanged stationary coordinates need not mean a repeated sample.
Age excludes Tracker computation, waiting before RF transmission, and host reception latency.
VR-derived poses also depend on the waist Tracker; expiration of a dependency can invalidate the pose.
Age and measurement sequence still describe the RF source identified by source_id.

### 7.2 Monotonic and absolute time

Both clocks exist in separate fields:

- snapshot_mono_us, submit_mono_us, rx_mono_us: monotonic microseconds since the base boot, for intervals, delays, and age. Restart baselines after reboot using boot_id.
- snapshot_utc_ns: absolute Unix UTC nanoseconds, for alignment with external devices/logs. Before the first successful NTP synchronization it is zero and header flags bit 0 is cleared; when valid, bit 0 is set.

Wi-Fi configuration alone does not establish valid UTC.
Without Wi-Fi or successful initial NTP synchronization, monotonic time still works; uptime is never substituted for UTC.
After successful synchronization, the system clock can continue during temporary network loss.
A later failed synchronization does not immediately invalidate UTC; the validity flag does not guarantee a fixed accuracy bound.
Further NTP corrections may adjust UTC; always use monotonic time for interval statistics and timeouts.

### 7.3 Diagnostic examples

- Increasing frame sequence, unchanged measurement_sequence, increasing age: cached pose output.
- Increasing snapshot-to-submit delay: base queue/processing delay, not complete USB latency.
- UTC jumps but monotonic time is normal: clock correction; use monotonic time for periodic statistics.
- Continuous frames with STALE set: expired source data; an entirely stopped stream is a separate failure.
- Identical coordinates do not prove a stall; a stationary device may report the same coordinates.
  An increasing RF reception counter does not prove the Tracker recomputed a solution.

measurement_sequence counts base receptions, not solver iterations.
The raw 8-bit RF sequence is diagnostic only.
The default 500 ms stale decision is independent of HTTP polling, Wi-Fi, and NTP.
Do not indefinitely repeat an offline source as a valid old pose.
The protocol does not retransmit historical poses; bounded queues prioritize the latest snapshot when the host is slow.
The host must enforce its own stream timeout rather than use the last valid pose forever.

## 8. Entry counts and lengths

Decoded length is `60 + 52*n`, where n=pose_count.
For 0–3 entries the decoded frame is shorter than 254 bytes; standard COBS adds one byte and the delimiter adds another:

| Entries | Decoded bytes, including CRC | Wire bytes, including COBS and 00 |
|---:|---:|---:|
| 0 | 60 | 62 |
| 1 | 112 | 114 |
| 2 | 164 | 166 |
| 3 | 216 | 218 |

Fewer than three entries makes a shorter frame; no padding is added.
Retained STALE entries still count toward n, so two online devices do not necessarily mean two entries.
For larger frames, COBS overhead depends on nonzero-run lengths. Do not frame the stream using a fixed wire byte count.

## 9. Parsing reference

```python
import struct, zlib
HEADER = struct.Struct('<4sBBHHHIIIQQ')  # 40 bytes
PREFIX = struct.Struct('<QHBBHH')       # 16 bytes
ITEM = struct.Struct('<HBBIQIBBH7f')    # 52 bytes

# Split at wire 00 and apply standard COBS decoding to obtain decoded:
assert len(decoded) >= 44
assert decoded[:4] == b'EMP2' and decoded[4] == 1
payload_len = struct.unpack_from('<H', decoded, 8)[0]
header_len = struct.unpack_from('<H', decoded, 10)[0]
assert header_len == 40 and len(decoded) == 40 + payload_len + 4
expected_crc = struct.unpack_from('<I', decoded, len(decoded)-4)[0]
assert zlib.crc32(decoded[:-4]) & 0xffffffff == expected_crc
# Then validate payload size, count, IDs, flags, and finite numbers by message type.
```

This illustrates the format only. Production receivers should discard bad frames, not terminate the receive task on an assertion failure.
After validation, unknown message types may be skipped; do not interpret unknown major versions.
Discard frames that violate field constraints.

## 10. Relationship to UDP pose output

This compares UDP poses (type=1) and timing diagnostics (type=3) with EMP2.
Their binary layouts differ and must not share a single frame parser.

| Content | UDP | USB Mode 2 (EMP2) |
|---|---|---|
| Core pose | sensor_id, tracking_state, XYZ position, XYZW quaternion | Same core semantics, ID mapping, units, coordinates, and processing under identical configuration |
| Device entry | 32 bytes in pose messages | 52 bytes, adding source/freshness metadata |
| Framing/integrity | Datagram boundary; no extra application CRC32 | COBS + 00; CRC32 |
| Common header | 18 bytes | 40 bytes, with payload length, session, and monotonic time |
| Output sequence | 16-bit; pose and associated diagnostics share a sequence | 32-bit, shared by session poses and ACKs |
| UTC/frame_id | Pose header; frame_id may be 0 | Pose prefix, plus explicit UTC-valid flag; frame_id is still not an incrementing sequence |
| Boot/session identity | Diagnostics include boot_id | Every frame includes boot_id and stream_id |
| Monotonic/RF reception metadata | Separate type=3 datagram, correlated with the pose | Header and device entries, no separate-message correlation |
| Age/status | Can derive age from diagnostics | data_age_us, STALE, NEW_SOURCE_SAMPLE, source link and source ID provided directly |
| Command response | Pose datagrams are not control responses | Separate type=80 ACK with a 24-byte payload |

Mode 2 is not simply a UDP packet wrapped in COBS: it preserves core pose semantics while adding stream framing, session identity, and per-device freshness.
