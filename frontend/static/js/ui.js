/**
 * UI Controller for SmartZone dashboard
 */
class UIController {
    constructor() {
        this.statsChart = null;
        this.demandData = {
            labels: [],
            datasets: [{
                label: 'Zone Demand Levels',
                data: [],
                backgroundColor: 'rgba(54, 162, 235, 0.5)',
                borderColor: 'rgba(54, 162, 235, 1)',
                borderWidth: 1
            }]
        };
    }

    /**
     * Initialize the UI components
     */
    initialize() {
        // Set up charts
        this.initializeCharts();

        // Set up event listeners
        this.setupEventListeners();
    }

    /**
     * Initialize charts
     */
    initializeCharts() {
        const statsChartElement = document.getElementById('statsChart');
        if (statsChartElement) {
            this.statsChart = new Chart(statsChartElement, {
                type: 'bar',
                data: this.demandData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 10,
                            title: {
                                display: true,
                                text: 'Demand Level'
                            }
                        },
                        x: {
                            title: {
                                display: true,
                                text: 'Zones'
                            }
                        }
                    }
                }
            });
        }
    }

    /**
     * Setup event listeners
     */
    setupEventListeners() {
        // Toggle sidebar on smaller screens
        const sidebar = document.querySelector('.sidebar');
        const toggleButton = document.createElement('button');
        toggleButton.textContent = '≡';
        toggleButton.className = 'sidebar-toggle';
        toggleButton.style.cssText = `
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            font-size: 24px;
            background: white;
            border: none;
            border-radius: 4px;
            padding: 5px 10px;
            box-shadow: 0 1px 5px rgba(0,0,0,0.2);
            display: none;
        `;

        document.body.appendChild(toggleButton);

        // Show toggle button on smaller screens
        const checkScreenSize = () => {
            if (window.innerWidth <= 768) {
                toggleButton.style.display = 'block';
                if (sidebar) sidebar.classList.add('hidden');
            } else {
                toggleButton.style.display = 'none';
                if (sidebar) sidebar.classList.remove('hidden');
            }
        };

        window.addEventListener('resize', checkScreenSize);
        checkScreenSize();

        toggleButton.addEventListener('click', () => {
            if (sidebar) sidebar.classList.toggle('hidden');
        });
    }

    /**
     * Update the zone statistics chart
     */
    updateZoneStats(zonesData) {
        if (!this.statsChart) return;

        // Sort zones by demand level (highest first)
        const sortedZones = [...zonesData.zones].sort((a, b) => b.demand_level - a.demand_level);

        // Take top 10 zones
        const topZones = sortedZones.slice(0, 10);

        // Update chart data
        this.demandData.labels = topZones.map(zone => zone.zone_id.slice(-4));
        this.demandData.datasets[0].data = topZones.map(zone => zone.demand_level);

        // Add color based on surge status
        this.demandData.datasets[0].backgroundColor = topZones.map(zone =>
            zone.is_surge ? 'rgba(231, 76, 60, 0.5)' : 'rgba(52, 152, 219, 0.5)'
        );
        this.demandData.datasets[0].borderColor = topZones.map(zone =>
            zone.is_surge ? 'rgba(231, 76, 60, 1)' : 'rgba(52, 152, 219, 1)'
        );

        // Update chart
        this.statsChart.update();
    }
}

// Create and initialize the UI controller
let uiController;
document.addEventListener('DOMContentLoaded', () => {
    uiController = new UIController();
    uiController.initialize();

    // Register WebSocket handler for zone updates to update chart
    wsClient.addMessageHandler('zone_updates', (data) => {
        uiController.updateZoneStats(data);
    });
});

// Add CSS for sidebar toggle on small screens
const style = document.createElement('style');
style.textContent = `
    @media (max-width: 768px) {
        .sidebar.hidden {
            display: none;
        }

        .sidebar {
            position: absolute;
            z-index: 900;
            background: white;
            height: auto;
            max-height: 80vh;
            box-shadow: 0 0 10px rgba(0,0,0,0.2);
        }
    }
`;
document.head.appendChild(style);