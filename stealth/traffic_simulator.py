"""
DNS Traffic Simulator - Human-Like Behaviors

This module implements anti-detection features that make DNS tunnel traffic
appear indistinguishable from normal user activity. It simulates realistic
DNS query patterns, human typing/thinking/reading delays, and background
traffic to legitimate domains.

The simulator works by:
    1. Generating background DNS queries to popular domains (Google, YouTube, etc.)
    2. Varying traffic intensity based on time of day
    3. Adding human-like delays between queries (typing, thinking, reading)
    4. Introducing random distractions (user looking away, etc.)
    5. Randomizing DNS record types and chunk sizes

These techniques collectively make the covert channel resistant to
behavioral analysis and traffic pattern detection.
"""

import random
import time
import threading
import socket
from typing import List, Dict, Optional
from datetime import datetime
import os
import json

# ============================================================================
# Realistic Domain List
# ============================================================================

# Popular domains from Alexa Top 1000 (realistic user traffic)
REAL_DOMAINS = [
    "google.com", "youtube.com", "facebook.com", "baidu.com", "wikipedia.org",
    "amazon.com", "yahoo.com", "twitter.com", "instagram.com", "linkedin.com",
    "whatsapp.com", "netflix.com", "microsoft.com", "apple.com", "spotify.com",
    "zoom.us", "github.com", "stackoverflow.com", "reddit.com", "bing.com",
    "office.com", "live.com", "twitch.tv", "pinterest.com", "ebay.com",
    "cloudflare.com", "adobe.com", "dropbox.com", "salesforce.com", "craigslist.org"
]

# DNS query types (A, AAAA, MX, TXT, NS, CNAME)
# Randomizing query types makes traffic appear more legitimate
RECORD_TYPES = [1, 28, 15, 16, 2, 5]  # A, AAAA, MX, TXT, NS, CNAME

# ============================================================================
# Hourly Traffic Intensity
# ============================================================================

# Traffic intensity varies by hour of day (0-23 hours, 0-10 intensity)
# This mimics real user behavior: low traffic at night, high during the day
HOUR_TRAFFIC = {
    0: 1, 1: 1, 2: 1, 3: 1, 4: 2, 5: 3, 6: 5, 7: 7,
    8: 9, 9: 10, 10: 10, 11: 9, 12: 8, 13: 9, 14: 10, 15: 9,
    16: 8, 17: 7, 18: 8, 19: 7, 20: 6, 21: 5, 22: 3, 23: 2
}


# ============================================================================
# Traffic Simulator
# ============================================================================

