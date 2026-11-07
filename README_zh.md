# EMCAP Business SDK

[English](README.md) | 简体中文

Python位姿接收示例，包含两种独立接入方式：

|方式|目录|依赖|
|---|---|---|
|局域网UDP位姿|[python/udp](python/udp/README_zh.md)|Python标准库|
|USB模式2（EMP2）|[python/usb](python/usb/README_zh.md)|pyserial|

建议Python 3.10及以上。各示例在对应目录运行，不需要安装整个仓库。
位置单位为米，四元数顺序为 **X、Y、Z、W**；必须检查有效标志，不能仅凭收到包判断定位有效。

本仓库只提供接收库、应用示例与协议说明，不包含固件、OTA、标定、管理接口、单元测试或稳定性测试。
协议兼容性取决于所用基站固件；USB旧版JustFloat模式不能用USB模式2解析器接收。

