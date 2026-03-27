/**
 * Calibration page — talks to /calibration/api/* endpoints.
 */
(function () {
    'use strict';

    var pollTimer = null;
    var currentRunId = null;

    function val(id) { return parseFloat(document.getElementById(id).value) || 0; }
    function setText(id, v) { document.getElementById(id).textContent = v; }

    function api(url, method, body) {
        var opts = { method: method || 'GET', headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        return fetch(url, opts).then(function (r) { return r.json(); });
    }

    // ---- Grid point counter ----

    function updateTotal() {
        var nx = Math.max(1, parseInt(document.getElementById('gx-n').value) || 1);
        var ny = Math.max(1, parseInt(document.getElementById('gy-n').value) || 1);
        var nz = Math.max(1, parseInt(document.getElementById('gz-n').value) || 1);
        setText('cal-total', nx * ny * nz + ' points');
    }

    ['gx-n', 'gy-n', 'gz-n'].forEach(function (id) {
        document.getElementById(id).addEventListener('input', updateTotal);
    });
    updateTotal();

    // ---- Start / Cancel ----

    window.calStart = function () {
        var body = {
            origin_x: val('origin-x'),
            origin_y: val('origin-y'),
            origin_z: val('origin-z'),
            dwell: val('cal-dwell'),
            speed: val('cal-speed'),
            name: document.getElementById('cal-name').value.trim(),
            grid: {
                x: { start: val('gx-start'), spacing: val('gx-space'), count: parseInt(document.getElementById('gx-n').value) || 1 },
                y: { start: val('gy-start'), spacing: val('gy-space'), count: parseInt(document.getElementById('gy-n').value) || 1 },
                z: { start: val('gz-start'), spacing: val('gz-space'), count: parseInt(document.getElementById('gz-n').value) || 1 },
            }
        };

        api('/calibration/api/start', 'POST', body).then(function (r) {
            if (r.status === 'ok') {
                currentRunId = r.run_id;
                startPolling();
            } else {
                alert(r.msg || 'Failed to start.');
            }
        }).catch(function (e) { alert('Error: ' + e); });
    };

    window.calCancel = function () {
        api('/calibration/api/cancel', 'POST').then(function (r) {
            if (r.status !== 'ok') alert(r.msg || 'Cancel failed.');
        });
    };

    // ---- Status polling ----

    function startPolling() {
        document.getElementById('progress-panel').style.display = '';
        document.getElementById('btn-start').style.display = 'none';
        document.getElementById('btn-cancel').style.display = '';
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(pollStatus, 500);
        pollStatus();
    }

    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        document.getElementById('btn-start').style.display = '';
        document.getElementById('btn-cancel').style.display = 'none';
    }

    function pollStatus() {
        api('/calibration/api/status').then(function (r) {
            var dot = document.getElementById('run-dot');
            dot.className = 'status-dot ' + (r.status || 'idle');
            setText('run-status', r.status || 'idle');

            var p = r.progress || {};
            var pct = p.total ? Math.round((p.current / p.total) * 100) : 0;
            document.getElementById('progress-fill').style.width = pct + '%';
            setText('progress-text', (p.current || 0) + ' / ' + (p.total || 0) + '  —  ' + (p.phase || ''));

            if (r.status !== 'running') {
                stopPolling();
                if (r.run_id) {
                    currentRunId = r.run_id;
                    loadRunDetail(r.run_id);
                }
                loadRuns();
            }
        });
    }

    // ---- Run detail ----

    function loadRunDetail(id) {
        api('/calibration/api/runs/' + id).then(function (r) {
            currentRunId = r.id;
            showResults(r);
            showPoints(r.points);
        });
    }

    function showResults(run) {
        var panel = document.getElementById('results-panel');
        if (!run.results) { panel.style.display = 'none'; return; }
        panel.style.display = '';

        var res = run.results;
        renderStats('stats-before', res.stats_before);
        renderStats('stats-after', res.stats_after);

        // Corrections table
        var tbody = document.querySelector('#corr-table tbody');
        tbody.innerHTML = '';
        var corr = res.corrections || {};
        Object.keys(corr).forEach(function (did) {
            var c = corr[did];
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + (c.hex || did) + '</td>'
                + '<td>' + c.bias.toFixed(4) + '</td>'
                + '<td>' + c.scale.toFixed(4) + '</td>'
                + '<td>' + c.mean_error.toFixed(4) + '</td>'
                + '<td>' + c.std_error.toFixed(4) + '</td>'
                + '<td>' + c.n_samples + '</td>';
            tbody.appendChild(tr);
        });
    }

    function renderStats(containerId, stats) {
        var el = document.getElementById(containerId);
        if (!stats || stats.n_points === 0) {
            el.innerHTML = '<div class="stat-box"><div class="stat-val">—</div><div class="stat-label">No data</div></div>';
            return;
        }
        el.innerHTML = ''
            + '<div class="stat-box"><div class="stat-val">' + (stats.rmse != null ? stats.rmse.toFixed(4) : '—') + '</div><div class="stat-label">RMSE (m)</div></div>'
            + '<div class="stat-box"><div class="stat-val">' + (stats.mean_error != null ? stats.mean_error.toFixed(4) : '—') + '</div><div class="stat-label">Mean (m)</div></div>'
            + '<div class="stat-box"><div class="stat-val">' + (stats.max_error != null ? stats.max_error.toFixed(4) : '—') + '</div><div class="stat-label">Max (m)</div></div>'
            + '<div class="stat-box"><div class="stat-val">' + stats.n_points + '</div><div class="stat-label">Points</div></div>';
    }

    function showPoints(points) {
        var panel = document.getElementById('points-panel');
        if (!points || points.length === 0) { panel.style.display = 'none'; return; }
        panel.style.display = '';
        var tbody = document.querySelector('#points-table tbody');
        tbody.innerHTML = '';
        points.forEach(function (p) {
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + p.index + '</td>'
                + '<td>' + p.true_x.toFixed(3) + '</td>'
                + '<td>' + p.true_y.toFixed(3) + '</td>'
                + '<td>' + p.true_z.toFixed(3) + '</td>'
                + '<td>' + (p.uwb_x != null ? p.uwb_x.toFixed(3) : '—') + '</td>'
                + '<td>' + (p.uwb_y != null ? p.uwb_y.toFixed(3) : '—') + '</td>'
                + '<td>' + (p.uwb_z != null ? p.uwb_z.toFixed(3) : '—') + '</td>'
                + '<td>' + (p.error_m != null ? p.error_m.toFixed(4) : '—') + '</td>';
            tbody.appendChild(tr);
        });
    }

    // ---- Apply corrections ----

    window.calApply = function () {
        if (!currentRunId) return;
        var msg = document.getElementById('apply-msg');
        msg.textContent = 'Applying…';
        msg.style.color = 'var(--text-muted)';
        api('/calibration/api/apply', 'POST', { run_id: currentRunId }).then(function (r) {
            if (r.status === 'ok') {
                msg.textContent = 'Applied ✓';
                msg.style.color = 'var(--green)';
                document.getElementById('corr-toggle').checked = true;
                setText('corr-label', 'Enabled');
                loadActiveCorrections();
            } else {
                msg.textContent = r.msg || 'Error';
                msg.style.color = 'var(--red)';
            }
        });
    };

    // ---- Toggle corrections ----

    window.calToggle = function (enabled) {
        api('/calibration/api/toggle', 'POST', { enabled: enabled }).then(function (r) {
            setText('corr-label', r.enabled ? 'Enabled' : 'Disabled');
        });
    };

    // ---- Load active corrections ----

    function loadActiveCorrections() {
        api('/calibration/api/corrections').then(function (r) {
            var el = document.getElementById('active-corr');
            var corr = r.corrections || {};
            var keys = Object.keys(corr);
            if (keys.length === 0) {
                el.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">No corrections stored.</span>';
                return;
            }
            var html = '<table class="corr-table"><thead><tr><th>Anchor</th><th>Bias</th><th>Scale</th></tr></thead><tbody>';
            keys.forEach(function (did) {
                var c = corr[did];
                html += '<tr><td>' + (c.hex || did) + '</td><td>' + (c.bias != null ? c.bias.toFixed(4) : '—') + '</td><td>' + (c.scale != null ? c.scale.toFixed(4) : '—') + '</td></tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;
        });
    }

    // ---- Run history ----

    function loadRuns() {
        api('/calibration/api/runs').then(function (runs) {
            var tbody = document.querySelector('#runs-table tbody');
            tbody.innerHTML = '';
            runs.forEach(function (r) {
                var tr = document.createElement('tr');
                tr.onclick = function () { loadRunDetail(r.id); };
                tr.innerHTML = '<td>' + r.id + '</td>'
                    + '<td>' + (r.name || '—') + '</td>'
                    + '<td><span class="status-dot ' + r.status + '"></span>' + r.status + '</td>'
                    + '<td>' + r.n_points + '</td>';
                tbody.appendChild(tr);
            });
        });
    }

    // ---- Init ----
    loadRuns();
    loadActiveCorrections();
    loadEngine();

    // ---- Engine settings ----

    function loadEngine() {
        api('/calibration/api/engine').then(function (cfg) {
            document.getElementById('eng-ekf').checked = cfg.ekf_enabled !== false;
            document.getElementById('eng-nlos').checked = cfg.nlos_enabled !== false;
            document.getElementById('eng-nlos-thr').value = cfg.nlos_threshold || 0.5;
            document.getElementById('eng-pn').value = cfg.process_noise || 0.1;
            document.getElementById('eng-rv').value = cfg.range_var || 0.1;
        });
    }

    window.saveEngine = function () {
        var body = {
            ekf_enabled: document.getElementById('eng-ekf').checked,
            nlos_enabled: document.getElementById('eng-nlos').checked,
            nlos_threshold: val('eng-nlos-thr'),
            process_noise: val('eng-pn'),
            range_var: val('eng-rv'),
        };
        var msg = document.getElementById('eng-msg');
        api('/calibration/api/engine', 'POST', body).then(function (r) {
            msg.textContent = r.status === 'ok' ? 'Saved' : (r.msg || 'Error');
            msg.style.color = r.status === 'ok' ? 'var(--green)' : 'var(--red)';
            setTimeout(function () { msg.textContent = ''; }, 2000);
        });
    };

    window.resetEKF = function () {
        api('/calibration/api/engine/reset', 'POST').then(function (r) {
            var msg = document.getElementById('eng-msg');
            msg.textContent = 'EKF reset';
            msg.style.color = 'var(--green)';
            setTimeout(function () { msg.textContent = ''; }, 2000);
        });
    };

    // ---- Trajectory smoother ("deblur") ----

    window.calSmooth = function () {
        if (!currentRunId) return;
        var msg = document.getElementById('apply-msg');
        msg.textContent = 'Smoothing…';
        msg.style.color = 'var(--text-muted)';

        api('/calibration/api/smooth', 'POST', {
            source: 'run', run_id: currentRunId,
            process_noise: val('eng-pn'),
            measurement_noise: 0.01,
            dt: 0.1,
        }).then(function (r) {
            if (r.status !== 'ok') {
                msg.textContent = r.msg || 'Error';
                msg.style.color = 'var(--red)';
                return;
            }
            msg.textContent = 'Smoothed ' + r.n + ' points ✓';
            msg.style.color = 'var(--green)';
            showSmoothed(r.positions);
        }).catch(function () {
            msg.textContent = 'Failed';
            msg.style.color = 'var(--red)';
        });
    };

    function showSmoothed(positions) {
        var panel = document.getElementById('smooth-panel');
        panel.style.display = '';

        // Stats
        var statsEl = document.getElementById('smooth-stats');
        var avgConf = 0;
        positions.forEach(function (p) { avgConf += (p.confidence || 0); });
        avgConf = positions.length ? (avgConf / positions.length) : 0;
        statsEl.innerHTML =
            '<div class="stat-box"><div class="stat-val">' + positions.length + '</div><div class="stat-label">Points</div></div>' +
            '<div class="stat-box"><div class="stat-val">' + avgConf.toFixed(2) + '</div><div class="stat-label">Avg Confidence</div></div>';

        // Table
        var tbody = document.querySelector('#smooth-table tbody');
        tbody.innerHTML = '';
        positions.forEach(function (p, i) {
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + i + '</td>'
                + '<td>' + p.x.toFixed(3) + '</td>'
                + '<td>' + p.y.toFixed(3) + '</td>'
                + '<td>' + (p.vx != null ? p.vx.toFixed(3) : '—') + '</td>'
                + '<td>' + (p.vy != null ? p.vy.toFixed(3) : '—') + '</td>'
                + '<td>' + (p.confidence != null ? p.confidence.toFixed(2) : '—') + '</td>';
            tbody.appendChild(tr);
        });
    }

    // ---- Auto-origin (coordinate alignment) ----

    var lastRefinement = null;  // stashed for "Apply Refined Positions"

    window.autoOrigin = function () {
        if (!currentRunId) { alert('Select a calibration run first.'); return; }
        var msg = document.getElementById('align-msg');
        msg.textContent = 'Computing…';
        msg.style.color = 'var(--text-muted)';
        document.getElementById('alignment-panel').style.display = '';

        api('/calibration/api/auto-origin', 'POST', { run_id: currentRunId }).then(function (r) {
            if (r.status !== 'ok') {
                msg.textContent = r.msg || 'Error';
                msg.style.color = 'var(--red)';
                return;
            }
            msg.textContent = 'Transform saved ✓';
            msg.style.color = 'var(--green)';
            showTransform(r.transform);
        }).catch(function () {
            msg.textContent = 'Failed';
            msg.style.color = 'var(--red)';
        });
    };

    function showTransform(tf) {
        document.getElementById('transform-result').style.display = '';
        setText('tf-rot', tf.rotation_deg.toFixed(2) + '°');
        setText('tf-trans', '(' + tf.translation_m[0].toFixed(4) + ', ' + tf.translation_m[1].toFixed(4) + ')');
        setText('tf-scale', tf.scale.toFixed(6));
        setText('tf-rmse', tf.rmse_m.toFixed(4) + ' m');
    }

    window.refineAnchors = function () {
        if (!currentRunId) { alert('Select a calibration run first.'); return; }
        var msg = document.getElementById('align-msg');
        msg.textContent = 'Refining…';
        msg.style.color = 'var(--text-muted)';
        document.getElementById('alignment-panel').style.display = '';

        api('/calibration/api/refine-anchors', 'POST', { run_id: currentRunId }).then(function (r) {
            if (r.status !== 'ok') {
                msg.textContent = r.msg || 'Error';
                msg.style.color = 'var(--red)';
                return;
            }
            msg.textContent = 'Done ✓';
            msg.style.color = 'var(--green)';

            // Show transform if present
            if (r.transform) showTransform(r.transform);

            // Show anchor refinement
            var ref = r.refinement;
            lastRefinement = ref;
            document.getElementById('anchor-refine-result').style.display = '';
            setText('ar-before', ref.rmse_before.toFixed(4) + ' m');
            setText('ar-after', ref.rmse_after.toFixed(4) + ' m');

            var tbody = document.querySelector('#anchor-delta-table tbody');
            tbody.innerHTML = '';
            var anchors = ref.anchors || {};
            Object.keys(anchors).forEach(function (did) {
                var a = anchors[did];
                var tr = document.createElement('tr');
                tr.innerHTML = '<td>' + (a.hex || did) + '</td>'
                    + '<td>' + (a.old_x != null ? a.old_x.toFixed(3) : '—') + '</td>'
                    + '<td>' + (a.old_y != null ? a.old_y.toFixed(3) : '—') + '</td>'
                    + '<td>' + a.x.toFixed(3) + '</td>'
                    + '<td>' + a.y.toFixed(3) + '</td>'
                    + '<td>' + a.dx.toFixed(4) + '</td>'
                    + '<td>' + a.dy.toFixed(4) + '</td>';
                tbody.appendChild(tr);
            });
        }).catch(function () {
            msg.textContent = 'Failed';
            msg.style.color = 'var(--red)';
        });
    };

    window.applyRefinedAnchors = function () {
        if (!lastRefinement) { alert('Run "Refine Anchors" first.'); return; }
        var anchors = {};
        var src = lastRefinement.anchors || {};
        Object.keys(src).forEach(function (did) {
            anchors[did] = { x: src[did].x, y: src[did].y };
        });
        var applyMsg = document.getElementById('ar-apply-msg');
        applyMsg.textContent = 'Saving…';
        applyMsg.style.color = 'var(--text-muted)';

        api('/calibration/api/apply-refined-anchors', 'POST', { anchors: anchors }).then(function (r) {
            if (r.status === 'ok') {
                applyMsg.textContent = 'Applied ✓';
                applyMsg.style.color = 'var(--green)';
            } else {
                applyMsg.textContent = r.msg || 'Error';
                applyMsg.style.color = 'var(--red)';
            }
        }).catch(function () {
            applyMsg.textContent = 'Failed';
            applyMsg.style.color = 'var(--red)';
        });
    };

    // Show alignment panel when a run is loaded
    var _origShowResults = showResults;
    showResults = function (run) {
        _origShowResults(run);
        if (run.results) {
            document.getElementById('alignment-panel').style.display = '';
        }
    };

})();
