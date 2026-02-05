/**
 * Event Log Viewer
 * Displays and manages system event logs for audit trail
 */

// State
let currentPage = 0;
const pageSize = 50;
let totalEvents = 0;
let currentFilters = {};

// Event type labels and icons
const eventTypeInfo = {
    'system_start': { label: 'System Start', icon: 'fa-power-off', color: 'blue' },
    'ros2_start': { label: 'ROS2 Start', icon: 'fa-play', color: 'green' },
    'ros2_stop': { label: 'ROS2 Stop', icon: 'fa-stop', color: 'red' },
    'rosbag_start': { label: 'Rosbag Start', icon: 'fa-circle', color: 'red' },
    'rosbag_stop': { label: 'Rosbag Stop', icon: 'fa-stop-circle', color: 'gray' },
    'alert_resolved': { label: 'Alert Resolved', icon: 'fa-check-circle', color: 'green' },
    'alert_ignored': { label: 'Alert Ignored', icon: 'fa-ban', color: 'orange' },
    'user_action': { label: 'User Action', icon: 'fa-user', color: 'purple' },
    'queue_overflow': { label: 'Queue Overflow', icon: 'fa-layer-group', color: 'red' },
    'sensor_disconnected': { label: 'Sensor Disconnected', icon: 'fa-plug', color: 'red' }
};

/**
 * Initialize the events page
 */
document.addEventListener('DOMContentLoaded', () => {
    initFilters();
    loadStats();
    loadEvents();

    // Event listeners
    document.getElementById('refreshBtn').addEventListener('click', () => {
        loadStats();
        loadEvents();
    });

    document.getElementById('applyFilters').addEventListener('click', () => {
        currentPage = 0;
        loadEvents();
    });

    document.getElementById('clearFilters').addEventListener('click', clearFilters);

    document.getElementById('exportCsvBtn').addEventListener('click', () => exportEvents('csv'));
    document.getElementById('exportJsonBtn').addEventListener('click', () => exportEvents('json'));

    document.getElementById('prevPage').addEventListener('click', () => {
        if (currentPage > 0) {
            currentPage--;
            loadEvents();
        }
    });

    document.getElementById('nextPage').addEventListener('click', () => {
        if ((currentPage + 1) * pageSize < totalEvents) {
            currentPage++;
            loadEvents();
        }
    });

    document.getElementById('toggleFilters').addEventListener('click', () => {
        const body = document.querySelector('.filters-body');
        const icon = document.querySelector('#toggleFilters i');
        body.classList.toggle('collapsed');
        icon.classList.toggle('fa-chevron-down');
        icon.classList.toggle('fa-chevron-up');
    });
});

/**
 * Initialize filter event listeners
 */
function initFilters() {
    const filters = ['eventTypeFilter', 'actionFilter', 'resourceFilter',
                     'startDateFilter', 'endDateFilter', 'successFilter'];

    filters.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', () => {
                // Auto-apply filters on change
                currentPage = 0;
                loadEvents();
            });
        }
    });
}

/**
 * Get current filter values
 */
function getFilters() {
    const eventType = document.getElementById('eventTypeFilter').value;
    const action = document.getElementById('actionFilter').value;
    const resource = document.getElementById('resourceFilter').value;
    const startDate = document.getElementById('startDateFilter').value;
    const endDate = document.getElementById('endDateFilter').value;
    const success = document.getElementById('successFilter').value;

    const filters = {};
    if (eventType) filters.event_type = eventType;
    if (action) filters.action = action;
    if (resource) filters.resource = resource;
    if (startDate) filters.start_date = new Date(startDate).toISOString();
    if (endDate) filters.end_date = new Date(endDate).toISOString();
    if (success) filters.success = success;

    return filters;
}

/**
 * Clear all filters
 */
function clearFilters() {
    document.getElementById('eventTypeFilter').value = '';
    document.getElementById('actionFilter').value = '';
    document.getElementById('resourceFilter').value = '';
    document.getElementById('startDateFilter').value = '';
    document.getElementById('endDateFilter').value = '';
    document.getElementById('successFilter').value = '';
    currentPage = 0;
    loadEvents();
}

/**
 * Load event statistics
 */
