/* common.js — Shared utilities */

/**
 * Format an ISO timestamp string as a human-readable "time ago" string.
 */
function timeAgo(isoStr) {
    if (!isoStr) return '—';
    var d = new Date(isoStr);
    var now = new Date();
    var sec = Math.floor((now - d) / 1000);
    if (sec < 0) sec = 0;
    if (sec < 5) return 'just now';
    if (sec < 60) return sec + 's ago';
    var min = Math.floor(sec / 60);
    if (min < 60) return min + 'm ago';
    var hr = Math.floor(min / 60);
    if (hr < 24) return hr + 'h ago';
    return Math.floor(hr / 24) + 'd ago';
}

/**
 * Update all elements with class "time-ago" based on their data-ts attribute.
 */
function updateTimeAgos() {
    document.querySelectorAll('.time-ago').forEach(function(el) {
        var ts = el.getAttribute('data-ts');
        el.textContent = timeAgo(ts);
    });
}

/**
 * Determine freshness badge class from ISO timestamp.
 */
function freshnessBadge(isoStr) {
    if (!isoStr) return { cls: 'badge-gray', text: 'Unknown' };
    var sec = (new Date() - new Date(isoStr)) / 1000;
    if (sec < 5) return { cls: 'badge-green', text: 'Fresh' };
    if (sec < 30) return { cls: 'badge-orange', text: 'Stale' };
    return { cls: 'badge-red', text: 'Offline' };
}

/**
 * Draw a simple sparkline SVG from an array of numeric values.
 */
function drawSparkline(svgEl, values) {
    if (!svgEl || !values || values.length < 2) {
        svgEl.innerHTML = '';
        return;
    }
    var w = svgEl.clientWidth || 200;
    var h = svgEl.clientHeight || 30;
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    var range = max - min || 1;
    var points = values.map(function(v, i) {
        var x = (i / (values.length - 1)) * w;
        var y = h - ((v - min) / range) * (h - 4) - 2;
        return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    svgEl.innerHTML = '<polyline points="' + points + '"/>';
}

// Update time-ago elements every 2 seconds
setInterval(updateTimeAgos, 2000);
document.addEventListener('DOMContentLoaded', updateTimeAgos);
