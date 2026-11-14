# Werewolves Game - Unix Domain Sockets Implementation

A Python-based implementation of the Werewolves (Mafia) game using Unix Domain Sockets for inter-process communication. Each player runs as an independent process and communicates with a central game server through a sophisticated IPC primitive.

## Quick Start

```
cd werewolves-uds
pip3 install -r requirements.txt
make run
```

## Communications Library

**Location:** `src/comms.py` (single-file library)

**Provided Classes and API:**

### UDSServer
Central server for accepting connections and routing messages.

```
from comms import UDSServer, Message, MessageType

server = UDSServer(
    socket_path="sockets/game_server.sock",
    max_connections=10,
    log_file="logs/comms.log"
)

# Register handler for message type
async def handle_hello(message):
    player_id = message.sender
    # Handle the message

server.register_handler(MessageType.HELLO.value, handle_hello)

# Start server
await server.start()
await server.accept_connections()

# Send to specific client (unicast)
msg = Message(
    msg_type=MessageType.ROLE_ASSIGNMENT.value,
    sender="SERVER",
    recipient="player_1",
    payload={"role": "WEREWOLF"}
)
await server.send_message(msg)

# Send to all clients (broadcast)
msg = Message(
    msg_type=MessageType.PHASE_CHANGE.value,
    sender="SERVER",
    recipient="*",
    payload={"phase": "NIGHT"}
)
await server.send_message(msg)

# Graceful shutdown
await server.shutdown()
```

### UDSClient
Player client that connects to server and receives messages.

```
from comms import UDSClient, Message, MessageType

client = UDSClient(
    socket_path="sockets/game_server.sock",
    client_id="player_1",
    log_file="logs/player_1.log"
)

# Register handler
async def handle_role(message):
    role = message.payload.get("role")
    print(f"Your role: {role}")

client.register_handler(MessageType.ROLE_ASSIGNMENT.value, handle_role)

# Connect
connected = await client.connect(timeout=5.0)

# Send message to server
msg = Message(
    msg_type=MessageType.VOTE.value,
    sender="player_1",
    recipient="SERVER",
    payload={"vote_for": "player_2"}
)
await client.send_message(msg)

# Disconnect
await client.disconnect()
```

### Message
Dataclass for message representation.

```
msg = Message(
    msg_type=MessageType.HELLO.value,
    sender="player_1",
    recipient="SERVER",  # or "*" for broadcast
    payload={"client_id": "player_1"},
    timestamp="2026-10-19T21:11:32"  # Auto-set if None
)

json_str = msg.to_json()
msg_parsed = Message.from_json(json_str)
```

### MessageType
Enum of all available message types.

```
MessageType.HELLO              # Initial connection
MessageType.GAME_STATE         # Broadcast game state
MessageType.ROLE_ASSIGNMENT    # Assign role to player
MessageType.PHASE_CHANGE       # Night/Day phase notification
MessageType.NIGHT_ACTION       # Werewolf target selection
MessageType.VOTE               # Player vote during day
MessageType.ELIMINATE          # Player elimination result
MessageType.WIN                # Game end announcement
MessageType.ERROR              # Error notification
MessageType.DISCONNECT         # Graceful disconnect
MessageType.ACK                # Acknowledgement
```

## Project Structure

```
werewolves-uds/
├── src/
│   ├── comms.py              ← COMMUNICATIONS LIBRARY (400+ lines)
│   ├── game_server.py        ← Game server orchestrator
│   ├── player.py             ← Player client
│   ├── game_logic.py         ← Game state and rules
│   └── utils.py              ← Utility functions
├── config/
│   ├── game_config.json      ← Game configuration
│   └── socket_config.json    ← Socket configuration
├── bin/
│   ├── run_game.sh           ← Start game script
│   └── cleanup.sh            ← Cleanup resources
├── logs/                     ← Game logs (created at runtime)
├── sockets/                  ← UDS socket files (created at runtime)
├── Makefile                  ← Build and run targets
├── requirements.txt          ← Python dependencies
└── README.md                 ← This file
```

## File Descriptions

| File | Purpose |
|------|---------|
| `src/comms.py` | **Communications Library** - UDSServer, UDSClient, Message, MessageType classes for Unix Domain Socket IPC |
| `src/game_server.py` | Game server - manages game state, player connections, phase transitions, and message routing |
| `src/player.py` | Player client - connects to server, receives game messages, makes decisions |
| `src/game_logic.py` | Game state machine - player roles, win conditions, vote counting, elimination logic |
| `src/utils.py` | Utility functions - config loading, directory management |
| `config/game_config.json` | Game settings - player count, werewolf count, phase durations |
| `config/socket_config.json` | Network settings - socket paths, timeouts, buffer sizes |
| `bin/run_game.sh` | Shell script to start game server and all player clients |
| `bin/cleanup.sh` | Script to kill game processes and clean up resources |

