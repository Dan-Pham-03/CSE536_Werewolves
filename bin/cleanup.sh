#!/bin/bash
# Clean up game resources

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOCKET_DIR="$PROJECT_ROOT/sockets"
LOG_DIR="$PROJECT_ROOT/logs"

echo "Cleaning up Werewolves game..."

# Kill any running processes
pkill -f "python3 src/game_server.py" || true
pkill -f "python3 src/player.py" || true

# Remove sockets
rm -f "$SOCKET_DIR"/*.sock
echo "Removed sockets"

# Optionally archive logs
if [ -d "$LOG_DIR" ]; then
    echo "Logs are in $LOG_DIR"
fi

echo "Cleanup complete"
