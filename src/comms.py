"""
Unix Domain Socket Communications Library
A single-file library for inter-process communication using Unix domain sockets.
Provides both synchronous and asynchronous message passing with broadcast support.

This library handles:
- Server socket creation and listening
- Client connection management
- Async message sending/receiving
- Broadcast and multicast communication patterns
- Connection lifecycle management
"""

import asyncio
import json
import logging
import os
import socket
import sys
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
from datetime import datetime


class MessageType(Enum):
    """Message types for game communication."""
    HELLO = "HELLO"                    # Initial connection
    GAME_STATE = "GAME_STATE"          # Broadcast game state update
    ACTION = "ACTION"                  # Player action (vote, etc.)
    PHASE_CHANGE = "PHASE_CHANGE"      # Night/Day phase change
    ROLE_ASSIGNMENT = "ROLE_ASSIGNMENT" # Assign role to player
    NIGHT_ACTION = "NIGHT_ACTION"      # Werewolf/special role action
    VOTE = "VOTE"                      # Player vote during day
    ELIMINATE = "ELIMINATE"            # Player eliminated result
    WIN = "WIN"                        # Game end message
    ERROR = "ERROR"                    # Error notification
    DISCONNECT = "DISCONNECT"          # Graceful disconnect
    ACK = "ACK"                        # Acknowledgement


@dataclass
class Message:
    """Represents a single message in the system."""
    msg_type: str
    sender: str
    recipient: str  # "*" for broadcast, player_id for unicast
    payload: Dict[str, Any]
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def to_json(self) -> str:
        """Convert message to JSON string."""
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(json_str: str) -> 'Message':
        """Create message from JSON string."""
        data = json.loads(json_str)
        return Message(**data)


class UDSServer:
    """Unix Domain Socket Server for handling multiple client connections."""

    def __init__(self, socket_path: str, max_connections: int = 10, log_file: Optional[str] = None):
        """
        Initialize the UDS server.

        Args:
            socket_path: Path to the Unix domain socket
            max_connections: Maximum pending connections
            log_file: Optional log file path for communications
        """
        self.socket_path = socket_path
        self.max_connections = max_connections
        self.server_socket: Optional[socket.socket] = None
        self.clients: Dict[str, asyncio.StreamWriter] = {}
        self.message_handlers: Dict[str, Callable] = {}
        self.logger = self._setup_logger(log_file)

    def _setup_logger(self, log_file: Optional[str]) -> logging.Logger:
        """Setup logging for communications."""
        logger = logging.getLogger("UDSComms")
        logger.setLevel(logging.DEBUG)

        if log_file:
            handler = logging.FileHandler(log_file)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    async def start(self):
        """Start the UDS server."""
        # Remove existing socket file
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        # Create socket directory if needed
        socket_dir = os.path.dirname(self.socket_path)
        if socket_dir and not os.path.exists(socket_dir):
            os.makedirs(socket_dir, mode=0o755)

        # Create Unix domain socket
        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(self.socket_path)
        self.server_socket.listen(self.max_connections)
        self.server_socket.setblocking(False)

        self.logger.info(f"Server started on {self.socket_path}")

    async def accept_connections(self):
        """Accept incoming client connections."""
        loop = asyncio.get_event_loop()

        while True:
            try:
                client_socket, _ = await loop.sock_accept(self.server_socket)
                client_socket.setblocking(False)
                asyncio.create_task(self._handle_client(client_socket))
            except Exception as e:
                self.logger.error(f"Error accepting connection: {e}")
                await asyncio.sleep(0.1)

    async def _handle_client(self, client_socket: socket.socket):
        """Handle a single client connection."""
        client_id = None
        try:
            # Create reader/writer from raw socket
            reader, writer = await asyncio.open_connection(sock=client_socket)

            while True:
                # Read message length (4 bytes)
                length_data = await reader.readexactly(4)
                if not length_data:
                    break

                msg_length = int.from_bytes(length_data, byteorder='big')

                # Read message data
                data = await reader.readexactly(msg_length)
                message_str = data.decode('utf-8')
                message = Message.from_json(message_str)

                # Store client ID from first HELLO message
                if message.msg_type == MessageType.HELLO.value and client_id is None:
                    client_id = message.sender
                    self.clients[client_id] = writer
                    self.logger.info(f"Client connected: {client_id}")

                # Call registered handler
                if message.msg_type in self.message_handlers:
                    await self.message_handlers[message.msg_type](message)

        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            self.logger.error(f"Error handling client {client_id}: {e}")
        finally:
            if client_id and client_id in self.clients:
                del self.clients[client_id]
                self.logger.info(f"Client disconnected: {client_id}")
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass

    def register_handler(self, msg_type: str, handler: Callable):
        """Register a handler for a specific message type."""
        self.message_handlers[msg_type] = handler

    async def send_message(self, message: Message):
        """Send a message to a specific client or broadcast."""
        msg_json = message.to_json()
        msg_bytes = msg_json.encode('utf-8')
        msg_length = len(msg_bytes).to_bytes(4, byteorder='big')

        if message.recipient == "*":
            # Broadcast to all clients
            await self.broadcast(msg_length + msg_bytes)
        else:
            # Send to specific client
            if message.recipient in self.clients:
                writer = self.clients[message.recipient]
                try:
                    writer.write(msg_length + msg_bytes)
                    await writer.drain()
                    self.logger.debug(f"Message sent to {message.recipient}: {message.msg_type}")
                except Exception as e:
                    self.logger.error(f"Error sending message to {message.recipient}: {e}")

    async def broadcast(self, data: bytes):
        """Broadcast data to all connected clients."""
        disconnected = []
        for client_id, writer in self.clients.items():
            try:
                writer.write(data)
                await writer.drain()
            except Exception as e:
                self.logger.error(f"Error broadcasting to {client_id}: {e}")
                disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            if client_id in self.clients:
                del self.clients[client_id]

    async def shutdown(self):
        """Shutdown the server gracefully."""
        self.logger.info("Shutting down server...")
        # Create a copy of the clients dict to avoid "dictionary changed size during iteration"
        clients_copy = list(self.clients.values())
        for writer in clients_copy:
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass

        if self.server_socket:
            self.server_socket.close()

        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)


