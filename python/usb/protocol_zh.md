# USB模式2二进制协议（EMP2 v1）

[English](protocol.md) | 简体中文

## 1. 连接和模式切换

连接基站ESP32的USB Serial/JTAG端口。不要选择tracker或线圈MCU串口。
主机串口API可设115200；它不是USB实际传输速率。串口须由一个程序独占。

发送ASCII命令，以LF或CRLF结束：

|命令|用途|
|---|---|
|`mode wired2`|进入模式2，默认100Hz，等待二进制成功ACK|
|`mode wired2 status`|读取当前模式和参数，返回二进制ACK|
|`mode log`|退出数据模式；退出ACK后恢复文本日志|
|`mode wired`|原有JustFloat协议，与模式2不同，不使用本解析器|

重启回到日志模式。模式选择不写Flash。重复进入已启用的模式2只返回当前状态，不重置会话。
进入时忽略遗留文本，直到收到完整、CRC有效的成功ACK；2秒内没有成功ACK则报告进入失败，不能把旧协议按模式2解释。
退出ACK是该会话最后一个模式2帧。模式2期间不回显文本；配置命令先退出到日志模式再执行。
主机每次只发一条控制命令，收到ACK后再发下一条。

## 2. 分帧与COBS

```text
线上帧 = COBS(40字节帧头 + 载荷 + 4字节CRC32) + 00
```

使用标准COBS，不是COBS/R。**只有编码后的COBS段不含00；原始头、位姿、CRC可以含00。**
COBS以非零长度码表示各段，在解码时恢复原始零字节，不限制用户数值，不丢失零值。

例如仅演示COBS编码：
```text
原始字节：11 00 22 00
编码字节：02 11 02 22 01
线上字节：02 11 02 22 01 00
```
最后一个00是分隔符，不属于编码段。实际要编码整个帧，不是分别编码每个字段。

### 2.1 编解码规则简介

- **编码**：将原始数据按零字节划分为连续非零块，每块前写一个长度码`C=非零字节数+1`，原始零字节不直接写入编码段。空块的长度码为`01`，因此连续零字节也能无损表示。
- 一个块最多容纳254个非零字节，此时长度码为`FF`，后面继续编码下一块；`FF`块之间不表示原始零字节。
- **解码**：读取长度码C，复制随后C−1个字节；若C小于255且编码段还有剩余字节，则追加一个原始零字节，再读取下一长度码。编码段结束时不额外追加零字节。
- 长度码不能为00，所声明的字节数不能越过编码段末尾。编码完成后，另加一个00作为整帧结束分隔符。

例如原始`00 00 00`编码为`01 01 01 01`，线上为`01 01 01 01 00`。
**长度码划分的是帧内COBS块，只有线上00划分整帧**；大量零值不会被误认为多个帧。

### 2.2 错误处理与重新同步

串口是字节流：一次read可能只有半帧，也可能包含多帧。接收程序按00切段，
对非空段COBS解码，然后校验帧头、长度、CRC及载荷。失败则丢弃该段，继续读下一段。
如果已经读到结束00并发现该段解码/校验失败，直接从这个00之后开始积累下一段，**不要再额外跳过一个00或一整帧**。
若00本身丢失或损坏，相邻帧可能合并而被丢弃；遇到后续完整00后恢复分段，并继续校验下一候选帧。
最大解码帧2048字节、最大编码段2057字节；超过上限仍无00时，丢弃直到下一00，防止缓存无限增长。

以下偏移均指COBS解码后的字节，不是线上偏移。多字节整数和IEEE754 float32均为小端，结构体不得带padding。

### 2.3 数据包与ACK包结构

两类消息使用同一外层封装，先对整个解码帧做COBS编码，再追加00：

