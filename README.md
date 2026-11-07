# EMCAP Business SDK

English | [简体中文](README_zh.md)

Python pose receivers for two independent connection methods:

| Transport | Directory | Dependencies |
|---|---|---|
| LAN UDP pose stream | [python/udp](python/udp/README.md) | Python standard library |
| USB Mode 2 (EMP2) | [python/usb](python/usb/README.md) | pyserial |

Python 3.10 or later is recommended. Run each example in its own directory; installing the entire repository as a package is not required.
Positions are in meters; quaternion order is **X, Y, Z, W**.
Always check validity flags: receiving a packet does not establish that tracking is valid.

This repository contains receiver libraries, application examples, and protocol documentation only.
It does not include firmware, OTA, calibration, management interfaces, unit tests, or stability tests.
Protocol compatibility depends on the base station firmware. The USB Mode 2 parser cannot decode the legacy USB JustFloat stream.