class UDSClient:
    """Unix Domain Socket Client for connecting to server."""

    def __init__(self, socket_path: str, client_id: str, log_file: Optional[str] = None):
        """
        Initialize the UDS client.

        Args:
            socket_path: Path to the Unix domain socket
            client_id: Unique identifier for this client
            log_file: Optional log file path for communications
        """
        self.socket_path = socket_path
        self.client_id = client_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.message_handlers: Dict[str, Callable] = {}
        self.logger = self._setup_logger(log_file)

    def _setup_logger(self, log_file: Optional[str]) -> logging.Logger:
        """Setup logging for communications."""
        logger = logging.getLogger(f"UDSClient-{self.client_id}")
        logger.setLevel(logging.DEBUG)

        if log_file:
            handler = logging.FileHandler(log_file)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    async def connect(self, timeout: float = 5.0) -> bool:
        """
        Connect to the server.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connected, False otherwise
        """
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path),
                timeout=timeout
            )
            self.logger.info(f"Connected to server at {self.socket_path}")

            # Send HELLO message
            hello_msg = Message(
                msg_type=MessageType.HELLO.value,
                sender=self.client_id,
                recipient="SERVER",
                payload={"client_id": self.client_id}
            )
            await self.send_message(hello_msg)

            # Start receiving messages
            asyncio.create_task(self._receive_loop())
            return True

        except asyncio.TimeoutError:
            self.logger.error(f"Connection timeout to {self.socket_path}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            return False

    async def send_message(self, message: Message):
        """Send a message to the server."""
        if not self.writer:
            self.logger.error("Not connected to server")
            return

        try:
            msg_json = message.to_json()
            msg_bytes = msg_json.encode('utf-8')
            msg_length = len(msg_bytes).to_bytes(4, byteorder='big')

            self.writer.write(msg_length + msg_bytes)
            await self.writer.drain()
            self.logger.debug(f"Message sent: {message.msg_type}")

        except Exception as e:
            self.logger.error(f"Error sending message: {e}")

    async def _receive_loop(self):
        """Listen for incoming messages from server."""
        try:
            while True:
                # Read message length (4 bytes)
                length_data = await self.reader.readexactly(4)
                if not length_data:
                    break

                msg_length = int.from_bytes(length_data, byteorder='big')

                # Read message data
                data = await self.reader.readexactly(msg_length)
                message_str = data.decode('utf-8')
                message = Message.from_json(message_str)

                self.logger.debug(f"Message received: {message.msg_type} from {message.sender}")

                # Call registered handler
                if message.msg_type in self.message_handlers:
                    await self.message_handlers[message.msg_type](message)

        except asyncio.IncompleteReadError:
            self.logger.info("Server closed connection")
        except Exception as e:
            self.logger.error(f"Error in receive loop: {e}")
        finally:
            await self.disconnect()

    def register_handler(self, msg_type: str, handler: Callable):
        """Register a handler for a specific message type."""
        self.message_handlers[msg_type] = handler

    async def disconnect(self):
        """Disconnect from the server."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except:
                pass
            self.logger.info("Disconnected from server")