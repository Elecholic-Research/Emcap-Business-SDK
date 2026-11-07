# UDP二进制位姿协议（v1）

[English](protocol.md) | 简体中文

## 概述

本协议面向机器人和数据采集应用，在同一数据报内携带位置与姿态。
相比拆分的OSC消息，它具有更低的开销、更方便的帧关联、明确的序号和有效标志，
以及适合自定义记录器、机器人中间件和离线工具的稳定二进制格式。

采用**固定字段布局、逐字段序列化**，不允许依赖编译器结构体填充。

- 传输：同一局域网内UDP单播或广播。
- 字节序：所有多字节整数和浮点数均为小端。
- 浮点数：IEEE-754 float32。
- 时间戳：timestamp_ns是对应运动帧的**RF同步包发射事件**的Unix时间，单位纳秒。
- 一帧UDP数据报可包含同一帧的一个或多个Tracker位姿。
- v1没有额外应用层CRC；面向局域网部署，使用常规网络校验。
- v1不包含协方差，留待后续协议扩展。

## 1. 包头（v1）

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

| 字段 | 类型 | 是否必需 | 说明 |
|---|---|---|---|
| magic | uint16_t | 是 | 固定ASCII字节EM，用于识别数据报 |
| version | uint8_t | 是 | 当前为1 |
| msg_type | uint8_t | 是 | 1位姿，2原始幅值，3时间诊断 |
| seq | uint16_t | 是 | 包序号，模65536递增，用于辅助判断丢失/乱序 |
| timestamp_ns | uint64_t | 是 | 对应RF同步包发射时间的Unix纳秒时间戳 |
| frame_id | uint16_t | 语义可选 | 坐标系标识；0表示默认或未指定，字段仍占据固定空间 |
| pose_count | uint16_t | 是 | 本数据报随后包含的位姿条目数 |

v1不包含packet_len字段；接收端可根据以下公式校验数据报长度：

```text
sizeof(header_v1) + pose_count * sizeof(pose_item_v1)
```

## 2. 位姿条目（v1）

```c
typedef struct {
    uint16_t sensor_id;       // Tracker / rigid body ID
    uint8_t  tracking_state;  // bit0=position valid, bit1=orientation valid
    uint8_t  reserved;        // Reserved for future use, set to 0 in v1
    float    position[3];     // x, y, z in meters
    float    quaternion[4];   // x, y, z, w
} PoseItemV1_t;
```

| 字段 | 类型 | 是否必需 | 说明 |
|---|---|---|---|
| sensor_id | uint16_t | 是 | Tracker或刚体ID |
| tracking_state | uint8_t | 是 | 有效性位掩码 |
| reserved | uint8_t | 是 | v1固定为0 |
| position | float[3] | bit0置位时有效 | XYZ位置，米 |
| quaternion | float[4] | bit1置位时有效 | 四元数，顺序XYZW |

## 3. 位姿有效性

tracking_state是位掩码：bit0表示位置有效，bit1表示姿态有效。

| 数值 | 含义 |
|---:|---|
| 0 | 没有有效位姿数据 |
| 1 | 仅位置有效 |
| 2 | 仅姿态有效 |
| 3 | 位置和姿态均有效 |

姿态无效时，发送端可能保留上一帧四元数以减少显示跳变。
**即使数值被保留，bit1未置位时仍必须按无效姿态处理。**
位置与bit0遵循相同规则。

## 4. 数据报布局

```text
+----------------------+--------------------+--------------------+ ...
| PosePacketHeaderV1_t |   PoseItemV1_t #0  |   PoseItemV1_t #1  | ...
+----------------------+--------------------+--------------------+ ...
```

包头18字节，每条位姿32字节：

```text
18 + 32 * pose_count bytes
```

例如1条为50字节，2条为82字节，4条为146字节，均明显小于标准以太网MTU。

## 5. 序列化规则

不得直接发送内存中的C结构体，因为编译器对齐和padding不属于协议。

1. 严格按上述字段顺序写入。
2. 整数采用小端。
3. 浮点采用IEEE-754 32位格式。
4. 所有保留字节写0。
5. 包头之后紧接pose_count个位姿条目。

## 6. 坐标与时间语义

- position单位为米。
- quaternion顺序为(x, y, z, w)。
- frame_id=0表示基站当前配置的默认跟踪坐标系。
- timestamp_ns对应RF同步广播所关联的运动帧，不是本地Wi-Fi发送完成时刻。

## 7. v1限制与后续扩展

当前没有：

- 协方差矩阵；
- 线速度/角速度；
- 常规网络校验之外的应用层CRC；
- 每个位姿的坐标系字符串；
- 有效掩码之外的显式质量评分。

未来可能扩展：

- 协方差需要新消息类型；type=3已经分配给时间诊断。
- msg_type=4可用于设备描述或传感器注册表。
- 可选速度、协方差、质量/诊断字段。
- 若部署反馈确有需要，增加更强完整性检查。
