// Socket.IO connection
const socket = io();

// Global variables
let mediaRecorderInstance = null;
let audioChunksArray = [];
let currentStealthMode = "normal";
let messageCount = 0;

// DOM Elements
const genkeysBtn = document.getElementById('genkeys-btn');
const loadkeysBtn = document.getElementById('loadkeys-btn');
const startReceiverBtn = document.getElementById('start-receiver-btn');
const stopReceiverBtn = document.getElementById('stop-receiver-btn');
const sendTextBtn = document.getElementById('send-text-btn');
const sendVoiceBtn = document.getElementById('send-voice-btn');
const recordBtn = document.getElementById('record-btn');
const recordFastBtn = document.getElementById('record-fast-btn');
const clearHistoryBtn = document.getElementById('clear-history-btn');

// Stealth mode selection
document.querySelectorAll('.stealth-card').forEach(card => {
    card.addEventListener('click', () => {
        document.querySelectorAll('.stealth-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        card.querySelectorAll('.stealth-select').forEach(s => s.textContent = 'Selected ✓');
        document.querySelectorAll('.stealth-card:not(.active) .stealth-select').forEach(s => s.textContent = 'Select');
        
        currentStealthMode = card.getAttribute('data-stealth');
        console.log('Stealth mode changed to:', currentStealthMode);
        showNotification(`Stealth mode: ${card.querySelector('.stealth-title').textContent}`, 'info');
    });
});

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadHistory();
    
    document.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const cmd = btn.getAttribute('data-cmd');
            navigator.clipboard.writeText(cmd);
            btn.textContent = '✓ Copied!';
            setTimeout(() => btn.textContent = '📋 Copy', 2000);
        });
    });
});

// Socket events
socket.on('connect', () => {
    console.log('Connected to server');
});

socket.on('keys_updated', (data) => {
    document.getElementById('public-key-display').textContent = data.public;
    document.getElementById('private-key-display').textContent = data.private;
    showNotification('Keys updated!', 'success');
});

socket.on('receiver_status', (data) => {
    const statusEl = document.getElementById('receiver-status');
    statusEl.textContent = data.running ? 'Running ✅' : 'Stopped ❌';
    statusEl.style.color = data.running ? '#00ff9d' : '#ff4444';
});

socket.on('new_message', (data) => {
    addMessageToHistory(data);
    updateMessageCount();
    showNotification(`New ${data.type} message received!`, 'info');
    
    // If voice message, play automatically
    if (data.type === 'voice' && data.voice_id) {
        playVoiceMessage(data.voice_id);
    }
});

socket.on('message_sent', (data) => {
    showNotification(`Message sent to ${data.target}`, 'success');
    addMessageToHistory({
        type: 'sent',
        from: 'You',
        to: data.target,
        message: data.message,
        time: data.time,
        encrypted: data.encrypted,
        stealth_mode: data.stealth_mode
    });
});

socket.on('chunk_progress', (data) => {
    updateChunkProgress(data);
});

socket.on('send_progress', (data) => {
    updateSendProgress(data);
});

socket.on('error', (data) => {
    showNotification(`Error: ${data.message}`, 'error');
});

