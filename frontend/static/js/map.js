/**
 * Map Controller for the SmartZone application
 */
class MapController {
    constructor() {
        this.map = null;
        this.layers = {
            zones: new L.LayerGroup(),
            drivers: new L.LayerGroup(),
            requests: new L.LayerGroup(),
            heatmap: new L.LayerGroup()
        };
        this.markers = {
            drivers: {},
            requests: {}
        };
        this.zonePolygons = {};
        this.mapStyles = {
            streets: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            satellite: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            dark: 'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png'
        };
        this.currentStyle = 'streets';
        this.defaultCenter = [1.3521, 103.8198]; // Singapore
        this.defaultZoom = 13;

        // Color scales for zones based on demand level (0-10)
        this.demandColors = [
            '#f7fcf5', // 0 - Very Low
            '#e5f5e0',
            '#c7e9c0',
            '#a1d99b',
            '#74c476', // 4 - Medium
            '#41ab5d',
            '#238b45',
            '#006d2c',
            '#00441b', // 8 - High
            '#7a0177', // 9 - Very High
            '#49006a'  // 10 - Extreme
        ];
    }

    /**
     * Initialize the map
     */
    initialize() {
        // Create the map
        this.map = L.map('map').setView(this.defaultCenter, this.defaultZoom);

        // Add the base tile layer
        this.tileLayer = L.tileLayer(this.mapStyles[this.currentStyle], {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        }).addTo(this.map);

        // Add layer groups to the map
        Object.values(this.layers).forEach(layer => layer.addTo(this.map));

        // Set up event handlers
        this.setupEventHandlers();

        // Load initial data
        this.loadInitialData();
    }

    /**
     * Set up event handlers for map controls
     */
    setupEventHandlers() {
        // Map style selector
        const mapStyleSelect = document.getElementById('mapStyle');
        if (mapStyleSelect) {
            mapStyleSelect.addEventListener('change', (e) => {
                this.changeMapStyle(e.target.value);
            });
        }

        // Start simulation button
        const startSimBtn = document.getElementById('startSimulation');
        if (startSimBtn) {
            startSimBtn.addEventListener('click', () => {
                this.startSimulation();
            });
        }

        // Stop simulation button
        const stopSimBtn = document.getElementById('stopSimulation');
        if (stopSimBtn) {
            stopSimBtn.addEventListener('click', () => {
                this.stopSimulation();
            });
        }
    }

    /**
     * Change the map style
     */
    changeMapStyle(style) {
        if (style in this.mapStyles) {
            this.currentStyle = style;
            this.tileLayer.setUrl(this.mapStyles[style]);
        }
    }

    /**
     * Load initial data from the API
     */
    async loadInitialData() {
        try {
            // Fetch zones
            const zonesResponse = await fetch('/api/zones');
            if (zonesResponse.ok) {
                const zones = await zonesResponse.json();
                this.renderZones(zones);
            }

            // Fetch drivers
            const driversResponse = await fetch('/api/drivers');
            if (driversResponse.ok) {
                const drivers = await driversResponse.json();
                this.renderDrivers(drivers);
            }

            // Fetch recent ride requests
            const requestsResponse = await fetch('/api/ride-requests?status=pending,accepted,in_progress');
            if (requestsResponse.ok) {
                const requests = await requestsResponse.json();
                this.renderRequests(requests);
            }

        } catch (error) {
            console.error('Error loading initial data:', error);
        }
    }

    /**
     * Start the simulation
     */
    async startSimulation() {
        try {
            // Check if zones exist, if not initialize them
            const zonesResponse = await fetch('/api/zones');
            const zones = await zonesResponse.json();

            if (!zones.length) {
                // Initialize zones
                await fetch('/api/initialize-zones', {
                    method: 'POST'
                });
            }

            // Start simulation
            const response = await fetch('/api/simulation/start', {
                method: 'POST'
            });

            if (response.ok) {
                const simulationStatus = document.getElementById('simulationStatus');
                if (simulationStatus) {
                    simulationStatus.textContent = '🟢 Simulation Running';
                    simulationStatus.className = 'running';
                }
                console.log('Simulation started');
            }

        } catch (error) {
            console.error('Error starting simulation:', error);
        }
    }

