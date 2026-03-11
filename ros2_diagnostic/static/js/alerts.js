/**
 * Alert Management Module
 * WebSocket-based real-time updates
 */

const AlertManager = {
    alerts: [],
    activeCount: 0,
    stats: { total: 0, active: 0, resolved: 0, ignored: 0, critical: 0, warning: 0 },

    /**
     * Resolve an alert
     * @param {number} alertId - Alert ID to resolve
     */
    async resolveAlert(alertId) {
        try {
            const result = await API.alerts.resolve(alertId);

            if (result.success) {
                // Remove from local list
                this.alerts = this.alerts.filter(a => a.id !== alertId);
                this.activeCount = this.alerts.length;
                this.render();
                showNotification('success', 'Alert resolved');
                return true;
            } else {
                showNotification('error', result.message || 'Failed to resolve alert');
            }
        } catch (error) {
            console.error('Error resolving alert:', error);
            showNotification('error', 'Error resolving alert');
        }
        return false;
    },

    /**
     * Ignore an alert
     * @param {number} alertId - Alert ID to ignore
     */
    async ignoreAlert(alertId) {
        try {
            const result = await API.alerts.ignore(alertId);

            if (result.success) {
                this.alerts = this.alerts.filter(a => a.id !== alertId);
                this.activeCount = this.alerts.length;
                this.render();
                showNotification('success', 'Alert ignored');
                return true;
            }
        } catch (error) {
            console.error('Error ignoring alert:', error);
            showNotification('error', 'Error ignoring alert');
        }
        return false;
    },

    /**
     * Resolve all active alerts
     */
    async resolveAllAlerts() {
        if (this.alerts.length === 0) {
            showNotification('warning', 'No active alerts');
            return false;
        }
        if (!confirm('Resolve all active alerts?')) return false;

        try {
            const result = await API.alerts.resolveAll();
            if (result.success) {
                this.alerts = result.active || [];
                this.activeCount = this.alerts.length;
                this.render();
                this.fetchStats();
                showNotification('success', result.message || 'All alerts resolved');
                return true;
            }
            showNotification('error', result.message || 'Failed to resolve alerts');
        } catch (error) {
            console.error('Error resolving all alerts:', error);
            // Fallback: resolve one-by-one if bulk API is unavailable
            const ok = await this._bulkActionFallback('resolve', 'Resolved');
            if (ok) return true;
            showNotification('error', 'Error resolving alerts');
        }
        return false;
    },

    /**
     * Ignore all active alerts
     */
    async ignoreAllAlerts() {
        if (this.alerts.length === 0) {
            showNotification('warning', 'No active alerts');
            return false;
        }
        if (!confirm('Ignore all active alerts?')) return false;

        try {
            const result = await API.alerts.ignoreAll();
            if (result.success) {
                this.alerts = result.active || [];
                this.activeCount = this.alerts.length;
                this.render();
                this.fetchStats();
                showNotification('success', result.message || 'All alerts ignored');
                return true;
            }
            showNotification('error', result.message || 'Failed to ignore alerts');
        } catch (error) {
            console.error('Error ignoring all alerts:', error);
            // Fallback: ignore one-by-one if bulk API is unavailable
            const ok = await this._bulkActionFallback('ignore', 'Ignored');
            if (ok) return true;
            showNotification('error', 'Error ignoring alerts');
        }
        return false;
    },

    /**
     * Fallback bulk handler using per-alert APIs.
     * @param {'resolve'|'ignore'} action
     * @param {string} verb
     * @returns {boolean}
     */
    async _bulkActionFallback(action, verb) {
        const ids = this.alerts.map(a => a.id);
        if (ids.length === 0) return false;

        const succeeded = new Set();
        for (const id of ids) {
            try {
                const result = action === 'resolve'
                    ? await API.alerts.resolve(id)
                    : await API.alerts.ignore(id);
                if (result && result.success) {
                    succeeded.add(id);
                }
            } catch (e) {
                console.error(`Bulk ${action} failed for alert ${id}:`, e);
            }
        }

        if (succeeded.size > 0) {
            this.alerts = this.alerts.filter(a => !succeeded.has(a.id));
            this.activeCount = this.alerts.length;
            this.render();
            this.fetchStats();
            showNotification('success', `${verb} ${succeeded.size} alert(s)`);
            return true;
        }

        return false;
    },

    /**
     * Render alerts to the DOM
     */
    render() {
        const container = document.getElementById('activeAlertsList');
        const countEl = document.getElementById('alertCount');

        if (!container) return;

        // Update count badge
        if (countEl) {
            countEl.textContent = this.activeCount;
            countEl.className = 'alert-count' + (this.activeCount > 0 ? ' has-alerts' : '');
        }

        // Update notification count in header
        this.updateNotificationCount();

        // Clear container
        container.innerHTML = '';

        if (this.alerts.length === 0) {
            container.innerHTML = '<div class="no-alerts">No active alerts</div>';
            return;
        }

        // Render each alert
        this.alerts.forEach(alert => {
            const alertEl = this.createAlertElement(alert);
            container.appendChild(alertEl);
        });
    },

    /**
     * Create HTML element for an alert
     * @param {Object} alert - Alert data object
     * @returns {HTMLElement}
     */
    createAlertElement(alert) {
        const div = document.createElement('div');
        div.className = `alert-item ${alert.severity}`;
        div.dataset.id = alert.id;

        const metadata = this.parseMetadata(alert.metadata);
        const iconClass = alert.severity === 'critical' ? 'fa-exclamation-triangle' : 'fa-exclamation-circle';

        div.innerHTML = `
            <div class="alert-header">
                <i class="fa-solid ${iconClass}"></i>
                <span class="alert-sensor">${this.formatSensorName(alert.sensor)}</span>
                <span class="alert-time">${this.formatTime(alert.created_at)}</span>
                <div class="alert-actions">
                    <button class="btn-resolve" onclick="AlertManager.resolveAlert(${alert.id})" title="Resolve">
                        <i class="fa-solid fa-check"></i>
                    </button>
                    <button class="btn-ignore" onclick="AlertManager.ignoreAlert(${alert.id})" title="Ignore">
                        <i class="fa-solid fa-ban"></i>
                    </button>
                </div>
            </div>
            <div class="alert-message">${alert.message}</div>
            ${this.renderAlertDetails(alert, metadata)}
        `;

        return div;
    },

    /**
     * Render alert details with metrics
     * @param {Object} alert - Alert data object
     * @param {Object} metadata - Parsed metadata
     * @returns {string}
     */
    renderAlertDetails(alert, metadata) {
        const details = [];

        if (alert.metric_value !== undefined && alert.threshold !== undefined) {
            details.push(`
                <div class="alert-details">
                    <span class="metric-label">Value:</span>
                    <span class="metric-value">${this.formatMetricValue(alert)}</span>
                    <span class="metric-label">Threshold:</span>
                    <span class="metric-threshold">${alert.threshold}</span>
                </div>
            `);
        }

        // Add additional metadata details if available
        if (metadata.avg_points) {
            details.push(`
                <div class="alert-details">
                    <span class="metric-label">Avg Points:</span>
                    <span class="metric-value">${metadata.avg_points.toFixed(0)}</span>
                </div>
            `);
        }

        return details.join('');
    },

    /**
     * Format metric value for display
     * @param {Object} alert - Alert data object
     * @returns {string}
     */
    formatMetricValue(alert) {
        const value = alert.metric_value;
        const alertType = alert.alert_type;

        if (alertType && alertType.includes('frame_loss') || alertType.includes('frequency')) {
            return `${value.toFixed(1)} Hz`;
        } else if (alertType && (alertType.includes('point_count') || alertType.includes('points'))) {
            return value.toFixed(0);
        } else if (alertType && alertType.includes('latency')) {
            return `${value.toFixed(0)} ms`;
        }

        return value ? value.toString() : '--';
    },

    /**
     * Parse JSON metadata safely
     * @param {string} metadataStr - JSON string
     * @returns {Object}
     */
    parseMetadata(metadataStr) {
        try {
            return JSON.parse(metadataStr || '{}');
        } catch (e) {
            return {};
        }
    },

    /**
     * Format sensor name for display
     * @param {string} sensor - Sensor identifier
     * @returns {string}
     */
    formatSensorName(sensor) {
        const names = {
            'navi_lidar': 'Navi LiDAR',
            'uli_lidar': 'U-LiDAR',
            'camera': 'Camera',
            'imu': 'IMU',
            'thruster': 'Arduino',
            'ptp': 'PTP'
        };
        return names[sensor] || sensor;
    },

    /**
     * Format timestamp for display
     * @param {string} isoString - ISO 8601 timestamp
     * @returns {string}
     */
    formatTime(isoString) {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);

        if (diffMins < 1) {
            return 'Just now';
        } else if (diffMins < 60) {
            return `${diffMins}m ago`;
        } else if (diffHours < 24) {
            return `${diffHours}h ago`;
        } else {
            return date.toLocaleDateString();
        }
    },

    /**
     * Update the notification count badge in header
     */
    updateNotificationCount() {
        const notifBadge = document.getElementById('alertNotificationBadge');
        if (notifBadge) {
            notifBadge.textContent = this.activeCount;
            notifBadge.className = 'notification-badge' + (this.activeCount > 0 ? ' visible' : '');
        }
    },

    /**
     * Update stats display on dashboard
     */
    updateStatsDisplay() {
        const statsContainer = document.getElementById('alertStatsContainer');
        if (!statsContainer) return;

        statsContainer.innerHTML = `
            <span class="stat-item critical">${this.stats.critical || 0} Critical</span>
            <span class="stat-item warning">${this.stats.warning || 0} Warnings</span>
            <span class="stat-item active">${this.stats.active || 0} Active</span>
        `;
    },

    /**
     * Update alerts from WebSocket data
     * @param {Array} alertsData - Alerts array from WebSocket
     */
    updateFromWebSocket(alertsData) {
        if (!alertsData) return;

        this.alerts = alertsData;
        this.activeCount = this.alerts.length;
        this.render();
    },

    /**
     * Fetch alert statistics (one-time, not polling)
     */
    async fetchStats() {
        try {
            const result = await API.alerts.stats();
            if (result.success) {
                this.stats = result.data || {};
                this.updateStatsDisplay();
            }
        } catch (error) {
            console.error('Error fetching alert stats:', error);
        }
    }
};

// ==========================================
// WebSocket Message Handler
// ==========================================

// Override main.js placeholder function to handle alert updates
function updateAlertsDisplay(alertsData) {
    if (!alertsData) return;
    AlertManager.updateFromWebSocket(alertsData);
}

// ==========================================
// Global Functions for onclick handlers
// ==========================================

async function resolveAlert(alertId) {
    await AlertManager.resolveAlert(alertId);
}

async function ignoreAlert(alertId) {
    await AlertManager.ignoreAlert(alertId);
}

async function resolveAllAlerts() {
    await AlertManager.resolveAllAlerts();
}

async function ignoreAllAlerts() {
    await AlertManager.ignoreAllAlerts();
}

/**
 * Refresh alerts button handler (one-time fetch, not polling)
 */
function refreshAlerts() {
    API.alerts.stats().then(result => {
        if (result.success) {
            AlertManager.stats = result.data || {};
            AlertManager.updateStatsDisplay();
        }
    });
}

// ==========================================
// Initialization
// ==========================================

// Auto-start when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Fetch stats once on page load
    AlertManager.fetchStats();
});
