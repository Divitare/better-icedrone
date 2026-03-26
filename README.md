# UWB Web — Raspberry Pi UWB Range Logger & Visualizer

A Flask-based web application for logging and visualizing UWB (Ultra-Wideband) range data from **Makerfabs ESP32 UWB Pro with Display** modules connected via USB serial to a **Raspberry Pi 5**.

## Features

- **Live dashboard** with per-device range, RX power, freshness badges, and sparklines
- **Background serial ingestion** with auto-reconnect on USB disconnect
- **SQLite storage** for measurements, events, raw serial lines
- **Session-based logging** — start/stop/rename/export sessions
- **CSV export** by time range, session, and device
- **Server-Sent Events (SSE)** for real-time browser updates
- **Robust parser** for the Makerfabs default firmware serial output
- **Demo mode** for testing without hardware
- **systemd integration** for headless operation on Raspberry Pi
- **Scaffolded** for future trilateration / 3D position estimation

---

## Hardware Setup

```
[Anchor 1]         [Anchor 2]
  (DW1000)           (DW1000)
      \                 /
       \               /
        \   UWB RF    /
         +-----------+
         |  Tag/Recv |  <--- USB cable ---> Raspberry Pi 5
         | (DW1000)  |       Serial          (runs this app)
         +-----------+
        /               \
       /                 \
[Anchor 3]         [Anchor 4]
```

- **Tag/Receiver**: One Makerfabs ESP32 UWB Pro board connected to the Pi via USB.
- **Anchors**: Four (or more) boards placed at known positions, running the default Makerfabs ranging firmware.
- **Baud rate**: 115200 (Makerfabs default).

---

## Quick Start — Raspberry Pi

### Automated Install

```bash
curl -sSL https://raw.githubusercontent.com/Divitare/better-icedrone/main/install.sh | sudo bash
```

This will:
1. Install system dependencies (Python 3, git, etc.)
2. Clone the repo to `/opt/uwb-web`
3. Create a Python virtual environment
4. Initialize the SQLite database
5. Install and start a systemd service
6. Print the URL to access the web UI

### Manual Install

```bash
# Clone
git clone https://github.com/Divitare/better-icedrone.git
cd better-icedrone

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Initialize database
python scripts/init_db.py

# Run development server
python app.py
```

Open **http://\<pi-ip\>:5000** in a browser.

### Update Existing Installation

```bash
cd /opt/uwb-web
sudo bash install.sh
# Choose option 1 to update code + deps (keeps data & config)
```

---

## Configuration

Edit `config.yaml` (or `/opt/uwb-web/config.yaml` for system install):

```yaml
serial:
  port: auto          # 'auto' detects ESP32 USB, or set '/dev/ttyUSB0'
  baud: 115200
  timeout: 1.0
  reconnect_delay: 3.0

database:
  path: data/uwb_data.db

web:
  host: 0.0.0.0
  port: 5000
  debug: false

demo:
  enabled: false      # Set to true to replay sample data without hardware
  replay_file: tests/sample_serial_output.txt
  replay_speed: 1.0
```

---

## Demo Mode (No Hardware)

To test the UI without a real UWB board:

**Option A — Built-in demo mode:**
Set `demo.enabled: true` in `config.yaml` and start the app normally.

**Option B — Replay script:**
```bash
source venv/bin/activate
python scripts/demo_serial_replay.py --speed 5.0
```

---

## Running as a systemd Service

The installer sets this up automatically. Manual setup:

```bash
sudo cp systemd/uwb-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable uwb-web
sudo systemctl start uwb-web
```

View logs:
```bash
sudo journalctl -u uwb-web -f
```

---

## Project Structure

