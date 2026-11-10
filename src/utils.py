"""
Utility functions for the Werewolves game.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any


def load_config(config_file: str) -> Dict[str, Any]:
    """Load configuration from JSON file."""
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file, 'r') as f:
        return json.load(f)


def save_config(config: Dict[str, Any], config_file: str):
    """Save configuration to JSON file."""
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)


def ensure_directories(directories: list):
    """Ensure directories exist."""
    for directory in directories:
        os.makedirs(directory, exist_ok=True)


def cleanup_sockets(socket_dir: str):
    """Clean up leftover socket files."""
    if os.path.exists(socket_dir):
        for file in os.listdir(socket_dir):
            file_path = os.path.join(socket_dir, file)
            if file.endswith('.sock'):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Warning: Could not remove {file_path}: {e}")