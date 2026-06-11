const socket = io();

const startBtn = document.getElementById('start-receiver-btn');
const stopBtn = document.getElementById('stop-receiver-btn');
const genkeysBtn = document.getElementById('genkeys-btn');
const loadkeysBtn = document.getElementById('loadkeys-btn');
const sendBtn = document.getElementById('send-btn');

socket.on('receiver_status', (data) => {
    const statusText = document.getElementById('receiver-status-text');
    const dot = document.getElementById('status-dot');
    if (data.running) {
        statusText.textContent = 'Running ✅';
        dot.className = 'status-dot running';
    } else {
        statusText.textContent = 'Not Running ❌';
        dot.className = 'status-dot stopped';
    }
});

socket.on('keys_updated', (data) => {
    document.getElementById('public-key-display').textContent = data.public || '-';
    document.getElementById('private-key-display').textContent = data.private || '-';
    document.getElementById('public-key-input').value = data.public || '';
    showToast('Keys updated!', 'success');
});

socket.on('send_progress', (data) => {
    const div = document.getElementById('send-progress');
    div.style.display = 'block';
    document.getElementById('send-progress-fill').style.width = `${data.percent}%`;
    document.getElementById('send-progress-fill').textContent = `${Math.round(data.percent)}%`;
    document.getElementById('send-progress-text').textContent = `Sending... ${Math.round(data.percent)}%`;
});

socket.on('send_complete', () => {
    setTimeout(() => {
        document.getElementById('send-progress').style.display = 'none';
        document.getElementById('send-progress-fill').style.width = '0%';
    }, 1500);
    loadHistory();
});

socket.on('message_sent', () => { loadHistory(); showToast('Message sent!', 'success'); });
socket.on('error', (data) => showToast(`Error: ${data.message}`, 'error'));
socket.on('info', (data) => showToast(data.message, 'info'));

startBtn.onclick = async () => {
    startBtn.disabled = true;
    startBtn.innerHTML = '⏳ Updating...';
    const res = await fetch('/api/receiver/start', { method: 'POST' });
    const data = await res.json();
    if (data.success) showToast('Receiver status updated to RUNNING', 'success');
    else showToast(`Error: ${data.error}`, 'error');
    startBtn.disabled = false;
    startBtn.innerHTML = '✅ Mark Receiver as Running';
};

stopBtn.onclick = async () => {
    const res = await fetch('/api/receiver/stop', { method: 'POST' });
    const data = await res.json();
    if (data.success) showToast('Receiver status updated to STOPPED', 'info');
};

genkeysBtn.onclick = async () => {
    genkeysBtn.disabled = true;
    genkeysBtn.innerHTML = '⏳ Generating...';
    const res = await fetch('/api/keys/generate', { method: 'POST' });
    const data = await res.json();
    if (data.success) showToast('Keys generated!', 'success');
    else showToast(`Error: ${data.error}`, 'error');
    genkeysBtn.disabled = false;
    genkeysBtn.innerHTML = '✨ Generate New Keys';
};

loadkeysBtn.onclick = async () => {
    const res = await fetch('/api/keys/load', { method: 'POST' });
    const data = await res.json();
    if (data.success) showToast('Keys loaded!', 'success');
    else showToast('No key files found', 'warning');
};

sendBtn.onclick = async () => {
    const target = document.getElementById('target-ip').value;
    const pubkey = document.getElementById('public-key-input').value;
    const msg = document.getElementById('text-message').value;
    if (!msg) { showToast('Enter a message', 'warning'); return; }
    
    sendBtn.disabled = true;
    sendBtn.innerHTML = '⏳ Sending...';
    const res = await fetch('/api/sender/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_ip: target, message: msg, public_key: pubkey || null })
    });
    const data = await res.json();
    if (data.success) {
        showToast('Message sent!', 'success');
        document.getElementById('text-message').value = '';
    } else showToast(`Error: ${data.error}`, 'error');
    sendBtn.disabled = false;
    sendBtn.innerHTML = '📨 Send Message';
};

async function loadHistory() {
    const res = await fetch('/api/history');
    const data = await res.json();
    const sentList = document.getElementById('sent-list');
    if (data.sent?.length) {
        sentList.innerHTML = data.sent.map(m => `<div class="message-item"><div class="message-header">📤 To: ${escapeHtml(m.to)} <span>${m.time}</span></div><div class="message-content">${escapeHtml(m.message)}</div>${m.encrypted ? '<div style="font-size:0.7em;color:#888;">🔐 Encrypted</div>' : ''}</div>`).join('');
    } else sentList.innerHTML = '<div class="empty-message">-</div>';
    
    const recvList = document.getElementById('received-list');
    if (data.received?.length) {
        recvList.innerHTML = data.received.map(m => `<div class="message-item"><div class="message-header">📥 From: ${escapeHtml(m.from)} <span>${m.time}</span></div><div class="message-content">${escapeHtml(m.message)}</div></div>`).join('');
    } else recvList.innerHTML = '<div class="empty-message">-</div>';
}

async function loadStatus() {
    const res = await fetch('/api/status');
    const status = await res.json();
    document.getElementById('port-status').textContent = status.port;
    document.getElementById('domain-status').textContent = status.domain;
    document.getElementById('total-count').textContent = status.sent_count + status.received_count;
}

function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }

function showToast(msg, type) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.animation = 'slideOut 0.3s ease'; setTimeout(() => toast.remove(), 300); }, 3000);
}

loadStatus();
loadHistory();
setInterval(() => { loadStatus(); loadHistory(); }, 3000);