# UDP Binary Pose Protocol (v1)

English | [简体中文](protocol_zh.md)

This section defines a lightweight UDP protocol intended for robotics and data-capture users who need:

- position and orientation in the same datagram
- lower overhead and easier synchronization than split OSC messages
- explicit packet sequencing and validity flags
- a stable binary format for custom loggers, robot middleware, and offline tools

This protocol uses a **fixed-layout binary datagram** with **manual serialization**. It must not rely on compiler padding.

#### Design Notes

- **Transport**: UDP unicast or broadcast on the same LAN
- **Byte order**: Little-endian for all integer and floating-point fields
- **Floating-point**: IEEE-754 `float32`
- **Timestamp source**: `timestamp_ns` is the Unix epoch time of the **RF sync packet transmit event** associated with the motion frame
- **Frame semantics**: one UDP datagram may contain one or more tracker poses belonging to the same frame
- **No packet CRC in v1**: Ethernet/IP/UDP checksums are considered sufficient for the intended LAN deployment
- **No covariance in v1**: reserved for future protocol versions

#### 3.5.1 Packet Header (v1)

```c
typedef struct {
    uint16_t magic;         // ASCII 'EM'
    uint8_t  version;       // Protocol version, v1 = 1
    uint8_t  msg_type;      // 1 = pose_frame, 2 = raw_amp_frame, 3 = timing diagnostics
    uint16_t seq;           // Packet sequence number, increments modulo 65536
    uint64_t timestamp_ns;  // Unix epoch timestamp in nanoseconds, aligned to sync-packet send time
    uint16_t frame_id;      // Optional coordinate frame ID, 0 = default / unspecified
    uint16_t pose_count;    // Number of PoseItem entries following the header
} PosePacketHeaderV1_t;
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `magic` | `uint16_t` | Yes | Packet discriminator. Fixed to ASCII `EM`. |
| `version` | `uint8_t` | Yes | Protocol version. Current version is `1`. |
| `msg_type` | `uint8_t` | Yes | Message type: `1` means pose frame; `2` means raw amplitude frame; `3` means timing diagnostics. |
| `seq` | `uint16_t` | Yes | Monotonic packet sequence number modulo 65536. Useful for loss / reordering detection. |
| `timestamp_ns` | `uint64_t` | Yes | Unix epoch timestamp in nanoseconds. Defined by RF sync packet transmit time. |
| `frame_id` | `uint16_t` | Optional semantic field | Coordinate frame identifier. `0` means default frame or unspecified. |
| `pose_count` | `uint16_t` | Yes | Number of pose records appended to this datagram. |

`packet_len` is intentionally omitted in v1. It is not needed for memory alignment, and the receiver can validate the datagram size from:

```text
sizeof(header_v1) + pose_count * sizeof(pose_item_v1)
```

#### 3.5.2 Pose Item (v1)

```c
typedef struct {
    uint16_t sensor_id;       // Tracker / rigid body ID
    uint8_t  tracking_state;  // bit0=position valid, bit1=orientation valid
    uint8_t  reserved;        // Reserved for future use, set to 0 in v1
    float    position[3];     // x, y, z in meters
    float    quaternion[4];   // x, y, z, w
} PoseItemV1_t;
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sensor_id` | `uint16_t` | Yes | Tracker or rigid-body ID. |
| `tracking_state` | `uint8_t` | Yes | Validity bitmask for the payload. |
| `reserved` | `uint8_t` | Yes | Reserved for future use, set to `0` in v1. |
| `position` | `float[3]` | Required when bit0 is set | Cartesian position in meters. |
| `quaternion` | `float[4]` | Required when bit1 is set | Quaternion ordered as `(x, y, z, w)`. |

#### 3.5.3 Tracking State Definition

`tracking_state` uses a bitmask in v1:

- bit0 = position valid
- bit1 = orientation valid

Therefore the current values are:

| Value | Meaning |
|-------|---------|
| `0` | No valid pose data |
| `1` | Position valid only |
| `2` | Orientation valid only |
| `3` | Position and orientation both valid |

When orientation is invalid, the sender may preserve the last transmitted quaternion to avoid visualization jumps. Receivers **must still treat the quaternion as invalid unless bit1 is set**. The same rule applies to position and bit0.

#### 3.5.4 Datagram Layout

```text
+----------------------+--------------------+--------------------+ ...
| PosePacketHeaderV1_t |   PoseItemV1_t #0  |   PoseItemV1_t #1  | ...
+----------------------+--------------------+--------------------+ ...
```

Header size in v1: 18 bytes  
Pose item size in v1: 32 bytes  
Total packet size in v1:

```text
18 + 32 * pose_count bytes
```

Examples:

- `pose_count = 1` -> 50 bytes
- `pose_count = 2` -> 82 bytes
- `pose_count = 4` -> 146 bytes

All are well below a standard Ethernet MTU.

#### 3.5.5 Serialization Rules

The packet must be serialized field-by-field. Do **not** send an in-memory C struct directly, because compiler padding and alignment are not part of the protocol definition.

Required v1 serialization rules:

1. Write fields in the exact order defined above
2. Use little-endian encoding for integers
3. Encode floats as IEEE-754 32-bit values
4. Set all reserved bytes to zero
5. Emit `pose_count` pose items immediately after the header

#### 3.5.6 Coordinate and Time Semantics

- `position` is expressed in meters
- `quaternion` ordering is `(x, y, z, w)`
- `frame_id = 0` means the default tracking frame currently configured by the base station
- `timestamp_ns` corresponds to the motion frame referenced by the RF sync broadcast, not to local WiFi transmit completion time

#### 3.5.7 Internal Limitations and Future Extensions

The following are intentionally not implemented in v1:

- covariance matrix
- linear velocity / angular velocity
- explicit packet CRC beyond normal network checksums
- per-pose frame strings
- explicit quality score beyond the validity bitmask

Possible future additions:

- Covariance requires a new message type; type 3 is assigned to timing diagnostics
- `msg_type = 4`: device description / sensor registry
- optional velocity fields
- optional covariance fields
- optional quality metrics or diagnostics
- stronger integrity checks if deployment feedback requires them