    /**
     * Stop the simulation
     */
    async stopSimulation() {
        try {
            const response = await fetch('/api/simulation/stop', {
                method: 'POST'
            });

            if (response.ok) {
                const simulationStatus = document.getElementById('simulationStatus');
                if (simulationStatus) {
                    simulationStatus.textContent = '🔴 Simulation Stopped';
                    simulationStatus.className = 'stopped';
                }
                console.log('Simulation stopped');
            }

        } catch (error) {
            console.error('Error stopping simulation:', error);
        }
    }

    /**
     * Render zones on the map
     */
    renderZones(zones) {
        // Clear existing zones
        this.layers.zones.clearLayers();
        this.zonePolygons = {};

        zones.forEach(zone => {
            // Create a polygon for the zone
            const boundary = zone.boundary;
            const polygon = L.polygon(boundary, {
                color: this.getZoneColor(zone.demand_level),
                weight: 1,
                fillOpacity: zone.is_surge ? 0.6 : 0.3,
                className: `zone-polygon ${zone.is_surge ? 'surge' : ''}`
            });

            // Add popup with zone info
            const popupContent = `
                <div class="zone-popup">
                    <h3>Zone ${zone.zone_id.slice(-4)}</h3>
                    <p>Demand Level: ${zone.demand_level}/10</p>
                    <p>Active Requests: ${zone.current_requests}</p>
                    <p>Drivers: ${zone.drivers_count}</p>
                    <p>${zone.is_surge ? '🔥 Surge Pricing Active' : 'Normal Pricing'}</p>
                </div>
            `;
            polygon.bindPopup(popupContent);

            // Add hover effect
            polygon.on('mouseover', function() {
                this.setStyle({
                    weight: 3,
                    fillOpacity: zone.is_surge ? 0.8 : 0.5
                });
            });

            polygon.on('mouseout', function() {
                this.setStyle({
                    weight: 1,
                    fillOpacity: zone.is_surge ? 0.6 : 0.3
                });
            });

            // Store reference to the polygon
            this.zonePolygons[zone.zone_id] = polygon;

            // Add to layer group
            this.layers.zones.addLayer(polygon);
        });
    }

    /**
     * Get color for a zone based on demand level
     */
    getZoneColor(demandLevel) {
        // Cap demand level to 0-10 range
        const level = Math.min(10, Math.max(0, demandLevel));
        return this.demandColors[level];
    }

    /**
     * Update zones based on real-time data
     */
    updateZones(zonesData) {
        zonesData.zones.forEach(zone => {
            const polygon = this.zonePolygons[zone.zone_id];
            if (polygon) {
                // Update color based on demand level
                polygon.setStyle({
                    color: this.getZoneColor(zone.demand_level),
                    fillOpacity: zone.is_surge ? 0.6 : 0.3
                });

                // Update class
                if (zone.is_surge) {
                    polygon._path.classList.add('surge');
                } else {
                    polygon._path.classList.remove('surge');
                }

                // Update popup content
                const popupContent = `
                    <div class="zone-popup">
                        <h3>Zone ${zone.zone_id.slice(-4)}</h3>
                        <p>Demand Level: ${zone.demand_level}/10</p>
                        <p>Active Requests: ${zone.current_requests}</p>
                        <p>Drivers: ${zone.drivers_count}</p>
                        <p>${zone.is_surge ? '🔥 Surge Pricing Active' : 'Normal Pricing'}</p>
                    </div>
                `;
                polygon.setPopupContent(popupContent);
            }
        });

        // Update the sidebar with surge zones
        this.updateSurgeList(zonesData.zones);
    }

