import asyncio
import logging
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comms import Message, MessageType, UDSClient, UDSServer
from game_logic import GamePhase, GameState, PlayerRole, calculate_role_counts
from game_server import WerewolvesGameServer
from player import WerewolvesPlayer


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


def test_chat_is_scoped_to_living_players_and_phase():
    async def run_scenario():
        server = WerewolvesGameServer.__new__(WerewolvesGameServer)
        server.game_state = GameState()
        for player_id, role in (("wolf1", PlayerRole.WEREWOLF), ("wolf2", PlayerRole.WEREWOLF),
                                ("villager", PlayerRole.VILLAGER), ("dead", PlayerRole.WEREWOLF)):
            server.game_state.add_player(player_id).role = role
        server.game_state.players["dead"].is_alive = False
        server.comm_server = FakeComms()
        server.logger = logging.getLogger("test-game-server")

        async def send(sender, text="hello"):
            await server._handle_chat(Message(
                msg_type=MessageType.CHAT.value, sender=sender, recipient="SERVER",
                payload={"text": text},
            ))

        server.game_state.phase = GamePhase.NIGHT
        await send("wolf1")
        assert {m.recipient for m in server.comm_server.messages} == {"wolf1", "wolf2"}
        assert all(m.payload["channel"] == "werewolves" for m in server.comm_server.messages)
        server.comm_server.messages.clear()
        await send("villager")
        await send("dead")
        await send("wolf1", " " * 3)
        await send("wolf1", "a" * 501)
        assert not server.comm_server.messages

        for phase in (GamePhase.DAY, GamePhase.VOTING):
            server.game_state.phase = phase
            await send("villager")
            assert {m.recipient for m in server.comm_server.messages} == {"wolf1", "wolf2", "villager"}
            assert all(m.payload["channel"] == "day" for m in server.comm_server.messages)
            server.comm_server.messages.clear()
        server.game_state.phase = GamePhase.RESULTS
        await send("wolf1")
        assert not server.comm_server.messages

    asyncio.run(run_scenario())


def test_player_can_chat_while_selecting_and_sends_valid_wolf_action(tmp_path, capsys):
    async def run_scenario():
        player = WerewolvesPlayer("wolf", "unused", str(tmp_path), interactive=True)
        comms = FakeComms()
        player.client.send_message = comms.send_message
        sent = comms.messages
        player.role = "WEREWOLF"
        await player._handle_phase_change(Message(
            msg_type=MessageType.PHASE_CHANGE.value, sender="SERVER", recipient="*",
            payload={"phase": "NIGHT", "round": 1},
        ))
        await player._handle_night_action(Message(
            msg_type=MessageType.NIGHT_ACTION.value, sender="SERVER", recipient="wolf",
            payload={"action": "select_victim", "available_targets": ["villager"]},
        ))
        await player._handle_input("/chat who should we choose?")
        await player._handle_chat(Message(
            msg_type=MessageType.CHAT.value, sender="wolf2", recipient="wolf",
            payload={"channel": "werewolves", "text": "villager"},
        ))
        await player._handle_input("villager")
        assert sent[0].payload == {"text": "who should we choose?"}
        assert sent[1].payload == {"action": "select_victim", "victim": "villager"}
        assert "wolf2: villager" in capsys.readouterr().out
        server = WerewolvesGameServer.__new__(WerewolvesGameServer)
        server.game_state = GameState()
        server.game_state.add_player("wolf").role = PlayerRole.WEREWOLF
        server.game_state.add_player("villager").role = PlayerRole.VILLAGER
        server.game_state.phase = GamePhase.NIGHT
        server._expected_night_actions = {"wolf"}
        server._received_night_actions = set()
        server._night_actions_complete = asyncio.Event()
        server.logger = logging.getLogger("test-game-server")
        await server._handle_night_action(sent[1])
        assert server.game_state.night_actions == {"wolf": "villager"}

    asyncio.run(run_scenario())


@pytest.mark.parametrize("action", [None, "invalid"])
def test_player_rejects_invalid_night_action_requests(tmp_path, action):
    async def run_scenario():
        player = WerewolvesPlayer("wolf", "unused", str(tmp_path), interactive=True)
        comms = FakeComms()
        player.client.send_message = comms.send_message
        await player._handle_night_action(Message(
            msg_type=MessageType.NIGHT_ACTION.value, sender="SERVER", recipient="wolf",
            payload={"action": action, "available_targets": ["villager"]},
        ))
        assert player._pending_choice is None
        assert not comms.messages
        assert "Rejected invalid night action request" in (tmp_path / "player_wolf.log").read_text()

    asyncio.run(run_scenario())


def test_elimination_announcements_update_player_and_distinguish_results(tmp_path, capsys):
    async def run_scenario():
        player = WerewolvesPlayer("victim", "unused", str(tmp_path), interactive=True)
        for eliminated, cause in ((None, "vote"), ("other", "vote"), ("victim", "night")):
            await player._handle_eliminate(Message(
                msg_type=MessageType.ELIMINATE.value, sender="SERVER", recipient="*",
                payload={"eliminated": eliminated, "cause": cause},
            ))
        assert not player.is_alive
        output = capsys.readouterr().out
        assert "No player was executed" in output
        assert "other was executed by the vote" in output
        assert "You were killed during the night" in output
        await player._handle_eliminate(Message(
            msg_type=MessageType.ELIMINATE.value, sender="SERVER", recipient="*",
            payload={"eliminated": "victim", "cause": "vote"},
        ))
        assert "You were executed by the vote" in capsys.readouterr().out

    asyncio.run(run_scenario())


