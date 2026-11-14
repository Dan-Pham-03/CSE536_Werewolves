"""
Werewolves Player Client
Individual player process that connects to the game server.
"""

import asyncio
import logging
import os
import random
import sys
from typing import Optional

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from comms import UDSClient, Message, MessageType


class WerewolvesPlayer:
    """Represents a single player in the game."""

    def __init__(self, player_id: str, socket_path: str, log_dir: str = "logs", interactive: bool = False):
        """
        Initialize the player.

        Args:
            player_id: Unique player identifier
            socket_path: Path to game server socket
            log_dir: Directory for logs
            interactive: Prompt for choices instead of selecting randomly
        """
        self.player_id = player_id
        self.socket_path = socket_path
        self.log_dir = log_dir
        self.interactive = interactive
        self.role: Optional[str] = None
        self.is_alive = True
        self.phase: Optional[str] = None
        self._pending_choice: Optional[tuple[str, list[str]]] = None
        self._shutdown_event = asyncio.Event()
        self.logger = self._setup_logger()

        # Create communications client
        self.client = UDSClient(
            socket_path=socket_path,
            client_id=player_id,
            log_file=os.path.join(log_dir, f"player_{player_id}.log")
        )
        self._original_client_disconnect = self.client.disconnect
        self.client.disconnect = self._disconnect_client_wrapper

        # Register message handlers
        self._register_handlers()

    def _setup_logger(self) -> logging.Logger:
        """Setup logging."""
        os.makedirs(self.log_dir, exist_ok=True)
        logger = logging.getLogger(f"Player-{self.player_id}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

        fh = logging.FileHandler(os.path.join(self.log_dir, f"player_{self.player_id}.log"))
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        if not self.interactive:
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            logger.addHandler(ch)

        return logger

    def _register_handlers(self):
        """Register message handlers."""
        self.client.register_handler(MessageType.ROLE_ASSIGNMENT.value, self._handle_role_assignment)
        self.client.register_handler(MessageType.PHASE_CHANGE.value, self._handle_phase_change)
        self.client.register_handler(MessageType.GAME_STATE.value, self._handle_game_state)
        self.client.register_handler(MessageType.NIGHT_ACTION.value, self._handle_night_action)
        self.client.register_handler(MessageType.SEER_RESULT.value, self._handle_seer_result)
        self.client.register_handler(MessageType.VOTE.value, self._handle_vote)
        self.client.register_handler(MessageType.ELIMINATE.value, self._handle_eliminate)
        self.client.register_handler(MessageType.CHAT.value, self._handle_chat)
        self.client.register_handler(MessageType.WIN.value, self._handle_win)

    async def _handle_role_assignment(self, message: Message):
        """Handle role assignment from server."""
        self.role = message.payload.get("role")
        num_players = message.payload.get("num_players")
        num_werewolves = message.payload.get("num_werewolves")

        self.logger.info(f"Role assigned: {self.role} ({num_players} players, {num_werewolves} werewolves)")
        print(f"\n[{self.player_id}] Your role: {self.role}")

    async def _handle_phase_change(self, message: Message):
        """Handle phase change notification."""
        phase = message.payload.get("phase")
        round_num = message.payload.get("round")

        self.logger.info(f"Phase changed to {phase} (Round {round_num})")
        if self.phase:
            print(f"\n--- {self.phase} phase ended ---")
        self.phase = phase
        self._pending_choice = None
        print(f"\n=== ROUND {round_num}: {phase} PHASE BEGINS ===")
        if self.interactive and self.is_alive:
            if phase in ("DAY", "VOTING"):
                print("Day discussion: type /chat followed by your message.")
            elif phase == "NIGHT" and self.role == "WEREWOLF":
                print("Werewolf discussion: type /chat followed by your message before choosing a target.")

    async def _handle_game_state(self, message: Message):
        """Handle game state broadcast."""
        state = message.payload

        self.logger.debug(f"Game state: {state}")
        print(f"\n[{self.player_id}] Alive players: {state.get('num_alive')}, Werewolves: {state.get('num_werewolves')}")

    async def _handle_night_action(self, message: Message):
        """Handle night action request."""
        action = message.payload.get("action")
        targets = message.payload.get("available_targets")

        if action not in ("investigate", "select_victim"):
            self.logger.warning("Rejected invalid night action request: %r", action)
            return

        self.logger.info(f"Night action requested: {action}")
        prompt = "Investigate" if action == "investigate" else "Select a target"
        print(f"\n[{self.player_id}] {prompt}: {targets}")

        if targets:
            if self.interactive:
                self._pending_choice = (action, targets)
                print("Enter a target ID.")
            else:
                await self._submit_choice(action, random.choice(targets))

    async def _handle_seer_result(self, message: Message):
        target = message.payload.get("target")
        result = "a WEREWOLF" if message.payload.get("is_werewolf") else "not a werewolf"
        print(f"\n[{self.player_id}] Seer result: {target} is {result}.")

    async def _handle_vote(self, message: Message):
        """Handle voting request."""
        targets = message.payload.get("available_targets")

        self.logger.info(f"Vote requested from targets: {targets}")
        print(f"\n[{self.player_id}] Cast your vote from: {targets}")

        if targets:
            if self.interactive:
                self._pending_choice = ("vote", targets)
                print("Enter a player ID to vote.")
            else:
                await self._submit_choice("vote", random.choice(targets))

    async def _submit_choice(self, action: str, target: str):
        if action == "vote":
            msg_type = MessageType.VOTE.value
            payload = {"vote_for": target}
            label = "Voted for"
        else:
            msg_type = MessageType.NIGHT_ACTION.value
            payload = (
                {"action": action, "target": target}
                if action == "investigate"
                else {"action": action, "victim": target}
            )
            label = "Target selected"
        await self.client.send_message(Message(
            msg_type=msg_type, sender=self.player_id, recipient="SERVER", payload=payload
        ))
        print(f"[{self.player_id}] {label}: {target}")

    async def _handle_input(self, line: str):
        line = line.strip()
        if not line:
            return
        if line == "/chat" or line.startswith("/chat "):
            text = line[5:].strip()
            allowed = self.is_alive and (
                self.phase in ("DAY", "VOTING")
                or (self.phase == "NIGHT" and self.role == "WEREWOLF")
            )
            if not text or len(text) > 500:
                print("Enter /chat followed by a message of 1-500 characters.")
            elif not allowed:
                print("Chat is not available to you in this phase.")
            else:
                await self.client.send_message(Message(
                    msg_type=MessageType.CHAT.value, sender=self.player_id,
                    recipient="SERVER", payload={"text": text},
                ))
        elif self._pending_choice:
            action, targets = self._pending_choice
            if line not in targets:
                print(f"Please enter one of: {', '.join(targets)}")
                return
            self._pending_choice = None
            await self._submit_choice(action, line)
        else:
            print("No choice is pending. Use /chat to send a message when discussion is open.")

    async def _handle_chat(self, message: Message):
        channel = message.payload.get("channel")
        print(f"\n[{channel} chat] {message.sender}: {message.payload.get('text')}")

    async def _read_input(self):
        """Read terminal lines without blocking the message receive loop."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        buffer = b""

        def on_input():
            try:
                data = os.read(sys.stdin.fileno(), 4096)
            except OSError as error:
                self.logger.error("Could not read terminal input: %s", error)
                data = b""
            queue.put_nowait(data if data else None)
            if not data:
                loop.remove_reader(sys.stdin.fileno())

        try:
            loop.add_reader(sys.stdin.fileno(), on_input)
        except (OSError, ValueError) as error:
            self.logger.error("Could not monitor terminal input: %s", error)
            print(f"Could not monitor terminal input: {error}")
            return
        try:
            while True:
                data = await queue.get()
                if data is None:
                    self.logger.warning("No terminal input available")
                    print("Terminal input closed; you can no longer chat or make choices.")
                    return
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        text = line.decode("utf-8")
                    except UnicodeDecodeError:
                        print("Input must be valid UTF-8.")
                        continue
                    await self._handle_input(text)
        finally:
            loop.remove_reader(sys.stdin.fileno())

    async def _handle_eliminate(self, message: Message):
        """Handle elimination notification."""
        eliminated = message.payload.get("eliminated")
        cause = message.payload.get("cause")
        if eliminated is None:
            print("\nNo player was executed by the vote.")
            return
        description = "executed by the vote" if cause == "vote" else "killed during the night"
        self.logger.info("Player %s was %s", eliminated, description)
        if eliminated == self.player_id:
            self.is_alive = False
            self._pending_choice = None
            print(f"\n[{self.player_id}] You were {description}. You can no longer vote or chat.")
        else:
            print(f"\n[{self.player_id}] Player {eliminated} was {description}.")

    async def _handle_win(self, message: Message):
        """Handle game end."""
        winner = message.payload.get("winner") or "unknown"
        self.logger.info(f"GAME OVER! {winner} WIN!")
        if self.phase:
            print(f"\n--- {self.phase} phase ended ---")
        print(f"\n[{self.player_id}] *** GAME OVER! {winner.upper()} WIN! ***")
        self._shutdown_event.set()

    async def _disconnect_client_wrapper(self):
        """Stop the player loop when the client disconnects."""
        self._shutdown_event.set()
        await self._original_client_disconnect()

    async def connect(self) -> bool:
        """Connect to the game server."""
        self.logger.info(f"Connecting to {self.socket_path}")
        return await self.client.connect(timeout=10.0)

    async def run(self):
        """Run the player until the game ends or the connection closes."""
        if not await self.connect():
            self.logger.error("Failed to connect to server")
            print(f"Failed to connect to server at {self.socket_path}.")
            return

        input_task = asyncio.create_task(self._read_input()) if self.interactive else None
        try:
            await self._shutdown_event.wait()
        except KeyboardInterrupt:
            self.logger.info("Player shutting down")
        finally:
            if input_task:
                input_task.cancel()
                try:
                    await input_task
                except asyncio.CancelledError:
                    pass
            await self.client.disconnect()


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Werewolves Player Client")
    parser.add_argument("player_id", help="Player ID")
    parser.add_argument("--socket", default="sockets/game_server.sock", help="Socket path")
    parser.add_argument("--log-dir", default="logs", help="Log directory")
    parser.add_argument("--interactive", action="store_true", help="Prompt for choices in this terminal")

    args = parser.parse_args()

    player = WerewolvesPlayer(
        player_id=args.player_id,
        socket_path=args.socket,
        log_dir=args.log_dir,
        interactive=args.interactive
    )

    try:
        await player.run()
    except KeyboardInterrupt:
        print(f"\nPlayer {args.player_id} shutting down...")


if __name__ == "__main__":
    asyncio.run(main())