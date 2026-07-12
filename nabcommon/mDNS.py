import os
from typing import Optional


def get_pi_serial() -> Optional[str]:
    """Read Pi serial number from /proc/cpuinfo or device tree."""
    # Try /proc/cpuinfo first (works on older Pi OS)
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    return line.split(":")[1].strip()
    except FileNotFoundError:
        pass
    
    # Try device tree (works on newer Pi OS)
    try:
        with open("/sys/firmware/devicetree/base/serial-number", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        pass
    
    return None


def get_mdns_hostname(prefix: str = "nabaztag") -> Optional[str]:
    """Get mDNS hostname in format prefix-serial.local."""
    serial = get_pi_serial()
    if serial:
        return f"{prefix}-{serial}.local"
    return None


def get_tts_addr(default: str = "pi4.local:8765") -> str:
    """Get TTS address with mDNS auto-discovery and env override.
    
    Priority:
    1. TTS_ADDR environment variable
    2. mDNS auto-discovery (nabaztag-<serial>.local:8765)
    3. Provided default fallback
    """
    # Check env override first
    env_addr = os.environ.get("TTS_ADDR")
    if env_addr:
        return env_addr
    
    # Try mDNS auto-discovery
    mdns_host = get_mdns_hostname()
    if mdns_host:
        return f"{mdns_host}:8765"
    
    # Fallback to default
    return default
