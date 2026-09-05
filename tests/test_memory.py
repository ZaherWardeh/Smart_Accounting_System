import threading
import time

import graph
from fakes import FakePart, FakeResponse, install_fake_client


def test_history_store_starts_empty_and_round_trips():
    graph.clear_conversation("conv-a")

    assert graph._get_history("conv-a") == []

    graph._save_history("conv-a", ["turn-1", "turn-2"])

    assert graph._get_history("conv-a") == ["turn-1", "turn-2"]
    graph.clear_conversation("conv-a")


def test_conversations_are_isolated_by_id():
    graph.clear_conversation("conv-x")
    graph.clear_conversation("conv-y")

    graph._save_history("conv-x", ["only in x"])

    assert graph._get_history("conv-x") == ["only in x"]
    assert graph._get_history("conv-y") == []

    graph.clear_conversation("conv-x")


def test_history_is_trimmed_to_max_entries():
    graph.clear_conversation("conv-trim")
    long_history = [f"turn-{i}" for i in range(graph.MAX_HISTORY_ENTRIES + 10)]

    graph._save_history("conv-trim", long_history)

    trimmed = graph._get_history("conv-trim")
    assert len(trimmed) == graph.MAX_HISTORY_ENTRIES
    assert trimmed[-1] == f"turn-{graph.MAX_HISTORY_ENTRIES + 9}"

    graph.clear_conversation("conv-trim")


def test_oldest_conversation_is_evicted_once_over_capacity():
    graph.clear_conversation("conv-first")
    graph._save_history("conv-first", ["only turn"])

    try:
        for i in range(graph.MAX_TRACKED_CONVERSATIONS):
            graph._save_history(f"conv-filler-{i}", ["turn"])

        # least-recently-saved conversation is the one that gets evicted
        assert graph._get_history("conv-first") == []
        assert len(graph._CONVERSATIONS) == graph.MAX_TRACKED_CONVERSATIONS
    finally:
        for i in range(graph.MAX_TRACKED_CONVERSATIONS):
            graph.clear_conversation(f"conv-filler-{i}")


def test_intro_instruction_included_only_on_first_turn(monkeypatch, seeded_db):
    graph.clear_conversation("conv-intro")
    captured_configs = []

    def fake_generate_content(model, contents, config=None):
        captured_configs.append(config)
        return FakeResponse(parts=[FakePart()], text="رد")

    install_fake_client(monkeypatch, fake_generate_content)

    graph.agent_loop({"conversation_id": "conv-intro", "question": "مرحبا", "db": seeded_db})
    graph.agent_loop({"conversation_id": "conv-intro", "question": "شو رصيد الصندوق؟", "db": seeded_db})

    assert "أول رسالة" in captured_configs[0].system_instruction
    assert "أول رسالة" not in captured_configs[1].system_instruction

    graph.clear_conversation("conv-intro")


def test_history_grows_and_is_reused_across_turns(monkeypatch, seeded_db):
    graph.clear_conversation("conv-grow")
    captured_contents = []

    def fake_generate_content(model, contents, config=None):
        captured_contents.append(list(contents))
        return FakeResponse(parts=[FakePart()], text="رد")

    install_fake_client(monkeypatch, fake_generate_content)

    graph.agent_loop({"conversation_id": "conv-grow", "question": "سؤال أول", "db": seeded_db})
    graph.agent_loop({"conversation_id": "conv-grow", "question": "سؤال ثاني", "db": seeded_db})

    # second call's contents include the first turn's exchange plus the new question
    assert len(captured_contents[1]) > len(captured_contents[0])

    graph.clear_conversation("conv-grow")


def test_concurrent_requests_on_same_conversation_do_not_lose_a_turn(monkeypatch, seeded_db):
    graph.clear_conversation("conv-race")

    def slow_fake_generate_content(model, contents, config=None):
        time.sleep(0.1)  # widen the race window a concurrent request would hit
        return FakeResponse(parts=[FakePart()], text="رد")

    install_fake_client(monkeypatch, slow_fake_generate_content)

    def worker(question):
        graph.agent_loop({"conversation_id": "conv-race", "question": question, "db": seeded_db})

    t1 = threading.Thread(target=worker, args=("سؤال أ",))
    t2 = threading.Thread(target=worker, args=("سؤال ب",))
    t1.start()
    time.sleep(0.02)  # ensure t1 is inside its slow call before t2 starts
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # without the per-conversation lock, t2 would read t1's stale pre-save
    # history and overwrite it on save, losing t1's turn entirely (length 2).
    assert len(graph._get_history("conv-race")) == 4

    graph.clear_conversation("conv-race")
