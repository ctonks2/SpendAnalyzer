/**
 * Spend Analyzer - Main Application JavaScript
 * Used by Dashboard (index.html via base.html)
 */

// === Initialization ===

document.addEventListener('DOMContentLoaded', function() {
    // Handle URL parameters for alerts
    const urlParams = new URLSearchParams(window.location.search);
    const message = urlParams.get('message');
    const msgType = urlParams.get('type');
    
    // Show alert from URL params
    if (message) {
        showAlert(decodeURIComponent(message), msgType || 'success');
        // Clean up URL
        urlParams.delete('message');
        urlParams.delete('type');
        const newUrl = window.location.pathname + (urlParams.toString() ? '?' + urlParams.toString() : '');
        window.history.replaceState({}, '', newUrl);
    }
});

// === Alert System ===

function showAlert(message, type) {
    const alert = document.getElementById('alert');
    alert.textContent = message;
    alert.className = 'alert alert-' + type;
    alert.classList.remove('hidden');
    setTimeout(() => alert.classList.add('hidden'), 5000);
}
