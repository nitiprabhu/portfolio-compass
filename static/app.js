document.addEventListener('DOMContentLoaded', () => {
    // API endpoints
    const API_URL = '';

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
            trHead.innerHTML = `<td colspan="7" style="background: rgba(255, 255, 255, 0.03); font-weight: 700; color: var(--primary); padding: 12px 16px;">
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
                
                tr.innerHTML = `
                    <td style="padding-left: 38px; color: var(--text-muted); font-size: 13px;">
                        ${dateStr}
                    </td>
                    <td><span class="badge ${badgeClass}">${rec.recommendation}</span></td>
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
                    <td>${rec.fundamentals_score}/13 | ${rec.technical_score}/5</td>
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
            startAnalysisBtn.textContent = 'Start Background Analysis';
            startAnalysisBtn.disabled = false;
        }
    });

    // Portfolio Fetch Logic
    const viewDashboard = document.getElementById('view-dashboard');
    const viewPortfolio = document.getElementById('view-portfolio');
    const navDashboard = document.getElementById('nav-dashboard');
    const navPortfolio = document.getElementById('nav-portfolio');
    
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

    // Navigation handlers
    navDashboard.addEventListener('click', (e) => {
        e.preventDefault();
        navDashboard.classList.add('active');
        navPortfolio.classList.remove('active');
        viewDashboard.classList.remove('hidden');
        viewPortfolio.classList.add('hidden');
        document.querySelector('.top-header h1').textContent = "Dashboard";
    });

    navPortfolio.addEventListener('click', (e) => {
        e.preventDefault();
        navPortfolio.classList.add('active');
        navDashboard.classList.remove('active');
        viewPortfolio.classList.remove('hidden');
        viewDashboard.classList.add('hidden');
        document.querySelector('.top-header h1').textContent = "Live Portfolio Tracker";
        fetchPortfolio();
    });

    // Initial load
    fetchStats();
    fetchRecommendations();
});
