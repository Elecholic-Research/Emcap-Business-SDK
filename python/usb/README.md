# USB Mode 2 Pose Receiver (EMP2)

English | [简体中文](README_zh.md)

## Quick start

The base station firmware must support `mode wired2`.
Connect to the **base station ESP32 USB serial port**, not a Tracker port.
Close the Web application, serial terminal, or any other program using that port.

```powershell
python -m pip install -r requirements.txt
python -m serial.tools.list_ports -v
python usb_pose_mode2_demo.py --port COM6
# Linux example: --port /dev/ttyACM0
# Receive for a limited time:
python usb_pose_mode2_demo.py --port COM6 --seconds 30
```

The example enters Mode 2 automatically and waits for an ACK. It prints one frame per second by default while continuously decoding all received data.
On Ctrl+C or normal completion it attempts to switch back to `mode log` and close the port.
After forced termination, run it again. If the device is in the legacy JustFloat wired mode, first send `mode log` using a serial terminal.
Wi-Fi is not required for reception. The default serial setting is 115200; the USB virtual serial baud rate is not the actual USB link bandwidth.

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

- `enter(timeout=10)` waits for a successful ACK and retries the idempotent entry command.
- `poll()` returns `(host_monotonic_time, frame_dict)` or None. It may wait for the serial read timeout; it is not strictly nonblocking.
- `close()` attempts to return to log mode before closing. It still closes the port if the exit ACK fails, but may raise an exception.
- `StreamDecoder.feed(bytes)` decodes a byte stream into a list of complete frames; pyserial is not needed for decoding alone.
- `client.decoder.stats` counts validation/decoding errors. Bad segments are discarded and synchronization continues.
- Use one receive loop per client. `command()` consumes poses while waiting for an ACK, so avoid frequent commands during acquisition.

## Interpreting data

Positions are in meters; `quaternion_xyzw` is XYZW.
tracking_state bits 0/1 indicate valid position/orientation.
field_quality (0 unknown, 1 green, 2 yellow, 3 red) and battery_percent (0..100, 0xFF unknown) are merged from the matching type 0x82 companion. Check diagnostic_flags bits 0/1 before using them.

sample_flags bits: 0 source metadata valid; 1 stale; 2 new source sample; 3 source link online.
Online alone does not establish valid tracking: always check tracking_state.
When source metadata is valid, use measurement_sequence to identify repeated samples, not coordinate equality.
data_age_us is the source sample age; 0xFFFFFFFF means unknown, not zero latency.
A boot_id change indicates a new boot identity; re-entering Mode 2 may change stream_id.
UTC is valid only when frame flags bit 0 is set.
Prefer device monotonic timestamps for frequency/interval measurements.
One host read can contain several frames; host arrival time is not precise wire-transmission time.

## Troubleshooting

- Cannot open port: check the port name, port ownership, USB cable, and drivers. The program does not reconnect automatically.
- No entry ACK: verify Mode 2 firmware support, select the base station port, and wait for startup to finish.
- Invalid/zero poses only: ensure the Tracker is online and has completed tracking initialization. Check validity flags; receiving USB packets alone is not enough.
- Persistent header/COBS/CRC errors: preserve raw bytes, firmware version, and error counts. Check for text mixed into the binary stream; do not automatically attribute all decoding errors to physical USB noise.
- Before opening the port, the SDK sets DTR/RTS to False and disables hardware flow control. Some operating systems/drivers may still produce control-line transients.
- Do not send extra debug commands from a serial terminal during a Mode 2 stream.

See [protocol.md](protocol.md) for the binary layout and timestamp/source fields.