```text
位姿数据包（解码后）
┌ 公共帧头：40字节，message_type=01
├ 位姿载荷前缀：16字节（UTC、frame_id、坐标/profile、条目数、条目大小）
├ 设备条目0：52字节（ID、状态、新鲜度/来源、位置、四元数）
├ …设备条目n−1：每条52字节；n=0时没有设备条目
└ CRC32：4字节
总计60+52*n字节；payload_length=16+52*n

命令ACK包（解码后）
┌ 公共帧头：40字节，message_type=80
├ ACK载荷：24字节（命令、结果、当前模式、速率、能力、阈值、容量）
└ CRC32：4字节
总计68字节；payload_length=24

线上：COBS(上述完整包) + 00
```

公共头字段见第3节，位姿载荷见第5节，ACK载荷见第6节。CRC覆盖公共头及全部载荷。

## 3. 帧头（40字节）

|偏移|类型|字段|说明|
|---:|---|---|---|
|0|bytes[4]|magic|`EMP2`：45 4D 50 32|
|4|uint8|version|1|
|5|uint8|message_type|01位姿；82诊断伴随；80命令ACK|
|6|uint16|flags|bit0：载荷UTC已同步且有效；bit1：自上一成功提交帧起丢弃过待发快照；其余位发送0|
|8|uint16|payload_length|载荷字节数，不含头和CRC|
|10|uint16|header_length|40|
|12|uint32|stream_sequence|会话内所有帧共用递增序号，模2³²回绕|
|16|uint32|boot_id|本次基站启动标识|
|20|uint32|stream_id|本次模式2会话标识，非零|
|24|uint64|snapshot_mono_us|基站创建快照的启动后单调微秒数|
|32|uint64|submit_mono_us|开始提交完整帧前的单调微秒数，非PC到达时间|

总长度必须等于`40 + payload_length + 4`。
新建模式2会话时入口成功ACK序号为0，之后所有帧递增。已处于模式2时再次发送`mode wired2`仍返回成功ACK，但保持原会话并沿用当前序号，不要求ACK序号为0。丢弃待发帧可能形成缺号；不能仅凭缺号认定USB物理丢包。
boot_id变化时重建时间/序号基准；stream_id变化时重建会话序号基准。
同启动的单调时间不受NTP调整影响；submit不得早于snapshot。

## 4. CRC32

使用CRC-32/ISO-HDLC，覆盖解码后的完整帧头和载荷，不含CRC、COBS编码或分隔符。
poly=0x04C11DB7，反射实现poly=0xEDB88320，init=0xFFFFFFFF，
refin/refout=true，xorout=0xFFFFFFFF。结果uint32小端放在帧末。
`123456789`的CRC为0xCBF43926，与Python `zlib.crc32`一致。
CRC用于差错检测，不提供身份认证。

## 5. 位姿消息（type=01）

### 5.1 载荷前缀（16字节）

|载荷偏移|类型|字段|说明|
|---:|---|---|---|
|0|uint64|snapshot_utc_ns|快照Unix UTC纳秒；未同步为0，帧头flags bit0清零|
|8|uint16|frame_id|与同配置UDP一致；可能为0，不用于判断递增|
|10|uint8|coordinate_frame|0非VR基站报告坐标；1 VR对齐输出坐标|
|11|uint8|output_profile|0 NON_VR；1 VR；2 RAW|
|12|uint16|pose_count|设备条目数，允许0|
|14|uint16|entry_size|52|

`payload_length = 16 + 52 * pose_count`。
ID按升序输出，同帧不能重复；按sensor_id关联设备，不按条目下标关联。
数量不得超过ACK报告的max_pose_count，协议帧大小上限允许最多38条。

### 5.2 每设备条目（52字节）

