# UDP Pose Receiver

English | [简体中文](README_zh.md)

## Quick start

Use Python 3.10+; no third-party dependencies are required. Connect the computer and base station to the same LAN.

Configure the base station through its serial CLI, replacing the address below with the computer's LAN IPv4 address:

```text
osc ip 192.168.1.100
osc target udp
```

Check that the base station is connected to the network and its operating mode permits network output.
Do not assume UDP remains available while using a USB wired mode.
Run in this directory:

```powershell
python receiver_example.py
python receiver_example.py --port 9003 --max-packets 10
```

The default listener binds to UDP port 9003 on all local interfaces.
**--bind-ip is a local address on the computer, not the base station address.**
On Windows, allow Python through the firewall for the appropriate private network.
Ensure no other application occupies UDP port 9003.
The example is a passive listener: it does not discover the base station or configure its destination.

## Integration

`udp_pose.py` exposes `parse_pose_packet(data)`, returning `(header, items)`.
Invalid or unsupported datagrams raise `ValueError`.
`receiver_example.py` continuously receives and prints poses; press Ctrl+C to stop.

- `item.position`: XYZ, in meters.
- `item.quaternion`: XYZW.
- `item.position_valid / orientation_valid`: tracking_state bits 0/1; check each independently.
- `sensor_id` is the output ID and may be affected by device mapping. Coordinate axes depend on the base station output configuration.
- The parser handles type=1 poses only. Type=2 raw amplitude and type=3 timing diagnostics may share the same port; the example ignores/skips them rather than interpreting them as poses.
- Equal coordinates while stationary do not mean packet loss. UDP v1 does not carry USB Mode 2's per-device freshness metadata in the pose datagram.
- UDP does not guarantee acknowledgments or automatic retransmission; packets may be lost, duplicated, or reordered. The 16-bit seq wraps. Track different source base stations separately.
- timestamp_ns is the protocol's UTC timestamp in nanoseconds. Do not treat it as a reliable cross-device absolute clock without confirming time synchronization; account for clock adjustments when computing intervals.
- For high-rate reception, keep expensive printing and disk processing out of the receive loop; use a separate queue.

See [protocol.md](protocol.md) for the binary layout.
