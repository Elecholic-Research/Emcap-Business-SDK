# UDP位姿接收

[English](README.md) | 简体中文

## 快速开始
Python 3.10+，无第三方依赖。电脑与基站处于同一局域网。

先在基站串口CLI配置（将示例地址替换为电脑的局域网IPv4地址）：
```text
osc ip 192.168.1.100
osc target udp
```
确认基站网络已连接，当前运行模式允许网络输出；使用USB有线模式时不要假定UDP同时可用。
然后在本目录运行：
```powershell
python receiver_example.py
python receiver_example.py --port 9003 --max-packets 10
```
默认绑定本机所有网卡的UDP 9003端口。**--bind-ip是电脑本地地址，不是基站地址**。
Windows首次运行应允许Python通过专用网络防火墙；确认9003端口未被其他程序占用。
本示例是被动监听，不自动发现基站或替你配置目标地址。

## 集成
`udp_pose.py`提供`parse_pose_packet(data)`，返回`(header, items)`；数据不符合协议时抛出`ValueError`。
`receiver_example.py`是持续接收并打印的示例，Ctrl+C结束。

- `item.position`：米，XYZ。
- `item.quaternion`：XYZW。
- `item.position_valid / orientation_valid`：对应tracking_state的bit0/bit1，分别检查。
- `sensor_id`是输出ID，可能受设备映射配置影响；坐标轴由基站输出配置决定。
- UDP只解析type=1位姿。type=2原始幅值、type=3时序诊断可能共用端口，示例忽略/跳过，不作为位姿处理。
- 静止时坐标相同不是丢包；UDP v1没有USB模式2的逐设备新鲜度元数据。
- UDP无确认/自动重发保证，可能丢失、重复、乱序；16位seq会回绕。不同来源基站的流必须分开统计。
- timestamp_ns是协议定义的UTC纳秒时间戳；未确认时间同步时，不用它作可靠跨设备绝对时钟。计算间隔应考虑同步校时。
- 高速接收时不要在收包循环做耗时打印或磁盘处理，建议交给独立队列。

协议布局见[protocol.md](protocol_zh.md)。

## 电量与磁场质量

Type 3 的 battery_valid / field_quality_valid 表示当前值是否在 1 秒内更新；过期后数值仍保留供显示，但必须按无效处理。0=unknown，1=green，2=yellow，3=red。客户 UI 对 unknown、启动、离线、无数据和检测关闭统一显示红色。
