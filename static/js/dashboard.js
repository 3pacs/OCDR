/* OCDR Dashboard - Auto-refresh KPI cards */
(function () {
    function loadKPIs() {
        fetch('/health')
            .then(r => r.json())
            .then(data => {
                document.getElementById('kpi-records').textContent = data.record_count.toLocaleString();
                document.getElementById('kpi-status').textContent = data.status === 'ok' ? 'OK' : 'Error';
            })
            .catch(() => {
                document.getElementById('kpi-status').textContent = 'Offline';
            });

        fetch('/api/filing-deadlines/alerts')
            .then(r => r.json())
            .then(data => {
                const total = (data.past_deadline || 0) + (data.warning || 0);
                document.getElementById('kpi-alerts').textContent = total;
            })
            .catch(() => {});

        fetch('/api/underpayments/summary')
            .then(r => r.json())
            .then(data => {
                document.getElementById('kpi-underpaid').textContent = (data.total_flagged || 0).toLocaleString();
            })
            .catch(() => {});
    }

    loadKPIs();
    setInterval(loadKPIs, 60000);
})();
