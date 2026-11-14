import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comms import Message, MessageType, UDSServer
from game_logic import GamePhase, GameState, PlayerRole, calculate_role_counts
from game_server import WerewolvesGameServer


class FakeComms(UDSServer):
    def __init__(self):
        self.messages: list[Message] = []

    async def send_message(self, message: Message) -> None:
        self.messages.append(message)


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


def test_broadcast_game_state_does_not_expose_player_roles():
    async def run_scenario():
        server = WerewolvesGameServer.__new__(WerewolvesGameServer)
        server.game_state = GameState()
        server.game_state.add_player("seer")
        server.game_state.add_player("wolf")
        server.game_state.players["seer"].role = PlayerRole.SEER
        server.game_state.players["wolf"].role = PlayerRole.WEREWOLF
        server.comm_server = FakeComms()

        await server._broadcast_game_state()

        assert len(server.comm_server.messages) == 1
        state_message = server.comm_server.messages[0]
        assert state_message.msg_type == MessageType.GAME_STATE.value
        assert state_message.recipient == "*"
        assert all(
            "role" not in player
            for player in state_message.payload["players"].values()
        )
        assert server.game_state.to_dict()["players"]["wolf"]["role"] == "WEREWOLF"

    asyncio.run(run_scenario())


def test_vote_handler_rejects_malformed_and_duplicate_votes():
    async def run_scenario():
        server = WerewolvesGameServer.__new__(WerewolvesGameServer)
        server.game_state = GameState()
        server.game_state.add_player("voter")
        server.game_state.add_player("target_1")
        server.game_state.add_player("target_2")
        server.game_state.phase = GamePhase.VOTING
        server._expected_votes = {"voter"}
        server._received_votes = set()
        server._votes_complete = asyncio.Event()
        server.interactive = True
        server.logger = logging.getLogger("test-game-server")

        await server._handle_vote(Message(
            msg_type=MessageType.VOTE.value,
            sender="voter",
            recipient="SERVER",
            payload={},
        ))
        assert server.game_state.players["voter"].voted_for is None

        await server._handle_vote(Message(
            msg_type=MessageType.VOTE.value,
            sender="voter",
            recipient="SERVER",
            payload={"vote_for": "target_1"},
        ))
        await server._handle_vote(Message(
            msg_type=MessageType.VOTE.value,
            sender="voter",
            recipient="SERVER",
            payload={"vote_for": "target_2"},
        ))

        assert server.game_state.players["voter"].voted_for == "target_1"
        assert server._votes_complete.is_set()

    asyncio.run(run_scenario())