|条目偏移|类型|字段|说明|
|---:|---|---|---|
|0|uint16|sensor_id|与同配置UDP输出ID一致|
|2|uint8|tracking_state|bit0位置可用；bit1旋转可用；其余位0|
|3|uint8|sample_flags|见下表|
|4|uint32|measurement_sequence|基站识别的新RF WORLD_POSE接收计数|
|8|uint64|rx_mono_us|该位姿的RF接收单调微秒数|
|16|uint32|data_age_us|submit−rx；未知0xFFFFFFFF；溢出饱和0xFFFFFFFE|
|20|uint8|rf_sequence|RF包8位序号，会回绕|
|21|uint8|source_kind|0 RF tracker；1外部输入；2派生位姿；3静态参考|
|22|uint16|source_id|RF物理tracker ID；其他来源未知为0xFFFF|
|24|float32[3]|position_xyz|X/Y/Z，米|
|36|float32[4]|quaternion_xyzw|X/Y/Z/W，归一化四元数|

|sample_flags bit|名称|说明|
|---:|---|---|
|0|SOURCE_META_VALID|RF接收序号、时间、年龄和rf_sequence可用|
|1|STALE|年龄超过ACK阈值或来源掉线；tracking_state清0|
|2|NEW_SOURCE_SAMPLE|源序号相对会话上一成功提交条目改变；首次有效RF样本置1|
|3|SOURCE_LINK_ONLINE|来源链路在线，不保证位姿新鲜或解算正确|

sample_flags其余位发送0。外部/派生来源无RF元数据时，SOURCE_META_VALID及NEW_SOURCE_SAMPLE清0，
measurement_sequence、rx_mono_us、rf_sequence填0，age填未知，不能把未知年龄当成0。

### 5.3 位姿和有效性

与UDP复用同配置位姿处理：ID映射、四元数归一化、低通、中心偏移及VR坐标变换一致。
它是解算位姿，不是ADC；RAW名称不表示tracker关闭融合。不要再次应用设备中心偏移。
当前默认中心偏移约定为`P_center=P_coil-R(q)*offset`，offset为`(-0.0125,-0.0075,-0.0029)`米。

位置必须有限；有效四元数必须有限、归一化，q与−q表示同一旋转。
无效数值清对应tracking_state，位置填0，四元数填`[0,0,0,1]`；这些只是占位，不是有效零位姿。
STALE可保留最后一次有限位姿用于诊断，但tracking_state清0，不能继续当作当前测量。

已出现且适用于当前profile的RF设备掉线后保留STALE/无效条目；未出现设备不补位。
无设备时pose_count=0仍输出帧作为心跳。不是固定3个tracker，也不输出虚构的默认tracker凑包。
VR设备ID不一定对应独立RF tracker，应同时读取source_kind/source_id。

## 5.4 诊断伴随消息（type=0x82）

每个成功提交的位姿消息之后，基站发送一个同`stream_id`、同`sequence`的诊断伴随消息。它紧跟在 type `0x01` 之后；关联前必须校验这两个标识一致。type `0x01` 格式保持不变。

```text
解码帧：40字节公共头 + 8字节条目 + 4字节CRC32
payload_length = 8 * diagnostic_count
```

每个8字节条目：

|偏移|类型|字段|说明|
|---:|---|---|---|
|0|uint16|sensor_id|与关联位姿条目的ID一致|
|2|uint8|diagnostic_flags|bit0电量有效；bit1磁场质量有效；bit2 STALE；其余为0|
|3|uint8|field_quality|0未知，1绿，2黄，3红|
|4|uint8|battery_percent|0..100；0xFF未知|
|5|uint8|rf_sequence|最近RF WORLD_POSE序号；不可用为0|
|6|uint16|reserved|必须为0|

条目按`sensor_id`升序且不重复。无效值通过清除对应valid位并将质量写0或电量写0xFF表示。来源停止更新后可保留数值，但超过1秒必须清除对应valid位。缺失伴随包不影响 type `0x01` 位姿本身；没有匹配位姿的伴随包不得用于关联。

## 6. ACK消息（type=80，载荷24字节）

ACK也使用公共帧头和CRC，**有24字节载荷，不是无载荷帧**：

```text
解码后：40字节公共帧头（message_type=80，payload_length=24）
        + 24字节ACK载荷 + 4字节CRC32 = 68字节
线上：COBS(上述68字节) + 00 = 70字节
```

