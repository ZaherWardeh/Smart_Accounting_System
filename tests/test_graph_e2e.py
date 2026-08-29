import json

import graph
from fakes import FakeFunctionCall, FakePart, FakeResponse, install_fake_client


def test_full_graph_routes_data_question_through_tool_calls(monkeypatch, seeded_db):
    """classify_intent -> route -> agent_loop, with two scripted tool-call
    rounds before the model settles on a final answer."""
    calls = []

    def fake_generate_content(model, contents, config=None):
        calls.append(config)
        if len(calls) == 1:
            return FakeResponse(
                parts=[],
                text=json.dumps({"intent": "Accounting Inquiry", "confidence": "high", "reason": "balance question"}),
            )
        if len(calls) == 2:
            fc = FakeFunctionCall(name="get_chart_of_accounts", args={})
            return FakeResponse(parts=[FakePart(function_call=fc)])
        if len(calls) == 3:
            fc = FakeFunctionCall(name="get_account_balance", args={"acc_ids": [2]})
            return FakeResponse(parts=[FakePart(function_call=fc)])
        return FakeResponse(parts=[FakePart()], text="رصيد الصندوق 800 مدين.")

    install_fake_client(monkeypatch, fake_generate_content)

    answer = graph.run_agent(seeded_db, "شو رصيد الصندوق؟")

    assert answer == "رصيد الصندوق 800 مدين."
    assert len(calls) == 4
    # classify_intent never binds tools; agent_loop always does
    assert calls[0] is None
    assert all(c is not None for c in calls[1:])


def test_full_graph_routes_greeting_without_touching_tools(monkeypatch, seeded_db):
    def fake_generate_content(model, contents, config=None):
        assert config is None, "greeting path should never bind tools"
        if isinstance(contents[0], dict) and "تحليل نية" in contents[0]["parts"][0]["text"]:
            return FakeResponse(parts=[], text=json.dumps({"intent": "Greeting", "confidence": "high", "reason": "greeting"}))
        return FakeResponse(parts=[], text="أهلاً وسهلاً!")

    install_fake_client(monkeypatch, fake_generate_content)

    answer = graph.run_agent(seeded_db, "مرحبا")

    assert answer == "أهلاً وسهلاً!"


def test_full_graph_routes_low_confidence_to_ambiguous(monkeypatch, seeded_db):
    def fake_generate_content(model, contents, config=None):
        if isinstance(contents[0], dict) and "تحليل نية" in contents[0]["parts"][0]["text"]:
            return FakeResponse(parts=[], text=json.dumps({"intent": "Data Request", "confidence": "low", "reason": "unclear"}))
        return FakeResponse(parts=[], text="ممكن تعيد صياغة السؤال؟")

    install_fake_client(monkeypatch, fake_generate_content)

    answer = graph.run_agent(seeded_db, "بدي شي")

    assert answer == "ممكن تعيد صياغة السؤال؟"