```
better-icedrone/
├── app.py                      # Dev server entry point
├── wsgi.py                     # Production WSGI entry point
├── config.yaml                 # Configuration file
├── requirements.txt
├── install.sh                  # Automated installer/updater
│
├── uwb_web/
│   ├── __init__.py             # App factory (create_app)
│   ├── config.py               # Config loader
│   ├── db.py                   # SQLAlchemy instance
│   ├── models.py               # All database models
│   ├── parser.py               # Serial line parser
│   ├── serial_worker.py        # Background serial reader thread
│   ├── sse.py                  # SSE broadcaster
│   │
│   ├── services/               # Business logic layer
│   │   ├── config_service.py
│   │   ├── device_service.py
│   │   ├── export_service.py
│   │   ├── measurement_service.py
│   │   ├── session_service.py
│   │   ├── filtering.py        # Phase 2 placeholder
│   │   └── trilateration.py    # Phase 2 placeholder
│   │
│   ├── routes/                 # Flask blueprints
│   │   ├── api.py              # JSON API + SSE endpoint
│   │   ├── dashboard.py
│   │   ├── devices.py
│   │   ├── export.py           # CSV download endpoints
│   │   ├── logs.py
│   │   ├── measurements.py
│   │   ├── sessions.py
│   │   └── system.py
│   │
│   ├── templates/              # Jinja2 HTML templates
│   └── static/                 # CSS + vanilla JS
│
├── scripts/
│   ├── init_db.py              # Database initialization
│   └── demo_serial_replay.py   # Replay sample data into DB
│
├── tests/
│   ├── test_parser.py          # Parser unit tests
│   ├── test_models.py          # Model + service tests
│   └── sample_serial_output.txt
│
├── systemd/
│   ├── uwb-web.service         # Main service file
│   └── uwb-serial.service      # Future: standalone serial worker
│
└── data/                       # Runtime data (DB, logs) — gitignored
```

---

## Database Schema

| Table | Purpose |
|-------|---------|
| **sessions** | Logical logging runs (start/end, name, notes) |
| **devices** | Known UWB device addresses with labels, coordinates |
| **measurements** | Parsed range + RX power readings with Pi timestamp |
| **events** | Lifecycle events (device add/remove, reconnect, errors) |
| **raw_lines** | Every serial line for debugging (optional retention) |
| **app_config** | Persistent key-value settings |

Key design choices:
- All timestamps are UTC.
- Device identity is the DW1000 short address in canonical uppercase hex.
- Measurements are linked to sessions and devices via foreign keys.
- Composite index on `(session_id, device_id, pi_received_at_utc)` for fast filtered queries and CSV export.

---

## Parser Logic

The parser (`uwb_web/parser.py`) classifies each serial line:

| Pattern | Classification |
|---------|---------------|
| `from: 1786  Range: 2.43 m  RX power: -75.31 dBm` | **measurement** — extracts addr, range, power |
| `ranging init; 1 device added ! -> short:1786` | **device_added** event |
| `blink; 1 device added ! -> short:2A3F` | **device_added** event |
| `delete inactive device: 4B01` | **device_inactive** event |
| `add_link:find struct Link end` | **debug_noise** — ignored |
| `find_link:Link is empty` | **debug_noise** — ignored |
| `fresh_link:Fresh fail` | **debug_noise** — ignored |
| Bare hex (`1786`) or bare float (`2.43`) | **debug_noise** (display refresh artifact) |
| Empty/whitespace | **blank** |
| Anything else | **unknown** — stored for debugging |

The parser is tolerant of tabs vs spaces, CRLF vs LF, and serial garbage. It never raises exceptions.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | System status + active session |
| GET | `/api/devices` | Device list with live data |
| GET | `/api/measurements?limit=&device_id=&session_id=&start=&end=` | Filtered measurements |
| GET | `/api/sessions` | All sessions with counts |
| POST | `/api/sessions/start` | Start new session |
| POST | `/api/sessions/end` | End current session |
| GET | `/api/events?limit=` | Recent events |
| GET | `/api/config` | App config key-values |
| POST | `/api/config` | Update config |
| DELETE | `/api/measurements` | Delete filtered measurements |
| DELETE | `/api/sessions/<id>` | Delete session + data |
| POST | `/api/clear-all` | Clear all data (requires confirm) |
| GET | `/api/sse` | SSE stream for live updates |
| GET | `/export/measurements?...` | CSV download |
| GET | `/export/raw_lines?...` | CSV download |
| GET | `/export/events?...` | CSV download |

---

## Running Tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

---

## Phase 2 Roadmap

- [ ] 3D trilateration from 4+ anchor ranges
- [ ] 2D position scatter plot
- [ ] Kalman filter tracking
- [ ] Outlier rejection and signal filtering
- [ ] Position CSV export
- [ ] Standalone serial worker process

---

## License

See LICENSE file (if applicable).