async function loadStats() {
    try {
        const response = await fetch('/api/events/stats');
        const result = await response.json();

        if (result.success) {
            const stats = result.data;
            document.getElementById('totalEvents').textContent = stats.total || 0;
            document.getElementById('successfulEvents').textContent = stats.successful || 0;
            document.getElementById('failedEvents').textContent = stats.failed || 0;
            document.getElementById('last24hEvents').textContent = stats.last_24h || 0;
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

/**
 * Load events from API
 */
async function loadEvents() {
    const tbody = document.getElementById('eventsTableBody');
    tbody.innerHTML = '<tr class="loading-row"><td colspan="7" class="text-center"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</td></tr>';

    try {
        const filters = getFilters();
        const params = new URLSearchParams({
            limit: pageSize,
            offset: currentPage * pageSize,
            ...filters
        });

        const response = await fetch(`/api/events/logs?${params}`);
        const result = await response.json();

        if (result.success) {
            totalEvents = result.total || result.data.length;
            displayEvents(result.data);
            updatePagination();
        } else {
            tbody.innerHTML = `<tr class="error-row"><td colspan="7" class="text-center text-danger">Error: ${result.error}</td></tr>`;
        }
    } catch (error) {
        console.error('Failed to load events:', error);
        tbody.innerHTML = `<tr class="error-row"><td colspan="7" class="text-center text-danger">Failed to load events</td></tr>`;
    }
}

/**
 * Display events in table
 */
function displayEvents(events) {
    const tbody = document.getElementById('eventsTableBody');

    if (events.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7" class="text-center">No events found</td></tr>';
        document.getElementById('eventsCount').textContent = 'Showing 0 events';
        return;
    }

    tbody.innerHTML = events.map(event => {
        const typeInfo = eventTypeInfo[event.event_type] || {
            label: event.event_type,
            icon: 'fa-circle',
            color: 'gray'
        };

        const statusBadge = event.success
            ? '<span class="badge badge-success"><i class="fa-solid fa-check"></i> Success</span>'
            : '<span class="badge badge-danger"><i class="fa-solid fa-xmark"></i> Failed</span>';

        const timestamp = formatTimestamp(event.created_at);

        return `
            <tr class="event-row" data-id="${event.id}">
                <td class="event-id">${event.id}</td>
                <td class="event-timestamp">${timestamp}</td>
                <td class="event-type">
                    <i class="fa-solid ${typeInfo.icon} text-${typeInfo.color}"></i>
                    ${typeInfo.label}
                </td>
                <td class="event-action">${event.action}</td>
                <td class="event-resource">${event.resource}</td>
                <td class="event-message">${escapeHtml(event.message)}</td>
                <td class="event-status">${statusBadge}</td>
            </tr>
        `;
    }).join('');

    // Add click handlers for row detail
    document.querySelectorAll('.event-row').forEach(row => {
        row.addEventListener('click', () => showEventDetail(parseInt(row.dataset.id)));
    });

    const start = currentPage * pageSize + 1;
    const end = Math.min(start + events.length - 1, totalEvents);
    document.getElementById('eventsCount').textContent = `Showing ${start}-${end} of ${totalEvents} events`;
}

/**
 * Update pagination controls
 */
function updatePagination() {
    const prevBtn = document.getElementById('prevPage');
    const nextBtn = document.getElementById('nextPage');
    const pageInfo = document.getElementById('pageInfo');

    prevBtn.disabled = currentPage === 0;
    nextBtn.disabled = (currentPage + 1) * pageSize >= totalEvents;

    const totalPages = Math.ceil(totalEvents / pageSize);
    pageInfo.textContent = `Page ${currentPage + 1} of ${totalPages || 1}`;
}

/**
 * Show event detail modal
 */
async function showEventDetail(eventId) {
    try {
        const response = await fetch(`/api/events/logs?limit=1&offset=0`);
        const result = await response.json();

        if (result.success) {
            const event = result.data.find(e => e.id === eventId);
            if (event) {
                const modal = document.getElementById('eventDetailModal');
                const modalBody = document.getElementById('modalBody');

                const typeInfo = eventTypeInfo[event.event_type] || {
                    label: event.event_type,
                    icon: 'fa-circle',
                    color: 'gray'
                };

                let metadataHtml = '';
                if (event.metadata) {
                    try {
                        const metadata = JSON.parse(event.metadata);
                        metadataHtml = `
                            <div class="detail-section">
                                <h4>Metadata</h4>
                                <pre>${JSON.stringify(metadata, null, 2)}</pre>
                            </div>
                        `;
                    } catch (e) {
                        metadataHtml = `
                            <div class="detail-section">
                                <h4>Metadata</h4>
                                <pre>${escapeHtml(event.metadata)}</pre>
                            </div>
                        `;
                    }
                }

                modalBody.innerHTML = `
                    <div class="detail-grid">
                        <div class="detail-item">
                            <span class="detail-label">ID</span>
                            <span class="detail-value">${event.id}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Timestamp</span>
                            <span class="detail-value">${formatTimestamp(event.created_at)}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Event Type</span>
                            <span class="detail-value">
                                <i class="fa-solid ${typeInfo.icon} text-${typeInfo.color}"></i>
                                ${typeInfo.label}
                            </span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Action</span>
                            <span class="detail-value">${event.action}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Resource</span>
                            <span class="detail-value">${event.resource}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Status</span>
                            <span class="detail-value">
                                ${event.success
                                    ? '<span class="badge badge-success">Success</span>'
                                    : '<span class="badge badge-danger">Failed</span>'}
                            </span>
                        </div>
                    </div>
                    <div class="detail-section">
                        <h4>Message</h4>
                        <p>${escapeHtml(event.message)}</p>
                    </div>
                    ${event.error ? `
                        <div class="detail-section">
                            <h4>Error</h4>
                            <p class="text-danger">${escapeHtml(event.error)}</p>
                        </div>
                    ` : ''}
                    ${metadataHtml}
                `;

                modal.classList.add('show');
            }
        }
    } catch (error) {
        console.error('Failed to load event detail:', error);
    }
}

/**
 * Close modal
 */
function closeModal() {
    document.getElementById('eventDetailModal').classList.remove('show');
}

/**
 * Export events to CSV or JSON
 */
function exportEvents(format) {
    const filters = getFilters();
    const params = new URLSearchParams({ format, ...filters });

    const url = `/api/events/export?${params}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `events_${new Date().toISOString().slice(0, 10)}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

/**
 * Format timestamp for display
 */
function formatTimestamp(isoString) {
    if (!isoString) return '-';

    try {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        let relative = '';
        if (diffMins < 1) relative = 'Just now';
        else if (diffMins < 60) relative = `${diffMins}m ago`;
        else if (diffHours < 24) relative = `${diffHours}h ago`;
        else relative = `${diffDays}d ago`;

        const dateStr = date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });

        return `${dateStr} <span class="text-muted">(${relative})</span>`;
    } catch (e) {
        return isoString;
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Close modal on outside click
window.addEventListener('click', (e) => {
    const modal = document.getElementById('eventDetailModal');
    if (e.target === modal) {
        closeModal();
    }
});