    /**
     * Render drivers on the map
     */
    renderDrivers(drivers) {
        // Clear existing drivers
        this.layers.drivers.clearLayers();
        this.markers.drivers = {};

        drivers.forEach(driver => {
            // Create custom marker
            const marker = this.createDriverMarker(driver);

            // Store reference to the marker
            this.markers.drivers[driver.id] = marker;

            // Add to layer group
            this.layers.drivers.addLayer(marker);
        });

        // Update the sidebar with driver list
        this.updateDriverList(drivers);
    }

    /**
     * Create a custom marker for a driver
     */
    createDriverMarker(driver) {
        const [lon, lat] = driver.location.coordinates;

        // Create icon with rotation
        const icon = L.divIcon({
            className: `driver-marker ${driver.status}`,
            html: `<div style="transform: rotate(${driver.heading}deg);">▲</div>`,
            iconSize: [20, 20]
        });

        // Create marker
        const marker = L.marker([lat, lon], { icon });

        // Add popup with driver info
        const popupContent = `
            <div>
                <h3>${driver.name}</h3>
                <p>Status: ${driver.status}</p>
                <p>Vehicle: ${driver.vehicle_type}</p>
                <p>Speed: ${driver.speed.toFixed(1)} km/h</p>
            </div>
        `;
        marker.bindPopup(popupContent);

        return marker;
    }

    /**
     * Update drivers based on real-time data
     */
    updateDrivers(driversData) {
        driversData.drivers.forEach(driver => {
            const marker = this.markers.drivers[driver.id];
            const [lon, lat] = driver.location.coordinates;

            if (marker) {
                // Update marker position with smooth animation
                marker.setLatLng([lat, lon]);

                // Update icon with new heading and status
                const icon = L.divIcon({
                    className: `driver-marker ${driver.status}`,
                    html: `<div style="transform: rotate(${driver.heading}deg);">▲</div>`,
                    iconSize: [20, 20]
                });
                marker.setIcon(icon);

                // Update popup content
                const popupContent = `
                    <div>
                        <h3>${driver.name}</h3>
                        <p>Status: ${driver.status}</p>
                        <p>Vehicle: ${driver.vehicle_type || 'Unknown'}</p>
                        <p>Speed: ${driver.speed ? driver.speed.toFixed(1) : '0'} km/h</p>
                    </div>
                `;
                marker.getPopup()?.setContent(popupContent);
            } else {
                // Create new marker for new driver
                const newMarker = this.createDriverMarker(driver);
                this.markers.drivers[driver.id] = newMarker;
                this.layers.drivers.addLayer(newMarker);
            }
        });

        // Update the sidebar with driver list
        this.updateDriverList(driversData.drivers);
    }

    /**
     * Render ride requests on the map
     */
    renderRequests(requests) {
        // Clear existing requests
        this.layers.requests.clearLayers();
        this.markers.requests = {};

        requests.forEach(request => {
            // Only show pending or in progress requests
            if (['pending', 'accepted', 'in_progress'].includes(request.status)) {
                // Create pickup marker
                const marker = this.createRequestMarker(request);

                // Store reference to the marker
                this.markers.requests[request.id] = marker;

                // Add to layer group
                this.layers.requests.addLayer(marker);
            }
        });

        // Update the sidebar with request list
        this.updateRequestList(requests);
    }

    /**
     * Create a marker for a ride request
     */
    createRequestMarker(request) {
        const [pickupLon, pickupLat] = request.pickup_location.coordinates;

        // Create icon
        const icon = L.divIcon({
            className: 'request-marker',
            html: '📍',
            iconSize: [24, 24]
        });

        // Create marker
        const marker = L.marker([pickupLat, pickupLon], { icon });

        // Add popup with request info
        const popupContent = `
            <div>
                <h3>Ride Request</h3>
                <p>Status: ${request.status}</p>
                <p>Created: ${new Date(request.created_at).toLocaleTimeString()}</p>
                ${request.driver_id ? `<p>Assigned to: ${request.driver_id}</p>` : ''}
            </div>
        `;
        marker.bindPopup(popupContent);

        return marker;
    }

