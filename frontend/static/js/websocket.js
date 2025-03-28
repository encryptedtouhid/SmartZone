/**
 * WebSocket client for real-time updates
 */
class WebSocketClient {
    constructor() {
        this.socket = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // Starting delay in ms
        this.handlers = {
            driver_updates: [],
            zone_updates: [],
            request_updates: []
        };
        this.connectionStatusElement = document.getElementById('connectionStatus');
    }

    /**
     * Connect to the WebSocket server
     */
    connect() {
        // Close existing connection if any
        if (this.socket) {
            this.socket.close();
        }

        // Create new WebSocket connection
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.socket = new WebSocket(wsUrl);

        // Set up event handlers
        this.socket.onopen = () => this.onOpen();
        this.socket.onclose = (event) => this.onClose(event);
        this.socket.onerror = (error) => this.onError(error);
        this.socket.onmessage = (event) => this.onMessage(event);
    }

    /**
     * Handle WebSocket open event
     */
    onOpen() {
        console.log('WebSocket connection established');
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.updateConnectionStatus(true);

        // Start ping interval to keep connection alive
        this.startPingInterval();
    }

    /**
     * Handle WebSocket close event
     */
    onClose(event) {
        console.log('WebSocket connection closed', event);
        this.isConnected = false;
        this.updateConnectionStatus(false);
        clearInterval(this.pingInterval);

        // Attempt to reconnect if not a clean close
        if (event.code !== 1000) {
            this.attemptReconnect();
        }
    }

    /**
     * Handle WebSocket error
     */
    onError(error) {
        console.error('WebSocket error:', error);
        this.updateConnectionStatus(false);
    }

    /**
     * Handle incoming WebSocket messages
     */
    onMessage(event) {
        try {
            const message = JSON.parse(event.data);

            // Handle different message types
            if (message.type === 'pong') {
                // Pong response, connection is still alive
                return;
            }

            // Dispatch messages to registered handlers
            if (message.type in this.handlers) {
                for (const handler of this.handlers[message.type]) {
                    handler(message.data);
                }
            }
        } catch (error) {
            console.error('Error processing WebSocket message:', error);
        }
    }

    /**
     * Register a handler for a specific message type
     */
    addMessageHandler(type, handler) {
        if (type in this.handlers) {
            this.handlers[type].push(handler);
        }
    }

    /**
     * Start a ping interval to keep the connection alive
     */
    startPingInterval() {
        // Send a ping message every 30 seconds
        this.pingInterval = setInterval(() => {
            if (this.isConnected) {
                this.sendMessage({
                    type: 'ping',
                    timestamp: new Date().toISOString()
                });
            }
        }, 30000);
    }

    /**
     * Send a message to the server
     */
    sendMessage(message) {
        if (this.isConnected) {
            this.socket.send(JSON.stringify(message));
        } else {
            console.warn('Cannot send message, WebSocket not connected');
        }
    }

    /**
     * Attempt to reconnect to the server
     */
    attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('Max reconnect attempts reached, giving up');
            return;
        }

        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1);

        console.log(`Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts})`);

        setTimeout(() => {
            console.log('Reconnecting...');
            this.connect();
        }, delay);
    }

    /**
     * Update the connection status UI element
     */
    updateConnectionStatus(connected) {
        if (this.connectionStatusElement) {
            if (connected) {
                this.connectionStatusElement.textContent = '🟢 Connected';
                this.connectionStatusElement.className = 'connected';
            } else {
                this.connectionStatusElement.textContent = '🔴 Disconnected';
                this.connectionStatusElement.className = 'disconnected';
            }
        }
    }

    /**
     * Disconnect from the WebSocket server
     */
    disconnect() {
        if (this.socket) {
            this.socket.close(1000, 'Client disconnecting');
            this.socket = null;
        }
        clearInterval(this.pingInterval);
        this.isConnected = false;
        this.updateConnectionStatus(false);
    }
}

// Create a global WebSocket client instance
const wsClient = new WebSocketClient();

// Connect when the page loads
document.addEventListener('DOMContentLoaded', () => {
    wsClient.connect();
});

// Reconnect when the page becomes visible again
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !wsClient.isConnected) {
        wsClient.connect();
    }
});