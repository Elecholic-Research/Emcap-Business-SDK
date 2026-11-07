from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import List, Tuple

UDP_POSE_MAGIC = b"EM"
UDP_POSE_PORT = 9003
_HEADER_STRUCT = struct.Struct("<2sBBHQHH")
_ITEM_STRUCT = struct.Struct("<HBB3f4f")


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


def expected_packet_size(pose_count: int) -> int:
    return _HEADER_STRUCT.size + _ITEM_STRUCT.size * pose_count


def parse_pose_packet(data: bytes) -> tuple[PosePacketHeader, List[PoseItem]]:
    if len(data) < _HEADER_STRUCT.size:
        raise ValueError("packet too short for header")

    magic, version, msg_type, seq, timestamp_ns, frame_id, pose_count = _HEADER_STRUCT.unpack_from(data, 0)
    if magic != UDP_POSE_MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    if version != 1:
        raise ValueError(f"unsupported version: {version}")
    if msg_type != 1:
        raise ValueError(f"unsupported msg_type: {msg_type}")

    expected = expected_packet_size(pose_count)
    if len(data) != expected:
        raise ValueError(f"packet size mismatch: got {len(data)}, expected {expected}")

    header = PosePacketHeader(magic, version, msg_type, seq, timestamp_ns, frame_id, pose_count)
    items: List[PoseItem] = []
    offset = _HEADER_STRUCT.size
    for _ in range(pose_count):
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