    /**
     * Update ride requests based on real-time data
     */
    updateRequests(requestsData) {
        // Clear old markers
        this.layers.requests.clearLayers();
        this.markers.requests = {};

        // Add current requests
        requestsData.requests.forEach(request => {
            // Only show active requests
            if (['pending', 'accepted', 'in_progress'].includes(request.status)) {
                // Create marker
                const marker = this.createRequestMarker(request);

                // Store reference
                this.markers.requests[request.id] = marker;

                // Add to layer
                this.layers.requests.addLayer(marker);
            }
        });

        // Update the sidebar with request list
        this.updateRequestList(requestsData.requests);
    }

    /**
     * Update the surge zone list in the sidebar
     */
    updateSurgeList(zones) {
        const surgeList = document.getElementById('surgeList');
        if (!surgeList) return;

        // Filter for surge zones
        const surgeZones = zones.filter(zone => zone.is_surge);

        // Sort by demand level (highest first)
        surgeZones.sort((a, b) => b.demand_level - a.demand_level);

        // Create HTML
        let html = '';
        if (surgeZones.length === 0) {
            html = '<div class="list-item">No surge zones active</div>';
        } else {
            surgeZones.forEach(zone => {
                html += `
                    <div class="list-item surge">
                        <strong>Zone ${zone.zone_id.slice(-4)}</strong>
                        <br>
                        Demand: ${zone.demand_level}/10
                        <br>
                        Requests: ${zone.current_requests}
                    </div>
                `;
            });
        }

        surgeList.innerHTML = html;
    }

    /**
     * Update the driver list in the sidebar
     */
    updateDriverList(drivers) {
        const driverList = document.getElementById('driverList');
        if (!driverList) return;

        // Sort by status (available first)
        drivers.sort((a, b) => {
            if (a.status === 'available' && b.status !== 'available') return -1;
            if (a.status !== 'available' && b.status === 'available') return 1;
            return 0;
        });

        // Limit to top 10
        const topDrivers = drivers.slice(0, 10);

        // Create HTML
        let html = '';
        topDrivers.forEach(driver => {
            html += `
                <div class="list-item ${driver.status}">
                    <strong>${driver.name}</strong>
                    <br>
                    Status: ${driver.status}
                    <br>
                    Vehicle: ${driver.vehicle_type || 'Unknown'}
                </div>
            `;
        });

        driverList.innerHTML = html;
    }

    /**
     * Update the request list in the sidebar
     */
    updateRequestList(requests) {
        const requestList = document.getElementById('requestList');
        if (!requestList) return;

        // Filter active requests
        const activeRequests = requests.filter(req =>
            ['pending', 'accepted', 'in_progress'].includes(req.status)
        );

        // Sort by creation time (newest first)
        activeRequests.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

        // Limit to top 5
        const topRequests = activeRequests.slice(0, 5);

        // Create HTML
        let html = '';
        if (topRequests.length === 0) {
            html = '<div class="list-item">No active requests</div>';
        } else {
            topRequests.forEach(request => {
                const time = new Date(request.created_at).toLocaleTimeString();
                html += `
                    <div class="list-item">
                        <strong>Request ${request.id.slice(-4)}</strong>
                        <br>
                        Status: ${request.status}
                        <br>
                        Time: ${time}
                    </div>
                `;
            });
        }

        requestList.innerHTML = html;
    }
}

// Create and initialize the map controller when the page loads
let mapController;
document.addEventListener('DOMContentLoaded', () => {
    mapController = new MapController();
    mapController.initialize();

    // Register WebSocket handlers for real-time updates
    wsClient.addMessageHandler('driver_updates', (data) => {
        mapController.updateDrivers(data);
    });

    wsClient.addMessageHandler('zone_updates', (data) => {
        mapController.updateZones(data);
    });

    wsClient.addMessageHandler('request_updates', (data) => {
        mapController.updateRequests(data);
    });
});