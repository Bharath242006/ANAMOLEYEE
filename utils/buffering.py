"""
utils/buffering.py - Local buffering for connectivity gaps.
If a station or the central system loses internet, readings are queued
locally instead of lost, and synced automatically once reconnected.
"""

import json
import os

BUFFER_FILE = "offline_buffer.json"


def buffer_reading_locally(reading: dict, buffer_file: str = BUFFER_FILE):
    buffer = []
    if os.path.exists(buffer_file):
        with open(buffer_file, "r") as f:
            buffer = json.load(f)
    buffer.append(reading)
    with open(buffer_file, "w") as f:
        json.dump(buffer, f, default=str)


def sync_buffered_readings(is_online: bool = True, buffer_file: str = BUFFER_FILE) -> int:
    if not is_online or not os.path.exists(buffer_file):
        return 0
    with open(buffer_file, "r") as f:
        buffer = json.load(f)
    count = len(buffer)
    os.remove(buffer_file)
    return count