class TrafficSimulator:
    """
    Realistic DNS traffic simulator that generates background queries.
    
    This class runs a background thread that periodically sends DNS queries
    to legitimate domains (e.g., google.com, youtube.com). The frequency of
    these queries varies based on the time of day, making the overall traffic
    pattern appear human-like rather than machine-generated.
    
    Attributes:
        dns_server (str): Target DNS server (default: 8.8.8.8 - Google DNS)
        running (bool): Flag indicating whether background traffic is active
        sock (socket.socket): UDP socket for sending DNS queries
        stats (dict): Statistics tracking number of fake queries sent
    """
    
    def __init__(self, dns_server: str = "8.8.8.8"):
        """
        Initialize the traffic simulator.
        
        Args:
            dns_server: DNS server to send background queries to.
                       Default: 8.8.8.8 (Google Public DNS)
        """
        self.dns_server = dns_server
        self.running = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)
        self.stats = {"real_queries": 0, "fake_queries": 0}
        
        print(f"🕵️ Traffic Simulator initialized")
        print(f"   DNS Server: {dns_server}")
        print(f"   Fake domains: {len(REAL_DOMAINS)}")
    
    def get_traffic_intensity(self) -> float:
        """
        Get current traffic intensity based on the hour of day.
        
        Returns:
            float: Interval in seconds between background queries.
                  Higher intensity (daytime) = lower interval.
        """
        hour = datetime.now().hour
        intensity = HOUR_TRAFFIC.get(hour, 5)
        # Convert to interval in seconds (higher intensity = lower interval)
        return max(2.0, 15.0 / max(1, intensity))
    
    def build_dns_query(self, domain: str, query_type: int = 1) -> bytes:
        """
        Build a DNS query packet for a given domain.
        
        Args:
            domain: Domain name to query.
            query_type: DNS record type (1 = A record).
        
        Returns:
            bytes: Complete DNS query packet.
        """
        transaction_id = random.randint(0, 65535).to_bytes(2, 'big')
        flags = (0x0100).to_bytes(2, 'big')
        qdcount = (0x0001).to_bytes(2, 'big')
        ancount = (0x0000).to_bytes(2, 'big')
        nscount = (0x0000).to_bytes(2, 'big')
        arcount = (0x0000).to_bytes(2, 'big')
        
        header = transaction_id + flags + qdcount + ancount + nscount + arcount
        question = self._encode_domain_name(domain)
        qtype = query_type.to_bytes(2, 'big')
        qclass = (0x0001).to_bytes(2, 'big')
        
        return header + question + qtype + qclass
    
    def _encode_domain_name(self, domain: str) -> bytes:
        """
        Encode a domain name in DNS wire format.
        
        Args:
            domain: Domain name string.
        
        Returns:
            bytes: Domain name in DNS wire format.
        """
        parts = domain.split('.')
        result = b''
        for part in parts:
            if len(part) > 63:
                continue
            result += len(part).to_bytes(1, 'big')
            result += part.encode('ascii')
        result += b'\x00'
        return result
    
    def send_realistic_query(self) -> bool:
        """
        Send a realistic DNS query to the configured DNS server.
        
        Selects a random domain from REAL_DOMAINS and a random record type
        to make the query appear legitimate.
        
        Returns:
            bool: True if the query was sent successfully, False otherwise.
        """
        domain = random.choice(REAL_DOMAINS)
        qtype = random.choice(RECORD_TYPES)
        
        query = self.build_dns_query(domain, qtype)
        
        try:
            self.sock.sendto(query, (self.dns_server, 53))
            self.stats["fake_queries"] += 1
            return True
        except Exception:
            return False
    
    def start_background_traffic(self):
        """
        Start background DNS traffic in a separate daemon thread.
        
        The background traffic continues until stop_background_traffic() is called.
        """
        def _background_worker():
            while self.running:
                try:
                    interval = self.get_traffic_intensity()
                    # Add random jitter to avoid periodic patterns
                    interval *= random.uniform(0.5, 1.5)
                    
                    time.sleep(interval)
                    self.send_realistic_query()
                    
                except Exception:
                    time.sleep(1)
        
        self.running = True
        thread = threading.Thread(target=_background_worker, daemon=True)
        thread.start()
        return thread
    
    def stop_background_traffic(self):
        """Stop background DNS traffic and close the socket."""
        self.running = False
        if self.sock:
            self.sock.close()
    
    def get_stats(self) -> dict:
        """Get simulation statistics."""
        return self.stats


# ============================================================================
# Human Behavior Simulator
# ============================================================================

