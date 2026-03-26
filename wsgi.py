"""WSGI entry point for gunicorn / production."""

from uwb_web import create_app

app = create_app()
