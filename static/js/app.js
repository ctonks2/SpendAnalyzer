/**
 * Spend Analyzer - Main Application JavaScript
 */

// === State Variables ===
let items = [];
let currentView = 'items';
let currentPage = 1;
let itemsPerPage = 25;
let sortedData = [];

// Store last chat exchange for saving
let lastQuestion = '';
let lastResponse = '';
let lastInsightSaved = false;

// allTransactions is initialized from template

// === Utility Functions ===

/**
 * Simple markdown to HTML converter
 */
function markdownToHtml(text) {
    if (!text) return '';
    
    let html = text;
    
    // Headers (### text)
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    
    // Bold (**text**)
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    
    // Italic (*text*)
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    
    // Code (`text`)
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Horizontal rule (---)
    html = html.replace(/^---+$/gm, '<hr>');
    
    // Numbered lists (1. item)
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
    
    // Bullet lists (- item)
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    
    // Wrap consecutive <li> in <ul>
    html = html.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, function(match) {
        return '<ul>' + match + '</ul>';
    });
    
    // Convert newlines to <br> for readability
    html = html.replace(/\n/g, '<br>');
    
    // Clean up multiple <br>
    html = html.replace(/(<br>){3,}/g, '<br><br>');
    
    // Clean up <br> after block elements
    html = html.replace(/<\/(h3|ul|li|hr)><br>/g, '</$1>');
    html = html.replace(/<br><(h3|ul|hr)/g, '<$1');
    
    return html;
}

/**
 * Normalize date to YYYY-MM-DD for proper sorting/display
 */
function normalizeDate(d) {
    if (!d) return '';
    const str = String(d).trim();
    // If already YYYY-MM-DD, return as-is
    if (/^\d{4}-\d{2}-\d{2}$/.test(str)) return str;
    // Try to extract YYYY-MM-DD from datetime strings
    const match = str.match(/(\d{4}-\d{2}-\d{2})/);
    if (match) return match[1];
    // Try parsing as Date
    try {
        const dt = new Date(str);
        if (!isNaN(dt)) {
            return dt.toISOString().split('T')[0];
        }
    } catch(e) {}
    return str;
}

// === Initialization ===

document.addEventListener('DOMContentLoaded', function() {
    // Initialize data view if transactions exist
    if (typeof allTransactions !== 'undefined' && allTransactions && allTransactions.length > 0) {
        sortData();
    }
    
    // Format saved insights with markdown
    document.querySelectorAll('.insight-response').forEach(el => {
        el.innerHTML = markdownToHtml(el.textContent);
    });
    
    // Set today's date as default for receipt form
    const receiptDate = document.getElementById('receiptDate');
    if (receiptDate) {
        receiptDate.valueAsDate = new Date();
    }
});

// === Tab Navigation ===

function showTab(tabId) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.target.classList.add('active');
}

// === Alert System ===

function showAlert(message, type) {
    const alert = document.getElementById('alert');
    alert.textContent = message;
    alert.className = 'alert alert-' + type;
    alert.classList.remove('hidden');
    setTimeout(() => alert.classList.add('hidden'), 5000);
}

// === User Management ===

function loadUser() {
    const userId = document.getElementById('userId').value.trim();
    if (!userId) {
        showAlert('Please enter a User ID', 'error');
        return;
    }
    window.location.href = '/?user_id=' + encodeURIComponent(userId);
}

// === Data View Functions ===