// Key Management
genkeysBtn.addEventListener('click', async () => {
    genkeysBtn.disabled = true;
    genkeysBtn.innerHTML = '<span class="btn-icon">⏳</span> Generating...';
    
    try {
        const response = await fetch('/api/keys/generate', { method: 'POST' });
        const result = await response.json();
        
        if (result.success) {
            document.getElementById('public-key-input').value = result.public;
            document.getElementById('private-key-input').value = result.private;
            showNotification('Keys generated successfully!', 'success');
        } else {
            showNotification(`Error: ${result.error}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        genkeysBtn.disabled = false;
        genkeysBtn.innerHTML = '<span class="btn-icon">✨</span> Generate New Keys';
    }
});

loadkeysBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('/api/keys/load', { method: 'POST' });
        const result = await response.json();
        
        if (result.success) {
            document.getElementById('public-key-input').value = result.public;
            document.getElementById('private-key-input').value = result.private;
            showNotification('Keys loaded from files!', 'success');
        } else {
            showNotification(`Error: ${result.error}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
});

// Receiver Control
startReceiverBtn.addEventListener('click', async () => {
    const privateKey = document.getElementById('private-key-input').value;
    
    startReceiverBtn.disabled = true;
    startReceiverBtn.innerHTML = '<span class="btn-icon">⏳</span> Starting...';
    
    try {
        const response = await fetch('/api/receiver/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ private_key: privateKey || null })
        });
        const result = await response.json();
        
        if (result.success) {
            showNotification('Receiver started!', 'success');
        } else {
            showNotification(`Error: ${result.error}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        startReceiverBtn.disabled = false;
        startReceiverBtn.innerHTML = '<span class="btn-icon">▶️</span> Start Receiver';
    }
});

stopReceiverBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('/api/receiver/stop', { method: 'POST' });
        const result = await response.json();
        
        if (result.success) {
            showNotification('Receiver stopped!', 'success');
        } else {
            showNotification(`Error: ${result.error}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
});

// Send Text Message
sendTextBtn.addEventListener('click', async () => {
    const targetIP = document.getElementById('target-ip').value;
    const message = document.getElementById('text-message').value;
    const publicKey = document.getElementById('public-key-input').value;
    const encryptRadio = document.querySelector('input[name="encrypt"]:checked');
    const encrypt = encryptRadio ? encryptRadio.value === 'encrypted' : true;
    
    if (!message) {
        showNotification('Please enter a message', 'warning');
        return;
    }
    
    sendTextBtn.disabled = true;
    sendTextBtn.innerHTML = '<span class="btn-icon">⏳</span> Sending...';
    
    try {
        const response = await fetch('/api/sender/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_ip: targetIP,
                message: message,
                encrypt: encrypt,
                public_key: publicKey || null,
                stealth_mode: currentStealthMode
            })
        });
        const result = await response.json();
        
        if (result.success) {
            showNotification(`Message sent with ${currentStealthMode} stealth mode!`, 'success');
            document.getElementById('text-message').value = '';
        } else {
            showNotification(`Error: ${result.error}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        sendTextBtn.disabled = false;
        sendTextBtn.innerHTML = '<span class="btn-icon">📨</span> Send Text Message';
    }
});

// Voice Recording
async function startRecording(duration) {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorderInstance = new MediaRecorder(stream);
        audioChunksArray = [];
        
        mediaRecorderInstance.ondataavailable = (event) => {
            audioChunksArray.push(event.data);
        };
        
        mediaRecorderInstance.onstop = async () => {
            const audioBlob = new Blob(audioChunksArray, { type: 'audio/wav' });
            const reader = new FileReader();
            
            reader.onloadend = async () => {
                const base64Audio = reader.result.split(',')[1];
                document.getElementById('audio-preview').src = URL.createObjectURL(audioBlob);
                document.getElementById('audio-preview').style.display = 'block';
                sendVoiceBtn.disabled = false;
                window.currentAudioBase64 = base64Audio;
            };
            
            reader.readAsDataURL(audioBlob);
            stream.getTracks().forEach(track => track.stop());
        };
        
        mediaRecorderInstance.start();
        showNotification(`Recording for ${duration/1000} seconds... Speak now!`, 'info');
        
        setTimeout(() => {
            if (mediaRecorderInstance && mediaRecorderInstance.state === 'recording') {
                mediaRecorderInstance.stop();
                showNotification('Recording complete!', 'success');
            }
        }, duration);
        
    } catch (error) {
        showNotification('Microphone access denied! Please check permissions.', 'error');
    }
}

recordBtn.addEventListener('click', () => startRecording(5000));
recordFastBtn.addEventListener('click', () => startRecording(1000));

sendVoiceBtn.addEventListener('click', async () => {
    if (!window.currentAudioBase64) {
        showNotification('No audio recorded. Please record first.', 'warning');
        return;
    }
    
    const targetIP = document.getElementById('target-ip').value;
    const publicKey = document.getElementById('public-key-input').value;
    const encryptRadio = document.querySelector('input[name="encrypt"]:checked');
    const encrypt = encryptRadio ? encryptRadio.value === 'encrypted' : true;
    
    sendVoiceBtn.disabled = true;
    sendVoiceBtn.innerHTML = '<span class="btn-icon">⏳</span> Sending...';
    
    try {
        const response = await fetch('/api/sender/send_voice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_ip: targetIP,
                audio: window.currentAudioBase64,
                encrypt: encrypt,
                public_key: publicKey || null,
                stealth_mode: currentStealthMode
            })
        });
        const result = await response.json();
        
        if (result.success) {
            showNotification('Voice message sent!', 'success');
            document.getElementById('audio-preview').style.display = 'none';
            sendVoiceBtn.disabled = true;
            window.currentAudioBase64 = null;
        } else {
            showNotification(`Error: ${result.error}`, 'error');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        sendVoiceBtn.disabled = false;
        sendVoiceBtn.innerHTML = '<span class="btn-icon">🎵</span> Send Voice Message';
    }
});

// Play voice message
function playVoiceMessage(voiceId) {
    const audioUrl = `/api/download/${voiceId}`;
    const audio = new Audio(audioUrl);
    audio.play().catch(e => console.log('Auto-play blocked:', e));
}

// Download voice message
async function downloadVoiceMessage(voiceId) {
    window.location.href = `/api/download/${voiceId}`;
    showNotification('Download started!', 'success');
}

// Clear History
clearHistoryBtn.addEventListener('click', () => {
    document.getElementById('message-list').innerHTML = '<div class="empty-message">No messages yet. Follow steps 1-5 to send your first message...</div>';
    messageCount = 0;
    updateMessageCount();
});

// Helper Functions
function addMessageToHistory(data) {
    const messageList = document.getElementById('message-list');
    const emptyMsg = messageList.querySelector('.empty-message');
    if (emptyMsg) emptyMsg.remove();
    
    const messageEl = document.createElement('div');
    messageEl.className = 'message-item';
    
    const isSent = data.type === 'sent';
    const typeClass = data.type === 'voice' ? 'voice' : 'text';
    
    // Debug için console.log
    console.log('Adding message:', data);
    
    let actionButtons = '';
    if (data.type === 'voice' && data.voice_id) {
        actionButtons = `
            <div style="margin-top: 10px; display: flex; gap: 10px; flex-wrap: wrap;">
                <button onclick="playVoice('${data.voice_id}')" class="btn-small" style="background: #00ff9d20; cursor: pointer;">
                    ▶️ Play
                </button>
                <button onclick="downloadVoice('${data.voice_id}')" class="btn-small" style="background: #00ff9d20; cursor: pointer;">
                    💾 Download
                </button>
            </div>
        `;
    }
    
    let durationInfo = '';
    if (data.duration) {
        durationInfo = `<div style="font-size:0.7em; color:#888;">⏱️ Duration: ${data.duration.toFixed(1)} seconds</div>`;
    }
    
    messageEl.innerHTML = `
        <div class="message-header">
            <span class="message-type ${typeClass}">${isSent ? '📤 SENT' : (data.type === 'voice' ? '🎤 VOICE' : '📝 TEXT')}</span>
            <span>${data.time || new Date().toLocaleTimeString()}</span>
            ${data.from ? `<span>From: ${data.from}</span>` : ''}
            ${data.to ? `<span>To: ${data.to}</span>` : ''}
        </div>
        <div class="message-content">${data.message || data.text || '[Message]'}</div>
        ${data.encrypted !== undefined ? `<div style="font-size:0.7em; color:#888; margin-top:5px;">🔐 ${data.encrypted ? 'Encrypted (Kyber-768)' : 'Plain text'}</div>` : ''}
        ${data.stealth_mode ? `<div style="font-size:0.7em; color:#888;">🕵️ Stealth: ${data.stealth_mode}</div>` : ''}
        ${data.size ? `<div style="font-size:0.7em; color:#888;">📦 Size: ${data.size} bytes</div>` : ''}
        ${data.chunks ? `<div style="font-size:0.7em; color:#888;">📦 Chunks: ${data.chunks}</div>` : ''}
        ${durationInfo}
        ${actionButtons}
    `;
    
    messageList.insertBefore(messageEl, messageList.firstChild);
    messageCount++;
}

// Global fonksiyonlar
window.playVoice = function(voiceId) {
    console.log('Playing voice:', voiceId);
    const audio = new Audio(`/api/download/${voiceId}`);
    audio.play().catch(e => console.error('Play error:', e));
    showNotification('Playing voice message...', 'info');
};

window.downloadVoice = function(voiceId) {
    console.log('Downloading voice:', voiceId);
    window.location.href = `/api/download/${voiceId}`;
    showNotification('Download started!', 'success');
};

function updateChunkProgress(data) {
    const chunkProgressDiv = document.getElementById('chunk-progress');
    const chunkList = document.getElementById('chunk-list');
    
    if (!data.complete) {
        chunkProgressDiv.style.display = 'block';
        const percent = (data.received / data.total) * 100;
        document.getElementById('chunk-progress-fill').style.width = `${percent}%`;
        document.getElementById('chunk-progress-fill').textContent = `${Math.round(percent)}%`;
        document.getElementById('chunk-progress-text').textContent = 
            `Receiving from ${data.client}: Chunk ${data.seq} (${data.received}/${data.total})`;
        
        const emptyChunk = chunkList.querySelector('.empty-message');
        if (emptyChunk) emptyChunk.remove();
        
        const chunkItem = document.createElement('div');
        chunkItem.className = 'chunk-item';
        chunkItem.innerHTML = `
            <span>📦 Chunk ${data.seq}</span>
            <span>From: ${data.client}</span>
            <span>Progress: ${data.received}/${data.total}</span>
        `;
        chunkList.insertBefore(chunkItem, chunkList.firstChild);
        
        while (chunkList.children.length > 20) {
            chunkList.removeChild(chunkList.lastChild);
        }
    } else {
        setTimeout(() => {
            chunkProgressDiv.style.display = 'none';
            document.getElementById('chunk-progress-fill').style.width = '0%';
        }, 2000);
    }
}

function updateSendProgress(data) {
    const sendProgressDiv = document.getElementById('send-progress');
    sendProgressDiv.style.display = 'block';
    
    document.getElementById('send-progress-fill').style.width = `${data.percent}%`;
    document.getElementById('send-progress-fill').textContent = `${Math.round(data.percent)}%`;
    document.getElementById('send-progress-text').textContent = 
        `Sending: Chunk ${data.chunk}/${data.total} - ${data.domain}`;
    
    if (data.chunk === data.total) {
        setTimeout(() => {
            sendProgressDiv.style.display = 'none';
            document.getElementById('send-progress-fill').style.width = '0%';
        }, 2000);
    }
}

function updateMessageCount() {
    const count = document.querySelectorAll('#message-list .message-item').length;
    document.getElementById('message-count').textContent = count;
}

function showNotification(message, type) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    let bgColor = '#00cc88';
    if (type === 'error') bgColor = '#ff4444';
    else if (type === 'warning') bgColor = '#ffaa00';
    else if (type === 'info') bgColor = '#00aacc';
    
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${bgColor};
        color: white;
        border-radius: 8px;
        z-index: 1000;
        animation: slideIn 0.3s ease;
        font-size: 14px;
        font-family: monospace;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

async function loadStatus() {
    try {
        const response = await fetch('/api/status');
        const status = await response.json();
        
        document.getElementById('port-status').textContent = status.port;
        document.getElementById('domain-status').textContent = status.domain;
        document.getElementById('receiver-status').textContent = status.receiver_running ? 'Running ✅' : 'Stopped ❌';
        document.getElementById('message-count').textContent = status.message_count;
        messageCount = status.message_count;
    } catch (error) {
        console.error('Failed to load status:', error);
    }
}

async function loadHistory() {
    try {
        const response = await fetch('/api/history');
        const data = await response.json();
        
        if (data.messages && data.messages.length > 0) {
            data.messages.forEach(msg => addMessageToHistory(msg));
            updateMessageCount();
        }
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

// Make functions global for onclick handlers
window.playVoiceMessage = playVoiceMessage;
window.downloadVoiceMessage = downloadVoiceMessage;

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

console.log('CovertDNS Web Interface loaded');
console.log('Stealth mode available:', currentStealthMode);