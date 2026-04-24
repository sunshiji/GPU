import os
from typing import List

VERSION = "1.0.0"
APP_NAME = "GPU Monitor"

HOST = os.getenv("GPU_MONITOR_HOST", "0.0.0.0")
PORT = int(os.getenv("GPU_MONITOR_PORT", 8000))

UPDATE_INTERVAL = float(os.getenv("GPU_MONITOR_UPDATE_INTERVAL", 1.0))
HISTORY_SIZE = int(os.getenv("GPU_MONITOR_HISTORY_SIZE", 300))

ALLOWED_ORIGINS: List[str] = [
    os.getenv("GPU_MONITOR_ALLOWED_ORIGIN", "*"),
]
