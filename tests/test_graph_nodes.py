import json

import graph
from fakes import FakeResponse, install_fake_client


def _fake_generate_content(text):
    def _inner(model, contents, config=None):
        return FakeResponse(parts=[], text=text)

    return _inner


def test_classify_intent_parses_json(monkeypatch):
    install_fake_client(
        monkeypatch,
        _fake_generate_content(json.dumps({"intent": "Greeting", "confidence": "high", "reason": "friendly greeting"})),
    )

    state = graph.classify_intent({"question": "مرحبا"})

    assert state["intent"] == "Greeting"
    assert state["confidence"] == "high"
    assert state["reason"] == "friendly greeting"


def test_classify_intent_strips_markdown_fences(monkeypatch):
    install_fake_client(
        monkeypatch,
        _fake_generate_content("```json\n" + json.dumps({"intent": "Data Request", "confidence": "medium", "reason": "r"}) + "\n```"),
    )

    state = graph.classify_intent({"question": "عطيني المعاملات"})

    assert state["intent"] == "Data Request"


def test_classify_intent_handles_unparseable_response(monkeypatch):
    install_fake_client(monkeypatch, _fake_generate_content("not json at all"))

    state = graph.classify_intent({"question": "???"})

    assert state["intent"] is None
    assert state["confidence"] == "low"


def test_route_low_confidence_goes_to_ambiguous():
    assert graph.route({"confidence": "low", "intent": "Accounting Inquiry"}) == "handle_ambiguous"


def test_route_out_of_scope():
    assert graph.route({"confidence": "high", "intent": "Out of Scope"}) == "handle_out_of_scope"


def test_route_greeting():
    assert graph.route({"confidence": "medium", "intent": "Greeting"}) == "handle_greeting"


def test_route_data_intents_go_to_agent_loop():
    for intent in ("Accounting Inquiry", "Financial Analysis", "Data Request"):
        assert graph.route({"confidence": "high", "intent": intent}) == "agent_loop"


def test_route_unknown_intent_falls_back_to_ambiguous():
    assert graph.route({"confidence": "high", "intent": "Something Else"}) == "handle_ambiguous"


def test_handle_greeting(monkeypatch):
    install_fake_client(monkeypatch, _fake_generate_content("أهلاً بك!"))

    state = graph.handle_greeting({"question": "مرحبا"})

    assert state["answer"] == "أهلاً بك!"


def test_handle_ambiguous(monkeypatch):
    install_fake_client(monkeypatch, _fake_generate_content("ممكن توضح أكثر؟"))

    state = graph.handle_ambiguous({"question": "؟؟؟"})

    assert state["answer"] == "ممكن توضح أكثر؟"


def test_handle_out_of_scope(monkeypatch):
    install_fake_client(monkeypatch, _fake_generate_content("هذا خارج نطاق اختصاصي"))

    state = graph.handle_out_of_scope({"question": "شو الجو اليوم"})

    assert state["answer"] == "هذا خارج نطاق اختصاصي"
