#!/bin/bash
# Run the Werewolves game

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOCKET_DIR="$PROJECT_ROOT/sockets"
LOG_DIR="$PROJECT_ROOT/logs"
NUM_PLAYERS=${1:-4}
NUM_WEREWOLVES=${2:-}

# Create directories
mkdir -p "$SOCKET_DIR" "$LOG_DIR"

# Clean up old sockets
rm -f "$SOCKET_DIR"/*.sock

echo "=========================================="
echo "Werewolves Game - Unix Domain Sockets"
echo "=========================================="
echo "Players: $NUM_PLAYERS"
echo "Werewolves: ${NUM_WEREWOLVES:-auto}"
echo "Socket Dir: $SOCKET_DIR"
echo "Log Dir: $LOG_DIR"
echo "=========================================="
echo ""

# Start game server
echo "[*] Starting game server..."
cd "$PROJECT_ROOT"
SERVER_ARGS=(
    --socket "$SOCKET_DIR/game_server.sock"
    --players "$NUM_PLAYERS"
    --log-dir "$LOG_DIR"
)
if [[ -n "$NUM_WEREWOLVES" ]]; then
    SERVER_ARGS+=(--werewolves "$NUM_WEREWOLVES")
fi
python3 src/game_server.py "${SERVER_ARGS[@]}" &

SERVER_PID=$!
echo "[+] Server started (PID: $SERVER_PID)"

# Wait for server to start
sleep 1

# Start player clients
echo "[*] Starting players..."
PLAYER_PIDS=()
for ((i=1; i<=NUM_PLAYERS; i++)); do
    PLAYER_ID="player_$i"
    echo "[*] Starting $PLAYER_ID..."
    python3 src/player.py "$PLAYER_ID" \
        --socket "$SOCKET_DIR/game_server.sock" \
        --log-dir "$LOG_DIR" &
    PLAYER_PIDS+=($!)
done

echo "[+] All players started"
echo ""
echo "Game running... (Press Ctrl+C to stop)"
echo ""

# Wait for all processes
wait $SERVER_PID 2>/dev/null || true

# Cleanup
echo ""
echo "[*] Cleaning up..."
for pid in "${PLAYER_PIDS[@]}"; do
    kill $pid 2>/dev/null || true
done

rm -f "$SOCKET_DIR"/*.sock
echo "[+] Cleanup complete"
