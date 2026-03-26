"""Devices and configuration page."""

from flask import Blueprint, render_template, request, redirect, url_for
from uwb_web.services import device_service, config_service

bp = Blueprint('devices', __name__)


@bp.route('/devices')
def index():
    devices = device_service.get_all_devices()
    config = config_service.get_all_config()
    return render_template('devices.html', devices=devices, config=config)


@bp.route('/devices/<int:device_id>/update', methods=['POST'])
def update(device_id):
    kwargs = {}
    kwargs['label'] = request.form.get('label', '').strip() or None
    kwargs['is_expected'] = request.form.get('is_expected') == 'on'
    kwargs['is_anchor'] = request.form.get('is_anchor') == 'on'
    for coord in ('x', 'y', 'z'):
        val = request.form.get(coord, '').strip()
        kwargs[coord] = float(val) if val else None
    device_service.update_device(device_id, **kwargs)
    return redirect(url_for('devices.index'))


@bp.route('/config/update', methods=['POST'])
def update_config():
    for key in ('serial_port', 'serial_baud', 'retention_days_raw', 'retention_days_measurements'):
        if key in request.form:
            config_service.set_config(key, request.form[key])
    config_service.set_config(
        'store_raw_lines',
        'true' if request.form.get('store_raw_lines') == 'on' else 'false',
    )
    return redirect(url_for('devices.index'))
