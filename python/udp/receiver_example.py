from __future__ import annotations

import argparse
import datetime as dt
import socket

from udp_pose import UDP_POSE_PORT, parse_pose_packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive and print EM beacon UDP pose packets.")
    parser.add_argument("--bind-ip", default="0.0.0.0", help="Local bind IP")
    parser.add_argument("--port", type=int, default=UDP_POSE_PORT, help="UDP port")
    parser.add_argument("--max-packets", type=int, default=0, help="Stop after N packets (0 = infinite)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind_ip, args.port))
    print(f"Listening on {args.bind_ip}:{args.port}")

    packet_count = 0
    invalid_packets = 0
    diagnostic_packets = 0
    while True:
        data, addr = sock.recvfrom(2048)
        # Type 3 timing diagnostics share the port with type 1 poses.
        # Do not pass diagnostic payloads to the pose-only parser.
        if len(data) >= 18 and data[:3] == b'EM\x01' and data[3] == 3:
            diagnostic_packets += 1
            if diagnostic_packets == 1:
                print('Timing diagnostic packets (type=3) detected; skipped by this pose-only demo.')
            continue
        try:
            header, items = parse_pose_packet(data)
        except ValueError as exc:
            invalid_packets += 1
            if invalid_packets == 1 or invalid_packets % 100 == 0:
                print(f'Ignored non-pose/invalid packets={invalid_packets}: {exc}')
            continue
        ts = dt.datetime.utcfromtimestamp(header.timestamp_ns / 1e9)
        print(f"\nPacket seq={header.seq} poses={header.pose_count} frame_id={header.frame_id} time={ts.isoformat()}Z from {addr[0]}:{addr[1]}")
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


if __name__ == "__main__":
    main()
