class GPUMonitorApp {
    constructor() {
        this.ws = null;
        this.currentGpuIndex = -1;
        this.gpus = [];
        this.systemData = null;
        this.gpuHistory = {};
        this.systemHistory = {};
        this.charts = {};
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;

        this.init();
    }

    init() {
        this.initTabs();
        this.initCharts();
        this.connectWebSocket();
        this.startPing();
    }

    initTabs() {
        const tabBtns = document.querySelectorAll('.tab-btn');
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                this.switchTab(tab);
            });
        });
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('active');
            if (btn.dataset.tab === tabName) {
                btn.classList.add('active');
            }
        });

        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });
        document.getElementById(`${tabName}-tab`).classList.add('active');
    }

    initCharts() {
        const chartConfig = {
            type: 'line',
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: '#a0a0a0',
                            usePointStyle: true,
                            padding: 15
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(22, 33, 62, 0.95)',
                        titleColor: '#e4e4e4',
                        bodyColor: '#a0a0a0',
                        borderColor: '#2d3a5a',
                        borderWidth: 1,
                        padding: 12
                    }
                },
                scales: {
                    x: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)'
                        },
                        ticks: {
                            color: '#a0a0a0',
                            maxTicksLimit: 8
                        }
                    },
                    y: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)'
                        },
                        ticks: {
                            color: '#a0a0a0'
                        },
                        min: 0
                    }
                },
                elements: {
                    line: {
                        tension: 0.4,
                        borderWidth: 2
                    },
                    point: {
                        radius: 0,
                        hoverRadius: 4
                    }
                }
            }
        };

        const chartConfigs = [
            { id: 'tempChart', label: '温度 (°C)', maxValue: 120, color: '#ef4444' },
            { id: 'utilChart', label: 'GPU 利用率 (%)', maxValue: 100, color: '#4ade80' },
            { id: 'memChart', label: '显存使用率 (%)', maxValue: 100, color: '#60a5fa' },
            { id: 'powerChart', label: '功耗 (W)', maxValue: null, color: '#fbbf24' },
            { id: 'fanChart', label: '风扇转速 (%)', maxValue: 100, color: '#a78bfa' },
            { id: 'clockChart', label: '频率 (MHz)', maxValue: null, color: '#f472b6' }
        ];

        const gpuColors = [
            '#76b900',
            '#60a5fa',
            '#f472b6',
            '#fbbf24',
            '#a78bfa',
            '#ef4444'
        ];

        chartConfigs.forEach(config => {
            const ctx = document.getElementById(config.id).getContext('2d');
            
            const chartData = {
                labels: [],
                datasets: []
            };

            const chartOptions = JSON.parse(JSON.stringify(chartConfig.options));
            if (config.maxValue !== null) {
                chartOptions.scales.y.max = config.maxValue;
            }

            this.charts[config.id] = new Chart(ctx, {
                type: 'line',
                data: chartData,
                options: chartOptions
            });
        });

        this.gpuColors = gpuColors;
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.updateConnectionStatus('connecting', '连接中...');

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.connected = true;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus('connected', '已连接');
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (e) {
                    console.error('Failed to parse message:', e);
                }
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket disconnected:', event);
                this.connected = false;
                this.updateConnectionStatus('disconnected', '已断开');
                this.attemptReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        } catch (e) {
            console.error('Failed to create WebSocket:', e);
            this.updateConnectionStatus('disconnected', '连接失败');
            this.attemptReconnect();
        }
    }

    attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.updateConnectionStatus('disconnected', '连接失败，无法重连');
            return;
        }

        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.min(this.reconnectAttempts, 5);
        this.updateConnectionStatus('connecting', `重连中 (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

        setTimeout(() => {
            if (!this.connected) {
                this.connectWebSocket();
            }
        }, delay);
    }

    startPing() {
        setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);
    }

    updateConnectionStatus(status, text) {
        const statusDot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');

        statusDot.classList.remove('connected', 'disconnected');
        if (status === 'connected') {
            statusDot.classList.add('connected');
        } else if (status === 'disconnected') {
            statusDot.classList.add('disconnected');
        }

        statusText.textContent = text;
    }

    handleMessage(data) {
        const type = data.type;

        if (type === 'initial') {
            this.gpus = data.gpus || [];
            this.systemData = data.system;
            this.gpuHistory = data.gpu_history || {};
            this.systemHistory = data.system_history || {};
            this.renderGPUSelector();
            this.renderGPUCards();
            this.updateCharts();
            this.renderSystemInfo();
            this.renderProcesses();
        } else if (type === 'realtime') {
            this.gpus = data.gpus || [];
            this.systemData = data.system;
            this.gpuHistory = data.gpu_history || {};
            this.systemHistory = data.system_history || {};
            this.updateGPUCards();
            this.updateCharts();
            this.renderSystemInfo();
            this.renderProcesses();
        } else if (type === 'pong') {
            return;
        }

        document.getElementById('updateTime').textContent = 
            new Date(data.timestamp).toLocaleTimeString('zh-CN');
    }

    renderGPUSelector() {
        const selector = document.getElementById('gpuSelector');
        const processSelector = document.getElementById('processGpuSelector');
        
        if (!this.gpus || this.gpus.length === 0) {
            selector.innerHTML = '<div class="no-processes">未检测到 GPU</div>';
            processSelector.innerHTML = '';
            return;
        }

        let html = '';
        
        if (this.gpus.length > 1) {
            html += `<button class="gpu-select-btn ${this.currentGpuIndex === -1 ? 'all active' : ''}" data-index="-1">全部 GPU</button>`;
        }

        this.gpus.forEach((gpu, idx) => {
            const isActive = this.currentGpuIndex === gpu.index || 
                           (this.currentGpuIndex === -1 && this.gpus.length === 1);
            html += `<button class="gpu-select-btn ${isActive ? 'active' : ''}" data-index="${gpu.index}">
                GPU ${gpu.index}: ${gpu.name}
            </button>`;
        });

        selector.innerHTML = html;
        processSelector.innerHTML = html;

        selector.querySelectorAll('.gpu-select-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                this.selectGPU(index);
            });
        });

        processSelector.querySelectorAll('.gpu-select-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                this.selectGPU(index);
            });
        });
    }

    selectGPU(index) {
        this.currentGpuIndex = index;
        this.renderGPUSelector();
        this.updateGPUCards();
        this.updateCharts();
        this.renderProcesses();
    }

    renderGPUCards() {
        const container = document.getElementById('gpuCards');
        
        if (!this.gpus || this.gpus.length === 0) {
            container.innerHTML = '<div class="no-processes">未检测到 GPU</div>';
            return;
        }

        let html = '';
        
        const gpusToShow = this.currentGpuIndex === -1 ? 
            this.gpus : this.gpus.filter(g => g.index === this.currentGpuIndex);

        gpusToShow.forEach(gpu => {
            const tempLevel = this.getLevel(gpu.temperature, 70, 90);
            const utilLevel = this.getLevel(gpu.utilization_gpu, 50, 80);
            const memLevel = this.getLevel(gpu.memory_used_percent, 50, 80);

            html += `
                <div class="gpu-card" data-index="${gpu.index}">
                    <div class="gpu-card-header">
                        <span class="gpu-name">${gpu.name}</span>
                        <span class="gpu-index">GPU ${gpu.index}</span>
                    </div>
                    <div class="gpu-stats">
                        <div class="stat-item">
                            <span class="stat-label">温度</span>
                            <span class="stat-value">${gpu.temperature}°C</span>
                            <div class="progress-bar">
                                <div class="progress-fill ${tempLevel}" style="width: ${(gpu.temperature / 120 * 100).toFixed(1)}%"></div>
                                <span class="progress-label">${(gpu.temperature / 120 * 100).toFixed(1)}%</span>
                            </div>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">GPU 利用率</span>
                            <span class="stat-value">${gpu.utilization_gpu.toFixed(1)}%</span>
                            <div class="progress-bar">
                                <div class="progress-fill ${utilLevel}" style="width: ${gpu.utilization_gpu}%"></div>
                                <span class="progress-label">${gpu.utilization_gpu.toFixed(1)}%</span>
                            </div>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">显存</span>
                            <span class="stat-value">${(gpu.memory_used_mb).toFixed(1)} / ${(gpu.memory_total_mb).toFixed(1)} MB</span>
                            <div class="progress-bar">
                                <div class="progress-fill ${memLevel}" style="width: ${gpu.memory_used_percent.toFixed(1)}%"></div>
                                <span class="progress-label">${gpu.memory_used_percent.toFixed(1)}%</span>
                            </div>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">功耗</span>
                            <span class="stat-value">${gpu.power_draw.toFixed(1)} W</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">风扇转速</span>
                            <span class="stat-value">${gpu.fan_speed}%</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">GPU 频率</span>
                            <span class="stat-value">${gpu.clock_gpu} MHz</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">显存频率</span>
                            <span class="stat-value">${gpu.clock_memory} MHz</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">驱动版本</span>
                            <span class="stat-value">${gpu.driver_version}</span>
                        </div>
                    </div>
                </div>
            `;
        });

        container.innerHTML = html;
    }

    updateGPUCards() {
        this.renderGPUCards();
    }

    getLevel(value, medium, high) {
        if (value >= high) return 'high';
        if (value >= medium) return 'medium';
        return 'low';
    }

    updateCharts() {
        if (!this.gpuHistory || Object.keys(this.gpuHistory).length === 0) {
            return;
        }

        const gpusToShow = this.currentGpuIndex === -1 ? 
            Object.keys(this.gpuHistory).map(k => parseInt(k)) : [this.currentGpuIndex];

        const chartDataMap = {
            'tempChart': 'temperature',
            'utilChart': 'utilization_gpu',
            'memChart': 'memory_used_percent',
            'powerChart': 'power_draw',
            'fanChart': 'fan_speed',
            'clockChart': 'clock_gpu'
        };

        Object.entries(chartDataMap).forEach(([chartId, dataKey]) => {
            const chart = this.charts[chartId];
            if (!chart) return;

            const labels = [];
            const datasets = [];

            gpusToShow.forEach((gpuIdx, colorIdx) => {
                const history = this.gpuHistory[gpuIdx];
                if (!history || !history.timestamp || history.timestamp.length === 0) return;

                const gpu = this.gpus.find(g => g.index === gpuIdx);
                const label = gpu ? `GPU ${gpuIdx}: ${gpu.name}` : `GPU ${gpuIdx}`;
                const color = this.gpuColors[colorIdx % this.gpuColors.length];

                if (labels.length === 0) {
                    labels.push(...history.timestamp);
                }

                datasets.push({
                    label: label,
                    data: history[dataKey] || [],
                    borderColor: color,
                    backgroundColor: `${color}20`,
                    fill: true
                });
            });

            chart.data.labels = labels;
            chart.data.datasets = datasets;
            chart.update('none');
        });
    }

    renderSystemInfo() {
        if (!this.systemData) return;

        const system = this.systemData.system;
        const cpu = this.systemData.cpu;
        const memory = this.systemData.memory;
        const swap = this.systemData.swap;
        const disks = this.systemData.disks;
        const networks = this.systemData.network_interfaces;
        const netStats = this.systemData.network_stats;

        let systemHtml = `
            <div class="info-item">
                <span class="info-label">主机名</span>
                <span class="info-value">${system.hostname}</span>
            </div>
            <div class="info-item">
                <span class="info-label">操作系统</span>
                <span class="info-value">${system.os} ${system.architecture}</span>
            </div>
            <div class="info-item">
                <span class="info-label">CPU</span>
                <span class="info-value">${system.cpu_brand}</span>
            </div>
            <div class="info-item">
                <span class="info-label">运行时间</span>
                <span class="info-value">${this.formatUptime(system.uptime_seconds)}</span>
            </div>
        `;
        document.getElementById('systemInfo').innerHTML = systemHtml;

        const cpuProgress = document.getElementById('cpuProgress');
        cpuProgress.querySelector('.progress-fill').style.width = `${cpu.percent}%`;
        cpuProgress.querySelector('.progress-fill').className = `progress-fill ${this.getLevel(cpu.percent, 50, 80)}`;
        cpuProgress.querySelector('.progress-label').textContent = `${cpu.percent.toFixed(1)}%`;

        let cpuHtml = `
            <div class="info-item">
                <span class="info-label">核心数</span>
                <span class="info-value">${cpu.count} (${cpu.count_physical} 物理)</span>
            </div>
            <div class="info-item">
                <span class="info-label">当前频率</span>
                <span class="info-value">${cpu.frequency_current} MHz</span>
            </div>
            <div class="info-item">
                <span class="info-label">负载</span>
                <span class="info-value">${cpu.load_avg_1.toFixed(2)} / ${cpu.load_avg_5.toFixed(2)} / ${cpu.load_avg_15.toFixed(2)}</span>
            </div>
        `;
        document.getElementById('cpuInfo').innerHTML = cpuHtml;

        const memProgress = document.getElementById('memProgress');
        memProgress.querySelector('.progress-fill').style.width = `${memory.percent}%`;
        memProgress.querySelector('.progress-fill').className = `progress-fill ${this.getLevel(memory.percent, 50, 80)}`;
        memProgress.querySelector('.progress-label').textContent = `${memory.percent.toFixed(1)}%`;

        let memHtml = `
            <div class="info-item">
                <span class="info-label">总量</span>
                <span class="info-value">${(memory.total_mb / 1024).toFixed(2)} GB</span>
            </div>
            <div class="info-item">
                <span class="info-label">已用</span>
                <span class="info-value">${(memory.used_mb / 1024).toFixed(2)} GB</span>
            </div>
            <div class="info-item">
                <span class="info-label">可用</span>
                <span class="info-value">${(memory.available_mb / 1024).toFixed(2)} GB</span>
            </div>
        `;
        document.getElementById('memInfo').innerHTML = memHtml;

        const swapProgress = document.getElementById('swapProgress');
        swapProgress.querySelector('.progress-fill').style.width = `${swap.percent}%`;
        swapProgress.querySelector('.progress-fill').className = `progress-fill ${this.getLevel(swap.percent, 50, 80)}`;
        swapProgress.querySelector('.progress-label').textContent = `${swap.percent.toFixed(1)}%`;

        let swapHtml = `
            <div class="info-item">
                <span class="info-label">总量</span>
                <span class="info-value">${(swap.total_mb / 1024).toFixed(2)} GB</span>
            </div>
            <div class="info-item">
                <span class="info-label">已用</span>
                <span class="info-value">${(swap.used_mb / 1024).toFixed(2)} GB</span>
            </div>
            <div class="info-item">
                <span class="info-label">可用</span>
                <span class="info-value">${(swap.free_mb / 1024).toFixed(2)} GB</span>
            </div>
        `;
        document.getElementById('swapInfo').innerHTML = swapHtml;

        let diskHtml = '';
        disks.forEach(disk => {
            const level = this.getLevel(disk.percent, 70, 90);
            diskHtml += `
                <div class="disk-item">
                    <div class="disk-header">
                        <span class="disk-name">${disk.mountpoint}</span>
                        <span class="disk-fstype">${disk.device} (${disk.fstype})</span>
                    </div>
                    <div class="disk-usage">
                        <span class="info-label">${disk.used_gb.toFixed(2)} GB / ${disk.total_gb.toFixed(2)} GB</span>
                        <div class="progress-bar">
                            <div class="progress-fill ${level}" style="width: ${disk.percent}%"></div>
                            <span class="progress-label">${disk.percent.toFixed(1)}%</span>
                        </div>
                    </div>
                </div>
            `;
        });
        document.getElementById('diskList').innerHTML = diskHtml || '<div class="no-processes">未检测到磁盘分区</div>';

        let networkHtml = '';
        networks.forEach(net => {
            networkHtml += `
                <div class="network-item">
                    <div class="network-name">
                        <span class="network-status ${net.is_up ? 'up' : ''}"></span>
                        ${net.name}
                    </div>
                    <div class="info-list">
                        <div class="info-item">
                            <span class="info-label">IPv4</span>
                            <span class="info-value">${net.ipv4 || '-'}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">IPv6</span>
                            <span class="info-value">${net.ipv6 || '-'}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">MAC</span>
                            <span class="info-value">${net.mac || '-'}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">速度</span>
                            <span class="info-value">${net.speed > 0 ? net.speed + ' Mbps' : '-'}</span>
                        </div>
                    </div>
                </div>
            `;
        });
        document.getElementById('networkList').innerHTML = networkHtml || '<div class="no-processes">未检测到网络接口</div>';
    }

    formatUptime(seconds) {
        const hours = Math.floor(seconds / 3600);
        const days = Math.floor(hours / 24);
        const remainingHours = hours % 24;
        
        if (days > 0) {
            return `${days} 天 ${remainingHours} 小时`;
        }
        return `${remainingHours} 小时`;
    }

    renderProcesses() {
        const tbody = document.getElementById('processTableBody');
        const noProcesses = document.getElementById('noProcesses');

        if (!this.gpus || this.gpus.length === 0) {
            tbody.innerHTML = '';
            noProcesses.style.display = 'block';
            noProcesses.textContent = '未检测到 GPU';
            return;
        }

        const gpusToShow = this.currentGpuIndex === -1 ? 
            this.gpus : this.gpus.filter(g => g.index === this.currentGpuIndex);

        let allProcesses = [];
        gpusToShow.forEach(gpu => {
            if (gpu.processes && gpu.processes.length > 0) {
                gpu.processes.forEach(proc => {
                    allProcesses.push({
                        ...proc,
                        gpuIndex: gpu.index,
                        gpuName: gpu.name,
                        memoryPercent: gpu.memory_total > 0 ? 
                            (proc.used_memory / gpu.memory_total * 100) : 0
                    });
                });
            }
        });

        if (allProcesses.length === 0) {
            tbody.innerHTML = '';
            noProcesses.style.display = 'block';
            noProcesses.textContent = '当前 GPU 没有运行中的进程';
            return;
        }

        noProcesses.style.display = 'none';

        allProcesses.sort((a, b) => b.used_memory - a.used_memory);

        let html = '';
        allProcesses.forEach(proc => {
            html += `
                <tr>
                    <td class="process-pid">${proc.pid}</td>
                    <td class="process-name">${proc.process_name}</td>
                    <td class="process-memory">${proc.used_memory_mb.toFixed(1)} MB</td>
                    <td>
                        <div class="progress-bar" style="margin-top: 25px;">
                            <div class="progress-fill ${this.getLevel(proc.memoryPercent, 20, 50)}" 
                                 style="width: ${Math.min(proc.memoryPercent, 100)}%"></div>
                            <span class="progress-label">${proc.memoryPercent.toFixed(2)}%</span>
                        </div>
                    </td>
                </tr>
            `;
        });

        tbody.innerHTML = html;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new GPUMonitorApp();
});
