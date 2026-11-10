"""
Werewolves Game Logic and State Management
Handles game phases, role assignments, win conditions, and game state.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import random


class GamePhase(Enum):
    """Game phases."""
    SETUP = "SETUP"
    NIGHT = "NIGHT"
    DAY = "DAY"
    VOTING = "VOTING"
    RESULTS = "RESULTS"
    GAME_OVER = "GAME_OVER"


class PlayerRole(Enum):
    """Player roles in the game."""
    WEREWOLF = "WEREWOLF"
    VILLAGER = "VILLAGER"
    DOCTOR = "DOCTOR"
    SEER = "SEER"


@dataclass
class Player:
    """Represents a player in the game."""
    player_id: str
    role: Optional[PlayerRole] = None
    is_alive: bool = True
    voted_for: Optional[str] = None

    def __hash__(self):
        return hash(self.player_id)

    def __eq__(self, other):
        if isinstance(other, Player):
            return self.player_id == other.player_id
        return self.player_id == other


class GameState:
    """Manages the complete game state."""

    def __init__(self, num_werewolves: int = 2):
        self.players: Dict[str, Player] = {}
        self.phase: GamePhase = GamePhase.SETUP
        self.num_werewolves = num_werewolves
        self.current_round = 0
        self.eliminated_players: List[str] = []
        self.night_actions: Dict[str, str] = {}  # werewolf_id -> victim_id
        self.doctor_protection: Optional[str] = None

    def add_player(self, player_id: str) -> Player:
        """Add a player to the game."""
        player = Player(player_id=player_id)
        self.players[player_id] = player
        return player

    def assign_roles(self):
        """Randomly assign roles to players."""
        if len(self.players) < 2:
            raise ValueError("Need at least 2 players")

        player_ids = list(self.players.keys())
        random.shuffle(player_ids)

        # Assign werewolves
        for i in range(min(self.num_werewolves, len(player_ids))):
            self.players[player_ids[i]].role = PlayerRole.WEREWOLF

        # Assign doctor (if enough players)
        if len(player_ids) >= 6:
            self.players[player_ids[self.num_werewolves]].role = PlayerRole.DOCTOR
            doctor_idx = self.num_werewolves + 1
        else:
            doctor_idx = self.num_werewolves

        # Assign seer (if enough players)
        if len(player_ids) >= 8:
            self.players[player_ids[doctor_idx]].role = PlayerRole.SEER
            seer_idx = doctor_idx + 1
        else:
            seer_idx = doctor_idx

        # Rest are villagers
        for i in range(seer_idx, len(player_ids)):
            self.players[player_ids[i]].role = PlayerRole.VILLAGER

    def get_alive_players(self) -> List[Player]:
        """Get all alive players."""
        return [p for p in self.players.values() if p.is_alive]

    def get_alive_werewolves(self) -> List[Player]:
        """Get all alive werewolves."""
        return [p for p in self.players.values() 
                if p.is_alive and p.role == PlayerRole.WEREWOLF]

    def get_alive_villagers(self) -> List[Player]:
        """Get all alive non-werewolf villagers."""
        return [p for p in self.players.values() 
                if p.is_alive and p.role != PlayerRole.WEREWOLF]

    def eliminate_player(self, player_id: str):
        """Eliminate a player."""
        if player_id in self.players:
            self.players[player_id].is_alive = False
            self.eliminated_players.append(player_id)

    def reset_votes(self):
        """Reset all player votes."""
        for player in self.players.values():
            player.voted_for = None

    def record_vote(self, voter_id: str, votee_id: str):
        """Record a player's vote."""
        if voter_id in self.players:
            self.players[voter_id].voted_for = votee_id

    def get_vote_count(self) -> Dict[str, int]:
        """Get vote counts."""
        vote_count: Dict[str, int] = {}
        for player in self.players.values():
            if player.voted_for:
                vote_count[player.voted_for] = vote_count.get(player.voted_for, 0) + 1
        return vote_count

    def get_most_voted(self) -> Optional[str]:
        """Get the player with the most votes."""
        votes = self.get_vote_count()
        if not votes:
            return None
        return max(votes, key=votes.get)

    def check_win_condition(self) -> Optional[str]:
        """
        Check if game is over.
        Returns: "werewolves", "villagers", or None
        """
        alive_werewolves = len(self.get_alive_werewolves())
        alive_villagers = len(self.get_alive_villagers())

        if alive_werewolves == 0:
            return "villagers"  # All werewolves eliminated
        elif alive_werewolves >= alive_villagers:
            return "werewolves"  # Werewolves equal/outnumber villagers
        else:
            return None  # Game continues

    def record_night_action(self, werewolf_id: str, victim_id: str):
        """Record a werewolf's night action."""
        self.night_actions[werewolf_id] = victim_id

    def resolve_night_actions(self):
        """Resolve night actions and eliminate victims."""
        if not self.night_actions:
            return

        # Count votes for elimination
        elimination_votes: Dict[str, int] = {}
        for victim in self.night_actions.values():
            elimination_votes[victim] = elimination_votes.get(victim, 0) + 1

        # Get most voted victim (with tie-breaking)
        if elimination_votes:
            victim = max(elimination_votes, key=elimination_votes.get)

            # Doctor can protect one person per night
            if self.doctor_protection == victim:
                self.doctor_protection = None  # Used protection
            else:
                self.eliminate_player(victim)

        self.night_actions.clear()

    def to_dict(self) -> Dict:
        """Convert game state to dictionary for serialization."""
        return {
            "phase": self.phase.value,
            "current_round": self.current_round,
            "players": {
                pid: {
                    "role": p.role.value if p.role else None,
                    "is_alive": p.is_alive,
                    "voted_for": p.voted_for
                }
                for pid, p in self.players.items()
            },
            "eliminated_players": self.eliminated_players,
            "num_alive": len(self.get_alive_players()),
            "num_werewolves": len(self.get_alive_werewolves())
        }