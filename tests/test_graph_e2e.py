import graph
from fakes import FakePart, FakeResponse, install_fake_client


def test_full_graph_answers_via_run_agent(monkeypatch, seeded_db):
    graph.clear_conversation("conv-run-agent")

    def fake_generate_content(model, contents, config=None):
        return FakeResponse(parts=[FakePart()], text="أهلاً وسهلاً! أنا ريما، كيف فيني ساعدك؟")

    install_fake_client(monkeypatch, fake_generate_content)

    answer = graph.run_agent(seeded_db, "conv-run-agent", "مرحبا")

    assert answer == "أهلاً وسهلاً! أنا ريما، كيف فيني ساعدك؟"

    graph.clear_conversation("conv-run-agent")


def test_out_of_scope_question_is_declined_without_tools_being_needed(monkeypatch, seeded_db):
    graph.clear_conversation("conv-scope")

    def fake_generate_content(model, contents, config=None):
        # the model itself decides not to call any tool for an out-of-scope
        # request; the system prompt still has tools available, it just
        # doesn't use them.
        return FakeResponse(parts=[FakePart()], text="عذراً، أنا مختصة فقط بالأسئلة المحاسبية.")

    install_fake_client(monkeypatch, fake_generate_content)

    answer = graph.run_agent(seeded_db, "conv-scope", "شو الجو اليوم؟")

    assert "مختصة" in answer

    graph.clear_conversation("conv-scope")


def test_memory_persists_across_two_calls_in_same_conversation(monkeypatch, seeded_db):
    graph.clear_conversation("conv-memory")
    seen_contents_lengths = []

    def fake_generate_content(model, contents, config=None):
        seen_contents_lengths.append(len(contents))
        return FakeResponse(parts=[FakePart()], text=f"رد رقم {len(seen_contents_lengths)}")

    install_fake_client(monkeypatch, fake_generate_content)

    first = graph.run_agent(seeded_db, "conv-memory", "شو رصيد الصندوق؟")
    second = graph.run_agent(seeded_db, "conv-memory", "وشو رصيد الزبائن؟")

    assert first == "رد رقم 1"
    assert second == "رد رقم 2"
    # the second call carried the first turn's exchange forward as history
    assert seen_contents_lengths[1] > seen_contents_lengths[0]

    graph.clear_conversation("conv-memory")


def test_different_conversation_ids_do_not_share_memory(monkeypatch, seeded_db):
    graph.clear_conversation("conv-a")
    graph.clear_conversation("conv-b")
    seen_contents_lengths = []

    def fake_generate_content(model, contents, config=None):
        seen_contents_lengths.append(len(contents))
        return FakeResponse(parts=[FakePart()], text="رد")

    install_fake_client(monkeypatch, fake_generate_content)

    graph.run_agent(seeded_db, "conv-a", "سؤال أول بمحادثة أ")
    graph.run_agent(seeded_db, "conv-b", "سؤال أول بمحادثة ب")

    # both are first turns in their own conversation, so both start from
    # a single-item contents list rather than the second inheriting the first's history.
    assert seen_contents_lengths[0] == seen_contents_lengths[1] == 1

    graph.clear_conversation("conv-a")
    graph.clear_conversation("conv-b")
