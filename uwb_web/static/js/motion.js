/**
 * Motion Control page — talks to /motion/api/* endpoints.
 */
(function () {
    'use strict';

    var pollInterval = null;
    var logEl = document.getElementById('motion-log');

    // ---- Helpers ----

    function val(id) { return parseFloat(document.getElementById(id).value) || 0; }

    function addLog(msg) {
        var ts = new Date().toLocaleTimeString();
        var line = document.createElement('div');
        line.textContent = ts + '  ' + msg;
        logEl.appendChild(line);
        logEl.scrollTop = logEl.scrollHeight;
        // Keep last 200 lines
        while (logEl.childElementCount > 200) logEl.removeChild(logEl.firstChild);
    }

    function apiCall(url, method, body) {
        var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        return fetch(url, opts).then(function (r) { return r.json(); });
    }

    // ---- Commands ----

    window.motionCmd = function (url, method) {
        addLog('>> ' + url.split('/').pop());
        apiCall(url, method).then(function (r) {
            addLog('<< ' + (r.msg || r.status || 'ok'));
            pollStatus();
        }).catch(function (e) { addLog('ERR ' + e); });
    };

    window.jog = function (dx, dy, dz) {
        var step = val('jog-step');
        var speed = val('jog-speed');
        var body = { x: dx * step, y: dy * step, z: dz * step, speed: speed };
        addLog('>> jog ' + JSON.stringify(body));
        apiCall('/motion/api/move_rel', 'POST', body).then(function (r) {
            addLog('<< ' + (r.msg || r.status || 'ok'));
            pollStatus();
        }).catch(function (e) { addLog('ERR ' + e); });
    };

    window.moveAbsolute = function () {
        var body = { x: val('abs-x'), y: val('abs-y'), z: val('abs-z'), speed: val('abs-speed') };
        addLog('>> move_abs ' + JSON.stringify(body));
        apiCall('/motion/api/move_abs', 'POST', body).then(function (r) {
            addLog('<< ' + (r.msg || r.status || 'ok'));
            pollStatus();
        }).catch(function (e) { addLog('ERR ' + e); });
    };

    window.setAccel = function () {
        var accel = val('set-accel');
        addLog('>> set_accel ' + accel);
        apiCall('/motion/api/set_accel', 'POST', { accel: accel }).then(function (r) {
            addLog('<< ' + (r.msg || r.status || 'ok'));
        }).catch(function (e) { addLog('ERR ' + e); });
    };

    window.saveConnection = function () {
        var body = {
            host: document.getElementById('cfg-host').value.trim(),
            port: parseInt(document.getElementById('cfg-port').value) || 5001,
            connect_timeout: parseFloat(document.getElementById('cfg-ctimeout').value) || 2.0,
            read_timeout: parseFloat(document.getElementById('cfg-rtimeout').value) || 10.0
        };
        var msgEl = document.getElementById('cfg-msg');
        msgEl.textContent = 'Saving…';
        msgEl.style.color = 'var(--text-muted)';
        addLog('>> connection ' + body.host + ':' + body.port);
        apiCall('/motion/api/connection', 'POST', body).then(function (r) {
            if (r.status === 'ok') {
                msgEl.textContent = 'Saved ✓';
                msgEl.style.color = 'var(--green)';
                addLog('<< ' + (r.msg || 'ok'));
            } else {
                msgEl.textContent = r.msg || 'Error';
                msgEl.style.color = 'var(--red)';
                addLog('<< ERR ' + (r.msg || 'error'));
            }
        }).catch(function (e) {
            msgEl.textContent = 'Failed';
            msgEl.style.color = 'var(--red)';
            addLog('ERR ' + e);
        });
    };

    window.startGrid = function () {
        var body = {
            x: { start: val('gx-start'), space: val('gx-space'), n: parseInt(document.getElementById('gx-n').value) || 1 },
            y: { start: val('gy-start'), space: val('gy-space'), n: parseInt(document.getElementById('gy-n').value) || 1 },
            z: { start: val('gz-start'), space: val('gz-space'), n: parseInt(document.getElementById('gz-n').value) || 1 },
            pattern: document.getElementById('grid-pattern').value,
            speed: val('grid-speed'),
            accel: val('grid-accel'),
            wait: val('grid-wait'),
            repetitions: parseInt(document.getElementById('grid-reps').value) || 1
        };
        addLog('>> grid start');
        apiCall('/motion/api/grid', 'POST', body).then(function (r) {
            addLog('<< ' + (r.msg || r.status || 'ok'));
            pollStatus();
        }).catch(function (e) { addLog('ERR ' + e); });
    };

    // ---- Status polling ----

    var pollInFlight = false;

    function setText(id, v) { document.getElementById(id).textContent = v; }

    function updatePos(pos) {
        if (!pos) return;
        setText('pos-x', (pos.x != null ? pos.x.toFixed(3) : '—'));
        setText('pos-y', (pos.y != null ? pos.y.toFixed(3) : '—'));
        setText('pos-z', (pos.z != null ? pos.z.toFixed(3) : '—'));
    }

    function pollStatus() {
        if (pollInFlight) return; // don't stack requests
        pollInFlight = true;
        apiCall('/motion/api/status', 'GET').then(function (r) {
            pollInFlight = false;
            var dot = document.getElementById('conn-dot');
            var txt = document.getElementById('conn-text');

            if (r.status === 'error') {
                dot.className = 'conn-dot err';
                txt.textContent = r.msg || 'Error';
                return;
            }

            var s = r.state || {};
            dot.className = 'conn-dot' + (s.is_connected ? ' ok' : ' err');
            txt.textContent = s.is_connected ? 'Connected' : 'Disconnected';

            setText('st-conn', s.is_connected ? 'Yes' : 'No');
            setText('st-busy', s.is_busy ? 'Yes' : 'No');
            setText('st-moving', s.is_moving ? 'Yes' : 'No');
            setText('st-grid', s.is_grid_running ? 'Yes' : 'No');
            setText('st-queue', (s.queue_size || 0) + ' (' + (s.unfinished_tasks || 0) + ' unfinished)');
            setText('st-msg', s.status_msg || '—');

            if (s.pos) updatePos(s.pos);
        }).catch(function () {
            pollInFlight = false;
            var dot = document.getElementById('conn-dot');
            dot.className = 'conn-dot err';
            document.getElementById('conn-text').textContent = 'Controller unreachable';
        });
    }

    // Poll every 1s (safe interval — previous request must finish first)
    pollStatus();
    pollInterval = setInterval(pollStatus, 1000);

})();
