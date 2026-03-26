#!/usr/bin/env python3
"""Development entry point — run Flask dev server."""

from uwb_web import create_app
from uwb_web.config import load_config

config = load_config()
app = create_app()

if __name__ == '__main__':
    app.run(
        host=config['web']['host'],
        port=config['web']['port'],
        debug=config['web']['debug'],
        threaded=True,
    )