function setView(view) {
    currentView = view;
    currentPage = 1;
    
    // Update toggle buttons
    document.querySelectorAll('.view-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('view' + view.charAt(0).toUpperCase() + view.slice(1)).classList.add('active');
    
    sortData();
}

function sortData() {
    const sortBy = document.getElementById('sortBy').value;
    let data = [];
    
    if (currentView === 'items') {
        // Filter out RECEIPT_TOTAL from items view
        data = allTransactions.filter(tx => tx.item_name !== 'RECEIPT_TOTAL');
    } else if (currentView === 'receipts') {
        data = getReceipts();
    } else if (currentView === 'stores') {
        data = getStores();
    }
    
    // Apply sorting
    const [field, direction] = sortBy.split('-');
    
    data.sort((a, b) => {
        let valA, valB, secA, secB;
        
        if (field === 'date') {
            valA = normalizeDate(a.date);
            valB = normalizeDate(b.date);
            secA = (a.store || '').toLowerCase();
            secB = (b.store || '').toLowerCase();
        } else if (field === 'name') {
            valA = (a.item_name || a.store || '').toLowerCase();
            valB = (b.item_name || b.store || '').toLowerCase();
            secA = normalizeDate(a.date);
            secB = normalizeDate(b.date);
        } else if (field === 'store') {
            valA = (a.store || '').toLowerCase();
            valB = (b.store || '').toLowerCase();
            secA = normalizeDate(a.date);
            secB = normalizeDate(b.date);
        } else if (field === 'total') {
            valA = parseFloat(a.total_price || a.total || 0);
            valB = parseFloat(b.total_price || b.total || 0);
            secA = normalizeDate(a.date);
            secB = normalizeDate(b.date);
        }
        
        let cmp;
        if (direction === 'asc') {
            cmp = valA > valB ? 1 : valA < valB ? -1 : 0;
        } else {
            cmp = valA < valB ? 1 : valA > valB ? -1 : 0;
        }
        
        // If primary sort is equal, use secondary sort (always ascending)
        if (cmp === 0 && secA !== undefined) {
            cmp = secA > secB ? 1 : secA < secB ? -1 : 0;
        }
        
        return cmp;
    });
    
    sortedData = data;
    currentPage = 1;
    renderTable();
}

function getReceipts() {
    const receipts = {};
    allTransactions.forEach(tx => {
        // Skip RECEIPT_TOTAL entries entirely
        if (tx.item_name === 'RECEIPT_TOTAL') return;
        
        const normDate = normalizeDate(tx.date) || 'unknown';
        const key = normDate + '|' + (tx.store || 'unknown');
        if (!receipts[key]) {
            receipts[key] = {
                date: normDate,
                store: tx.store,
                source: tx.source,
                items: 0,
                total: 0,
                itemsList: []
            };
        }
        receipts[key].items++;
        receipts[key].total += parseFloat(tx.total_price || 0);
        receipts[key].itemsList.push(tx);
    });
    return Object.values(receipts);
}

function getStores() {
    const stores = {};
    allTransactions.forEach(tx => {
        // Skip RECEIPT_TOTAL entries to avoid double-counting
        if (tx.item_name === 'RECEIPT_TOTAL') return;
        
        const store = tx.store || 'Unknown';
        if (!stores[store]) {
            stores[store] = {
                store: store,
                source: tx.source,
                receipts: new Set(),
                items: 0,
                total: 0
            };
        }
        stores[store].receipts.add(normalizeDate(tx.date));
        stores[store].items++;
        stores[store].total += parseFloat(tx.total_price || 0);
    });
    return Object.values(stores).map(s => ({
        ...s,
        receipts: s.receipts.size
    }));
}

function renderTable() {
    const thead = document.getElementById('tableHead');
    const tbody = document.getElementById('tableBody');
    
    if (!sortedData || sortedData.length === 0) {
        thead.innerHTML = '';
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 30px; color: #888;">No data to display</td></tr>';
        document.getElementById('pagination').innerHTML = '';
        return;
    }
    
    // Set headers based on view
    if (currentView === 'items') {
        thead.innerHTML = '<tr><th>Date</th><th>Store</th><th>Item</th><th>Qty</th><th>Price</th><th>Total</th></tr>';
    } else if (currentView === 'receipts') {
        thead.innerHTML = '<tr><th>Date</th><th>Store</th><th>Source</th><th>Items</th><th>Total</th></tr>';
    } else if (currentView === 'stores') {
        thead.innerHTML = '<tr><th>Store</th><th>Source</th><th>Visits</th><th>Items</th><th>Total Spent</th></tr>';
    }
    
    // Calculate pagination
    const totalPages = Math.ceil(sortedData.length / itemsPerPage);
    const start = (currentPage - 1) * itemsPerPage;
    const end = start + itemsPerPage;
    const pageData = sortedData.slice(start, end);
    
    // Render rows
    let html = '';
    pageData.forEach(item => {
        const displayDate = normalizeDate(item.date) || '-';
        
        if (currentView === 'items') {
            html += `<tr>
                <td>${displayDate}</td>
                <td>${item.store || '-'}</td>
                <td>${item.item_name || '-'}</td>
                <td>${item.quantity || 1}</td>
                <td>$${(item.unit_price || 0).toFixed(2)}</td>
                <td>$${(item.total_price || 0).toFixed(2)}</td>
            </tr>`;
        } else if (currentView === 'receipts') {
            const receiptId = `receipt-${displayDate}-${(item.store || 'unknown').replace(/\s+/g, '-')}`;
            html += `<tr class="receipt-row" onclick="toggleReceiptDetails('${receiptId}')">
                <td>${displayDate}</td>
                <td>${item.store || '-'}</td>
                <td>${item.source || '-'}</td>
                <td>${item.items}</td>
                <td>$${item.total.toFixed(2)}</td>
            </tr>`;
            html += `<tr class="receipt-details" id="${receiptId}">
                <td colspan="5">
                    <table class="receipt-items-table">`;
            if (item.itemsList && item.itemsList.length > 0) {
                item.itemsList.forEach(itm => {
                    html += `<tr>
                        <td style="width: 50%;">${itm.item_name || '-'}</td>
                        <td style="width: 15%; text-align: center;">x${itm.quantity || 1}</td>
                        <td style="width: 17%; text-align: right;">$${(itm.unit_price || 0).toFixed(2)}</td>
                        <td style="width: 18%; text-align: right;">$${(itm.total_price || 0).toFixed(2)}</td>
                    </tr>`;
                });
            } else {
                html += `<tr><td colspan="4" style="text-align: center; color: #888;">No items</td></tr>`;
            }
            html += `</table></td></tr>`;
        } else if (currentView === 'stores') {
            html += `<tr>
                <td>${item.store}</td>
                <td>${item.source || '-'}</td>
                <td>${item.receipts}</td>
                <td>${item.items}</td>
                <td>$${item.total.toFixed(2)}</td>
            </tr>`;
        }
    });
    tbody.innerHTML = html;
    
    renderPagination(totalPages);
}

function renderPagination(totalPages) {
    const pag = document.getElementById('pagination');
    if (totalPages <= 1) {
        pag.innerHTML = `<span class="page-info">Showing ${sortedData.length} items</span>`;
        return;
    }
    
    let html = '';
    html += `<button class="page-btn" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>&laquo; Prev</button>`;
    
    const maxButtons = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxButtons / 2));
    let endPage = Math.min(totalPages, startPage + maxButtons - 1);
    
    if (endPage - startPage < maxButtons - 1) {
        startPage = Math.max(1, endPage - maxButtons + 1);
    }
    
    if (startPage > 1) {
        html += `<button class="page-btn" onclick="goToPage(1)">1</button>`;
        if (startPage > 2) html += `<span class="page-info">...</span>`;
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }
    
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<span class="page-info">...</span>`;
        html += `<button class="page-btn" onclick="goToPage(${totalPages})">${totalPages}</button>`;
    }
    
    html += `<button class="page-btn" onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>Next &raquo;</button>`;
    html += `<span class="page-info">(${sortedData.length} total)</span>`;
    
    pag.innerHTML = html;
}

function goToPage(page) {
    const totalPages = Math.ceil(sortedData.length / itemsPerPage);
    if (page < 1 || page > totalPages) return;
    currentPage = page;
    renderTable();
    document.getElementById('dataDisplay').scrollIntoView({ behavior: 'smooth' });
}

function toggleReceiptDetails(receiptId) {
    const detailsRow = document.getElementById(receiptId);
    const parentRow = detailsRow.previousElementSibling;
    
    if (detailsRow.classList.contains('show')) {
        detailsRow.classList.remove('show');
        parentRow.classList.remove('expanded');
    } else {
        detailsRow.classList.add('show');
        parentRow.classList.add('expanded');
    }
}

// === Receipt Management ===

function addItem() {
    const userId = document.getElementById('userId').value.trim();
    if (!userId) {
        showAlert('Please enter a User ID first', 'error');
        return;
    }
    
    const name = document.getElementById('itemName').value.trim();
    const price = parseFloat(document.getElementById('itemPrice').value) || 0;
    const qty = parseInt(document.getElementById('itemQty').value) || 1;
    const discount = parseFloat(document.getElementById('itemDiscount').value) || 0;
    
    if (!name) {
        showAlert('Please enter an item name', 'error');
        return;
    }
    
    items.push({ name, price, qty, discount });
    updateItemsList();
    
    document.getElementById('itemName').value = '';
    document.getElementById('itemPrice').value = '';
    document.getElementById('itemQty').value = '1';
    document.getElementById('itemDiscount').value = '';
}

function updateItemsList() {
    const list = document.getElementById('itemsList');
    if (items.length === 0) {
        list.innerHTML = '<p style="color: var(--text-muted); text-align: center;">No items added yet</p>';
        return;
    }
    
    let html = '';
    let total = 0;
    items.forEach((item, i) => {
        const itemSubtotal = item.price * item.qty;
        const itemDiscount = item.discount || 0;
        const itemTotal = itemSubtotal - itemDiscount;
        total += itemTotal;
        
        let displayText = `${item.name} x${item.qty}`;
        let priceText = `$${itemTotal.toFixed(2)}`;
        if (itemDiscount > 0) {
            priceText = `<span style="text-decoration: line-through; color: var(--text-muted);">$${itemSubtotal.toFixed(2)}</span> $${itemTotal.toFixed(2)}`;
        }
        
        html += `<div class="item-row">
            <span>${displayText}</span>
            <span>${priceText}
                <button onclick="removeItem(${i})" style="margin-left: 10px; color: var(--danger); background: none; border: none; cursor: pointer;">✕</button>
            </span>
        </div>`;
    });
    
    html += `<div class="item-row" style="font-weight: bold; background: var(--bg-elevated); border: 1px solid var(--accent);">
        <span>Total</span><span>$${total.toFixed(2)}</span>
    </div>`;
    list.innerHTML = html;
}

function removeItem(index) {
    items.splice(index, 1);
    updateItemsList();
}

function addReceipt(event) {
    event.preventDefault();
    const userId = document.getElementById('userId').value.trim();
    if (!userId) {
        showAlert('Please load a user first', 'error');
        return;
    }
    
    if (items.length === 0) {
        showAlert('Please add at least one item', 'error');
        return;
    }
    
    const data = {
        user_id: userId,
        store_number: document.getElementById('storeNumber').value,
        store_name: document.getElementById('storeName').value || 'unknown',
        date: document.getElementById('receiptDate').value,
        items: items
    };
    
    fetch('/api/add_receipt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            showAlert('Receipt saved successfully!', 'success');
            items = [];
            updateItemsList();
            document.getElementById('receiptForm').reset();
            setTimeout(() => location.reload(), 1500);
        } else {
            showAlert('Error: ' + result.error, 'error');
        }
    })
    .catch(err => showAlert('Error saving receipt', 'error'));
}

// === Chat Functions ===

function setChatView(view) {
    document.getElementById('chatViewBtn').classList.toggle('active', view === 'chat');
    document.getElementById('detailedViewBtn').classList.toggle('active', view === 'detailed');
    document.getElementById('chatViewContent').style.display = view === 'chat' ? 'flex' : 'none';
    document.getElementById('detailedViewContent').style.display = view === 'detailed' ? 'block' : 'none';
    
    if (view === 'detailed') {
        refreshLLMContext();
    }
}

function refreshLLMContext() {
    const userId = document.getElementById('userId').value.trim();
    if (!userId) {
        document.getElementById('llmContextDisplay').textContent = 'Please load a user first to see context data.';
        document.getElementById('contextStats').textContent = '';
        document.getElementById('filterInfo').textContent = '';
        return;
    }
    
    const testQuestion = document.getElementById('testQuestion')?.value.trim() || '';
    document.getElementById('llmContextDisplay').textContent = 'Loading...';
    
    let url = `/api/llm_context?user_id=${encodeURIComponent(userId)}`;
    if (testQuestion) {
        url += `&question=${encodeURIComponent(testQuestion)}`;
    }
    
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                document.getElementById('llmContextDisplay').textContent = 'Error: ' + data.error;
                return;
            }
            
            const context = data.context || [];
            const totalCount = data.total_transactions || context.length;
            const filteredCount = data.filtered_count || context.length;
            const filters = data.filters_applied || [];
            
            const jsonStr = JSON.stringify(context);
            const charCount = jsonStr.length;
            const estimatedTokens = Math.ceil(charCount / 4);
            
            document.getElementById('contextStats').textContent = 
                `${filteredCount} of ${totalCount} transactions | ${charCount.toLocaleString()} chars | ~${estimatedTokens.toLocaleString()} tokens`;
            document.getElementById('filterInfo').textContent = 
                filters.length ? `Filters: ${filters.join(', ')}` : '';
            document.getElementById('llmContextDisplay').textContent = JSON.stringify(context, null, 2);
        })
        .catch(err => {
            document.getElementById('llmContextDisplay').textContent = 'Error loading context: ' + err.message;
        });
}

function sendMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message) return;
    
    const userId = document.getElementById('userId').value.trim();
    if (!userId) {
        showAlert('Please load a user first', 'error');
        return;
    }
    
    const messages = document.getElementById('chatMessages');
    messages.innerHTML += `<div class="message user">${message}</div>`;
    input.value = '';
    messages.scrollTop = messages.scrollHeight;
    
    // Show typing indicator
    messages.innerHTML += `<div class="message assistant" id="typing">Thinking...</div>`;
    messages.scrollTop = messages.scrollHeight;
    
    fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, message: message })
    })
    .then(r => r.json())
    .then(result => {
        document.getElementById('typing').remove();
        const response = result.response || 'Sorry, I encountered an error.';
        
        // Store for saving later
        lastQuestion = message;
        lastResponse = response;
        lastInsightSaved = false;
        
        // Show context status
        // Convert markdown to HTML for display
        const formattedResponse = markdownToHtml(response);
        messages.innerHTML += `<div class="message assistant">${formattedResponse}</div>`;
        messages.scrollTop = messages.scrollHeight;
        
        if (result.response && !result.error) {
            // Offer to save with category dropdown
            messages.innerHTML += `<div class="message assistant" id="saveInsightBox">
                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <select id="insightCategory" style="padding: 8px 12px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 0.9rem;">
                        <option value="Budget Tips">💰 Budget Tips</option>
                        <option value="Food & Groceries">🛒 Food & Groceries</option>
                        <option value="Shopping Advice">🛍️ Shopping Advice</option>
                        <option value="Entertainment">🎬 Entertainment</option>
                        <option value="Utilities">⚡ Utilities</option>
                        <option value="Travel">✈️ Travel</option>
                        <option value="Health">🏥 Health</option>
                        <option value="Other">📝 Other</option>
                    </select>
                    <button class="btn" style="padding: 8px 15px; font-size: 0.9rem;" 
                        id="saveInsightBtn" onclick="saveLastRecommendation()">
                        💾 Save
                    </button>
                </div>
            </div>`;
        }
    })
    .catch(err => {
        document.getElementById('typing')?.remove();
        messages.innerHTML += `<div class="message assistant">Sorry, something went wrong.</div>`;
    });
}

// === Recommendation Management ===

function saveLastRecommendation() {
    if (!lastQuestion || !lastResponse) {
        showAlert('No insight to save', 'error');
        return;
    }
    
    if (lastInsightSaved) {
        showAlert('This insight has already been saved', 'error');
        return;
    }
    
    const userId = document.getElementById('userId').value.trim();
    const categorySelect = document.getElementById('insightCategory');
    const category = categorySelect ? categorySelect.value : 'Other';
    
    const saveBtn = document.getElementById('saveInsightBtn');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = '⏳ Saving...';
    }
    
    fetch('/api/save_recommendation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, question: lastQuestion, response: lastResponse, category: category })
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            lastInsightSaved = true;
            showAlert('Recommendation saved!', 'success');
            
            const saveBox = document.getElementById('saveInsightBox');
            if (saveBox) {
                saveBox.innerHTML = '<span style="color: #28a745; font-weight: 500;">✓ Insight saved to ' + category + '</span>';
            }
        } else {
            showAlert('Failed to save: ' + (result.error || 'Unknown error'), 'error');
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = '💾 Save';
            }
        }
    })
    .catch(err => {
        showAlert('Error saving recommendation', 'error');
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = '💾 Save';
        }
    });
}

function toggleInsight(index) {
    const answerDiv = document.getElementById('insightAnswer' + index);
    const card = answerDiv.closest('.insight-card');
    
    if (answerDiv.style.display === 'none') {
        answerDiv.style.display = 'block';
        card.classList.add('expanded');
    } else {
        answerDiv.style.display = 'none';
        card.classList.remove('expanded');
    }
}

function deleteRec(index) {
    if (!confirm('Delete this recommendation?')) return;
    const userId = document.getElementById('userId').value.trim();
    
    fetch('/api/delete_recommendation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, index: index })
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            showAlert('Deleted!', 'success');
            setTimeout(() => location.reload(), 1000);
        }
    });
}

// === File Import Functions ===

function loadFilesList() {
    const userId = document.getElementById('userId').value.trim();
    if (!userId) {
        showAlert('Please load a user first', 'error');
        return;
    }
    
    const filesList = document.getElementById('filesList');
    filesList.innerHTML = '<p style="color: #888; text-align: center;">Loading...</p>';
    
    fetch('/api/list_files?user_id=' + encodeURIComponent(userId))
    .then(r => r.json())
    .then(result => {
        if (result.files && result.files.length > 0) {
            let html = '';
            result.files.forEach(file => {
                const statusClass = file.imported ? 'color: #28a745;' : '';
                const statusIcon = file.imported ? '✓' : '';
                const btnDisabled = file.imported ? 'disabled style="opacity: 0.5; cursor: not-allowed;"' : '';
                const escapedName = file.name.replace(/'/g, "\\'");
                html += `<div class="item-row" style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="${statusClass}">${statusIcon} ${file.name}</span>
                    <button class="btn" style="padding: 6px 15px; font-size: 0.85rem;" 
                        onclick="importSingleFile('${escapedName}')" ${btnDisabled}>
                        ${file.imported ? 'Imported' : 'Import'}
                    </button>
                </div>`;
            });
            filesList.innerHTML = html;
        } else if (result.error) {
            filesList.innerHTML = `<p style="color: #dc3545; text-align: center;">${result.error}</p>`;
        } else {
            filesList.innerHTML = '<p style="color: #888; text-align: center;">No files found in data/raw folder</p>';
        }
    })
    .catch(err => {
        filesList.innerHTML = '<p style="color: #dc3545; text-align: center;">Error loading files</p>';
    });
}

function importSingleFile(filename) {
    const userId = document.getElementById('userId').value.trim();
    if (!userId) {
        showAlert('Please load a user first', 'error');
        return;
    }
    
    showAlert('Importing ' + filename + '...', 'success');
    
    fetch('/api/import_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, filename: filename })
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            showAlert(`Imported ${result.imported} items from ${filename}!`, 'success');
            loadFilesList();
            setTimeout(() => location.reload(), 2000);
        } else {
            showAlert('Error: ' + result.error, 'error');
        }
    })
    .catch(err => showAlert('Error importing file', 'error'));
}

// === Settings Functions ===

function deleteAllData() {
    if (!confirm('Are you sure you want to delete ALL your data? This cannot be undone.')) return;
    const userId = document.getElementById('userId').value.trim();
    
    fetch('/api/delete_data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            showAlert('All data deleted', 'success');
            setTimeout(() => location.reload(), 1500);
        }
    });
}