ACK载荷包含命令、执行结果及当前模式参数；ACK不是额外附加在帧头之外的标记。
它用于模式控制命令应答，不是逐个位姿帧的接收确认。

|载荷偏移|类型|字段|说明|
|---:|---|---|---|
|0|uint16|command|1进入；2退出；3状态查询；0未知命令|
|2|uint16|result|0成功；1不支持；2参数错误；3忙；4内部错误|
|4|uint8|current_usb_mode|0日志；1旧wired；2 wired2。退出ACK为0|
|5|uint8|protocol_version|1|
|6|uint16|nominal_rate_hz|默认100，不承诺严格10ms间隔|
|8|uint32|capabilities|bit0位姿；bit1 RF新鲜度；bit2 UTC能力；其余位0|
|12|uint32|stale_threshold_us|数据过期阈值，默认500000（500ms）|
|16|uint16|max_pose_count|固件可输出最大条目数，不是当前在线数|
|18|uint16|max_decoded_frame_size|2048|
|20|uint32|固定字段|0|

UTC能力不等于UTC已经同步。退出ACK仍使用退出前的boot_id/stream_id。
收到非成功ACK应报告错误，不开始按有效位姿使用后续数据。

## 7. 如何判断旧位姿和时钟跳变

### 7.1 每设备新鲜度与来源

|字段/标志|含义|
|---|---|
|`measurement_sequence`|基站每识别到一个新RF位姿，接收计数增加；不是tracker解算次数|
|`rx_mono_us`|基站收到这份RF位姿的单调时间|
|`data_age_us`|提交时间减去接收时间，表示位姿在基站缓存多久，单位微秒|
|`NEW_SOURCE_SAMPLE`|相比上一次成功输出，该设备有新的RF样本|
|`STALE`|缓存过期或来源掉线；位姿标记为无效，默认过期阈值500ms|
|`SOURCE_LINK_ONLINE`|来源链路在线，不保证位姿新鲜或准确|
|`SOURCE_META_VALID`|RF接收时间、序号等信息是否可用|
|`source_kind`|来源类别：RF tracker、外部输入、派生位姿、静态参考|
|`source_id`|实际物理tracker ID；可能不同于对外报告的sensor_id|

重复样本不一定过期；静止时坐标不变也不一定是重复样本。年龄不包含tracker内部计算、RF发送前等待及主机接收延迟。
VR派生位姿还依赖腰部tracker，依赖源过期也会使位姿无效；年龄及测量序号仍描述source_id对应的RF源。

### 7.2 单调时间与绝对时间

两种时间同时存在，不复用同一个字段：

- `snapshot_mono_us`、`submit_mono_us`及`rx_mono_us`：基站本次启动后的单调微秒计数，用于间隔、延迟和年龄计算；重启后重新计数，应结合boot_id使用。
- `snapshot_utc_ns`：Unix UTC绝对时间纳秒，用于与其他设备/日志对齐。首次NTP同步成功前为0，公共头flags bit0为0；有效时bit0为1。

配置Wi-Fi不等于已获得有效UTC。没有Wi-Fi或首次NTP同步失败时，仍完整输出单调时间，UTC字段不填启动计数冒充绝对时间。
成功同步后即使临时断网，系统时钟仍可继续走时，不因一次后续同步失败立即切回启动计数；UTC有效标志也不表示始终保持某个精度界限。
NTP再次校时可能调整UTC，因此间隔统计和超时判断始终使用单调时间。

### 7.3 诊断举例

- 帧序号增加、measurement_sequence不变且age增加：缓存位姿重发。
- snapshot到submit的延迟增加：基站队列/处理延迟增加，不代表完整USB传输延迟。
- UTC跳变而单调时间正常：时钟调整；周期统计使用单调时间。
- 帧仍连续但STALE置位：来源数据过期；整个流停止则是另外一种链路故障。
- 坐标相同不代表卡死，静止时可能相同；RF接收序号增加也不保证tracker内部重新解算。