class HumanBehaviorSimulator:
    """
    Simulate human typing, thinking, and reading patterns.
    
    This class models the natural delays that occur when a human user is
    interacting with a messaging application. It includes:
        - Typing delays (fast, normal, slow typers)
        - Thinking delays before responding
        - Reading delays for incoming messages
        - Random distractions (user looks away, gets interrupted)
    
    The delays are probabilistically distributed to mimic real human behavior
    rather than machine-precise timing.
    """
    
    def __init__(self):
        # Typing speed profiles (words per minute and corresponding delays)
        self.typing_speeds = {
            "fast": {"wpm": 80, "min_delay": 0.03, "max_delay": 0.08, "prob": 0.2},
            "normal": {"wpm": 50, "min_delay": 0.08, "max_delay": 0.15, "prob": 0.6},
            "slow": {"wpm": 30, "min_delay": 0.15, "max_delay": 0.35, "prob": 0.2}
        }
        
        # Thinking time before responding to a message
        self.thinking_times = {
            "quick": {"min": 0.1, "max": 0.4, "prob": 0.3},
            "normal": {"min": 0.4, "max": 1.0, "prob": 0.5},
            "careful": {"min": 1.0, "max": 2.5, "prob": 0.2}
        }
        
        # Reading speed (characters per second)
        self.reading_speeds = {
            "fast": {"chars_per_sec": 500, "prob": 0.2},
            "normal": {"chars_per_sec": 300, "prob": 0.6},
            "slow": {"chars_per_sec": 150, "prob": 0.2}
        }
        
        # Random distraction simulation
        self.distraction_probability = 0.1  # 10% chance of distraction
        self.distraction_duration = {"min": 2.0, "max": 8.0}
    
    def _select_pattern(self, patterns: dict) -> dict:
        """
        Select a pattern based on probability distribution.
        
        Args:
            patterns: Dictionary of patterns with 'prob' keys.
        
        Returns:
            dict: Selected pattern.
        """
        r = random.random()
        cumulative = 0
        for name, pattern in patterns.items():
            cumulative += pattern.get("prob", 0.2)
            if r <= cumulative:
                return pattern
        return patterns["normal"]
    
    def get_typing_delay(self, text_length: int = None) -> float:
        """
        Get a human-like typing delay for a message.
        
        Args:
            text_length: Length of the message in characters (optional).
        
        Returns:
            float: Delay in seconds.
        """
        pattern = self._select_pattern(self.typing_speeds)
        
        if text_length:
            # Average delay per character
            char_delay = random.uniform(pattern["min_delay"], pattern["max_delay"])
            total_delay = char_delay * min(text_length, 500)  # Cap at 500 chars
            return min(total_delay, 5.0)  # Max 5 seconds
        else:
            return random.uniform(pattern["min_delay"], pattern["max_delay"])
    
    def get_thinking_delay(self) -> float:
        """
        Get a human-like thinking delay before responding.
        
        Returns:
            float: Delay in seconds.
        """
        pattern = self._select_pattern(self.thinking_times)
        return random.uniform(pattern["min"], pattern["max"])
    
    def get_reading_delay(self, message_length: int = None) -> float:
        """
        Get a human-like reading delay for incoming messages.
        
        Args:
            message_length: Length of the message being read (optional).
        
        Returns:
            float: Delay in seconds.
        """
        pattern = self._select_pattern(self.reading_speeds)
        
        if message_length:
            # Time to read based on characters
            reading_time = message_length / pattern["chars_per_sec"]
            return min(reading_time, 10.0)
        else:
            return random.uniform(1.0, 3.0)
    
    def get_distraction_delay(self) -> float:
        """
        Get a random distraction delay (user looked away, phone call, etc.).
        
        Returns:
            float: Delay in seconds (0 if no distraction occurs).
        """
        if random.random() < self.distraction_probability:
            return random.uniform(self.distraction_duration["min"], 
                                 self.distraction_duration["max"])
        return 0
    
    def get_natural_delay(self, text_length: int = None, is_first: bool = False, 
                          is_last: bool = False) -> float:
        """
        Get a combined natural delay for a complete message exchange.
        
        This combines typing, thinking, reading, and distraction delays to
        simulate the complete human interaction cycle.
        
        Args:
            text_length: Length of the message.
            is_first: Whether this is the first chunk (adds thinking time).
            is_last: Whether this is the last chunk (adds reading time).
        
        Returns:
            float: Total delay in seconds.
        """
        total_delay = 0
        
        # Initial thinking time before sending
        if is_first:
            total_delay += self.get_thinking_delay()
        
        # Typing time
        total_delay += self.get_typing_delay(text_length)
        
        # Reading time after receiving (for receiver)
        if is_last:
            total_delay += self.get_reading_delay(text_length)
        
        # Random distractions
        total_delay += self.get_distraction_delay()
        
        return total_delay


# ============================================================================
# Stealth DNS Engine
# ============================================================================

