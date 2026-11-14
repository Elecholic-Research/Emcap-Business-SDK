from __future__ import annotations

import argparse
import datetime as dt
import socket

from udp_pose import UDP_POSE_PORT, parse_pose_packet, parse_timing_packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive EM beacon UDP pose and Type 3 telemetry packets.")
    parser.add_argument("--bind-ip", default="0.0.0.0", help="Local bind IP")
    parser.add_argument("--port", type=int, default=UDP_POSE_PORT, help="UDP port")
    parser.add_argument("--max-packets", type=int, default=0, help="Stop after N pose packets (0 = infinite)")
    parser.add_argument("--max-seconds", type=float, default=0.0, help="Stop after this many seconds (0 = infinite)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind_ip, args.port))
    sock.settimeout(0.5)
    print(f"Listening on {args.bind_ip}:{args.port}")
    started = dt.datetime.now(dt.timezone.utc)

    packet_count = 0
    timing_count = 0
    invalid_packets = 0
    while True:
        if args.max_seconds > 0 and (dt.datetime.now(dt.timezone.utc) - started).total_seconds() >= args.max_seconds:
            break
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue
        try:
            if len(data) >= 4 and data[:3] == b"EM\x01" and data[3] == 3:
                timing = parse_timing_packet(data)
                timing_count += 1
                print(f"Type3 seq={timing.header.seq} items={len(timing.items)} from {addr[0]}:{addr[1]}")
                for item in timing.items:
                    battery = "--" if item.battery_percent_or_none is None else f"{item.battery_percent_or_none}%"
                    print(
                        f"  sensor={item.sensor_id:>3} battery={battery:<4} "
                        f"battery_valid={int(item.battery_valid)} "
                        f"quality={item.field_quality_name:<7} "
                        f"quality_valid={int(item.field_quality_valid)}"
                    )
                continue
            header, items = parse_pose_packet(data)
        except ValueError as exc:
            invalid_packets += 1
            if invalid_packets == 1 or invalid_packets % 100 == 0:
                print(f"Ignored non-pose/invalid packets={invalid_packets}: {exc}")
            continue
        ts = dt.datetime.fromtimestamp(header.timestamp_ns / 1e9, dt.timezone.utc)
        print(f"\nPose seq={header.seq} poses={header.pose_count} frame_id={header.frame_id} time={ts.isoformat()} from {addr[0]}:{addr[1]}")
        for item in items:
            pos = item.position
            quat = item.quaternion
            print(
                f"  sensor={item.sensor_id:>3} state=0x{item.tracking_state:02X} "
                f"pos=({pos[0]:+.4f}, {pos[1]:+.4f}, {pos[2]:+.4f}) "
                f"quat=({quat[0]:+.4f}, {quat[1]:+.4f}, {quat[2]:+.4f}, {quat[3]:+.4f})"
            )
        packet_count += 1
        if args.max_packets > 0 and packet_count >= args.max_packets:
            break
    print(f"Stopped: pose_packets={packet_count} timing_packets={timing_count} invalid_packets={invalid_packets}")


if __name__ == "__main__":
    main()
