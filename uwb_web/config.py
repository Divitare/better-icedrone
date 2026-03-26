"""Configuration loader for UWB Web application."""

import os
import yaml

DEFAULT_CONFIG = {
    'serial': {
        'port': 'auto',
        'baud': 115200,
        'timeout': 1.0,
        'reconnect_delay': 3.0,
    },
    'database': {
        'path': 'data/uwb_data.db',
    },
    'logging': {
        'level': 'INFO',
        'file': 'data/uwb_web.log',
    },
    'web': {
        'host': '0.0.0.0',
        'port': 5000,
        'debug': False,
    },
    'retention': {
        'raw_lines_days': 30,
        'measurements_days': 365,
        'store_raw_lines': True,
    },
    'demo': {
        'enabled': False,
        'replay_file': 'tests/sample_serial_output.txt',
        'replay_speed': 1.0,
    },
    'motion': {
        'host': '127.0.0.1',
        'port': 5000,
        'timeout': 10.0,
    },
}


def _deep_merge(base, override):
    """Recursively merge override dict into base dict."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_config(path=None):
    """Load configuration from YAML file, merged with defaults."""
    import copy
    config = copy.deepcopy(DEFAULT_CONFIG)

    if path is None:
        path = os.environ.get('UWB_CONFIG', 'config.yaml')

    if os.path.exists(path):
        with open(path, 'r') as f:
            user_config = yaml.safe_load(f) or {}
        _deep_merge(config, user_config)

    return config
