// FinRecon AI – Dashboard Analytics & Chart.js Integration

let monthlyChart = null;
let statusChart = null;
let paymentTrendChart = null;
let topCustomersChart = null;

async function loadDashboardMetrics() {
    try {
        const res = await fetch('/api/dashboard/metrics');
        if (!res.ok) throw new Error('Failed to load metrics');
        const data = await res.json();

        // Populate stat cards
        document.getElementById('metricTotalInvoicesCount').textContent = data.total_invoices_count;
        document.getElementById('metricTotalInvoicesAmount').textContent = formatCurrency(data.total_invoices_amount);
        document.getElementById('metricTotalPaymentsCount').textContent = data.total_payments_count;
        document.getElementById('metricTotalPaymentsAmount').textContent = formatCurrency(data.total_payments_amount);
        if (document.getElementById('metricReconciledAmount')) {
            document.getElementById('metricReconciledAmount').textContent = formatCurrency(data.reconciled_amount || 0);
        }
        document.getElementById('metricOutstandingAmount').textContent = formatCurrency(data.outstanding_amount);
        document.getElementById('metricReconRate').textContent = `${data.reconciliation_rate_percent}%`;
        
        document.getElementById('metricUnmatchedCount').textContent = data.unmatched_payments_count;
        document.getElementById('metricUnmatchedAmount').textContent = formatCurrency(data.unmatched_payments_amount);
        if (document.getElementById('metricPendingReviewCount')) {
            document.getElementById('metricPendingReviewCount').textContent = data.pending_review_count || 0;
        }
        
        document.getElementById('metricOverdueCount').textContent = data.overdue_count;
        document.getElementById('metricDuplicateCount').textContent = data.duplicate_candidates_count;

        const reconProgressBar = document.getElementById('reconProgressBar');
        if (reconProgressBar) {
            reconProgressBar.style.width = `${Math.min(100, data.reconciliation_rate_percent)}%`;
            reconProgressBar.setAttribute('aria-valuenow', data.reconciliation_rate_percent);
        }
    } catch (err) {
        console.error('Error loading dashboard metrics:', err);
    }
}

async function loadDashboardCharts() {
    try {
        const res = await fetch('/api/dashboard/charts');
        if (!res.ok) throw new Error('Failed to load chart data');
        const data = await res.json();

        // 1. Monthly Invoice vs Payment Bar Chart
        const ctxMonthly = document.getElementById('monthlyChart')?.getContext('2d');
        if (ctxMonthly) {
            if (monthlyChart) monthlyChart.destroy();
            monthlyChart = new Chart(ctxMonthly, {
                type: 'bar',
                data: {
                    labels: data.monthly_trend.labels.length ? data.monthly_trend.labels : ['Current'],
                    datasets: [
                        {
                            label: 'Invoices Issued ($)',
                            data: data.monthly_trend.invoices.length ? data.monthly_trend.invoices : [0],
                            backgroundColor: 'rgba(99, 102, 241, 0.85)',
                            borderRadius: 6
                        },
                        {
                            label: 'Payments Received ($)',
                            data: data.monthly_trend.payments.length ? data.monthly_trend.payments : [0],
                            backgroundColor: 'rgba(16, 185, 129, 0.85)',
                            borderRadius: 6
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'top' },
                        tooltip: {
                            callbacks: {
                                label: ctx => `${ctx.dataset.label}: ${formatCurrency(ctx.parsed.y)}`
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { callback: v => `$${v.toLocaleString()}` }
                        }
                    }
                }
            });
        }

        // 2. Status Distribution Doughnut Chart
        const ctxStatus = document.getElementById('statusChart')?.getContext('2d');
        if (ctxStatus) {
            if (statusChart) statusChart.destroy();
            statusChart = new Chart(ctxStatus, {
                type: 'doughnut',
                data: {
                    labels: data.status_distribution.labels,
                    datasets: [{
                        data: data.status_distribution.counts,
                        backgroundColor: [
                            '#10b981', // Paid (Emerald)
                            '#f59e0b', // Partially Paid (Amber)
                            '#94a3b8', // Unpaid (Slate)
                            '#ef4444'  // Overdue (Rose)
                        ],
                        borderWidth: 2,
                        borderColor: '#ffffff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'bottom' }
                    },
                    cutout: '70%'
                }
            });
        }

        // 3. Payment Inflow Trend Line Chart
        const ctxTrend = document.getElementById('paymentTrendChart')?.getContext('2d');
        if (ctxTrend) {
            if (paymentTrendChart) paymentTrendChart.destroy();
            paymentTrendChart = new Chart(ctxTrend, {
                type: 'line',
                data: {
                    labels: data.payment_trend.labels.length ? data.payment_trend.labels : ['Recent'],
                    datasets: [{
                        label: 'Inflow ($)',
                        data: data.payment_trend.amounts.length ? data.payment_trend.amounts : [0],
                        borderColor: '#0ea5e9',
                        backgroundColor: 'rgba(14, 165, 233, 0.1)',
                        fill: true,
                        tension: 0.35,
                        pointRadius: 4,
                        pointHoverRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: ctx => `Payment: ${formatCurrency(ctx.parsed.y)}`
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { callback: v => `$${v.toLocaleString()}` }
                        }
                    }
                }
            });
        }

        // 4. Top Outstanding Customers Bar Chart
        const ctxTop = document.getElementById('topCustomersChart')?.getContext('2d');
        if (ctxTop) {
            if (topCustomersChart) topCustomersChart.destroy();
            topCustomersChart = new Chart(ctxTop, {
                type: 'bar',
                data: {
                    labels: data.top_customers.labels.length ? data.top_customers.labels : ['No Receivables'],
                    datasets: [{
                        label: 'Outstanding ($)',
                        data: data.top_customers.amounts.length ? data.top_customers.amounts : [0],
                        backgroundColor: 'rgba(239, 68, 68, 0.8)',
                        borderRadius: 6
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: ctx => `Outstanding: ${formatCurrency(ctx.parsed.x)}`
                            }
                        }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            ticks: { callback: v => `$${v.toLocaleString()}` }
                        }
                    }
                }
            });
        }

    } catch (err) {
        console.error('Error loading dashboard charts:', err);
    }
}

async function triggerQuickReconciliation() {
    const btn = document.getElementById('btnQuickReconcile');
    const origHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Reconciling...';
    }

    try {
        const res = await fetch('/api/reconciliation/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auto_approve_high: true, re_evaluate_all: false })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Reconciliation completed successfully', 'success');
            await loadDashboardMetrics();
            await loadDashboardCharts();
            setTimeout(() => window.location.reload(), 1500);
        } else {
            showToast(data.detail || 'Reconciliation failed', 'error');
        }
    } catch (err) {
        showToast('Error executing reconciliation', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadDashboardMetrics();
    loadDashboardCharts();

    const quickReconcileBtn = document.getElementById('btnQuickReconcile');
    if (quickReconcileBtn) {
        quickReconcileBtn.addEventListener('click', triggerQuickReconciliation);
    }
});
