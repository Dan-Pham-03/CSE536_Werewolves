"""
Werewolves Game Logic and State Management
Handles game phases, role assignments, win conditions, and game state.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional
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
    SEER = "SEER"


@dataclass(frozen=True)
class RoleCounts:
    werewolves: int
    seers: int
    villagers: int


def calculate_role_counts(num_players: int, num_werewolves: Optional[int] = None) -> RoleCounts:
    """Calculate a roster with at most one werewolf per four players."""
    if num_players < 4:
        raise ValueError("Need at least 4 players for a balanced game")

    recommended_werewolves = max(1, num_players // 4)
    werewolf_count = recommended_werewolves if num_werewolves is None else num_werewolves
    if werewolf_count < 1 or werewolf_count > recommended_werewolves:
        raise ValueError(
            f"Werewolf count must be between 1 and {recommended_werewolves} "
            f"for {num_players} players"
        )

    seer_count = 1
    villager_count = num_players - werewolf_count - seer_count
    return RoleCounts(werewolves=werewolf_count, seers=seer_count, villagers=villager_count)


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

    def __init__(self, num_werewolves: Optional[int] = None):
        self.players: Dict[str, Player] = {}
        self.phase: GamePhase = GamePhase.SETUP
        self.num_werewolves = num_werewolves
        self.current_round = 0
        self.eliminated_players: List[str] = []
        self.night_actions: Dict[str, str] = {}  # werewolf_id -> victim_id

    def add_player(self, player_id: str) -> Player:
        """Add a player to the game."""
        player = Player(player_id=player_id)
        self.players[player_id] = player
        return player

    def assign_roles(self):
        """Randomly assign roles to players."""
        if len(self.players) < 2:
            raise ValueError("Need at least 2 players")

        counts = calculate_role_counts(len(self.players), self.num_werewolves)
        self.num_werewolves = counts.werewolves
        player_ids = list(self.players.keys())
        random.shuffle(player_ids)

        for i in range(counts.werewolves):
            self.players[player_ids[i]].role = PlayerRole.WEREWOLF

        seer_idx = counts.werewolves
        self.players[player_ids[seer_idx]].role = PlayerRole.SEER

        for i in range(seer_idx + counts.seers, len(player_ids)):
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