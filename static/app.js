document.addEventListener('DOMContentLoaded', () => {
    // API endpoints
    const API_URL = '';
    const viewDashboard = document.getElementById('view-dashboard');
    const viewPortfolio = document.getElementById('view-portfolio');
    const viewBacktest = document.getElementById('view-backtest');
    const viewDiscovery = document.getElementById('view-discovery');
    
    const navDashboard = document.getElementById('nav-dashboard');
    const navPortfolio = document.getElementById('nav-portfolio');
    const navBacktest = document.getElementById('nav-backtest');
    const navDiscovery = document.getElementById('nav-discovery');
    const navWatchlist = document.getElementById('nav-watchlist');
    const navCosts = document.getElementById('nav-costs');

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
        if (viewId === 'view-portfolio') fetchPortfolio();
        if (viewId === 'view-backtest') {
            fetchPastRuns();
            fetchBacktestResults();
        }
        if (viewId === 'view-watchlist') fetchWatchlist();
        if (viewId === 'view-costs') fetchCostAnalysis();
    }

    navDashboard?.addEventListener('click', (e) => { e.preventDefault(); showView('view-dashboard'); });
    navPortfolio?.addEventListener('click', (e) => { e.preventDefault(); showView('view-portfolio'); });
    navBacktest?.addEventListener('click', (e) => { e.preventDefault(); showView('view-backtest'); });
    navDiscovery?.addEventListener('click', (e) => { e.preventDefault(); showView('view-discovery'); });
    navWatchlist?.addEventListener('click', (e) => { e.preventDefault(); showView('view-watchlist'); });
    navCosts?.addEventListener('click', (e) => { e.preventDefault(); showView('view-costs'); });


    // DOM Elements
    const analyzeBtn = document.getElementById('analyze-btn');
    const modal = document.getElementById('analysis-modal');
    const closeModalBtn = document.getElementById('close-modal');
    const startAnalysisBtn = document.getElementById('start-analysis');
    const symbolsInput = document.getElementById('symbols-input');
    const statusMsg = document.getElementById('analysis-status');
    const tbody = document.getElementById('recommendations-tbody');
    const loadingState = document.getElementById('loading-state');
    
    // Stats Elements
    const statAccuracy = document.getElementById('stat-accuracy');
    const statTotal = document.getElementById('stat-total');
    const statReturn = document.getElementById('stat-return');

    // Fetch Stats
    async function fetchStats() {
        try {
            const res = await fetch(`${API_URL}/api/accuracy`);
            const data = await res.json();
            if (data.status === 'success') {
                statAccuracy.textContent = `${data.data.accuracy_percent}%`;
                statTotal.textContent = data.data.total_recommendations;
                statReturn.textContent = `${data.data.average_return_percent}%`;
            }
        } catch (error) {
            console.error("Error fetching stats:", error);
        }
    }

    // Fetch Recommendations
    async function fetchRecommendations() {
        try {
            const res = await fetch(`${API_URL}/api/recommendations`);
            const data = await res.json();
            
            loadingState.classList.add('hidden');
            tbody.innerHTML = '';
            
            if (data.status === 'success' && data.data.length > 0) {
                renderRecommendations(data.data);
            } else {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No recommendations found. Run analysis to generate.</td></tr>';
            }
        } catch (error) {
            console.error("Error fetching recommendations:", error);
            loadingState.innerHTML = '<p style="color:var(--danger)">Failed to load data. Ensure backend is running.</p>';
        }
    }

    function renderRecommendations(recs) {
        // Group by symbol
        const grouped = {};
        recs.forEach(rec => {
            if(!grouped[rec.symbol]) grouped[rec.symbol] = [];
            grouped[rec.symbol].push(rec);
        });

        for (const [symbol, groupRecs] of Object.entries(grouped)) {
            // Group Header Row
            const trHead = document.createElement('tr');
            trHead.innerHTML = `<td colspan="9" style="background: rgba(255, 255, 255, 0.03); font-weight: 700; color: var(--primary); padding: 12px 16px;">
                <i data-lucide="folder" style="width: 16px; height: 16px; display: inline-block; vertical-align: text-bottom; margin-right: 8px;"></i>
                ${symbol}
            </td>`;
            tbody.appendChild(trHead);

            // Group Members
            groupRecs.forEach(rec => {
                const tr = document.createElement('tr');
                let badgeClass = 'hold';
                if(rec.recommendation === 'BUY') badgeClass = 'buy';
                if(rec.recommendation === 'SELL') badgeClass = 'sell';
                
                // Format relative time if possible, or just the date string
                let dateStr = "Just now";
                if(rec.created_at) {
                    const date = new Date(rec.created_at + "Z"); // SQLite timestamps are usually UTC
                    dateStr = date.toLocaleDateString() + " " + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
                    if (dateStr === "Invalid Date") dateStr = rec.created_at; // Fallback
                }
                
                const sentimentScore = rec.news_sentiment || 3;
                let sentimentLabel = 'Neutral';
                let sentimentClass = 'hold';
                if (sentimentScore >= 4) { sentimentLabel = 'Bullish'; sentimentClass = 'buy'; }
                else if (sentimentScore <= 2) { sentimentLabel = 'Bearish'; sentimentClass = 'sell'; }

                let newsHtml = '';
                try {
                    const newsData = JSON.parse(rec.news_json || '[]');
                    if (newsData.length > 0) {
                        newsHtml = `<div class="sentiment-tooltip">
                            <div class="tooltip-header"><i data-lucide="newspaper" style="width:12px"></i> Recent Headlines</div>
                            ${newsData.map(n => `<a href="${n.link}" target="_blank" class="news-item">• ${n.title}</a>`).join('')}
                        </div>`;
                    }
                } catch(e) { console.error("News parse error", e); }

                tr.innerHTML = `
                    <td style="padding-left: 38px; color: var(--text-muted); font-size: 13px;">
                        ${dateStr}
                    </td>
                    <td><span class="badge ${badgeClass}">${rec.recommendation}</span></td>
                    <td class="sentiment-cell">
                        <span class="badge ${sentimentClass}" style="opacity: 0.8; font-size: 11px;">📰 ${sentimentLabel}</span>
                        ${newsHtml}
                    </td>
                    <td style="max-width: 250px;"><div class="reflection-note">"${rec.reflection || 'No history yet.'}"</div></td>
                    <td>
                        <div title="${rec.conviction}%">
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${rec.conviction}%"></div>
                            </div>
                            ${rec.conviction}%
                        </div>
                    </td>
                    <td>$${rec.entry_price?.toFixed(2) || '--'}</td>
                    <td class="target-price">$${rec.target_price?.toFixed(2) || '--'}</td>
                    <td class="stop-loss">$${rec.stop_loss?.toFixed(2) || '--'}</td>
                    <td>${rec.fundamentals_score}/${rec.technical_score}</td>
                `;
                tbody.appendChild(tr);
            });
        }
        
        if(window.lucide) {
            window.lucide.createIcons();
        }
    }

    // Modal Logic
    analyzeBtn.addEventListener('click', () => {
        modal.classList.remove('hidden');
        symbolsInput.value = '';
        statusMsg.classList.add('hidden');
    });

    closeModalBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
        fetchRecommendations(); // Refresh when closing
        fetchStats();
    });

    startAnalysisBtn.addEventListener('click', async () => {
        const symbolsStr = symbolsInput.value.trim();
        if(!symbolsStr) return;
        
        const symbols = symbolsStr.split(',').map(s => s.trim().toUpperCase()).filter(s => s);
        
        try {
            startAnalysisBtn.textContent = 'Starting...';
            startAnalysisBtn.disabled = true;
            
            const res = await fetch(`${API_URL}/api/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbols })
            });
            const data = await res.json();
            
            statusMsg.textContent = data.message;
            statusMsg.classList.remove('hidden');
        } catch (error) {
            statusMsg.textContent = 'Error starting analysis.';
            statusMsg.classList.remove('hidden');
            statusMsg.style.color = 'var(--danger)';
        } finally {
            startAnalysisBtn.textContent = 'Start Analysis';
            startAnalysisBtn.disabled = false;
        }
    });

    // Backtest View Logic
    const submitBacktestBtn = document.getElementById('submit-backtest');
    const backtestSymbolInput = document.getElementById('backtest-symbol-input');
    const refreshBacktestBtn = document.getElementById('refresh-backtest');
    const backtestResultsContainer = document.getElementById('backtest-results-container');
    

    if (submitBacktestBtn) {
        submitBacktestBtn.addEventListener('click', async () => {
            const symbolsStr = backtestSymbolInput.value.trim();
            if(!symbolsStr) return;
            
            const symbols = symbolsStr.split(',').map(s => s.trim().toUpperCase()).filter(s => s);
            
            try {
                submitBacktestBtn.innerHTML = '<i data-lucide="loader"></i> Starting...';
                submitBacktestBtn.disabled = true;
                
                const res = await fetch(`${API_URL}/api/backtest/run`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbols })
                });
                const data = await res.json();
                
                backtestResultsContainer.innerHTML = `<p style="color: var(--success);">${data.message} Please refresh in a few minutes.</p>`;
            } catch (error) {
                backtestResultsContainer.innerHTML = `<p style="color: var(--danger);">Error starting backtest.</p>`;
            } finally {
                submitBacktestBtn.innerHTML = '<i data-lucide="history"></i> Start Generating Proof';
                submitBacktestBtn.disabled = false;
                if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        });
    }

    const pastRunsSelect = document.getElementById('past-runs-select');
    const btTotalInvested = document.getElementById('bt-total-invested');
    const btFinalValue = document.getElementById('bt-final-value');
    const btOverallPnl = document.getElementById('bt-overall-pnl');
    const btWinRate = document.getElementById('bt-win-rate');
    const btAggregateStats = document.getElementById('backtest-aggregate-stats');
    
    async function fetchPastRuns() {
        try {
            const res = await fetch(`${API_URL}/api/backtests`);
            const data = await res.json();
            if (data.status === 'success' && data.runs) {
                // Keep the first default option
                pastRunsSelect.innerHTML = '<option value="">Latest Run (Active)</option>';
                data.runs.forEach(run => {
                    const opt = document.createElement('option');
                    opt.value = run.id;
                    opt.textContent = `[${run.id}] ${new Date(run.run_date).toLocaleString()} - ${run.symbols}`;
                    pastRunsSelect.appendChild(opt);
                });
            }
        } catch (e) {
            console.error(e);
        }
    }
    
    if (pastRunsSelect) {
        pastRunsSelect.addEventListener('change', (e) => {
            const runId = e.target.value;
            fetchBacktestResults(runId);
        });
    }

    async function fetchBacktestResults(runId = "") {
        try {
            refreshBacktestBtn.style.opacity = '0.5';
            const url = runId ? `${API_URL}/api/backtests/${runId}` : `${API_URL}/api/backtest/results`;
            const res = await fetch(url);
            const data = await res.json();
            
            if (data.status === 'success' && data.data) {
                let html = '';
                for (const [symbol, result] of Object.entries(data.data)) {
                    if (result.status === 'Error') {
                        html += `<div style="margin-bottom: 16px; padding: 12px; background: rgba(239, 68, 68, 0.1); border-radius: 8px;">
                            <h4 style="font-weight: 600; color: var(--danger);">${symbol} - Error</h4>
                            <p>${result.error}</p>
                        </div>`;
                        continue;
                    }
                    
                    const pnlClass = result.pnl_if_followed >= 0 ? "text-success" : "text-danger";
                    const pnlColor = result.pnl_if_followed >= 0 ? "var(--success)" : "var(--danger)";
                    const totalInvestedHtml = result.total_invested ? `$${result.total_invested.toFixed(2)}` : '--';
                    const finalValueHtml = result.final_value ? `$${result.final_value.toFixed(2)}` : '--';
                    
                    html += `<div style="margin-bottom: 24px; padding: 16px; background: rgba(255,255,255,0.02); border-radius: 12px; border: 1px solid var(--border-color);">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                            <h4 style="font-size: 16px; font-weight: 600; color: var(--primary); margin: 0;">${symbol}</h4>
                            <div style="text-align: right;">
                                <span style="font-size: 13px; color: var(--text-muted); margin-right: 12px;">Inv: ${totalInvestedHtml} &rarr; ${finalValueHtml}</span>
                                <span style="font-weight: bold; color: ${pnlColor};">Net: ${result.pnl_if_followed ? result.pnl_if_followed.toFixed(2) : 0}%</span>
                            </div>
                        </div>
                        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                            <thead>
                                <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); text-align: left; color: var(--text-muted);">
                                    <th style="padding: 8px;">Date</th>
                                    <th style="padding: 8px;">Action</th>
                                    <th style="padding: 8px;">Entry/Price</th>
                                    <th style="padding: 8px;">Conviction</th>
                                    <th style="padding: 8px;">Score</th>
                                    <th style="padding: 8px; width: 40%;">Reasoning / Patterns</th>
                                </tr>
                            </thead>
                            <tbody>`;
                            
                    result.trades.forEach(t => {
                        let badgeClass = 'hold';
                        if (['BUY', 'STRONG BUY'].includes(t.action)) badgeClass = 'buy';
                        if (['SELL', 'AVOID'].includes(t.action)) badgeClass = 'sell';
                        
                        html += `<tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                            <td style="padding: 8px;">${t.date}</td>
                            <td style="padding: 8px;"><span class="backtest-trade-badge ${badgeClass}">${t.action}</span></td>
                            <td style="padding: 8px;">$${Number(t.price).toFixed(2)}</td>
                            <td style="padding: 8px;">${t.conviction}%</td>
                            <td style="padding: 8px; font-family: monospace; color: var(--text-muted);">${t.score}</td>
                            <td style="padding: 8px; font-size: 11px; color: var(--text-muted); line-height: 1.4;">${t.reasoning || '-'}</td>
                        </tr>`;
                    });
                    
                    html += `</tbody></table></div>`;
                }
                
                backtestResultsContainer.innerHTML = html;
                
                // Populate aggregate stats
                if (data.aggregate_stats) {
                    btAggregateStats.style.display = 'flex';
                    btTotalInvested.textContent = `$${data.aggregate_stats.total_invested.toFixed(2)}`;
                    btFinalValue.textContent = `$${data.aggregate_stats.total_final_value.toFixed(2)}`;
                    
                    const pnl = data.aggregate_stats.overall_pnl_pct;
                    btOverallPnl.textContent = `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%`;
                    btOverallPnl.style.color = pnl >= 0 ? 'var(--success)' : 'var(--danger)';
                    btWinRate.textContent = `${data.aggregate_stats.win_rate.toFixed(0)}%`;
                } else {
                    btAggregateStats.style.display = 'none';
                }
                
                // Update dropdown to match current run id if not specifically chosen
                if (data.run_id && !runId) {
                    await fetchPastRuns();
                    pastRunsSelect.value = data.run_id;
                }
                
                if (typeof lucide !== 'undefined') lucide.createIcons();
            } else {
                backtestResultsContainer.innerHTML = `<p style="color: var(--text-muted);">${data.message || 'No recent backtests. Run one to view history.'}</p>`;
                btAggregateStats.style.display = 'none';
            }
        } catch (error) {
            backtestResultsContainer.innerHTML = `<p style="color: var(--danger);">Failed to load results.</p>`;
            btAggregateStats.style.display = 'none';
        } finally {
            refreshBacktestBtn.style.opacity = '1';
        }
    }

    if (refreshBacktestBtn) {
        refreshBacktestBtn.addEventListener('click', () => fetchBacktestResults());
    }

    // Portfolio Fetch Logic

    
    const portInvested = document.getElementById('port-invested');
    const portValue = document.getElementById('port-value');
    const portPnl = document.getElementById('port-pnl');
    const portTbody = document.getElementById('portfolio-tbody');
    const loadingPort = document.getElementById('loading-state-port');

    async function fetchPortfolio() {
        try {
            loadingPort.classList.remove('hidden');
            const res = await fetch(`${API_URL}/api/portfolio`);
            const data = await res.json();
            
            loadingPort.classList.add('hidden');
            portTbody.innerHTML = '';
            
            if(data.status === 'success') {
                if(data.data.length === 0) {
                    portTbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No active portfolio holdings found.</td></tr>';
                } else {
                    // Update stats
                    portInvested.textContent = `$${data.summary.total_invested.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                    portValue.textContent = `$${data.summary.total_value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                    const pnl = data.summary.total_pnl_pct;
                    portPnl.textContent = `${pnl > 0 ? '+' : ''}${pnl.toFixed(2)}%`;
                    portPnl.className = `stat-value ${pnl >= 0 ? "text-success" : "text-danger"}`; // Assume text-success/danger exist or just relies on styles
                    if (pnl >= 0) portPnl.style.color = "var(--success)";
                    else portPnl.style.color = "var(--danger)";
                    
                    data.data.forEach(item => {
                        const tr = document.createElement('tr');
                        
                        let badgeClass = 'hold';
                        if(item.alert.includes('TARGET')) badgeClass = 'buy';
                        else if(item.alert.includes('STOP')) badgeClass = 'sell';
                        else if(item.alert.includes('UNDER')) badgeClass = 'sell';
                        
                        tr.innerHTML = `
                            <td style="font-weight: bold; color: var(--text-light);"><div class="symbol-cell">${item.symbol}</div></td>
                            <td>$${item.entry.toFixed(2)}</td>
                            <td>$${item.live_price.toFixed(2)}</td>
                            <td style="color: ${item.pnl_pct >= 0 ? 'var(--success)' : 'var(--danger)'}">
                                ${item.pnl_pct > 0 ? '+' : ''}${item.pnl_pct.toFixed(2)}%
                            </td>
                            <td class="target-price">$${item.target?.toFixed(2) || '--'}</td>
                            <td class="stop-loss">$${item.stop?.toFixed(2) || '--'}</td>
                            <td><span class="badge ${badgeClass}">${item.alert}</span></td>
                        `;
                        portTbody.appendChild(tr);
                    });
                }
            }
        } catch(e) {
            console.error(e);
            loadingPort.innerHTML = '<p style="color:var(--danger)">Failed to load portfolio.</p>';
        }
    }

    // Discovery Logic
    const runDiscoveryBtn = document.getElementById('run-discovery-btn');
    const discoveryStatus = document.getElementById('discovery-status');
    const discoveryGrid = document.getElementById('discovery-results-grid');

    async function fetchDiscoveryResults() {
        try {
            const res = await fetch(`${API_URL}/api/discover`);
            const data = await res.json();
            
            if (data.status === 'running') {
                discoveryStatus.style.display = 'block';
                setTimeout(fetchDiscoveryResults, 3000);
                return;
            }
            
            discoveryStatus.style.display = 'none';
            if (data.data && data.data.length > 0) {
                renderDiscoveryResults(data.data);
            } else if (data.status === 'idle') {
                discoveryGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-muted);">No scan results yet. Start a scan to discover active Nasdaq candidates.</div>';
            }
        } catch (e) {
            console.error("Discovery fetch error:", e);
        }
    }

    function renderDiscoveryResults(results) {
        discoveryGrid.innerHTML = '';
        results.forEach(rec => {
            const card = document.createElement('div');
            card.className = 'discovery-card';
            card.style = 'background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 12px; padding: 16px; transition: all 0.3s ease;';
            card.onmouseover = () => { card.style.background = 'rgba(255,255,255,0.04)'; card.style.borderColor = 'var(--primary)'; };
            card.onmouseout = () => { card.style.background = 'rgba(255,255,255,0.02)'; card.style.borderColor = 'var(--border-color)'; };

            const badgeClass = rec.recommendation === 'BUY' ? 'buy' : (rec.recommendation === 'SELL' ? 'sell' : 'hold');
            
            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div>
                        <h3 style="font-size: 18px; font-weight: 700; color: var(--text-main); margin: 0;">${rec.symbol}</h3>
                        <div style="font-size: 11px; color: var(--primary); font-weight: 600;">$${rec.entry_price?.toFixed(2) || '--'}</div>
                    </div>
                    <span class="badge ${badgeClass}" style="padding: 4px 10px;">${rec.recommendation}</span>
                </div>
                <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px; line-height: 1.4;">
                    ${rec.reasoning.substring(0, 150)}...
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-size: 12px; color: var(--primary);">Conviction: ${rec.conviction}%</div>
                    <div style="font-size: 12px; font-family: monospace; color: var(--text-muted);">${rec.fundamentals_score}/${rec.technical_score}</div>
                </div>
            `;
            discoveryGrid.appendChild(card);
        });
    }

    if (runDiscoveryBtn) {
        runDiscoveryBtn.addEventListener('click', async () => {
            try {
                discoveryStatus.style.display = 'block';
                runDiscoveryBtn.disabled = true;
                runDiscoveryBtn.style.opacity = '0.5';
                
                await fetch(`${API_URL}/api/discover/run`, { method: 'POST' });
                fetchDiscoveryResults();
            } catch (e) {
                console.error("Discovery run error:", e);
            }
        });
    }

    // Initial fetch to populate the dashboard on load
    fetchRecommendations();
    fetchStats();

    // Watchlist & Paper Trading logic
    const watchlistTbody = document.getElementById('watchlist-tbody');
    const watchlistAddBtn = document.getElementById('watchlist-add-btn');
    const watchlistAddInput = document.getElementById('watchlist-add-input');

    async function fetchWatchlist() {
        try {
            const res = await fetch(`${API_URL}/api/watchlist`);
            const data = await res.json();
            if (data.status === 'success') {
                renderWatchlist(data.data);
            }
        } catch (e) {
            console.error(e);
        }
    }

    function renderWatchlist(items) {
        watchlistTbody.innerHTML = '';
        if (items.length === 0) {
            watchlistTbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Watchlist is empty. Add a symbol above to start 90-day tracking.</td></tr>';
            return;
        }

        items.forEach(item => {
            const tr = document.createElement('tr');
            const pnl = item.trade ? ((item.trade.current_price - item.trade.entry_price) / item.trade.entry_price * 100).toFixed(2) : '0.00';
            const pnlClass = parseFloat(pnl) >= 0 ? 'positive' : 'negative';
            
            tr.innerHTML = `
                <td><div class="asset-info"><strong>${item.symbol}</strong></div></td>
                <td>${new Date(item.added_at).toLocaleDateString()}</td>
                <td>${new Date(item.expires_at).toLocaleDateString()}</td>
                <td><span class="badge ${item.trade ? 'badge-success' : 'badge-info'}">${item.trade ? 'TRACKING' : 'PENDING'}</span></td>
                <td><span class="stat-trend ${pnlClass}">${pnl}%</span></td>
                <td>
                    <button class="btn btn-icon remove-watchlist-btn" data-symbol="${item.symbol}">
                        <i data-lucide="trash-2" style="width:16px;height:16px;"></i>
                    </button>
                </td>
            `;
            watchlistTbody.appendChild(tr);
        });
        lucide.createIcons();
        
        document.querySelectorAll('.remove-watchlist-btn').forEach(btn => {
            btn.onclick = async () => {
                const sym = btn.dataset.symbol;
                await fetch(`${API_URL}/api/watchlist/${sym}`, { method: 'DELETE' });
                fetchWatchlist();
            };
        });
    }

    watchlistAddBtn?.addEventListener('click', async () => {
        const symbol = watchlistAddInput.value.toUpperCase().trim();
        if (!symbol) return;
        await fetch(`${API_URL}/api/watchlist?symbol=${symbol}`, { method: 'POST' });
        watchlistAddInput.value = '';
        fetchWatchlist();
    });

    // Cost Analysis Logic
    const costTotalSpent = document.getElementById('cost-total-spent');
    const costToday = document.getElementById('cost-today');
    const costProjection = document.getElementById('cost-projection');
    const costTotalCalls = document.getElementById('cost-total-calls');
    const costsTbody = document.getElementById('costs-tbody');

    async function fetchCostAnalysis() {
        try {
            const res = await fetch(`${API_URL}/api/cost-analysis`);
            const data = await res.json();
            if (data.status === 'success') {
                renderCostAnalysis(data);
            }
        } catch (e) { console.error(e); }
    }

    function renderCostAnalysis(data) {
        costTotalSpent.textContent = `$${data.summary.total_cost.toFixed(4)}`;
        costToday.textContent = `$${data.summary.today_cost.toFixed(4)}`;
        costProjection.textContent = `$${data.summary.monthly_projection.toFixed(2)}`;
        costTotalCalls.textContent = data.summary.total_calls;

        costsTbody.innerHTML = '';
        if (data.history.length === 0) {
            costsTbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">No usage recorded yet. Run analysis to see costs.</td></tr>';
            return;
        }

        data.history.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-size: 11px; color: var(--text-muted);">${new Date(item.timestamp).toLocaleString()}</td>
                <td style="font-family: monospace; font-size: 11px;">${item.model}</td>
                <td>${item.input_tokens}</td>
                <td>${item.output_tokens}</td>
                <td style="font-weight: bold; color: var(--text-main);">$${item.cost.toFixed(4)}</td>
            `;
            costsTbody.appendChild(tr);
        });
    }
    
    // Ensure the initial view is correctly set
    showView('view-dashboard');
});
