"""Position estimation page — live 2D map with trilaterated tag position."""

from flask import Blueprint, render_template
from uwb_web.services import device_service

bp = Blueprint('position', __name__)


@bp.route('/position')
def index():
    from uwb_web import get_serial_worker

    worker = get_serial_worker()
    devices = device_service.get_all_devices()

    anchors = [d for d in devices if d.is_anchor and d.x is not None and d.y is not None]
    anchor_data = [{
        'id': a.id,
        'hex': a.short_addr_hex,
        'label': a.display_name,
        'x': a.x,
        'y': a.y,
        'z': a.z,
    } for a in anchors]

    fused = worker.get_fused_pose() if worker else {'pose': None, 'history': []}
    live_data = worker.get_live_data() if worker else {}

    return render_template(
        'position.html',
        anchors=anchor_data,
        position=fused['pose'],
        history=fused['history'],
        live_data=live_data,
        enough_anchors=len(anchors) >= 3,
    )