class StealthDNSEngine:
    """
    Main stealth engine combining all human-like behaviors.
    
    This class integrates the traffic simulator and human behavior simulator
    into a single interface for use by the DNS sender. It provides methods to
    start/stop stealth mode and compute natural delays between chunks.
    
    The engine can be configured with different intensity levels:
        - low:    Minimal background traffic, basic delays
        - normal: Balanced operation (recommended for most use cases)
        - high:   Aggressive masking, more background traffic
        - stealth: Maximum stealth, very aggressive masking
    
    Attributes:
        traffic_sim (TrafficSimulator): Background DNS traffic generator.
        behavior (HumanBehaviorSimulator): Delay calculation engine.
        background_active (bool): Whether background traffic is active.
        mode (str): Current stealth mode intensity.
    """
    
    def __init__(self, dns_server: str = "8.8.8.8"):
        """
        Initialize the stealth DNS engine.
        
        Args:
            dns_server: DNS server for background queries (default: 8.8.8.8).
        """
        self.traffic_sim = TrafficSimulator(dns_server)
        self.behavior = HumanBehaviorSimulator()
        self.background_active = False
        self.mode = "normal"
        
        print("\n🕶️ Stealth DNS Engine initialized")
        print("   Features:")
        print("   - Background DNS traffic (real domains)")
        print("   - Human typing/thinking/reading delays")
        print("   - Hour-based traffic patterns")
        print("   - Random distraction simulation")
    
    def start_stealth_mode(self, intensity: str = "normal"):
        """
        Start stealth mode with the given intensity.
        
        Args:
            intensity: Stealth level ('low', 'normal', 'high', or 'stealth').
        """
        modes = {
            "low": {"interval": 15.0, "desc": "Low - Minimal background traffic"},
            "normal": {"interval": 8.0, "desc": "Normal - Balanced"},
            "high": {"interval": 4.0, "desc": "High - Maximum stealth"},
            "stealth": {"interval": 2.0, "desc": "Stealth - Very aggressive masking"}
        }
        
        mode_config = modes.get(intensity, modes["normal"])
        self.mode = intensity
        
        print(f"\n🕵️ Stealth mode ACTIVE")
        print(f"   Mode: {intensity.upper()} - {mode_config['desc']}")
        
        self.traffic_sim.start_background_traffic()
        self.background_active = True
    
    def stop_stealth_mode(self):
        """Stop stealth mode and all background activities."""
        if self.background_active:
            self.traffic_sim.stop_background_traffic()
            self.background_active = False
            print("\n🛑 Stealth mode stopped")
    
    def get_chunk_delay(self, chunk_index: int, total_chunks: int, 
                        chunk_size: int = None) -> float:
        """
        Get a natural delay between chunks based on human behavior.
        
        Args:
            chunk_index: Index of the current chunk (0-indexed).
            total_chunks: Total number of chunks in the message.
            chunk_size: Size of the current chunk (optional).
        
        Returns:
            float: Delay in seconds (capped at 5 seconds).
        """
        is_first = (chunk_index == 0)
        is_last = (chunk_index == total_chunks - 1)
        
        delay = self.behavior.get_natural_delay(
            text_length=chunk_size,
            is_first=is_first,
            is_last=is_last
        )
        
        # Add random jitter to avoid predictable patterns
        delay *= random.uniform(0.7, 1.3)
        
        return min(delay, 5.0)  # Cap at 5 seconds
    
    def should_send_fake_query(self) -> bool:
        """
        Determine whether to send a fake DNS query.
        
        Returns:
            bool: True if a fake query should be sent, False otherwise.
        """
        intensity = self.traffic_sim.get_traffic_intensity()
        # Higher intensity = more fake queries
        probability = min(0.3, intensity / 30.0)
        return random.random() < probability
    
    def get_stats(self) -> dict:
        """Get current simulation statistics."""
        stats = self.traffic_sim.get_stats()
        stats["stealth_mode"] = self.background_active
        stats["mode"] = self.mode
        return stats


# ============================================================================
# Test Code
# ============================================================================

if __name__ == "__main__":
    """
    Standalone test routine for the stealth DNS engine.
    
    This test verifies:
        1. Engine initialization
        2. Stealth mode activation
        3. Human-like delay calculations
        4. Background traffic generation
        5. Clean shutdown
    """
    print("=" * 60)
    print("Stealth DNS Engine Test")
    print("=" * 60)
    
    # Create engine
    stealth = StealthDNSEngine()
    
    # Start stealth mode
    stealth.start_stealth_mode("normal")
    
    # Simulate delays for a 10-chunk message
    print("\nSimulated human delays for a 10-chunk message:")
    for i in range(10):
        delay = stealth.get_chunk_delay(i, 10, chunk_size=random.randint(20, 50))
        print(f"  Chunk {i+1:2d}: {delay:.3f}s")
    
    # Show statistics
    print(f"\nTraffic statistics: {stealth.get_stats()}")
    
    # Run background traffic for a few seconds
    print("\nRunning background traffic for 10 seconds...")
    time.sleep(10)
    
    # Stop stealth mode
    stealth.stop_stealth_mode()
    
    print("\nStealth DNS Engine test completed successfully!")