measurement_sequence是基站接收计数，不能当tracker求解次数。RF原始8位seq只用于辅助诊断。
默认500ms过期判断独立于HTTP轮询、Wi-Fi与NTP。来源掉线不得无限重发“有效旧位姿”。
协议不重传历史位姿；主机读不动时有界队列优先保留最新快照。
主机须另设断流超时，不能永久使用最后一条有效位姿。

## 8. 条目数与长度

解码帧长为`60 + 52*n`，n=pose_count。0～3条时解码帧不足254字节，
标准COBS增加1字节，末尾分隔符再增加1字节：

|条目数|解码帧长（含CRC）|线上帧长（含COBS及00）|
|---:|---:|---:|
|0|60|62|
|1|112|114|
|2|164|166|
|3|216|218|

不足3条时包长缩短，不补齐。但掉线设备保留的STALE条目仍计入n，因此在线2个不必然意味着仅2条。
更多条目时COBS开销随非零块长度变化，解析不能靠固定线上字节数分帧。

## 9. 解析参考

```python
import struct, zlib
HEADER = struct.Struct('<4sBBHHHIIIQQ')  # 40 bytes
PREFIX = struct.Struct('<QHBBHH')       # 16 bytes
ITEM = struct.Struct('<HBBIQIBBH7f')    # 52 bytes

# 从串口按00切段，使用标准COBS解码，得到decoded：
assert len(decoded) >= 44
assert decoded[:4] == b'EMP2' and decoded[4] == 1
payload_len = struct.unpack_from('<H', decoded, 8)[0]
header_len = struct.unpack_from('<H', decoded, 10)[0]
assert header_len == 40 and len(decoded) == 40 + payload_len + 4
expected_crc = struct.unpack_from('<I', decoded, len(decoded)-4)[0]
assert zlib.crc32(decoded[:-4]) & 0xffffffff == expected_crc
# 再按message_type检查载荷尺寸、count、ID、有效标志和有限数值。
```

示例仅说明格式。实际程序应将失败作为坏帧丢弃，不因assert异常终止整个接收任务。
未知消息类型可在校验后跳过；未知主版本不解释，字段约束不满足时丢弃。

## 10. 与UDP位姿输出的对应关系

下表比较UDP位姿消息（type=1）及其时间诊断消息（type=3）与本协议；两者二进制布局不同，不能共用同一个帧解析器。

|内容|UDP|USB模式2（EMP2）|
|---|---|---|
|核心位姿|sensor_id、tracking_state、位置xyz、四元数xyzw|保留这些字段；同配置下ID映射、单位、坐标及位姿处理一致|
|设备条目大小|位姿消息每条32字节|每条52字节，加入来源、新鲜度信息|
|分帧/应用层校验|数据报边界；无额外应用层CRC32|COBS加00分帧；CRC32校验|
|公共帧头|18字节|40字节，明确载荷长度、会话和单调时间|
|发送序号|16位；位姿与配套诊断使用相同序号|32位，会话内位姿和ACK共用递增序号|
|UTC时间、frame_id|位姿头中携带；当前frame_id可能为0|位姿载荷前缀携带，另明确UTC有效标志；frame_id仍不作为递增序号|
|启动/会话标识|时间诊断带boot_id|每帧带boot_id及stream_id|
|单调时间与RF接收信息|另一个type=3诊断包携带，需与位姿包关联|公共头和对应设备条目内直接携带，无需关联另一包|
|数据年龄和状态|可根据诊断时间计算年龄|直接提供data_age_us、STALE、NEW_SOURCE_SAMPLE、来源链路状态及来源ID|
|命令应答|位姿数据报本身不是控制应答|独立type=80 ACK消息，载荷24字节|

因此模式2不是简单给UDP包套COBS：核心位姿语义对齐，但增加了流式分帧、会话识别和逐设备新鲜度信息。
