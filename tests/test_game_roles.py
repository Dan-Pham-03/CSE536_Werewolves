import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comms import Message, MessageType
from game_logic import GamePhase, GameState, PlayerRole, calculate_role_counts
from game_server import WerewolvesGameServer


def test_role_calculator_produces_balanced_rosters():
    four_players = calculate_role_counts(4)
    assert four_players.werewolves == 1
    assert four_players.seers == 1
    assert four_players.villagers == 2

    eight_players = calculate_role_counts(8)
    assert eight_players.werewolves == 2
    assert eight_players.seers == 1
    assert eight_players.villagers == 5


def test_role_calculator_rejects_small_or_overloaded_games():
    with pytest.raises(ValueError):
        calculate_role_counts(3)
    with pytest.raises(ValueError):
        calculate_role_counts(4, 2)


def test_role_assignment_matches_calculated_counts():
    game = GameState()
    for player_id in range(4):
        game.add_player(f"player_{player_id}")

    game.assign_roles()

    counts = Counter(player.role for player in game.players.values())
    assert counts == {
        PlayerRole.WEREWOLF: 1,
        PlayerRole.SEER: 1,
        PlayerRole.VILLAGER: 2,
    }


def test_seer_result_is_sent_only_to_the_seer():
    class FakeComms:
        def __init__(self):
            self.messages = []

        async def send_message(self, message):
            self.messages.append(message)

    async def run_scenario():
        server = WerewolvesGameServer.__new__(WerewolvesGameServer)
        server.game_state = GameState()
        server.game_state.add_player("seer")
        server.game_state.add_player("wolf")
        server.game_state.players["seer"].role = PlayerRole.SEER
        server.game_state.players["wolf"].role = PlayerRole.WEREWOLF
        server.game_state.phase = GamePhase.NIGHT
        server._expected_night_actions = {"seer"}
        server._received_night_actions = set()
        server._night_actions_complete = asyncio.Event()
        server.comm_server = FakeComms()
        server.logger = logging.getLogger("test-game-server")

        await server._handle_night_action(Message(
            msg_type=MessageType.NIGHT_ACTION.value,
            sender="seer",
            recipient="SERVER",
            payload={"action": "investigate", "target": "wolf"},
        ))

        assert len(server.comm_server.messages) == 1
        result = server.comm_server.messages[0]
        assert result.msg_type == MessageType.SEER_RESULT.value
        assert result.recipient == "seer"
        assert result.payload == {"target": "wolf", "is_werewolf": True}
        assert server._night_actions_complete.is_set()

    asyncio.run(run_scenario())