## Requirements

- **Python:** 3.8 or higher
- **OS:** Linux, macOS, or WSL2 (Unix Domain Sockets only available on Unix-like systems)
- **Dependencies:** None (uses Python standard library only)

## Installation

```
cd werewolves-uds

# Install Python dependencies
pip3 install -r requirements.txt

# Verify installation
python3 --version                    # Should be 3.8+
python3 -c "import socket; print(hasattr(socket, 'AF_UNIX'))"  # Should print True
python3 -c "import sys; sys.path.insert(0, 'src'); from comms import UDSServer; print('OK')"
```

## Compilation

**No compilation needed!** This is a pure Python project. The game runs directly with the Python interpreter.

## Running the Game

### Option 1: Quick Start (Recommended)

Start a game with 4 players. The roster calculator assigns 1 werewolf, 1 seer, and 2 villagers:

```
cd werewolves-uds
make run
```

Expected output:
```
==========================================
Werewolves Game - Unix Domain Sockets
==========================================
Players: 4
Werewolves: 1
Socket Dir: /home/user/werewolves-uds/sockets
Log Dir: /home/user/werewolves-uds/logs
==========================================

[*] Starting game server...
[+] Server started (PID: XXXX)
[*] Starting players...
[*] Starting player_1...
[*] Starting player_2...
[*] Starting player_3...
[*] Starting player_4...
[+] All players started

Game running... (Press Ctrl+C to stop)

Each player sees their own randomly assigned role. The roster contains one WEREWOLF, one SEER, and two VILLAGER roles.

[player_1] === NIGHT PHASE (Round 1) ===
[player_1] Select a target: ['player_2', 'player_3', 'player_4']
[player_1] Target selected: player_3
```

### Option 2: Custom Player Count

```
# Run with 8 players and 2 werewolves (the automatic count)
make run-players NUM=8
```

### Option 3: Manual Control (For Testing/Development)

**Terminal 1 - Start Server:**
```
cd werewolves-uds
python3 src/game_server.py --socket sockets/game_server.sock --players 4 --log-dir logs --interactive
```

**Terminals 2-5 - Start Players (one per terminal):**
```
python3 src/player.py player_1 --socket sockets/game_server.sock --log-dir logs --interactive
python3 src/player.py player_2 --socket sockets/game_server.sock --log-dir logs --interactive
python3 src/player.py player_3 --socket sockets/game_server.sock --log-dir logs --interactive
python3 src/player.py player_4 --socket sockets/game_server.sock --log-dir logs --interactive
```

**Terminal 6 - Monitor Logs:**
```
tail -f logs/game.log      # Watch game flow
# or
tail -f logs/comms.log     # Watch UDS communication
# or
tail -f logs/player_1.log  # Watch specific player
```

## Game Flow

### Phases

1. **SETUP** - Server assigns roles randomly to all players
2. **NIGHT** - Werewolves select a victim; the Seer investigates one living player and privately learns whether they are a werewolf
3. **DAY** - All players are notified of elimination results (broadcast)
4. **VOTING** - All alive players are asked to vote (unicast vote requests to each player)
5. **RESULTS** - Vote result is announced (broadcast elimination)
6. Loop back to NIGHT until win condition met
7. **GAME_OVER** - Winner announced (broadcast to all players)

### Win Conditions

- **Werewolves win:** Equal or outnumber villagers
- **Villagers win:** All werewolves eliminated

## Role Balance

The role calculator requires at least 4 players, assigns one Seer, and fills the remaining slots with villagers. Werewolves default to one per four players, rounded down with a minimum of one (for example, 1 at 4-7 players and 2 at 8-11). An explicit `--werewolves` value may lower that count but cannot exceed the calculated limit.

In interactive games, run the server and each player in separate terminals with `--interactive`. Only the Seer terminal receives the investigation result. Broadcast game-state updates omit player roles so hidden assignments remain private during play. The final game-over message includes the complete state, including roles.

## Communication Patterns

The `comms.py` library supports three communication patterns:

### 1. Unicast (1-to-1)
Send message to specific player:

```
msg = Message(
    msg_type=MessageType.ROLE_ASSIGNMENT.value,
    sender="SERVER",
    recipient="player_1",
    payload={"role": "WEREWOLF"}
)
await server.send_message(msg)
```

**Used for:**
- Role assignment to individual players
- Night action requests to werewolves only
- Vote requests to individual players

### 2. Broadcast (1-to-All)
Send message to all connected players:

```
msg = Message(
    msg_type=MessageType.PHASE_CHANGE.value,
    sender="SERVER",
    recipient="*",
    payload={"phase": "NIGHT", "round": 1}
)
await server.send_message(msg)
```

