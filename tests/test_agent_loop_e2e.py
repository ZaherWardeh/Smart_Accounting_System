import graph
from fakes import FakeFunctionCall, FakePart, FakeResponse, install_fake_client


def test_agent_loop_resolves_account_then_answers(monkeypatch, seeded_db):
    calls = []

    def fake_generate_content(model, contents, config=None):
        calls.append(contents)
        if len(calls) == 1:
            fc = FakeFunctionCall(name="get_chart_of_accounts", args={})
            return FakeResponse(parts=[FakePart(function_call=fc)])
        if len(calls) == 2:
            fc = FakeFunctionCall(name="get_account_balance", args={"acc_ids": [2]})
            return FakeResponse(parts=[FakePart(function_call=fc)])
        return FakeResponse(parts=[FakePart()], text="رصيد الصندوق هو 800 مدين.")

    install_fake_client(monkeypatch, fake_generate_content)

    state = graph.agent_loop({"question": "شو رصيد الصندوق؟", "intent": "Accounting Inquiry"}, seeded_db)

    assert state["answer"] == "رصيد الصندوق هو 800 مدين."
    assert len(calls) == 3
    # the function-call turn and the tool-response turn were both appended
    assert len(state["messages"]) == 1 + 2 * 2


def test_agent_loop_stops_at_max_rounds_without_crashing(monkeypatch, seeded_db):
    def fake_generate_content(model, contents, config=None):
        fc = FakeFunctionCall(name="get_chart_of_accounts", args={})
        return FakeResponse(parts=[FakePart(function_call=fc)], text=None)

    install_fake_client(monkeypatch, fake_generate_content)

    state = graph.agent_loop({"question": "...", "intent": "Data Request"}, seeded_db)

    assert state["answer"]


def test_agent_loop_unknown_tool_call_reports_error_without_crashing(monkeypatch, seeded_db):
    calls = []

    def fake_generate_content(model, contents, config=None):
        calls.append(contents)
        if len(calls) == 1:
            fc = FakeFunctionCall(name="not_a_real_tool", args={})
            return FakeResponse(parts=[FakePart(function_call=fc)])
        return FakeResponse(parts=[FakePart()], text="لم أتمكن من إيجاد المعلومة المطلوبة.")

    install_fake_client(monkeypatch, fake_generate_content)

    state = graph.agent_loop({"question": "؟", "intent": "Data Request"}, seeded_db)

    assert state["answer"] == "لم أتمكن من إيجاد المعلومة المطلوبة."
