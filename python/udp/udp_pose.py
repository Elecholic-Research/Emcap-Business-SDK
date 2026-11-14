from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import List, Tuple

UDP_POSE_MAGIC = b"EM"
UDP_POSE_PORT = 9003
UDP_MSG_TYPE_POSE = 1
UDP_MSG_TYPE_TIMING = 3
_HEADER_STRUCT = struct.Struct("<2sBBHQHH")
_ITEM_STRUCT = struct.Struct("<HBB3f4f")
_TIMING_PREFIX_STRUCT = struct.Struct("<IQQQQ")
_TIMING_ITEM_STRUCT = struct.Struct("<HH IQBBB5B".replace(" ", ""))


@dataclass
class PosePacketHeader:
    magic: bytes
    version: int
    msg_type: int
    seq: int
    timestamp_ns: int
    frame_id: int
    pose_count: int


@dataclass
class PoseItem:
    sensor_id: int
    tracking_state: int
    position: Tuple[float, float, float]
    quaternion: Tuple[float, float, float, float]

    @property
    def position_valid(self) -> bool:
        return bool(self.tracking_state & 0x01)

    @property
    def orientation_valid(self) -> bool:
        return bool(self.tracking_state & 0x02)


# Numeric values are the protocol values. Add new values only at the end.
FIELD_QUALITY_UNKNOWN = 0
FIELD_QUALITY_GREEN = 1
FIELD_QUALITY_YELLOW = 2
FIELD_QUALITY_RED = 3
FIELD_QUALITY_NAMES = {
    FIELD_QUALITY_UNKNOWN: "unknown",
    FIELD_QUALITY_GREEN: "green",
    FIELD_QUALITY_YELLOW: "yellow",
    FIELD_QUALITY_RED: "red",
}


@dataclass
class TimingPacketV1:
    header: PosePacketHeader
    boot_id: int
    enqueue_mono_us: int
    pose_send_mono_us: int
    pose_send_wall_ns: int
    diagnostic_mono_us: int
    items: List["TimingItemV1"]


@dataclass
class TimingItemV1:
    sensor_id: int
    flags: int
    measurement_seq: int
    pose_rx_mono_us: int
    rf_seq: int
    field_quality: int
    battery_percent: int

    @property
    def rf_timestamp_valid(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def battery_valid(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def field_quality_valid(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def field_quality_name(self) -> str:
        if not self.field_quality_valid:
            return "unknown"
        return FIELD_QUALITY_NAMES.get(self.field_quality, "unknown")

    @property
    def battery_percent_or_none(self) -> int | None:
        if not self.battery_valid or self.battery_percent == 0xFF:
            return None
        return self.battery_percent


def expected_packet_size(pose_count: int) -> int:
    return _HEADER_STRUCT.size + _ITEM_STRUCT.size * pose_count


def expected_timing_packet_size(item_count: int) -> int:
    return _HEADER_STRUCT.size + _TIMING_PREFIX_STRUCT.size + _TIMING_ITEM_STRUCT.size * item_count


def parse_packet_header(data: bytes) -> PosePacketHeader:
    if len(data) < _HEADER_STRUCT.size:
        raise ValueError("packet too short for header")
    magic, version, msg_type, seq, timestamp_ns, frame_id, item_count = _HEADER_STRUCT.unpack_from(data, 0)
    if magic != UDP_POSE_MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    if version != 1:
        raise ValueError(f"unsupported version: {version}")
    return PosePacketHeader(magic, version, msg_type, seq, timestamp_ns, frame_id, item_count)


def parse_pose_packet(data: bytes) -> tuple[PosePacketHeader, List[PoseItem]]:
    header = parse_packet_header(data)
    if header.msg_type != UDP_MSG_TYPE_POSE:
        raise ValueError(f"unsupported msg_type: {header.msg_type}")

    expected = expected_packet_size(header.pose_count)
    if len(data) != expected:
        raise ValueError(f"packet size mismatch: got {len(data)}, expected {expected}")

    items: List[PoseItem] = []
    offset = _HEADER_STRUCT.size
    for _ in range(header.pose_count):
        sensor_id, tracking_state, _reserved, px, py, pz, qx, qy, qz, qw = _ITEM_STRUCT.unpack_from(data, offset)
        items.append(
            PoseItem(
                sensor_id=sensor_id,
                tracking_state=tracking_state,
                position=(px, py, pz),
                quaternion=(qx, qy, qz, qw),
            )
        )
        offset += _ITEM_STRUCT.size
    return header, items


def parse_timing_packet(data: bytes) -> TimingPacketV1:
    header = parse_packet_header(data)
    if header.msg_type != UDP_MSG_TYPE_TIMING:
        raise ValueError(f"unsupported msg_type: {header.msg_type}")
    expected = expected_timing_packet_size(header.pose_count)
    if len(data) != expected:
        raise ValueError(f"timing packet size mismatch: got {len(data)}, expected {expected}")

    boot_id, enqueue, send_mono, send_wall, diagnostic_mono = _TIMING_PREFIX_STRUCT.unpack_from(
        data, _HEADER_STRUCT.size
    )
    offset = _HEADER_STRUCT.size + _TIMING_PREFIX_STRUCT.size
    items: List[TimingItemV1] = []
    for _ in range(header.pose_count):
        sensor_id, flags, measurement_seq, pose_rx_mono_us, rf_seq, quality, battery, r19, r20, r21, r22, r23 = (
            _TIMING_ITEM_STRUCT.unpack_from(data, offset)
        )
        items.append(
            TimingItemV1(
                sensor_id=sensor_id,
                flags=flags,
                measurement_seq=measurement_seq,
                pose_rx_mono_us=pose_rx_mono_us,
                rf_seq=rf_seq,
                field_quality=quality,
                battery_percent=battery,
            )
        )
        offset += _TIMING_ITEM_STRUCT.size
    return TimingPacketV1(header, boot_id, enqueue, send_mono, send_wall, diagnostic_mono, items)
