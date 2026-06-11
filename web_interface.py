#!/usr/bin/env python3
"""
CovertDNS - Web Interface
DNS Tunnel Management with Real-time Monitoring
"""
import socket
import threading
import time
import base64
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import eventlet

eventlet.monkey_patch()

# Import actual dns_tunnel modules
from dns_tunnel import DNSSender, DNSReceiver, generate_keys, VoiceMessageHandler
from encryption.hybrid_crypto import HybridCrypto
from shared.constants import DNS_PORT, BASE_DOMAIN, MAX_CHUNK_SIZE

app = Flask(__name__)
app.config['SECRET_KEY'] = 'covertdns-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state
receiver_instance = None
receiver_thread = None
is_receiving = False
message_history = []
current_keys = {"public": None, "private": None}


class WebDNSReceiver(DNSReceiver):
    def __init__(self, private_key_b64=None):
        super().__init__(private_key_b64)
    
    def _try_reassemble(self, client_ip):
        msg_data = self.messages.get(client_ip)
        if not msg_data:
            return
        
        chunks = msg_data['chunks']
        total_chunks = msg_data.get('total_chunks')
        
        sorted_seqs = sorted(chunks.keys())
        expected = 1
        collected = []
        
        for seq in sorted_seqs:
            if seq == expected:
                collected.append(chunks[seq])
                expected += 1
            else:
                return
        
        if total_chunks and len(collected) != total_chunks:
            return
        
        if len(collected) > 0:
            try:
                encoded = ''.join(collected)
                
                socketio.emit('chunk_progress', {
                    'client': client_ip,
                    'received': len(collected),
                    'total': total_chunks or len(collected),
                    'complete': True
                })
                
                decrypted = None
                if self.private_key:
                    try:
                        decrypted = HybridCrypto.decrypt_from_dns(encoded, self.private_key)
                    except:
                        pass
                
                if decrypted is None:
                    try:
                        decrypted = base64.b64decode(encoded).decode()
                    except:
                        decrypted = encoded
                
                if decrypted.startswith("VOICE:"):
                    audio_b64 = decrypted[6:]
                    audio_bytes = base64.b64decode(audio_b64)
                    filepath = VoiceMessageHandler.save_audio(audio_bytes)
                    
                    message_data = {
                        'type': 'voice',
                        'from': client_ip,
                        'size': len(audio_bytes),
                        'file': filepath,
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'message': f'[Voice message - {len(audio_bytes)} bytes]'
                    }
                elif decrypted.startswith("TEXT:"):
                    text_content = decrypted[5:]
                    message_data = {
                        'type': 'text',
                        'from': client_ip,
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'message': text_content,
                        'chunks': len(collected)
                    }
                else:
                    message_data = {
                        'type': 'text',
                        'from': client_ip,
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'message': decrypted,
                        'chunks': len(collected)
                    }
                
                global message_history
                message_history.insert(0, message_data)
                if len(message_history) > 100:
                    message_history = message_history[:100]
                
                socketio.emit('new_message', message_data)
                del self.messages[client_ip]
                
            except Exception as e:
                socketio.emit('error', {'message': f'Reassembly error: {str(e)}'})
    
    def _handle_dns_packet(self, data: bytes, addr: tuple):
        try:
            domain = self._extract_domain(data)
            if not domain or not domain.endswith(BASE_DOMAIN):
                return
            
            try:
                response = self._build_dns_response(data)
                self.sock.sendto(response, addr)
            except:
                pass
            
            parts = domain.replace(f'.{BASE_DOMAIN}', '').split('.')
            if len(parts) >= 2:
                try:
                    seq = int(parts[0])
                    chunk_data = parts[1] if len(parts) > 1 else ""
                    client_ip = addr[0]
                    
                    if client_ip not in self.messages:
                        self.messages[client_ip] = {'chunks': {}, 'total_chunks': None}
                    
                    if chunk_data.startswith('T'):
                        try:
                            total = int(chunk_data[1:4])
                            chunk_data = chunk_data[4:]
                            self.messages[client_ip]['total_chunks'] = total
                        except ValueError:
                            pass
                    
                    self.messages[client_ip]['chunks'][seq] = chunk_data
                    received = len(self.messages[client_ip]['chunks'])
                    total = self.messages[client_ip]['total_chunks'] or '?'
                    
                    socketio.emit('chunk_progress', {
                        'client': client_ip,
                        'seq': seq,
                        'received': received,
                        'total': total,
                        'complete': False
                    })
                    
                    self._try_reassemble(client_ip)
                except ValueError:
                    pass
        except Exception:
            pass


