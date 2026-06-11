#!/usr/bin/env python3
"""
CovertDNS - Simple Launcher
One command to rule them all
"""

import subprocess
import sys
import os
import time
import webbrowser
import threading

# Suppress eventlet warning
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

def print_banner():
    banner = """
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║      ██████╗ ██████╗ ██╗   ██╗███████╗██████╗ ████████╗     ║
    ║     ██╔════╝██╔═══██╗██║   ██║██╔════╝██╔══██╗╚══██╔══╝     ║
    ║     ██║     ██║   ██║██║   ██║█████╗  ██║  ██║   ██║        ║
    ║     ██║     ██║   ██║╚██╗ ██╔╝██╔══╝  ██║  ██║   ██║        ║
    ║     ╚██████╗╚██████╔╝ ╚████╔╝ ███████╗██████╔╝   ██║        ║
    ║      ╚═════╝ ╚═════╝   ╚═══╝  ╚══════╝╚═════╝    ╚═╝        ║
    ║                                                              ║
    ║                CovertDNS - DNS Tunnel Launcher               ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)

def check_and_install(package):
    """Check if package is installed, if not, install it"""
    try:
        __import__(package)
        return True
    except ImportError:
        print(f"📦 Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return True

def start_receiver():
    """Start DNS receiver in new window"""
    print("\n📡 Starting DNS Receiver...")
    
    if sys.platform == "win32":
        # Windows: Open new terminal with receiver
        cmd = f'start cmd /k "cd /d {os.getcwd()} && python dns_tunnel.py receiver"'
        os.system(cmd)
        print("   ✅ Receiver started in new window")
    else:
        # Linux/Mac
        cmd = f'gnome-terminal -- bash -c "cd {os.getcwd()} && python3 dns_tunnel.py receiver; exec bash"'
        os.system(cmd)
        print("   ✅ Receiver started in new terminal")

def start_web():
    """Start web interface"""
    print("\n🌐 Starting Web Interface...")
    
    # Start web server in background
    web_process = subprocess.Popen(
        [sys.executable, "web_interface.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    )
    
    time.sleep(2)
    print("   ✅ Web UI: http://localhost:5000")
    return web_process

def open_browser():
    """Open browser after delay"""
    time.sleep(3)
    webbrowser.open("http://localhost:5000")
    print("   ✅ Browser opened")

def generate_keys():
    """Generate keys"""
    print("\n🔑 Generating Keys...")
    try:
        subprocess.run([sys.executable, "dns_tunnel.py", "genkeys"], check=True)
        print("   ✅ Keys generated: public_key.b64, private_key.b64")
    except Exception as e:
        print(f"   ❌ Error: {e}")

def main():
    print_banner()
    
    # Check required packages
    print("\n🔍 Checking dependencies...")
    check_and_install("flask")
    check_and_install("flask_socketio")
    check_and_install("eventlet")
    print("   ✅ All dependencies OK")
    
    # Simple menu
    print("\n" + "=" * 60)
    print("📋 SIMPLE MENU")
    print("=" * 60)
    print("   [1] START EVERYTHING (Receiver + Web)")
    print("   [2] Generate New Keys")
    print("   [3] Start Web Only")
    print("   [4] Start Receiver Only")
    print("   [5] Exit")
    print("=" * 60)
    
    choice = input("\n👉 Choose (1-5): ").strip()
    
    if choice == "1":
        print("\n🚀 STARTING EVERYTHING...\n")
        
        # Start receiver
        start_receiver()
        time.sleep(1)
        
        # Start web
        web_proc = start_web()
        
        # Open browser
        threading.Thread(target=open_browser, daemon=True).start()
        
        print("\n" + "=" * 60)
        print("✅ ALL SYSTEMS RUNNING")
        print("=" * 60)
        print("\n📋 QUICK GUIDE:")
        print("   1. Web UI: http://localhost:5000")
        print("   2. In Receiver window, enter private key")
        print("   3. Generate keys from Web UI first!")
        print("   4. Close this window to stop web server")
        print("\n💡 Press Ctrl+C to stop...\n")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping...")
            web_proc.terminate()
            print("   ✅ Stopped")
    
    elif choice == "2":
        generate_keys()
    
    elif choice == "3":
        web_proc = start_web()
        threading.Thread(target=open_browser, daemon=True).start()
        print("\n💡 Press Ctrl+C to stop web server...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            web_proc.terminate()
            print("\n   ✅ Stopped")
    
    elif choice == "4":
        start_receiver()
        print("\n✅ Receiver started in new window")
    
    elif choice == "5":
        print("\n👋 Goodbye!\n")
    
    else:
        print("\n❌ Invalid choice!")

if __name__ == "__main__":
    main()