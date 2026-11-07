"""Customer example: python usb_pose_mode2_demo.py --port COM17"""
import argparse
import json
import time
from usb_pose_mode2 import SerialClient


def main():
    ap = argparse.ArgumentParser(description='EMP2 serial pose receiver (Ctrl+C to exit)')
    ap.add_argument('--port', required=True)
    ap.add_argument('--seconds', type=float, default=0, help='0: run until Ctrl+C')
    ap.add_argument('--print-interval', type=float, default=1)
    args = ap.parse_args()
    client = SerialClient(args.port)
    try:
        print('ACK:', json.dumps(client.enter()['ack']))
        start = time.monotonic(); last = 0
        while not args.seconds or time.monotonic()-start < args.seconds:
            received = client.poll()
            if not received:
                continue
            now, frame = received
            if frame['type'] == 1 and now-last >= args.print_interval:
                print(json.dumps(frame, ensure_ascii=False), flush=True); last = now
    except KeyboardInterrupt:
        print('Stopped by Ctrl+C')
    finally:
        print('Decoder counters:', dict(client.decoder.stats))
        try:
            client.close()
        except Exception as exc:
            print('Exit ACK unavailable:', exc)


if __name__ == '__main__':
    main()
