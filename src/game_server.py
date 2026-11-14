"""
Werewolves Game Server
Central coordinator managing game flow, player connections, and state synchronization.
"""

import asyncio
import logging
import os
import sys
from typing import Optional

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from comms import UDSServer, Message, MessageType
from game_logic import GameState, GamePhase, PlayerRole, calculate_role_counts


class WerewolvesGameServer:
    """Main game server orchestrating the Werewolves game."""

    def __init__(self, socket_path: str, num_players: int = 4, num_werewolves: Optional[int] = None, log_dir: str = "logs", interactive: bool = False):
        """
        Initialize the game server.

        Args:
            socket_path: Path to the Unix domain socket
            num_players: Number of players expected
            num_werewolves: Number of werewolves
            log_dir: Directory for logs
            interactive: Allow discussion and wait for terminal choices
        """
        self.socket_path = socket_path
        self.num_players = num_players
        role_counts = calculate_role_counts(num_players, num_werewolves)
        self.num_werewolves = role_counts.werewolves
        self.interactive = interactive
        self.action_timeout = 120
        self.discussion_seconds = 30
        self.game_state = GameState(num_werewolves=self.num_werewolves)
        self.log_dir = log_dir
        self._expected_night_actions = set()
        self._received_night_actions = set()
        self._night_actions_complete = asyncio.Event()
        self._expected_votes = set()
        self._received_votes = set()
        self._votes_complete = asyncio.Event()

        # Setup logging
        os.makedirs(log_dir, exist_ok=True)
        self.logger = self._setup_logger()

        # Create communications server
        self.comm_server = UDSServer(
            socket_path=socket_path,
            max_connections=num_players + 1,
            log_file=os.path.join(log_dir, "comms.log")
        )

        # Register message handlers
        self._register_handlers()

    def _setup_logger(self) -> logging.Logger:
        """Setup logging for the server."""
        logger = logging.getLogger("GameServer")
        logger.setLevel(logging.DEBUG)

        # File handler
        fh = logging.FileHandler(os.path.join(self.log_dir, "game.log"))
        fh.setLevel(logging.DEBUG)

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        # Formatter
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
        self.comm_server.register_handler(MessageType.HELLO.value, self._handle_hello)
        self.comm_server.register_handler(MessageType.VOTE.value, self._handle_vote)
        self.comm_server.register_handler(MessageType.NIGHT_ACTION.value, self._handle_night_action)

    async def _handle_hello(self, message: Message):
        """Handle player connection."""
        player_id = message.sender
        self.logger.info(f"Player {player_id} connected")

        # Add player to game
        self.game_state.add_player(player_id)

        # Check if all players have joined
        if len(self.game_state.players) == self.num_players:
            self.logger.info("All players connected, starting game")
            await self.start_game()

    async def _handle_vote(self, message: Message):
        """Handle player vote during day phase."""
        voter_id = message.sender
        votee_id = message.payload.get("vote_for")

        voter = self.game_state.players.get(voter_id)
        votee = self.game_state.players.get(votee_id) if isinstance(votee_id, str) else None
        if (
            self.game_state.phase != GamePhase.VOTING
            or not voter
            or not voter.is_alive
            or voter_id not in self._expected_votes
            or voter_id in self._received_votes
            or not isinstance(votee_id, str)
            or not votee
            or not votee.is_alive
            or votee_id == voter_id
        ):
            self.logger.warning("Rejected invalid vote from %s for %r", voter_id, votee_id)
            return

        self.logger.debug(f"Player {voter_id} votes for {votee_id}")
        self.game_state.record_vote(voter_id, votee_id)
        self._received_votes.add(voter_id)
        if self.interactive and voter_id in self._expected_votes:
            if self._expected_votes.issubset(self._received_votes):
                self._votes_complete.set()

    async def _handle_night_action(self, message: Message):
        """Handle a Werewolf attack or a Seer investigation."""
        player = self.game_state.players.get(message.sender)
        if (
            not player
            or not player.is_alive
            or self.game_state.phase != GamePhase.NIGHT
            or message.sender not in self._expected_night_actions
            or message.sender in self._received_night_actions
        ):
            return

        if player.role == PlayerRole.SEER and message.payload.get("action") == "investigate":
            target_id = message.payload.get("target")
            if not isinstance(target_id, str):
                self.logger.warning("Rejected invalid Seer target from %s", player.player_id)
                return
            target = self.game_state.players.get(target_id)
            if not target or not target.is_alive or target_id == player.player_id:
                self.logger.warning("Rejected invalid Seer target from %s", player.player_id)
                return

            result = Message(
                msg_type=MessageType.SEER_RESULT.value,
                sender="SERVER",
                recipient=player.player_id,
                payload={"target": target_id, "is_werewolf": target.role == PlayerRole.WEREWOLF}
            )
            await self.comm_server.send_message(result)
            self.logger.info(f"Seer {player.player_id} investigated a player")
        elif (
            player.role == PlayerRole.WEREWOLF
            and message.payload.get("action") == "select_victim"
        ):
            victim_id = message.payload.get("victim")
            if not isinstance(victim_id, str):
                self.logger.warning("Rejected invalid Werewolf target from %s", player.player_id)
                return
            victim = self.game_state.players.get(victim_id)
            if not victim or not victim.is_alive or victim.role == PlayerRole.WEREWOLF:
                self.logger.warning("Rejected invalid Werewolf target from %s", player.player_id)
                return

            self.logger.debug(f"Werewolf {player.player_id} targets {victim_id} for elimination")
            self.game_state.record_night_action(player.player_id, victim_id)
        else:
            return

        self._received_night_actions.add(player.player_id)
        if self._expected_night_actions.issubset(self._received_night_actions):
            self._night_actions_complete.set()

    async def start_game(self):
        """Start the game."""
        self.game_state.phase = GamePhase.SETUP
        self.logger.info("Assigning roles...")

        # Assign roles
        self.game_state.assign_roles()

        # Notify players of their roles
        for player_id, player in self.game_state.players.items():
            if player.role is None:
                raise RuntimeError(f"Role assignment missing for player {player_id}")
            role_msg = Message(
                msg_type=MessageType.ROLE_ASSIGNMENT.value,
                sender="SERVER",
                recipient=player_id,
                payload={
                    "role": player.role.value,
                    "num_players": len(self.game_state.players),
                    "num_werewolves": self.game_state.num_werewolves
                }
            )
            await self.comm_server.send_message(role_msg)
            self.logger.info(f"Assigned role {player.role.value} to {player_id}")

        # Start game loop
        asyncio.create_task(self.game_loop())

    async def game_loop(self):
        """Main game loop."""
        self.game_state.phase = GamePhase.NIGHT
        self.game_state.current_round = 1

        while True:
            # Check win condition
            winner = self.game_state.check_win_condition()
            if winner:
                await self.end_game(winner)
                break

            if self.game_state.phase == GamePhase.NIGHT:
                await self.night_phase()
            elif self.game_state.phase == GamePhase.DAY:
                await self.day_phase()
            elif self.game_state.phase == GamePhase.VOTING:
                await self.voting_phase()
            elif self.game_state.phase == GamePhase.RESULTS:
                await self.results_phase()

    async def night_phase(self):
        """Execute night phase."""
        self.logger.info(f"--- NIGHT {self.game_state.current_round} ---")

        # Notify all players that night has begun
        await self._broadcast_phase_change("NIGHT")

        # Ask werewolves for their targets
        werewolves = self.game_state.get_alive_werewolves()
        seers = [
            player for player in self.game_state.get_alive_players()
            if player.role == PlayerRole.SEER
        ]
        alive_villagers = self.game_state.get_alive_villagers()
        self._expected_night_actions = {
            player.player_id for player in werewolves + seers
        }
        self._received_night_actions.clear()
        self._night_actions_complete.clear()

        for werewolf in werewolves:
            action_msg = Message(
                msg_type=MessageType.NIGHT_ACTION.value,
                sender="SERVER",
                recipient=werewolf.player_id,
                payload={
                    "action": "select_victim",
                    "available_targets": [p.player_id for p in alive_villagers]
                }
            )
            await self.comm_server.send_message(action_msg)

        for seer in seers:
            action_msg = Message(
                msg_type=MessageType.NIGHT_ACTION.value,
                sender="SERVER",
                recipient=seer.player_id,
                payload={
                    "action": "investigate",
                    "available_targets": [
                        player.player_id
                        for player in self.game_state.get_alive_players()
                        if player.player_id != seer.player_id
                    ]
                }
            )
            await self.comm_server.send_message(action_msg)

        if self.interactive:
            if self._expected_night_actions:
                try:
                    await asyncio.wait_for(
                        self._night_actions_complete.wait(),
                        timeout=self.action_timeout
                    )
                except asyncio.TimeoutError:
                    self.logger.warning("Timed out waiting for night actions")
        else:
            await asyncio.sleep(5)

        # Resolve night actions
        self.game_state.resolve_night_actions()
        self.logger.info(f"Eliminated: {list(self.game_state.night_actions.values()) if self.game_state.night_actions else 'None'}")

        # Transition to day phase
        self.game_state.phase = GamePhase.DAY

    async def day_phase(self):
        """Execute day phase (discussion)."""
        self.logger.info(f"--- DAY {self.game_state.current_round} ---")

        # Notify all players
        await self._broadcast_phase_change("DAY")
        await self._broadcast_game_state()

        await asyncio.sleep(self.discussion_seconds if self.interactive else 3)

        self.game_state.phase = GamePhase.VOTING

    async def voting_phase(self):
        """Execute voting phase."""
        self.logger.info(f"--- VOTING ---")

        # Reset votes
        self.game_state.reset_votes()
        alive_players = self.game_state.get_alive_players()
        self._expected_votes = {player.player_id for player in alive_players}
        self._received_votes.clear()
        self._votes_complete.clear()

        # Ask all alive players to vote
        for player in alive_players:
            other_alive = [p.player_id for p in alive_players
                          if p.player_id != player.player_id]
            vote_msg = Message(
                msg_type=MessageType.VOTE.value,
                sender="SERVER",
                recipient=player.player_id,
                payload={
                    "action": "cast_vote",
                    "available_targets": other_alive
                }
            )
            await self.comm_server.send_message(vote_msg)

        if self.interactive:
            if self._expected_votes:
                try:
                    await asyncio.wait_for(
                        self._votes_complete.wait(),
                        timeout=self.action_timeout
                    )
                except asyncio.TimeoutError:
                    self.logger.warning("Timed out waiting for votes")
        else:
            await asyncio.sleep(5)

        self.game_state.phase = GamePhase.RESULTS

    async def results_phase(self):
        """Execute results phase."""
        most_voted = self.game_state.get_most_voted()

        if most_voted:
            self.logger.info(f"Player {most_voted} is eliminated by vote")
            self.game_state.eliminate_player(most_voted)
        else:
            self.logger.info("No clear vote result")

        # Broadcast elimination
        elim_msg = Message(
            msg_type=MessageType.ELIMINATE.value,
            sender="SERVER",
            recipient="*",
            payload={
                "eliminated": most_voted,
                "round": self.game_state.current_round
            }
        )
        await self.comm_server.send_message(elim_msg)

        self.game_state.current_round += 1
        self.game_state.phase = GamePhase.NIGHT

    async def end_game(self, winner: str):
        """End the game."""
        self.logger.info(f"Game Over! {winner.upper()} WIN!")

        # Notify all players
        final_state = self.game_state.to_dict()
        end_msg = Message(
            msg_type=MessageType.WIN.value,
            sender="SERVER",
            recipient="*",
            payload={
                "winner": winner,
                "final_state": final_state
            }
        )
        await self.comm_server.send_message(end_msg)

        # Cleanup
        await self.comm_server.shutdown()

    async def _broadcast_phase_change(self, phase: str):
        """Broadcast phase change to all players."""
        msg = Message(
            msg_type=MessageType.PHASE_CHANGE.value,
            sender="SERVER",
            recipient="*",
            payload={"phase": phase, "round": self.game_state.current_round}
        )
        await self.comm_server.send_message(msg)

    async def _broadcast_game_state(self):
        """Broadcast current game state to all players."""
        msg = Message(
            msg_type=MessageType.GAME_STATE.value,
            sender="SERVER",
            recipient="*",
            payload=self.game_state.to_public_dict()
        )
        await self.comm_server.send_message(msg)

    async def run(self):
        """Run the server."""
        await self.comm_server.start()
        await self.comm_server.accept_connections()


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Werewolves Game Server")
    parser.add_argument("--socket", default="sockets/game_server.sock", help="Socket path")
    parser.add_argument("--players", type=int, default=4, help="Number of players")
    parser.add_argument("--werewolves", type=int, default=None, help="Number of werewolves (defaults to one per four players)")
    parser.add_argument("--log-dir", default="logs", help="Log directory")
    parser.add_argument("--interactive", action="store_true", help="Allow discussion and wait for player choices")

    args = parser.parse_args()

    try:
        calculate_role_counts(args.players, args.werewolves)
    except ValueError as error:
        parser.error(str(error))

    server = WerewolvesGameServer(
        socket_path=args.socket,
        num_players=args.players,
        num_werewolves=args.werewolves,
        log_dir=args.log_dir,
        interactive=args.interactive
    )

    try:
        await server.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await server.comm_server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())