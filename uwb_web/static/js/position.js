/* position.js — Live 2D position map with SSE updates */

(function() {
    var canvas = document.getElementById('pos-canvas');
    var ctx = canvas.getContext('2d');
    var MAX_TRAIL = 200;

    // Live ranges per device hex
    var liveRanges = {};
    for (var hex in initialLive) {
        if (initialLive[hex].range_m != null) {
            liveRanges[hex] = initialLive[hex].range_m;
        }
    }

    // Controls
    var showTrail = document.getElementById('show-trail');
    var showRanges = document.getElementById('show-ranges');
    var autoCenter = document.getElementById('auto-center');

    // Stats
    var statCount = document.getElementById('stat-count');
    var posCoords = document.getElementById('pos-coords');
    var posTime = document.getElementById('pos-time');

    // DPI scaling
    function resizeCanvas() {
        var rect = canvas.parentElement.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = 500 * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = '500px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    }

    // Compute view bounds from anchors + positions
    function computeBounds() {
        var pts = anchors.map(function(a) { return [a.x, a.y]; });
        posHistory.forEach(function(p) { pts.push([p.x, p.y]); });
        if (pts.length === 0) return { xmin: -5, xmax: 5, ymin: -5, ymax: 5 };

        var xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
        pts.forEach(function(p) {
            if (p[0] < xmin) xmin = p[0];
            if (p[0] > xmax) xmax = p[0];
            if (p[1] < ymin) ymin = p[1];
            if (p[1] > ymax) ymax = p[1];
        });

        // Add padding (20% or minimum 2m)
        var dx = Math.max((xmax - xmin) * 0.2, 2);
        var dy = Math.max((ymax - ymin) * 0.2, 2);
        return { xmin: xmin - dx, xmax: xmax + dx, ymin: ymin - dy, ymax: ymax + dy };
    }

    // Transform world coords -> canvas pixel coords
    function worldToCanvas(wx, wy, bounds, w, h) {
        var bw = bounds.xmax - bounds.xmin;
        var bh = bounds.ymax - bounds.ymin;
        // Uniform scale (fit both axes)
        var scale = Math.min(w / bw, h / bh);
        var ox = (w - bw * scale) / 2;
        var oy = (h - bh * scale) / 2;
        return {
            x: ox + (wx - bounds.xmin) * scale,
            y: oy + (bounds.ymax - wy) * scale,  // flip Y
            scale: scale
        };
    }

    function draw() {
        var w = canvas.clientWidth;
        var h = canvas.clientHeight;
        ctx.clearRect(0, 0, w, h);

        var bounds = computeBounds();

        // Grid
        drawGrid(bounds, w, h);

        // Range circles (if enabled)
        if (showRanges.checked) {
            anchors.forEach(function(a) {
                var range = liveRanges[a.hex];
                if (range != null && range > 0) {
                    var cp = worldToCanvas(a.x, a.y, bounds, w, h);
                    var rp = range * cp.scale;
                    ctx.beginPath();
                    ctx.arc(cp.x, cp.y, rp, 0, Math.PI * 2);
                    ctx.strokeStyle = 'rgba(0,151,230,0.2)';
                    ctx.lineWidth = 1;
                    ctx.stroke();
                }
            });
        }

        // Trail
        if (showTrail.checked && posHistory.length > 1) {
            ctx.beginPath();
            for (var i = 0; i < posHistory.length; i++) {
                var p = worldToCanvas(posHistory[i].x, posHistory[i].y, bounds, w, h);
                if (i === 0) ctx.moveTo(p.x, p.y);
                else ctx.lineTo(p.x, p.y);
            }
            ctx.strokeStyle = 'rgba(228,65,24,0.3)';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Trail dots
            posHistory.forEach(function(pt, idx) {
                var alpha = 0.1 + 0.4 * (idx / posHistory.length);
                var pp = worldToCanvas(pt.x, pt.y, bounds, w, h);
                ctx.beginPath();
                ctx.arc(pp.x, pp.y, 3, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(228,65,24,' + alpha.toFixed(2) + ')';
                ctx.fill();
            });
        }

        // Anchors
        anchors.forEach(function(a) {
            var ap = worldToCanvas(a.x, a.y, bounds, w, h);
            ctx.beginPath();
            ctx.arc(ap.x, ap.y, 8, 0, Math.PI * 2);
            ctx.fillStyle = '#0097e6';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Label
            ctx.font = '12px -apple-system, BlinkMacSystemFont, sans-serif';
            ctx.fillStyle = '#2f3640';
            ctx.textAlign = 'center';
            ctx.fillText(a.label, ap.x, ap.y - 14);

            // Coordinate
            ctx.font = '10px monospace';
            ctx.fillStyle = '#7f8fa6';
            ctx.fillText('(' + a.x + ', ' + a.y + ')', ap.x, ap.y + 22);
        });

        // Current position (last in history)
        if (posHistory.length > 0) {
            var last = posHistory[posHistory.length - 1];
            var lp = worldToCanvas(last.x, last.y, bounds, w, h);

            // Pulsing outer ring
            ctx.beginPath();
            ctx.arc(lp.x, lp.y, 14, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(232,65,24,0.2)';
            ctx.fill();

            // Inner dot
            ctx.beginPath();
            ctx.arc(lp.x, lp.y, 7, 0, Math.PI * 2);
            ctx.fillStyle = '#e84118';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Coordinate label
            ctx.font = 'bold 11px monospace';
            ctx.fillStyle = '#e84118';
            ctx.textAlign = 'center';
            var label = last.x.toFixed(2) + ', ' + last.y.toFixed(2);
            if (last.z != null) label += ', ' + last.z.toFixed(2);
            ctx.fillText('(' + label + ')', lp.x, lp.y - 20);
        }
    }

    function drawGrid(bounds, w, h) {
        // Choose grid step based on extent
        var extent = Math.max(bounds.xmax - bounds.xmin, bounds.ymax - bounds.ymin);
        var step = 1;
        if (extent > 20) step = 5;
        if (extent > 50) step = 10;
        if (extent > 200) step = 50;

        ctx.strokeStyle = '#eee';
        ctx.lineWidth = 1;
        ctx.font = '9px monospace';
        ctx.fillStyle = '#ccc';
        ctx.textAlign = 'left';

        // Vertical lines
        var xs = Math.floor(bounds.xmin / step) * step;
        for (var x = xs; x <= bounds.xmax; x += step) {
            var p = worldToCanvas(x, 0, bounds, w, h);
            ctx.beginPath();
            ctx.moveTo(p.x, 0);
            ctx.lineTo(p.x, h);
            ctx.stroke();
            ctx.fillText(x.toFixed(0) + 'm', p.x + 2, h - 4);
        }

        // Horizontal lines
        var ys = Math.floor(bounds.ymin / step) * step;
        for (var y = ys; y <= bounds.ymax; y += step) {
            var p = worldToCanvas(0, y, bounds, w, h);
            ctx.beginPath();
            ctx.moveTo(0, p.y);
            ctx.lineTo(w, p.y);
            ctx.stroke();
            ctx.fillText(y.toFixed(0) + 'm', 2, p.y - 2);
        }
    }

    // Update sidebar displays
    function updateSidebar() {
        if (posHistory.length > 0) {
            var last = posHistory[posHistory.length - 1];
            var txt = 'X: ' + last.x.toFixed(3) + '  Y: ' + last.y.toFixed(3);
            if (last.z != null) txt += '  Z: ' + last.z.toFixed(3);
            posCoords.textContent = txt;
            posTime.textContent = timeAgo(last.ts);
        } else {
            posCoords.textContent = '—';
            posTime.textContent = 'Waiting for position data…';
        }
        statCount.textContent = posHistory.length;

        // Update live ranges
        anchors.forEach(function(a) {
            var el = document.getElementById('range-anchor-' + a.hex);
            if (el) {
                var r = liveRanges[a.hex];
                el.textContent = r != null ? r.toFixed(3) + ' m' : '—';
            }
        });
    }

    // SSE connection
    function connectSSE() {
        var sse = new EventSource('/api/sse');
        sse.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                if (data.type === 'position') {
                    var entry = { x: data.x, y: data.y, ts: data.ts };
                    if (data.z != null) entry.z = data.z;
                    posHistory.push(entry);
                    if (posHistory.length > MAX_TRAIL) posHistory.shift();
                    draw();
                    updateSidebar();
                } else if (data.type === 'measurement') {
                    liveRanges[data.device] = data.range_m;
                    updateSidebar();
                    if (showRanges.checked) draw();
                }
            } catch(e) { /* ignore */ }
        };
    }

    // Redraw on settings change
    showTrail.addEventListener('change', draw);
    showRanges.addEventListener('change', draw);
    autoCenter.addEventListener('change', draw);

    // Init
    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();
    updateSidebar();
    connectSSE();
})();
