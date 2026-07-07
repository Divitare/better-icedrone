/* measurements.js — Live measurement table updates with pause/resume */

(function() {
    var STORAGE_KEY = 'uwb.measurements.paused';
    var paused = localStorage.getItem(STORAGE_KEY) === 'true';
    var pauseBtn = document.getElementById('btn-pause');
    var pauseState = document.getElementById('pause-state');
    var tbody = document.getElementById('meas-body');
    var MAX_ROWS = 500;
    var page = (typeof measurementPage !== 'undefined') ? measurementPage : {};

    function updatePauseUi() {
        if (pauseBtn) {
            pauseBtn.textContent = paused ? 'Resume' : 'Pause';
            pauseBtn.classList.toggle('btn-warning', paused);
        }
        if (pauseState) {
            pauseState.textContent = paused ? 'Paused' : 'Live';
            pauseState.className = 'badge ' + (paused ? 'badge-orange' : 'badge-green');
        }
    }

    function shouldShow(data) {
        if (page.selectedDeviceId && data.device_id !== page.selectedDeviceId) {
            return false;
        }
        if (page.selectedSessionId && data.session_id !== page.selectedSessionId) {
            return false;
        }
        return true;
    }

    function sessionName(sessionId) {
        if (!sessionId) return '—';
        if (page.sessionNames && page.sessionNames[sessionId]) {
            return page.sessionNames[sessionId];
        }
        return String(sessionId);
    }

    if (pauseBtn) {
        pauseBtn.addEventListener('click', function() {
            paused = !paused;
            localStorage.setItem(STORAGE_KEY, paused ? 'true' : 'false');
            updatePauseUi();
        });
    }
    updatePauseUi();

    var sse = new EventSource('/api/sse');
    sse.onmessage = function(event) {
        if (paused) return;
        try {
            var data = JSON.parse(event.data);
            if (data.type !== 'measurement') return;
            if (!shouldShow(data)) return;
            var tr = document.createElement('tr');
            tr.innerHTML =
                '<td class="mono">' + (data.timestamp || '—') + '</td>' +
                '<td class="mono">' + (data.device || '—') + '</td>' +
                '<td>' + (data.label || '') + '</td>' +
                '<td class="mono">' + (data.range_m != null ? data.range_m.toFixed(3) : '—') + '</td>' +
                '<td class="mono">' + (data.rx_power_dbm != null ? data.rx_power_dbm.toFixed(1) : '—') + '</td>' +
                '<td>' + sessionName(data.session_id) + '</td>';
            if (tbody) {
                tbody.insertBefore(tr, tbody.firstChild);
                while (tbody.children.length > MAX_ROWS) {
                    tbody.removeChild(tbody.lastChild);
                }
            }
        } catch(e) {}
    };
})();
