"""Fakes for scripting the Gemini client shape (candidates/content/parts) in
tests, without depending on a live API key or network."""

import types


class FakeFunctionCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class FakePart:
    def __init__(self, function_call=None):
        self.function_call = function_call


class FakeContent:
    def __init__(self, parts):
        self.parts = parts


class FakeCandidate:
    def __init__(self, content):
        self.content = content


class FakeResponse:
    def __init__(self, parts, text=None):
        self.candidates = [FakeCandidate(FakeContent(parts))]
        self.text = text


def install_fake_client(monkeypatch, generate_content_fn):
    fake_client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate_content_fn))
    monkeypatch.setattr("graph.client", fake_client)
    return fake_client
