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
        self.logger = self._setup_logger()

        # Create communications client
        self.client = UDSClient(
            socket_path=socket_path,
            client_id=player_id,
            log_file=os.path.join(log_dir, f"player_{player_id}.log")
        )

        # Register message handlers
        self._register_handlers()

    def _setup_logger(self) -> logging.Logger:
        """Setup logging."""
        os.makedirs(self.log_dir, exist_ok=True)
        logger = logging.getLogger(f"Player-{self.player_id}")
        logger.setLevel(logging.DEBUG)

        fh = logging.FileHandler(os.path.join(self.log_dir, f"player_{self.player_id}.log"))
        ch = logging.StreamHandler()

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        logger.addHandler(fh)
        logger.addHandler(ch)

        return logger

    def _register_handlers(self):
        """Register message handlers."""
        self.client.register_handler(MessageType.ROLE_ASSIGNMENT.value, self._handle_role_assignment)
        self.client.register_handler(MessageType.PHASE_CHANGE.value, self._handle_phase_change)
        self.client.register_handler(MessageType.GAME_STATE.value, self._handle_game_state)
        self.client.register_handler(MessageType.NIGHT_ACTION.value, self._handle_night_action)
        self.client.register_handler(MessageType.VOTE.value, self._handle_vote)
        self.client.register_handler(MessageType.ELIMINATE.value, self._handle_eliminate)
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
        print(f"\n[{self.player_id}] === {phase} PHASE (Round {round_num}) ===")

    async def _handle_game_state(self, message: Message):
        """Handle game state broadcast."""
        state = message.payload

        self.logger.debug(f"Game state: {state}")
        print(f"\n[{self.player_id}] Alive players: {state.get('num_alive')}, Werewolves: {state.get('num_werewolves')}")

    async def _handle_night_action(self, message: Message):
        """Handle night action request."""
        action = message.payload.get("action")
        targets = message.payload.get("available_targets")

        self.logger.info(f"Night action requested: {action}")
        print(f"\n[{self.player_id}] Select a target: {targets}")

        if targets:
            target = await self._choose_target("Target", targets)
            if target is None:
                return
            self.logger.info(f"Selected target: {target}")

            # Send action
            action_msg = Message(
                msg_type=MessageType.NIGHT_ACTION.value,
                sender=self.player_id,
                recipient="SERVER",
                payload={"victim": target}
            )
            await self.client.send_message(action_msg)
            print(f"[{self.player_id}] Target selected: {target}")

    async def _handle_vote(self, message: Message):
        """Handle voting request."""
        action = message.payload.get("action")
        targets = message.payload.get("available_targets")

        self.logger.info(f"Vote requested from targets: {targets}")
        print(f"\n[{self.player_id}] Cast your vote from: {targets}")

        if targets:
            vote_for = await self._choose_target("Vote", targets)
            if vote_for is None:
                return
            self.logger.info(f"Voting for: {vote_for}")

            # Send vote
            vote_msg = Message(
                msg_type=MessageType.VOTE.value,
                sender=self.player_id,
                recipient="SERVER",
                payload={"vote_for": vote_for}
            )
            await self.client.send_message(vote_msg)
            print(f"[{self.player_id}] Voted for: {vote_for}")

    async def _choose_target(self, prompt: str, targets: list) -> Optional[str]:
        if not self.interactive:
            return random.choice(targets)

        loop = asyncio.get_running_loop()
        while True:
            try:
                target = await loop.run_in_executor(
                    None,
                    input,
                    f"[{self.player_id}] {prompt} ({', '.join(targets)}): "
                )
            except EOFError:
                self.logger.warning("No terminal input available for choice")
                return None

            if target in targets:
                return target
            print(f"Please enter one of: {', '.join(targets)}")

    async def _handle_eliminate(self, message: Message):
        """Handle elimination notification."""
        eliminated = message.payload.get("eliminated")
        self.logger.info(f"Player {eliminated} has been eliminated")
        print(f"\n[{self.player_id}] Player {eliminated} has been eliminated!")

    async def _handle_win(self, message: Message):
        """Handle game end."""
        winner = message.payload.get("winner")
        self.logger.info(f"GAME OVER! {winner} WIN!")
        print(f"\n[{self.player_id}] *** GAME OVER! {winner.upper()} WIN! ***")

    async def connect(self) -> bool:
        """Connect to the game server."""
        self.logger.info(f"Connecting to {self.socket_path}")
        return await self.client.connect(timeout=10.0)

    async def run(self):
        """Run the player."""
        if not await self.connect():
            self.logger.error("Failed to connect to server")
            return

        # Keep running until game ends
        try:
            await asyncio.sleep(float('inf'))
        except KeyboardInterrupt:
            self.logger.info("Player shutting down")
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