class WebDNSSender(DNSSender):
    def __init__(self, target_ip, public_key_b64=None):
        super().__init__(target_ip, public_key_b64)
    
    def _send_single_query(self, domain: str, chunk_num: int, total: int) -> bool:
        if not self.rate_limiter.allow():
            time.sleep(0.5)
        query = self.build_dns_query(domain)
        try:
            self.sock.sendto(query, (self.target_ip, DNS_PORT))
            
            socketio.emit('send_progress', {
                'chunk': chunk_num + 1,
                'total': total,
                'percent': ((chunk_num + 1) / total) * 100,
                'domain': domain[:80] + '...' if len(domain) > 80 else domain
            })
            
            return True
        except socket.error as e:
            socketio.emit('error', {'message': f'Failed to send chunk: {str(e)}'})
            return False


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/keys/generate', methods=['POST'])
def api_generate_keys():
    global current_keys
    try:
        pub_b64, priv_b64 = generate_keys()
        current_keys['public'] = pub_b64
        current_keys['private'] = priv_b64
        
        socketio.emit('keys_updated', {
            'public': pub_b64[:100] + '...',
            'private': priv_b64[:100] + '...'
        })
        
        return jsonify({'success': True, 'public': pub_b64, 'private': priv_b64})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/keys/load', methods=['POST'])
def api_load_keys():
    global current_keys
    try:
        if os.path.exists('public_key.b64'):
            with open('public_key.b64', 'r') as f:
                current_keys['public'] = f.read().strip()
        if os.path.exists('private_key.b64'):
            with open('private_key.b64', 'r') as f:
                current_keys['private'] = f.read().strip()
        
        if current_keys['public'] or current_keys['private']:
            socketio.emit('keys_updated', {
                'public': (current_keys['public'][:100] + '...') if current_keys['public'] else 'Not found',
                'private': (current_keys['private'][:100] + '...') if current_keys['private'] else 'Not found'
            })
            return jsonify({'success': True, 'public': current_keys['public'], 'private': current_keys['private']})
        else:
            return jsonify({'success': False, 'error': 'No key files found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/receiver/start', methods=['POST'])
def api_start_receiver():
    global receiver_instance, receiver_thread, is_receiving
    
    if is_receiving:
        return jsonify({'success': False, 'error': 'Receiver already running'})
    
    data = request.json
    private_key = data.get('private_key', None)
    
    try:
        receiver_instance = WebDNSReceiver(private_key if private_key else None)
        is_receiving = True
        
        def run_receiver():
            try:
                receiver_instance.start()
            except Exception as e:
                socketio.emit('error', {'message': f'Receiver error: {str(e)}'})
            finally:
                global is_receiving
                is_receiving = False
        
        receiver_thread = threading.Thread(target=run_receiver, daemon=True)
        receiver_thread.start()
        
        socketio.emit('receiver_status', {'running': True})
        return jsonify({'success': True})
    except Exception as e:
        is_receiving = False
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/receiver/stop', methods=['POST'])
def api_stop_receiver():
    global receiver_instance, is_receiving
    
    if receiver_instance:
        receiver_instance.stop()
        receiver_instance = None
        is_receiving = False
        socketio.emit('receiver_status', {'running': False})
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Receiver not running'})


@app.route('/api/sender/send', methods=['POST'])
def api_send_message():
    data = request.json
    target_ip = data.get('target_ip', '127.0.0.1')
    message = data.get('message', '')
    encrypt = data.get('encrypt', True)
    public_key = data.get('public_key', None)
    
    if not message:
        return jsonify({'success': False, 'error': 'No message provided'})
    
    try:
        sender = WebDNSSender(target_ip, public_key if public_key else None)
        success = sender.send_text_message(message, encrypt=encrypt)
        sender.close()
        
        if success:
            socketio.emit('message_sent', {
                'target': target_ip,
                'message': message[:100] + '...' if len(message) > 100 else message,
                'encrypted': encrypt,
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Send failed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/sender/send_voice', methods=['POST'])
def api_send_voice():
    data = request.json
    target_ip = data.get('target_ip', '127.0.0.1')
    audio_base64 = data.get('audio', '')
    encrypt = data.get('encrypt', True)
    public_key = data.get('public_key', None)
    
    if not audio_base64:
        return jsonify({'success': False, 'error': 'No audio provided'})
    
    try:
        audio_bytes = base64.b64decode(audio_base64)
        sender = WebDNSSender(target_ip, public_key if public_key else None)
        success = sender.send_voice_message(audio_bytes, encrypt=encrypt)
        sender.close()
        
        if success:
            socketio.emit('message_sent', {
                'target': target_ip,
                'message': '[Voice message]',
                'encrypted': encrypt,
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Send failed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/history', methods=['GET'])
def api_get_history():
    return jsonify({'messages': message_history})


@app.route('/api/status', methods=['GET'])
def api_get_status():
    return jsonify({
        'receiver_running': is_receiving,
        'port': DNS_PORT,
        'domain': BASE_DOMAIN,
        'keys_loaded': current_keys['public'] is not None,
        'message_count': len(message_history),
        'chunk_size': MAX_CHUNK_SIZE
    })


if __name__ == '__main__':
    for folder in ['templates', 'static/css', 'static/js', 'received_voices']:
        if not os.path.exists(folder):
            os.makedirs(folder)
    
    print("=" * 60)
    print("🌐 CovertDNS Web Interface")
    print("=" * 60)
    print(f"\n📍 Web UI: http://localhost:5000")
    print(f"📍 DNS Port: {DNS_PORT}")
    print(f"📍 Domain: {BASE_DOMAIN}")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)