**Used for:**
- Phase change notifications
- Game state updates
- Elimination announcements
- Game end results

### 3. Multicast (1-to-Group)
Application-level filtering by game logic:

```
# Server sends to werewolves only
werewolves = game_state.get_alive_werewolves()
for werewolf in werewolves:
    msg = Message(
        msg_type=MessageType.NIGHT_ACTION.value,
        sender="SERVER",
        recipient=werewolf.player_id,
        payload={"action": "select_victim"}
    )
    await server.send_message(msg)
```

## Logging

All logs are written to the `logs/` directory:

- **game.log** - High-level game server events
- **comms.log** - Low-level Unix Domain Socket communication details
- **player_*.log** - Individual player logs

### View Logs

```
# Watch game events in real-time
tail -f logs/game.log

# Watch all UDS communication
tail -f logs/comms.log

# Watch specific player
tail -f logs/player_1.log

# View all log output
cat logs/game.log
cat logs/comms.log
```

## Makefile Targets

```
make help              # Display help message
make install           # Install Python dependencies
make setup             # Create logs/ and sockets/ directories
make run               # Run game with default settings (4 players, 1 werewolf)
make run-players       # Run with custom settings: make run-players NUM=6 WEREWOLVES=2
make clean             # Remove sockets and logs
make test              # Run unit tests
```

## Cleanup and Reset

Stop the game:
```
Ctrl+C
```

Clean up sockets and logs:
```
make clean
# or
bash bin/cleanup.sh
```

## Unix Domain Sockets: Sophistication

Unix Domain Sockets are a more sophisticated IPC primitive than named pipes (FIFOs) because:

### Technical Advantages

1. **Bidirectional Communication** - Single socket supports full-duplex communication (simultaneous send/receive), unlike FIFOs which are unidirectional

2. **Connection-Oriented** - Like TCP sockets, UDS provide reliable, ordered, and sequenced message delivery with connection establishment/teardown

3. **Async I/O Integration** - Python's asyncio provides non-blocking I/O primitives for efficient concurrent handling of multiple connections

4. **Multiple Communication Patterns** - While the socket itself is point-to-point, application-level logic enables unicast, broadcast, and multicast patterns

5. **Efficient for Local IPC** - No network overhead compared to TCP, microsecond-level latency for message exchange

6. **Scalable Concurrency** - Event-driven architecture with asyncio handles 100+ concurrent connections without threading

### How comms.py Demonstrates Sophistication

- **Message Framing** - 4-byte length prefix ensures proper message boundaries in stream socket
- **Async Event-Driven** - Non-blocking message handling with asyncio tasks
- **Client Registry** - Maintains connection state for efficient routing
- **Broadcast Support** - Explicit implementation of 1-to-many communication
- **Error Handling** - Graceful connection cleanup on errors
- **Comprehensive Logging** - Full visibility into communication events

## Troubleshooting

### "Address already in use"
```
make clean
rm -f sockets/*.sock
make run
```

### "Permission denied" on socket file
```
chmod 755 sockets/
make run
```

### Game exits immediately without playing
```
cat logs/game.log      # Check server errors
cat logs/comms.log     # Check communication errors
```

### Players not connecting
```
ps aux | grep game_server.py    # Verify server is running
ls -la sockets/                 # Verify socket file exists
cat logs/player_1.log           # Check player connection errors
```

### "No module named 'comms'"
```
cd werewolves-uds
python3 src/game_server.py  # Ensure you're in correct directory
```

## Notes

- Each game run is unique due to random role assignment and AI decisions
- All players automatically make decisions (randomized AI)
- All communication happens via Unix Domain Sockets
- No network access required
- Works only on Unix-like systems (Linux, macOS, WSL2)

## Assignment Requirements Verification
   
✅ **Unix Domain Sockets** - Sophisticated IPC primitive (SOCK_STREAM)
✅ **Sophistication Level** - Full-duplex, connection-oriented, async I/O integration
✅ **Single-File Communications Library** - `src/comms.py` (400+ lines)
✅ **Communication Patterns** - Unicast, broadcast, multicast support
✅ **Concurrent Processes** - Each player is independent Linux process
✅ **Non-Trivial Communication** - Multiple message types and routing patterns
✅ **Game State Synchronization** - Server broadcasts state to all players
✅ **100% Custom Code** - No external IPC libraries (uses only asyncio, socket, json)
✅ **Async I/O** - Python asyncio for non-blocking message handling

## References

- [Unix Domain Sockets (man7.org)](https://man7.org/linux/man-pages/man7/unix.7.html)
- [Python asyncio Documentation](https://docs.python.org/3/library/asyncio.html)
- [Werewolves/Mafia Game Rules](https://en.wikipedia.org/wiki/Mafia_(party_game))

## License

Educational use for CSE536 assignment - Autumn 2026