def test_night_death_is_announced_before_a_game_ending(tmp_path):
    async def run_scenario():
        server = WerewolvesGameServer("unused", 4, log_dir=str(tmp_path))
        server.comm_server = FakeComms()
        for player_id, role in (("wolf", PlayerRole.WEREWOLF), ("seer", PlayerRole.SEER),
                                ("v1", PlayerRole.VILLAGER), ("v2", PlayerRole.VILLAGER)):
            server.game_state.add_player(player_id).role = role
        server.game_state.phase = GamePhase.NIGHT
        server.game_state.eliminate_player("v2")
        server.game_state.record_night_action("wolf", "seer")
        server.interactive = True
        server.action_timeout = 0
        await server.night_phase()
        deaths = [m for m in server.comm_server.messages if m.msg_type == MessageType.ELIMINATE.value]
        assert len(deaths) == 1
        assert deaths[0].payload["eliminated"] == "seer"
        assert deaths[0].payload["cause"] == "night"
        assert server.game_state.check_win_condition() == "werewolves"

    asyncio.run(run_scenario())


def test_chat_over_socket_is_private_and_rejects_spoofed_sender(tmp_path):
    async def run_scenario():
        socket_path = str(tmp_path / "game.sock")
        server = WerewolvesGameServer(socket_path, 4, log_dir=str(tmp_path))
        server.game_state.phase = GamePhase.NIGHT
        for player_id, role in (("wolf1", PlayerRole.WEREWOLF), ("wolf2", PlayerRole.WEREWOLF),
                                ("villager", PlayerRole.VILLAGER)):
            server.game_state.add_player(player_id).role = role
        async def ignore_hello(message):
            pass

        server.comm_server.register_handler(MessageType.HELLO.value, ignore_hello)
        await server.comm_server.start()
        accept_task = asyncio.create_task(server.comm_server.accept_connections())
        received = {player_id: [] for player_id in ("wolf1", "wolf2", "villager")}
        wolf2_received = asyncio.Event()
        clients = {}
        try:
            for player_id in received:
                client = UDSClient(socket_path, player_id)

                async def receive(message, player_id=player_id):
                    received[player_id].append(message)
                    if player_id == "wolf2":
                        wolf2_received.set()

                client.register_handler(MessageType.CHAT.value, receive)
                assert await client.connect()
                clients[player_id] = client

            async def wait_for_connections():
                while len(server.comm_server.clients) != 3:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_connections(), 1)
            await clients["wolf1"].send_message(Message(
                msg_type=MessageType.CHAT.value, sender="wolf1", recipient="SERVER",
                payload={"text": "secret"},
            ))
            await asyncio.wait_for(wolf2_received.wait(), 1)
            assert received["wolf2"][0].payload["text"] == "secret"
            assert not received["villager"]

            await clients["villager"].send_message(Message(
                msg_type=MessageType.CHAT.value, sender="wolf2", recipient="SERVER",
                payload={"text": "spoofed"},
            ))
            async def wait_for_disconnect():
                while "villager" in server.comm_server.clients:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_disconnect(), 1)
            assert len(received["wolf2"]) == 1
        finally:
            for client in clients.values():
                await client.disconnect()
            accept_task.cancel()
            try:
                await accept_task
            except asyncio.CancelledError:
                pass
            await server.comm_server.shutdown()

    asyncio.run(run_scenario())


def test_interactive_input_reads_multiple_lines_without_blocking_messages(tmp_path, monkeypatch):
    async def run_scenario():
        player = WerewolvesPlayer("wolf", "unused", str(tmp_path), interactive=True)
        comms = FakeComms()
        player.client.send_message = comms.send_message
        player.role = "WEREWOLF"
        player.phase = "NIGHT"
        player._pending_choice = ("select_victim", ["villager"])
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, "r") as terminal:
            monkeypatch.setattr(sys, "stdin", terminal)
            input_task = asyncio.create_task(player._read_input())
            try:
                os.write(write_fd, b"/chat hello\nvillager\n")
                async def wait_for_messages():
                    while len(comms.messages) < 2:
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(wait_for_messages(), 1)
                assert [m.msg_type for m in comms.messages] == [
                    MessageType.CHAT.value, MessageType.NIGHT_ACTION.value,
                ]
                await player._handle_phase_change(Message(
                    msg_type=MessageType.PHASE_CHANGE.value, sender="SERVER", recipient="*",
                    payload={"phase": "DAY", "round": 1},
                ))
                assert player.phase == "DAY"
            finally:
                input_task.cancel()
                try:
                    await input_task
                except asyncio.CancelledError:
                    pass
                os.close(write_fd)

    asyncio.run(run_scenario())