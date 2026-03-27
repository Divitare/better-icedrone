"""
Background serial ingestion worker.

Reads UWB serial data from the Makerfabs ESP32 UWB Pro board,
parses each line, and stores results in the database.

Supports:
- Auto-detection of serial ports
- Automatic reconnection on USB disconnect/reconnect
- Demo mode (replay from file)
- In-memory live cache for fast dashboard rendering
- Health stats for diagnostics
"""

import os
import time
import threading
import logging
from datetime import datetime, timezone
from collections import deque

from uwb_web.parser import parse_line
from uwb_web.services.filtering import DeviceFilterBank
from uwb_web.services.trilateration import estimate_position_2d, estimate_position_3d
from uwb_web.services.position_engine import PositionEngine

logger = logging.getLogger(__name__)


class SerialWorker:
    """Background thread that reads serial data and feeds it into the DB."""

    def __init__(self, app, config):
        self.app = app
        self.config = config
        self._thread = None
        self._stop_event = threading.Event()

        serial_cfg = config.get('serial', {})
        self._port = serial_cfg.get('port', 'auto')
        self._baud = serial_cfg.get('baud', 115200)
        self._timeout = serial_cfg.get('timeout', 1.0)
        self._reconnect_delay = serial_cfg.get('reconnect_delay', 3.0)

        # Health stats (read from dashboard / system page)
        self.stats = {
            'connected': False,
            'port': None,
            'bytes_read': 0,
            'lines_read': 0,
            'last_line_time': None,
            'parser_errors': 0,
            'reconnect_count': 0,
            'started_at': None,
            'measurements_ingested': 0,
            'events_ingested': 0,
        }

        # Per-device live cache: {addr_hex: {range_m, rx_power_dbm, last_seen, ...}}
        self.live_cache = {}
        self._cache_lock = threading.Lock()

        # Recent values per device for sparklines (last 30 values)
        self.recent_values = {}  # addr_hex -> deque of {range_m, ts}
        self._recent_lock = threading.Lock()

        # SSE broadcaster (set externally)
        self.sse_broadcaster = None

        # Current logging session
        self.is_logging = False
        self.current_session_id = None

        # Position tracking
        self._filter_bank = DeviceFilterBank()
        self._filtered_ranges = {}   # device_id -> filtered range_m
        self._position_lock = threading.Lock()
        self.last_position = None     # (x, y) or (x, y, z) or None
        self.position_history = deque(maxlen=200)  # list of {x, y, z?, ts}

        # Advanced position engine (EKF + WLS + NLOS rejection)
        self._engine = PositionEngine()
        self._engine_loaded = False

    # ---- lifecycle ----

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='serial-worker')
        self._thread.start()
        self.stats['started_at'] = datetime.now(timezone.utc).isoformat()
        logger.info("Serial worker started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Serial worker stopped")

    # ---- main loop ----

    def _run(self):
        self._ensure_session()
        demo = self.config.get('demo', {})
        if demo.get('enabled', False):
            self._run_demo(demo)
        else:
            self._run_serial()

    def _run_serial(self):
        """Main serial reading loop with auto-reconnect."""
        import serial
        import serial.tools.list_ports

        first_connect = True
        while not self._stop_event.is_set():
            port = self._find_port()
            if not port:
                logger.warning("No serial port found, retrying in %.1fs", self._reconnect_delay)
                self.stats['connected'] = False
                self.stats['port'] = None
                self._stop_event.wait(self._reconnect_delay)
                continue

            try:
                logger.info("Connecting to %s at %d baud", port, self._baud)
                ser = serial.Serial(port, self._baud, timeout=self._timeout)
                self.stats['connected'] = True
                self.stats['port'] = port

                if not first_connect:
                    self._store_event('serial_reconnected', f'Reconnected to {port}')
                first_connect = False
                self.stats['reconnect_count'] += 1

                while not self._stop_event.is_set():
                    try:
                        raw_bytes = ser.readline()
                        if not raw_bytes:
                            continue
                        line = raw_bytes.decode('utf-8', errors='replace').rstrip('\r\n')
                        now_utc = datetime.now(timezone.utc)

                        self.stats['bytes_read'] += len(raw_bytes)
                        self.stats['lines_read'] += 1
                        self.stats['last_line_time'] = now_utc.isoformat()

                        self._process_line(line, now_utc)

                    except serial.SerialException:
                        logger.warning("Serial connection lost on %s", port)
                        break
                    except Exception as e:
                        logger.error("Error reading serial: %s", e, exc_info=True)
                        self.stats['parser_errors'] += 1

                try:
                    ser.close()
                except Exception:
                    pass

            except serial.SerialException as e:
                logger.warning("Cannot open %s: %s", port, e)
            except Exception as e:
                logger.error("Serial worker error: %s", e, exc_info=True)

            self.stats['connected'] = False
            if not self._stop_event.is_set():
                logger.info("Reconnecting in %.1fs...", self._reconnect_delay)
                self._stop_event.wait(self._reconnect_delay)

    def _run_demo(self, demo_cfg):
        """Replay serial lines from a file for testing without hardware."""
        replay_file = demo_cfg.get('replay_file', 'tests/sample_serial_output.txt')
        speed = demo_cfg.get('replay_speed', 1.0)
        delay = 0.1 / max(speed, 0.01)

        self.stats['connected'] = True
        self.stats['port'] = f'demo:{replay_file}'
        logger.info("Demo mode: replaying %s at %.1fx speed", replay_file, speed)

        while not self._stop_event.is_set():
            if not os.path.exists(replay_file):
                logger.error("Demo replay file not found: %s", replay_file)
                self._stop_event.wait(5)
                continue

            with open(replay_file, 'r') as f:
                for line in f:
                    if self._stop_event.is_set():
                        return
                    line = line.rstrip('\r\n')
                    now_utc = datetime.now(timezone.utc)
                    self.stats['bytes_read'] += len(line)
                    self.stats['lines_read'] += 1
                    self.stats['last_line_time'] = now_utc.isoformat()
                    self._process_line(line, now_utc)
                    self._stop_event.wait(delay)

            logger.info("Demo replay complete, looping...")

    # ---- port detection ----

    def _find_port(self):
        """Auto-detect the serial port or return the configured one."""
        if self._port != 'auto':
            return self._port

        try:
            import serial.tools.list_ports
            ports = serial.tools.list_ports.comports()
            for p in ports:
                desc = (p.description or '').lower()
                if any(chip in desc for chip in ['cp210', 'ch340', 'ftdi', 'usb serial', 'esp32']):
                    return p.device
                if p.vid in (0x10C4, 0x1A86, 0x0403):
                    return p.device

            # Fallback: common Linux serial device paths
            for candidate in ['/dev/ttyUSB0', '/dev/ttyACM0', '/dev/ttyUSB1']:
                if os.path.exists(candidate):
                    return candidate
        except Exception as e:
            logger.error("Error detecting serial port: %s", e)

        return None

    # ---- line processing ----

    def _process_line(self, line, now_utc):
        """Parse one serial line and store the result."""
        result = parse_line(line)

        try:
            with self.app.app_context():
                from uwb_web.models import RawLine, Measurement, Event
                from uwb_web.services.device_service import get_or_create_device
                from uwb_web.db import db

                store_raw = self.config.get('retention', {}).get('store_raw_lines', True)

                # Store raw line
                raw_line_id = None
                if store_raw and result.line_type != 'blank':
                    raw = RawLine(
                        session_id=self.current_session_id,
                        pi_received_at_utc=now_utc,
                        line_text=line[:2000],  # cap length for safety
                        line_type_guess=result.line_type,
                        parser_status='parsed' if result.line_type != 'unknown' else 'unknown',
                    )
                    db.session.add(raw)
                    db.session.flush()
                    raw_line_id = raw.id

                if result.line_type == 'measurement' and result.short_addr_hex:
                    device = get_or_create_device(result.short_addr_hex, result.short_addr_int, now_utc)
                    m = Measurement(
                        session_id=self.current_session_id,
                        device_id=device.id,
                        pi_received_at_utc=now_utc,
                        range_m=result.range_m,
                        rx_power_dbm=result.rx_power_dbm,
                        parse_source='main_range_line',
                        raw_line_id=raw_line_id,
                    )
                    db.session.add(m)
                    self.stats['measurements_ingested'] += 1

                    # Update live cache
                    with self._cache_lock:
                        self.live_cache[result.short_addr_hex] = {
                            'short_addr_hex': result.short_addr_hex,
                            'device_id': device.id,
                            'label': device.label,
                            'range_m': result.range_m,
                            'rx_power_dbm': result.rx_power_dbm,
                            'last_seen': now_utc.isoformat(),
                            'is_anchor': device.is_anchor,
                        }

                    # Update recent values for sparklines
                    with self._recent_lock:
                        if result.short_addr_hex not in self.recent_values:
                            self.recent_values[result.short_addr_hex] = deque(maxlen=30)
                        self.recent_values[result.short_addr_hex].append({
                            'range_m': result.range_m,
                            'ts': now_utc.isoformat(),
                        })

                    # Broadcast SSE
                    if self.sse_broadcaster:
                        self.sse_broadcaster.publish({
                            'type': 'measurement',
                            'device': result.short_addr_hex,
                            'device_id': device.id,
                            'label': device.label,
                            'range_m': result.range_m,
                            'rx_power_dbm': result.rx_power_dbm,
                            'timestamp': now_utc.isoformat(),
                        })

                    # Position estimation
                    self._update_position(device.id, result.range_m, now_utc)

                elif result.line_type in ('device_added', 'device_inactive') and result.short_addr_hex:
                    device = get_or_create_device(result.short_addr_hex, result.short_addr_int, now_utc)
                    if result.line_type == 'device_inactive':
                        device.is_active = False
                    else:
                        device.is_active = True
                    evt = Event(
                        session_id=self.current_session_id,
                        device_id=device.id,
                        event_time_utc=now_utc,
                        event_type=result.event_type or result.line_type,
                        event_text=result.event_text or line,
                        raw_line_id=raw_line_id,
                    )
                    db.session.add(evt)
                    self.stats['events_ingested'] += 1

                    if self.sse_broadcaster:
                        self.sse_broadcaster.publish({
                            'type': 'event',
                            'event_type': result.event_type,
                            'device': result.short_addr_hex,
                            'text': result.event_text,
                            'timestamp': now_utc.isoformat(),
                        })

                elif result.line_type == 'unknown':
                    evt = Event(
                        session_id=self.current_session_id,
                        event_time_utc=now_utc,
                        event_type='parser_warning',
                        event_text=f'Unknown line: {line[:500]}',
                        raw_line_id=raw_line_id,
                    )
                    db.session.add(evt)

                db.session.commit()

        except Exception as e:
            logger.error("Error processing line '%s': %s", line[:100], e, exc_info=True)
            self.stats['parser_errors'] += 1
            try:
                with self.app.app_context():
                    from uwb_web.db import db
                    db.session.rollback()
            except Exception:
                pass

    # ---- session management ----

    def _ensure_session(self):
        """Ensure an active session exists to log measurements into."""
        try:
            with self.app.app_context():
                from uwb_web.services.session_service import get_active_session, create_session
                session = get_active_session()
                if session:
                    self.current_session_id = session.id
                    self.is_logging = True
                    logger.info("Resuming session '%s' (id=%d)", session.name, session.id)
                else:
                    session = create_session()
                    self.current_session_id = session.id
                    self.is_logging = True
                    logger.info("Created new session '%s' (id=%d)", session.name, session.id)
        except Exception as e:
            logger.error("Error ensuring session: %s", e, exc_info=True)

    def start_logging(self, session_id):
        self.current_session_id = session_id
        self.is_logging = True

    def stop_logging(self):
        self.is_logging = False
        self.current_session_id = None

    # ---- event helpers ----

    def _store_event(self, event_type, text):
        try:
            with self.app.app_context():
                from uwb_web.models import Event
                from uwb_web.db import db
                evt = Event(
                    session_id=self.current_session_id,
                    event_time_utc=datetime.now(timezone.utc),
                    event_type=event_type,
                    event_text=text,
                )
                db.session.add(evt)
                db.session.commit()
        except Exception as e:
            logger.error("Error storing event: %s", e)

    # ---- public accessors ----

    def get_live_data(self):
        with self._cache_lock:
            return dict(self.live_cache)

    def get_recent_values(self):
        with self._recent_lock:
            return {k: list(v) for k, v in self.recent_values.items()}

    def get_position(self):
        """Return current position estimate and history."""
        with self._position_lock:
            return {
                'position': self.last_position,
                'history': list(self.position_history),
            }

    # ---- position estimation ----

    def _load_engine_settings(self):
        """One-time load of engine settings and calibration weights."""
        if self._engine_loaded:
            return
        try:
            from uwb_web.services.config_service import get_config
            from uwb_web.services.calibration import get_active_corrections
            from uwb_web.services.position_engine import build_anchor_weights
            import json

            corrections = get_active_corrections(self.app)
            if corrections:
                self._engine.set_anchor_weights(build_anchor_weights(corrections))

            # Load tuneable settings from DB (if stored)
            raw = get_config('engine_settings')
            if raw:
                cfg = json.loads(raw)
                self._engine.load_settings(cfg)

            self._engine_loaded = True
        except Exception as e:
            logger.debug('Engine settings load: %s', e)

    def reload_engine(self):
        """Called when calibration / engine settings change."""
        self._engine_loaded = False
        self._engine.reset()

    def get_engine(self):
        """Public accessor for the position engine."""
        return self._engine

    def _update_position(self, device_id, range_m, now_utc):
        """Run filtered trilateration after each measurement."""
        filtered = self._filter_bank.filter_range(device_id, range_m)
        if filtered is None:
            return

        self._filtered_ranges[device_id] = filtered

        try:
            with self.app.app_context():
                from uwb_web.models import Device
                from uwb_web.services.calibration import get_active_corrections, correct_ranges

                self._load_engine_settings()

                anchors_2d = {}
                anchors_3d = {}
                anchor_z = {}
                for d in Device.query.filter_by(is_anchor=True).all():
                    if d.x is not None and d.y is not None:
                        anchors_2d[d.id] = (d.x, d.y)
                        if d.z is not None:
                            anchors_3d[d.id] = (d.x, d.y, d.z)
                            anchor_z[d.id] = d.z
                self._engine.set_anchor_heights(anchor_z)

                # Apply calibration corrections if enabled
                ranges_for_pos = correct_ranges(
                    self._filtered_ranges,
                    get_active_corrections(self.app),
                )

                # Try advanced engine first (EKF + WLS + NLOS)
                result = self._engine.update(ranges_for_pos, anchors_2d)
                if result is not None:
                    entry = {
                        'x': result['x'], 'y': result['y'],
                        'ts': now_utc.isoformat(),
                        'vx': result.get('vx', 0),
                        'vy': result.get('vy', 0),
                        'confidence': result.get('confidence', 0),
                        'method': result.get('method', 'ekf'),
                    }
                    if result.get('covariance'):
                        entry['covariance'] = result['covariance']
                    if result.get('rejected_anchors'):
                        entry['rejected'] = result['rejected_anchors']
                    with self._position_lock:
                        self.last_position = entry
                        self.position_history.append(entry)
                    if self.sse_broadcaster:
                        self.sse_broadcaster.publish({'type': 'position', **entry})
                    return

                # Fallback to basic trilateration
                from uwb_web.services.position_engine import _project_ranges_2d
                projected = _project_ranges_2d(ranges_for_pos, anchor_z, self._engine.tag_z)
                pos = None
                if len(anchors_3d) >= 4:
                    pos = estimate_position_3d(projected, anchors_3d)
                if pos is None and len(anchors_2d) >= 3:
                    pos = estimate_position_2d(projected, anchors_2d)

                if pos is not None:
                    entry = {'x': pos[0], 'y': pos[1], 'ts': now_utc.isoformat()}
                    if len(pos) == 3:
                        entry['z'] = pos[2]
                    with self._position_lock:
                        self.last_position = entry
                        self.position_history.append(entry)

                    if self.sse_broadcaster:
                        self.sse_broadcaster.publish({
                            'type': 'position',
                            **entry,
                        })
        except Exception as e:
            logger.debug("Position estimation error: %s", e)
