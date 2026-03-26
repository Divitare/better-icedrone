/* dashboard.js — SSE-driven live dashboard */

(function() {
    // In-memory sparkline buffers (per device addr)
    var sparkData = {};  // addr -> [range_m, ...]
    var MAX_SPARK = 30;

    // Seed from server-rendered data
    if (typeof recentValues !== 'undefined') {
        for (var addr in recentValues) {
            sparkData[addr] = recentValues[addr].map(function(v) { return v.range_m; });
        }
    }

    // Draw initial sparklines
    function drawAll() {
        for (var addr in sparkData) {
            var svg = document.getElementById('spark-' + addr);
            if (svg) drawSparkline(svg, sparkData[addr]);
        }
    }

    // Update freshness badges for all device cards
    function updateBadges() {
        document.querySelectorAll('.device-card').forEach(function(card) {
            var addr = card.getAttribute('data-addr');
            var seenEl = document.getElementById('seen-' + addr);
            var badgeEl = document.getElementById('status-' + addr);
            if (seenEl && badgeEl) {
                var ts = seenEl.getAttribute('data-ts');
                var fb = freshnessBadge(ts);
                badgeEl.className = 'badge status-badge ' + fb.cls;
                badgeEl.textContent = fb.text;
            }
        });
    }

    // Connect to SSE
    var sse = null;
    function connectSSE() {
        sse = new EventSource('/api/sse');
        var sseBadge = document.getElementById('sse-badge');

        sse.onopen = function() {
            if (sseBadge) {
                sseBadge.className = 'badge badge-green';
                sseBadge.textContent = 'Connected';
            }
        };

        sse.onerror = function() {
            if (sseBadge) {
                sseBadge.className = 'badge badge-red';
                sseBadge.textContent = 'Disconnected';
            }
            // Reconnect handled automatically by EventSource
        };

        sse.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                if (data.type === 'measurement') {
                    updateDeviceCard(data);
                } else if (data.type === 'event') {
                    // Could show a notification
                }
            } catch(e) {
                // ignore parse errors
            }
        };
    }

    function updateDeviceCard(data) {
        var addr = data.device;
        // Update range
        var rangeEl = document.getElementById('range-' + addr);
        if (rangeEl) rangeEl.textContent = (data.range_m != null ? data.range_m.toFixed(3) : '—') + ' m';

        // Update RX power
        var rxEl = document.getElementById('rxpow-' + addr);
        if (rxEl) rxEl.textContent = (data.rx_power_dbm != null ? data.rx_power_dbm.toFixed(1) : '—') + ' dBm';

        // Update last seen
        var seenEl = document.getElementById('seen-' + addr);
        if (seenEl) {
            seenEl.setAttribute('data-ts', data.timestamp);
            seenEl.textContent = timeAgo(data.timestamp);
        }

        // Sparkline data
        if (!sparkData[addr]) sparkData[addr] = [];
        if (data.range_m != null) {
            sparkData[addr].push(data.range_m);
            if (sparkData[addr].length > MAX_SPARK) sparkData[addr].shift();
            var svg = document.getElementById('spark-' + addr);
            if (svg) drawSparkline(svg, sparkData[addr]);
        }
    }

    // Init
    drawAll();
    updateBadges();
    setInterval(updateBadges, 2000);
    connectSSE();
})();
