# USB模式2位姿接收（EMP2）

[English](README.md) | 简体中文

## 快速开始
基站固件须支持`mode wired2`。连接**基站ESP32的USB串口**，不是Tracker串口。
关闭占用该串口的Web上位机、串口助手等程序。
```powershell
python -m pip install -r requirements.txt
python -m serial.tools.list_ports -v
python usb_pose_mode2_demo.py --port COM6
# Linux示例：--port /dev/ttyACM0
# 限时接收：
python usb_pose_mode2_demo.py --port COM6 --seconds 30
```
示例自动进入模式2并等待ACK，默认每秒打印一帧，但持续解析全部数据。
Ctrl+C/正常结束时尝试切回`mode log`并关闭串口。强制终止后可再次运行；若处于旧JustFloat wired模式，先用串口助手发送`mode log`。
无需Wi-Fi即可接收。串口默认115200；USB虚拟串口的波特率不等同实际USB链路带宽。

## API
```python
from usb_pose_mode2 import SerialClient
client = SerialClient("COM6")
try:
    client.enter()
    while True:
        received = client.poll()
        if received is None:
            continue
        host_time, frame = received
        if frame["type"] != 1:
            continue
        for pose in frame["poses"]:
            if pose["tracking_state"] & 1:
                print(pose["sensor_id"], pose["position"])
finally:
    client.close()
```
- `enter(timeout=10)`等待成功ACK并幂等重试入口命令。
- `poll()`返回`(主机单调时间, 帧字典)`或None；可能等待串口读超时，并非严格非阻塞。
- `close()`尝试退回日志模式后关闭；退出ACK失败仍关闭端口，但可能抛异常。
- `StreamDecoder.feed(bytes)`用于仅解析原始字节流，返回完整帧列表；无需pyserial。
- `client.decoder.stats`记录校验/解码错误；坏段丢弃后继续同步。
- 一个客户端应只由一个接收循环使用。`command()`等待ACK期间会消费位姿，不适合采集中频繁调用。

## 正确解释数据
位置单位米，四元数`quaternion_xyzw`为XYZW。tracking_state bit0/bit1分别表示位置/姿态有效。
sample_flags：bit0源元数据有效；bit1过期；bit2新源样本；bit3源链路在线。
仅有在线标志不代表定位有效；必须检查tracking_state。
有源元数据时，用measurement_sequence识别重复样本，不能根据坐标是否相同判断。
data_age_us表示源样本年龄；未知值0xFFFFFFFF不是0延迟。
boot_id变化表示设备启动身份变化；stream_id变化可由重新进入模式产生。
UTC只有帧flags bit0置位时有效；频率/间隔优先使用设备单调时间。主机一次读取可能包含多帧，主机到达时间不等于准确线上发送时间。

## 常见问题
- 打不开串口：检查端口号、占用、USB线和驱动。程序不自动重连。
- 入口无ACK：确认固件支持模式2、选择基站端口，并等待启动完成。
- 只有无效/零坐标：先确认Tracker上线并完成定位初始化，检查有效标志，不能单凭收到USB包认定有效。
- 连续header/COBS/CRC错误：保留原始字节、固件版本及错误计数，检查是否混入文本输出；不要将所有解码错误直接归因于USB物理噪声。
- SDK在打开端口前将DTR/RTS设为False并关闭硬件流控；仍不能保证所有操作系统/驱动没有打开瞬变。
- 不在模式2数据流期间使用串口助手额外发送调试命令，避免干扰接收。

完整二进制布局与时间/来源字段见[protocol.md](protocol_zh.md)。

