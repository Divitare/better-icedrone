/* measurements.js — Live measurement table updates with pause/resume */

(function() {
    var paused = false;
    var pauseBtn = document.getElementById('btn-pause');
    var tbody = document.getElementById('meas-body');
    var MAX_ROWS = 500;

    if (pauseBtn) {
        pauseBtn.addEventListener('click', function() {
            paused = !paused;
            pauseBtn.textContent = paused ? 'Resume' : 'Pause';
            pauseBtn.classList.toggle('btn-warning', paused);
        });
    }

    var sse = new EventSource('/api/sse');
    sse.onmessage = function(event) {
        if (paused) return;
        try {
            var data = JSON.parse(event.data);
            if (data.type !== 'measurement') return;
            var tr = document.createElement('tr');
            tr.innerHTML =
                '<td class="mono">' + (data.timestamp || '—') + '</td>' +
                '<td class="mono">' + (data.device || '—') + '</td>' +
                '<td>' + (data.label || '') + '</td>' +
                '<td class="mono">' + (data.range_m != null ? data.range_m.toFixed(3) : '—') + '</td>' +
                '<td class="mono">' + (data.rx_power_dbm != null ? data.rx_power_dbm.toFixed(1) : '—') + '</td>' +
                '<td>—</td>';
            if (tbody) {
                tbody.insertBefore(tr, tbody.firstChild);
                while (tbody.children.length > MAX_ROWS) {
                    tbody.removeChild(tbody.lastChild);
                }
            }
        } catch(e) {}
    };
})();
