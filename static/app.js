document.addEventListener('DOMContentLoaded', () => {
    const API_URL = '';
    
    // UI Utility: Clean Markdown from LLM reasoning
    const cleanMD = (text) => {
        if (!text) return '';
        return text.replace(/[#*`]/g, '').trim();
    };

    function showView(viewId) {
        document.querySelectorAll('[id^="view-"]').forEach(v => v.classList.add('hidden'));
        const targetView = document.getElementById(viewId);
        if (targetView) targetView.classList.remove('hidden');
        
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        const navId = `nav-${viewId.split('-')[1]}`;
        const activeNav = document.getElementById(navId);
        if (activeNav) activeNav.classList.add('active');

        const headerTitle = document.querySelector('.top-header h1');
        if (headerTitle) {
            const viewNames = {
                'view-dashboard': 'Dashboard',
                'view-portfolio': 'Live Portfolio',
                'view-backtest': 'Proof of History',
                'view-discovery': 'Market Discovery',
                'view-watchlist': 'Model Watchlist',
                'view-costs': 'Cost Analysis'
            };
            if (viewNames[viewId]) headerTitle.textContent = viewNames[viewId];
        }

        if (viewId === 'view-discovery') fetchDiscoveryResults();
        else if (viewId === 'view-portfolio') fetchPortfolio();
        else if (viewId === 'view-backtest') { fetchPastRuns(); fetchBacktestResults(); }
        else if (viewId === 'view-watchlist') fetchWatchlist();
        else if (viewId === 'view-costs') fetchCostAnalysis();
    }

    // Sidebar navigation
    document.querySelectorAll('.nav-item').forEach(nav => {
        nav.addEventListener('click', (e) => {
            e.preventDefault();
            const viewId = `view-${nav.id.split('-')[1]}`;
            showView(viewId);
        });
    });

    // --- Dashboard Elements & Modal ---
    const analyzeBtn = document.getElementById('analyze-btn');
    const modal = document.getElementById('analysis-modal');
    const closeModalBtn = document.getElementById('close-modal');
    const startAnalysisBtn = document.getElementById('start-analysis');
    const symbolsInput = document.getElementById('symbols-input');
    const statusMsg = document.getElementById('analysis-status');
    const tbody = document.getElementById('recommendations-tbody');

    analyzeBtn?.addEventListener('click', () => {
        modal?.classList.remove('hidden');
        if(symbolsInput) symbolsInput.value = '';
        statusMsg?.classList.add('hidden');
    });

    closeModalBtn?.addEventListener('click', () => {
        modal?.classList.add('hidden');
        fetchRecommendations();
        fetchStats();
    });

    startAnalysisBtn?.addEventListener('click', async () => {
        const symbolsStr = symbolsInput?.value.trim();
        if(!symbolsStr) return;
        const symbols = symbolsStr.split(',').map(s => s.trim().toUpperCase()).filter(s => s);
        try {
            startAnalysisBtn.textContent = 'Scanning...';
            startAnalysisBtn.disabled = true;
            const res = await fetch(`${API_URL}/api/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbols })
            });
            const data = await res.json();
            if(statusMsg) {
                statusMsg.textContent = data.message;
                statusMsg.classList.remove('hidden');
            }
        } catch (e) { console.error(e); } finally {
            startAnalysisBtn.textContent = 'Start Analysis';
            startAnalysisBtn.disabled = false;
        }
    });

    async function fetchStats() {
        try {
            const res = await fetch(`${API_URL}/api/accuracy`);
            const data = await res.json();
            if (data.status === 'success') {
                document.getElementById('stat-accuracy').textContent = `${data.data.accuracy_percent}%`;
                document.getElementById('stat-total').textContent = data.data.total_recommendations;
                document.getElementById('stat-return').textContent = `${data.data.average_return_percent}%`;
            }
        } catch (e) { console.error(e); }
    }

    async function fetchRecommendations() {
        try {
            if(!tbody) return;
            const res = await fetch(`${API_URL}/api/recommendations`);
            const data = await res.json();
            document.getElementById('loading-state')?.classList.add('hidden');
            tbody.innerHTML = '';
            if (data.status === 'success' && data.data.length > 0) {
                const grouped = {};
                data.data.forEach(rec => {
                    if(!grouped[rec.symbol]) grouped[rec.symbol] = [];
                    grouped[rec.symbol].push(rec);
                });
                for (const [symbol, groupRecs] of Object.entries(grouped)) {
                    const trHead = document.createElement('tr');
                    trHead.innerHTML = `<td colspan="9" style="background: rgba(255, 255, 255, 0.03); font-weight: 700; color: var(--primary); padding: 12px 16px;"><i data-lucide="folder" style="width:16px;height:16px;display:inline-block;vertical-align:text-bottom;margin-right:8px;"></i>${symbol}</td>`;
                    tbody.appendChild(trHead);
                    groupRecs.forEach(rec => {
                        const tr = document.createElement('tr');
                        const badge = (rec.recommendation === 'BUY') ? 'buy' : (rec.recommendation === 'SELL' ? 'sell' : 'hold');
                        tr.innerHTML = `
                            <td style="padding-left:38px;opacity:0.6;font-size:12px;">${new Date(rec.created_at + 'Z').toLocaleString()}</td>
                            <td><span class="badge ${badge}">${rec.recommendation}</span></td>
                            <td><span class="badge ${badge}" style="opacity:0.8;font-size:11px;">📰 Sentiment: ${rec.news_sentiment || 3}</span></td>
                            <td style="max-width:250px;"><div class="reflection-note">"${rec.reflection || 'No history yet.'}"</div></td>
                            <td><div class="progress-bar"><div class="progress-fill" style="width:${rec.conviction}%"></div></div> ${rec.conviction}%</td>
                            <td>$${rec.entry_price?.toFixed(2)}</td>
                            <td>$${rec.target_price?.toFixed(2)}</td>
                            <td>$${rec.stop_loss?.toFixed(2)}</td>
                            <td>${rec.fundamentals_score}/${rec.technical_score}</td>`;
                        tbody.appendChild(tr);
                    });
                }
                if(window.lucide) window.lucide.createIcons();
            }
        } catch (e) { console.error(e); }
    }

    // --- Portfolio Logic ---
    async function fetchPortfolio() {
        try {
            const portTbody = document.getElementById('portfolio-tbody');
            if(!portTbody) return;
            document.getElementById('loading-state-port')?.classList.remove('hidden');
            const res = await fetch(`${API_URL}/api/portfolio`);
            const data = await res.json();
            document.getElementById('loading-state-port')?.classList.add('hidden');
            portTbody.innerHTML = '';
            if(data.status === 'success') {
                document.getElementById('port-value').textContent = `$${data.summary.total_value.toLocaleString(undefined, {minimumFractionDigits:2})}`;
                document.getElementById('port-invested').textContent = `$${data.summary.total_invested.toLocaleString(undefined, {minimumFractionDigits:2})}`;
                const pnl = data.summary.total_pnl_pct;
                const pnlEl = document.getElementById('port-pnl');
                pnlEl.textContent = `${pnl > 0 ? '+' : ''}${pnl.toFixed(2)}%`;
                pnlEl.style.color = pnl >= 0 ? "var(--success)" : "var(--danger)";

                data.data.forEach(item => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td><strong>${item.symbol}</strong></td><td>$${item.entry.toFixed(2)}</td><td>$${item.live_price.toFixed(2)}</td><td style="color:${item.pnl_pct >= 0 ? 'var(--success)' : 'var(--danger)'};font-weight:bold;">${item.pnl_pct.toFixed(2)}%</td><td><span class="badge hold">${item.verdict}</span></td><td><span style="font-size:11px;color:var(--text-muted);">${item.alert}</span></td><td>${item.tech_score}</td><td><div class="sparkline-placeholder"></div></td>`;
                    portTbody.appendChild(tr);
                });
            }
        } catch (e) { console.error(e); }
    }

    // --- Backtest View Logic ---
    const submitBacktestBtn = document.getElementById('submit-backtest');
    const backtestSymbolInput = document.getElementById('backtest-symbol-input');
    const backtestResultsContainer = document.getElementById('backtest-results-container');
    const pastRunsSelect = document.getElementById('past-runs-select');

    async function fetchPastRuns() {
        try {
            if(!pastRunsSelect) return;
            const res = await fetch(`${API_URL}/api/backtests`);
            const data = await res.json();
            if (data.status === 'success' && data.runs) {
                pastRunsSelect.innerHTML = '<option value="">Latest Run (Active)</option>';
                data.runs.forEach(run => {
                    const opt = document.createElement('option');
                    opt.value = run.id;
                    opt.textContent = `[${run.id}] ${new Date(run.run_date).toLocaleString()} - ${run.symbols}`;
                    pastRunsSelect.appendChild(opt);
                });
            }
        } catch (e) { console.error(e); }
    }

    async function fetchBacktestResults(runId = "") {
        try {
            if(!backtestResultsContainer) return;
            const url = runId ? `${API_URL}/api/backtests/${runId}` : `${API_URL}/api/backtest/results`;
            const res = await fetch(url);
            const data = await res.json();
            if (data.status === 'success' && data.data) {
                let html = '';
                const pnlEl = document.getElementById('bt-overall-pnl');
                const agg = data.aggregate_stats;
                if(agg && pnlEl) {
                    document.getElementById('backtest-aggregate-stats').style.display = 'flex';
                    document.getElementById('bt-total-invested').textContent = `$${agg.total_invested.toFixed(2)}`;
                    document.getElementById('bt-final-value').textContent = `$${agg.total_final_value.toFixed(2)}`;
                    pnlEl.textContent = `${agg.overall_pnl_pct >= 0 ? '+' : ''}${agg.overall_pnl_pct.toFixed(2)}%`;
                    pnlEl.style.color = agg.overall_pnl_pct >= 0 ? 'var(--success)' : 'var(--danger)';
                    document.getElementById('bt-win-rate').textContent = `${agg.win_rate.toFixed(0)}%`;
                }
                for (const [symbol, result] of Object.entries(data.data)) {
                    let tradesHtml = '';
                    if (result.trades && result.trades.length > 0) {
                        tradesHtml = `
                            <div class="table-responsive" style="margin-top:15px; border-top: 1px solid rgba(255,255,255,0.05); padding-top:10px;">
                                <table class="data-table" style="font-size:11px;">
                                    <thead>
                                        <tr style="background:transparent; border-bottom:1px solid rgba(255,255,255,0.05);">
                                            <th>WEEK</th>
                                            <th>SIGNAL</th>
                                            <th>PRICE</th>
                                            <th>CONVICTION</th>
                                            <th>AI REASONING</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${result.trades.map(t => {
                                            const badge = t.action === 'BUY' ? 'buy' : (t.action === 'SELL' ? 'sell' : 'hold');
                                            return `
                                                <tr>
                                                    <td>${new Date(t.date).toLocaleDateString()}</td>
                                                    <td><span class="badge ${badge}" style="padding:2px 8px; font-size:10px;">${t.action}</span></td>
                                                    <td>$${t.price?.toFixed(2) || 'N/A'}</td>
                                                    <td>${t.conviction}%</td>
                                                    <td style="max-width:300px; white-space:normal; opacity:0.7;">${cleanMD(t.reasoning)}</td>
                                                </tr>
                                            `;
                                        }).join('')}
                                    </tbody>
                                </table>
                            </div>
                        `;
                    } else {
                        tradesHtml = '<p style="font-size:12px; opacity:0.5; margin-top:10px;">No trades generated during this period.</p>';
                    }

                    html += `
                        <div class="backtest-card glass-panel" style="margin-bottom: 25px; padding: 25px;">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <h3 style="margin:0; font-size:22px; color:var(--primary);">${symbol}</h3>
                                <div style="text-align:right;">
                                    <div style="font-size:18px; font-weight:700; color:${result.pnl_if_followed >= 0 ? 'var(--success)' : 'var(--danger)'}">
                                        ${result.pnl_if_followed >= 0 ? '+' : ''}${result.pnl_if_followed?.toFixed(2)}%
                                    </div>
                                    <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase;">Simulation ROI</div>
                                </div>
                            </div>
                            ${tradesHtml}
                        </div>
                    `;
                }
                backtestResultsContainer.innerHTML = html;
            }
        } catch (e) { console.error(e); }
    }

    submitBacktestBtn?.addEventListener('click', async () => {
        const symbolsStr = backtestSymbolInput?.value.trim();
        if(!symbolsStr) return;
        const symbols = symbolsStr.split(',').map(s => s.trim().toUpperCase()).filter(s => s);
        try {
            submitBacktestBtn.textContent = 'Simulating...';
            submitBacktestBtn.disabled = true;
            await fetch(`${API_URL}/api/backtest/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbols })
            });
            backtestResultsContainer.innerHTML = '<p class="text-success">Proof of History generation started.</p>';
        } catch (e) { console.error(e); } finally { submitBacktestBtn.textContent = 'Run 90-Day Simulation'; submitBacktestBtn.disabled = false; }
    });

    document.getElementById('refresh-backtest')?.addEventListener('click', () => {
        fetchPastRuns();
        fetchBacktestResults();
    });

    pastRunsSelect?.addEventListener('change', () => {
        fetchBacktestResults(pastRunsSelect.value);
    });

    // --- Discovery Logic ---
    async function fetchDiscoveryResults() {
        try {
            const grid = document.getElementById('discovery-results-grid');
            if(!grid) return;
            const res = await fetch(`${API_URL}/api/discover`);
            const data = await res.json();
            grid.innerHTML = '';
            if (data.data) {
                data.data.slice(0, 10).forEach(rec => {
                    const card = document.createElement('div');
                    card.className = 'discovery-card glass-panel';
                    card.style.padding = '20px';
                    card.innerHTML = `<div style="display:flex;justify-content:space-between;margin-bottom:15px;"><h3>${rec.symbol}</h3><span class="badge ${rec.recommendation === 'BUY' ? 'buy' : 'hold'}">${rec.recommendation}</span></div><p style="font-size:12px;color:var(--text-muted);line-height:1.5;margin-bottom:15px;height:60px;overflow:hidden;">${cleanMD(rec.reasoning)}</p><div style="display:flex;justify-content:space-between;align-items:center;margin-top:auto;"><span style="font-size:12px;color:var(--primary);font-weight:bold;">${rec.conviction}% Confidence</span><button class="btn btn-primary add-to-watchlist-btn" data-symbol="${rec.symbol}" style="padding:5px 12px;font-size:12px;">+ Watch</button></div>`;
                    grid.appendChild(card);
                });
                document.querySelectorAll('.add-to-watchlist-btn').forEach(btn => {
                    btn.onclick = async () => {
                        btn.disabled = true; btn.textContent = 'Added';
                        await fetch(`${API_URL}/api/watchlist?symbol=${btn.dataset.symbol}`, { method: 'POST' });
                    };
                });
            }
        } catch (e) { console.error(e); }
    }

    // --- Watchlist Logic ---
    async function fetchWatchlist() {
        try {
            const tbody = document.getElementById('watchlist-tbody');
            if(!tbody) return;
            const res = await fetch(`${API_URL}/api/watchlist`);
            const data = await res.json();
            tbody.innerHTML = '';
            if (data.status === 'success' && data.data) {
                data.data.forEach(item => {
                    const tr = document.createElement('tr');
                    const trade = item.trade;
                    const pnl = trade ? ((trade.current_value - trade.total_investment) / trade.total_investment * 100).toFixed(2) : '0.00';
                    tr.innerHTML = `<td><strong>${item.symbol}</strong></td><td style="font-size:12px;opacity:0.6;">${new Date(item.added_at).toLocaleDateString()}</td><td style="font-size:12px;opacity:0.6;">${new Date(item.expires_at).toLocaleDateString()}</td><td><span class="badge ${trade ? 'buy' : 'hold'}">${trade ? 'TRADING' : 'MONITORING'}</span></td><td style="font-weight:bold;color:${pnl >= 0 ? 'var(--success)' : 'var(--danger)'}">${pnl}%</td><td><button class="btn-icon remove-watchlist-btn" data-symbol="${item.symbol}"><i data-lucide="trash-2"></i></button></td>`;
                    tbody.appendChild(tr);
                });
                document.querySelectorAll('.remove-watchlist-btn').forEach(btn => {
                    btn.onclick = async () => { await fetch(`${API_URL}/api/watchlist/${btn.dataset.symbol}`, { method: 'DELETE' }); fetchWatchlist(); };
                });
                if(window.lucide) window.lucide.createIcons();
            }
        } catch (e) { console.error(e); }
    }

    // --- Cost Analysis Logic ---
    async function fetchCostAnalysis() {
        try {
            const tbody = document.getElementById('costs-tbody');
            if(!tbody) return;
            const res = await fetch(`${API_URL}/api/cost-analysis`);
            const data = await res.json();
            if (data.status === 'success') {
                document.getElementById('cost-total-spent').textContent = `$${data.summary.total_cost.toFixed(4)}`;
                document.getElementById('cost-today').textContent = `$${data.summary.today_cost.toFixed(4)}`;
                document.getElementById('cost-projection').textContent = `$${data.summary.monthly_projection.toFixed(2)}`;
                document.getElementById('cost-total-calls').textContent = data.summary.total_calls;
                tbody.innerHTML = '';
                data.history.forEach(item => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td style="font-size:11px;opacity:0.6;">${new Date(item.timestamp).toLocaleString()}</td><td style="font-family:monospace;font-size:11px;">${item.model}</td><td>${item.input_tokens}</td><td>${item.output_tokens}</td><td style="font-weight:bold;">$${item.cost.toFixed(4)}</td>`;
                    tbody.appendChild(tr);
                });
            }
        } catch (e) { console.error(e); }
    }

    showView('view-dashboard');
    fetchStats();
    fetchRecommendations();
});
