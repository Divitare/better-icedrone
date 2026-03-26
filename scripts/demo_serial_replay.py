#!/usr/bin/env python3
"""
Demo serial replay — feed sample serial lines into the database.

Usage:
    python scripts/demo_serial_replay.py [--speed 2.0] [--file tests/sample_serial_output.txt]

This bypasses the real serial port and directly processes lines through
the same parser pipeline used by the serial worker.
"""

import sys
import os
import time
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uwb_web import create_app
from uwb_web.db import db
from uwb_web.parser import parse_line
from uwb_web.models import RawLine, Measurement, Event
from uwb_web.services.device_service import get_or_create_device
from uwb_web.services.session_service import get_active_session, create_session


def replay(filepath, speed):
    app = create_app()

    with app.app_context():
        session = get_active_session()
        if not session:
            session = create_session(name='Demo Replay')
        session_id = session.id
        print(f"Using session '{session.name}' (id={session_id})")

        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            sys.exit(1)

        delay = 0.1 / max(speed, 0.01)
        count = 0

        with open(filepath, 'r') as f:
            for line in f:
                line = line.rstrip('\r\n')
                if not line:
                    continue
                now = datetime.now(timezone.utc)
                result = parse_line(line)

                # Store raw line
                raw = RawLine(
                    session_id=session_id,
                    pi_received_at_utc=now,
                    line_text=line[:2000],
                    line_type_guess=result.line_type,
                    parser_status='parsed' if result.line_type != 'unknown' else 'unknown',
                )
                db.session.add(raw)
                db.session.flush()

                if result.line_type == 'measurement' and result.short_addr_hex:
                    device = get_or_create_device(result.short_addr_hex, result.short_addr_int, now)
                    m = Measurement(
                        session_id=session_id,
                        device_id=device.id,
                        pi_received_at_utc=now,
                        range_m=result.range_m,
                        rx_power_dbm=result.rx_power_dbm,
                        parse_source='main_range_line',
                        raw_line_id=raw.id,
                    )
                    db.session.add(m)
                    count += 1
                    print(f"  [{result.short_addr_hex}] {result.range_m:.3f} m  {result.rx_power_dbm} dBm")

                elif result.line_type in ('device_added', 'device_inactive') and result.short_addr_hex:
                    device = get_or_create_device(result.short_addr_hex, result.short_addr_int, now)
                    evt = Event(
                        session_id=session_id,
                        device_id=device.id,
                        event_time_utc=now,
                        event_type=result.event_type or result.line_type,
                        event_text=result.event_text or line,
                        raw_line_id=raw.id,
                    )
                    db.session.add(evt)
                    print(f"  EVENT: {result.event_type} — {result.short_addr_hex}")

                db.session.commit()
                time.sleep(delay)

        print(f"\nReplay complete: {count} measurements inserted.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Demo serial replay')
    parser.add_argument('--file', default='tests/sample_serial_output.txt')
    parser.add_argument('--speed', type=float, default=1.0, help='Playback multiplier (1=real-time, 10=fast)')
    args = parser.parse_args()
    replay(args.file, args.speed)
