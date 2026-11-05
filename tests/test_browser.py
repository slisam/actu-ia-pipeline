"""Tests simulés du navigateur : aucun compte ni crédit Google n'est utilisé."""

import json
from contextlib import contextmanager

import pytest

from pipelineia import browser


class Locator:
    def __init__(self, items=None, text="", children=None):
        self.items = items if items is not None else []
        self.text = text
        self.children = children or {}
    def count(self):
        return len(self.items)
    @property
    def first(self):
        return self.items[0] if self.items else self
    @property
    def last(self):
        return self.items[-1] if self.items else self
    def nth(self, index):
        return self.items[index]
    def inner_text(self):
        return self.text
    def is_visible(self):
        return bool(self.items) or bool(self.text)
    def locator(self, selector):
        return self.children.get(selector, Locator())


class Page:
    url = browser.GEMINI_URL
    def __init__(self, response=""):
        content = Locator(text=response)
        last = Locator(children={browser.CONTENT_SELECTORS[0]: Locator([content])})
        self.responses = Locator([last]) if response else Locator()
        self.alerts = Locator()
        self.waits = 0
    def locator(self, selector):
        return self.responses if selector == browser.RESPONSES else Locator()
    def get_by_role(self, role, **_kwargs):
        return self.alerts if role == "alert" else Locator()
    def wait_for_timeout(self, _milliseconds):
        self.waits += 1


@pytest.mark.parametrize("text", ['{"ok":true}', '```json\n{"ok":true}\n```'])
def test_parses_only_json_object(text):
    assert browser.parse_response(text) == {"ok": True}


@pytest.mark.parametrize("text", ['[1,2]', 'Voici la réponse {"ok":true}', '{"incomplete":', 'x' * 100001],
                         ids=["array", "prose", "partial", "oversized"])
def test_rejects_incomplete_or_non_object_response(text):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        browser.parse_response(text)


def test_profile_is_dedicated_and_beneath_project_data(tmp_path):
    assert browser.profile_path({"project_root": str(tmp_path)}) == tmp_path / "data" / "google-browser"
    for path in ["../other-profile", str(tmp_path.parent / "personal"), "data"]:
        with pytest.raises(ValueError, match="sous-dossier dédié"):
            browser.profile_path({"project_root": str(tmp_path), "browser": {"profile_dir": path}})


def test_extracts_response_only_never_prompt_or_page_body():
    page = Page('{"title":"Une actualité"}')
    assert browser.extract_response(page) == '{"title":"Une actualité"}'
    assert browser.extract_response(Page()) == ""


def test_extracts_single_code_block_without_copy_button_labels():
    code = Locator(text='{"ok":true}')
    last = Locator(children={"pre code, code-block code": Locator([code])})
    page = Page()
    page.responses = Locator([last])
    assert browser.extract_response(page) == '{"ok":true}'


def test_waits_until_response_is_stable_and_parses(monkeypatch):
    page = Page('{"ok":true}')
    monkeypatch.setattr(browser.time, "monotonic", lambda: float(page.waits))
    assert browser.wait_for_response(page, {"browser": {"stable_seconds": 2}}) == {"ok": True}
    assert page.waits >= 2


def test_quota_interrupts_without_fallback():
    page = Page()
    page.alerts = Locator([Locator(text="Vous avez atteint votre limite de quota, réessayez plus tard")])
    with pytest.raises(RuntimeError, match="Quota"):
        browser._check_access(page)


def test_login_redirect_interrupts_without_exposing_credentials():
    page = Page()
    page.url = "https://accounts.google.com/ServiceLogin"
    with pytest.raises(RuntimeError, match="Connexion Google"):
        browser._check_access(page)


def test_timeout_does_not_invent_response(monkeypatch):
    page = Page()
    monkeypatch.setattr(browser.time, "monotonic", lambda: float(page.waits))
    with pytest.raises(RuntimeError, match="Délai"):
        browser.wait_for_response(page, {"browser": {"timeout_seconds": 10}})
    assert page.waits == 10


def test_generation_uses_visible_editor_and_no_existing_conversation(monkeypatch):
    class Editor:
        def wait_for(self, **kwargs):
            pass
        def fill(self, text):
            self.input = text
        def press(self, key):
            self.key = key
    class GeneratePage(Page):
        def __init__(self):
            super().__init__()
            self.editor = Editor()
        def goto(self, url, **_kwargs):
            assert url == browser.GEMINI_URL
        def locator(self, selector):
            if selector == browser.EDITOR:
                return Locator([self.editor])
            return super().locator(selector)
    page = GeneratePage()
    @contextmanager
    def session(_config):
        yield page
    monkeypatch.setattr(browser, "_session", session)
    monkeypatch.setattr(browser, "wait_for_response", lambda *_: {"ok": True})
    assert browser.browser_generate("Un prompt de rédaction", {}) == {"ok": True}
    assert page.editor.input == "Un prompt de rédaction"
    assert page.editor.key == "Enter"
    page.responses = Locator([Locator()])
    with pytest.raises(RuntimeError, match="ancienne conversation"):
        browser.browser_generate("Autre prompt", {})


def test_manual_login_saves_marker_only_after_ready_editor(monkeypatch, tmp_path):
    profile = tmp_path / "data" / "google-browser"
    profile.mkdir(parents=True)
    class LoginPage(Page):
        def goto(self, *_args, **_kwargs):
            pass
        def locator(self, selector):
            if selector == browser.EDITOR:
                return Locator([Locator(text="Champ prêt")])
            return super().locator(selector)
    @contextmanager
    def session(_config, **_kwargs):
        yield LoginPage()
    monkeypatch.setattr(browser, "_session", session)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    browser.login_browser({"project_root": str(tmp_path)})
    assert (profile / ".pipelineia-login").read_text().strip() == "configured"
