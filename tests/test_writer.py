"""Les scripts restent sourcés et ne passent pas un contrôle partiel."""

import copy
import json
import subprocess

import pytest

from pipelineia import writer

QUOTE = "Le laboratoire annonce un nouveau modèle ouvert"
ARTICLES = [{"id": "s1", "title": "Annonce du laboratoire", "url": "https://news.example/one",
             "published_at": "2026-11-05T08:00:00+00:00", "source": "Laboratoire",
             "text": QUOTE + ". " + "Le modèle est présenté dans une publication avec des limites à vérifier. " * 30}]


def valid_script():
    narrations = [
        "Voici ce que change cette annonce pour les modèles ouverts. Le laboratoire annonce un nouveau modèle ouvert dans une publication officielle. Son texte présente le projet et les limites de cette annonce.",
        "Pour comprendre cette nouvelle, il faut revenir à la source. Le laboratoire décrit son modèle et la façon dont il souhaite le présenter. Cette vidéo reprend les éléments de cette publication officielle.",
        "Les affirmations du laboratoire doivent être lues avec leur contexte. La publication constitue une annonce de son éditeur. Elle ne suffit pas à confirmer une supériorité face aux autres modèles disponibles.",
        "La suite consiste à examiner les limites indiquées dans cette publication. Pour se faire une idée du modèle annoncé, il faut donc consulter la source et distinguer les promesses des résultats vérifiés.",
    ]
    return {"title": "Un laboratoire annonce un modèle ouvert", "hook": "Voici ce que change cette annonce pour les modèles ouverts.",
            "scenes": [{"narration": text, "on_screen": "Une annonce à examiner avec ses limites",
                        "source_ids": ["s1"], "evidence": [{"source_id": "s1", "quote": QUOTE}]}
                       for text in narrations]}


def verification(script):
    return {"supported": True, "title_supported": True, "hook_supported": True,
            "checks": [{"scene": i + 1, "supported": True, "reason": "Attribué à la publication"}
                       for i in range(len(script["scenes"]))]}


def test_valid_script_replaces_llm_source_urls():
    script = valid_script()
    script["sources"] = [{"url": "https://invented.example"}]
    result = writer.validate_script(script, ARTICLES)
    assert 120 <= result["word_count"] <= 155
    assert result["sources"][0]["url"] == ARTICLES[0]["url"]


def test_rejects_invented_quote():
    script = valid_script()
    script["scenes"][1]["evidence"][0]["quote"] = "Le modèle bat tous les concurrents"
    with pytest.raises(ValueError, match="citation exacte"):
        writer.validate_script(script, ARTICLES)


def test_rejects_short_or_unhooked_script():
    script = valid_script()
    script["scenes"][0]["narration"] = "Une narration sans accroche."
    with pytest.raises(ValueError, match="hook"):
        writer.validate_script(script, ARTICLES)
    script = valid_script()
    for scene in script["scenes"]:
        scene["narration"] = script["hook"]
    with pytest.raises(ValueError, match="Durée orale"):
        writer.validate_script(script, ARTICLES)


def test_rejects_multiple_news_in_one_episode():
    script = valid_script()
    second = dict(ARTICLES[0], id="s2")
    script["scenes"][1]["source_ids"] = ["s2"]
    script["scenes"][1]["evidence"][0]["source_id"] = "s2"
    with pytest.raises(ValueError, match="seule actualité"):
        writer.validate_script(script, ARTICLES + [second])


def test_verification_requires_all_scenes_and_title():
    script = valid_script()
    check = verification(script)
    check["checks"].pop()
    with pytest.raises(ValueError, match="chaque scène"):
        writer._validate_verification(check, script)
    check = verification(script)
    check["title_supported"] = False
    with pytest.raises(ValueError, match="rejeté"):
        writer._validate_verification(check, script)


def test_write_script_requires_separate_successful_verification(monkeypatch):
    script = valid_script()
    responses = iter([script, verification(script)])
    def generate(self, _prompt):
        self.requests += 1
        return next(responses)
    monkeypatch.setattr(writer._Generator, "generate", generate)
    result = writer.write_script(ARTICLES, {"llm": {"generation_attempts": 1}})
    assert result["verification"]["supported"] is True
    assert result["llm_requests"] == 2


def test_verifier_can_block_plausible_but_unsupported_script(monkeypatch):
    script = valid_script()
    check = verification(script)
    check["checks"][2]["supported"] = False
    responses = iter([script, check])
    monkeypatch.setattr(writer._Generator, "generate", lambda *_: next(responses))
    with pytest.raises(ValueError, match="bloqué"):
        writer.write_script(ARTICLES, {"llm": {"generation_attempts": 1}})


def test_budget_and_no_paid_fallback(monkeypatch):
    generator = writer._Generator({"llm": {"model": "example-model", "max_requests_per_run": 2}})
    generator.requests = 2
    with pytest.raises(RuntimeError, match="Budget"):
        generator.generate("texte")
    monkeypatch.setattr(writer.shutil, "which", lambda *_: None)
    generator.requests = 0
    with pytest.raises(RuntimeError, match="CLI absent"):
        generator.generate("texte")


def test_cli_uses_cached_oauth_but_blocks_tools_hooks_extensions_and_api_keys(monkeypatch, tmp_path):
    home = tmp_path / "account"
    (home / ".gemini").mkdir(parents=True)
    (home / ".gemini" / "oauth_creds.json").write_text("{}")
    monkeypatch.setenv("GEMINI_CLI_HOME", str(home))
    monkeypatch.setenv("GEMINI_API_KEY", "never-sent")
    monkeypatch.setenv("GOOGLE_GENAI_USE_GCA", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_ACCESS_TOKEN", "never-sent-either")
    monkeypatch.setattr(writer.shutil, "which", lambda *_: "gemini")
    from pathlib import Path
    def run(command, **kwargs):
        assert command[command.index("--extensions") + 1] == "none"
        policy = Path(command[command.index("--admin-policy") + 1]).read_text()
        assert 'toolName = "*"' in policy and 'decision = "deny"' in policy
        assert kwargs["shell"] is False
        assert "GEMINI_API_KEY" not in kwargs["env"]
        assert "GOOGLE_GENAI_USE_GCA" not in kwargs["env"]
        assert "GOOGLE_CLOUD_ACCESS_TOKEN" not in kwargs["env"]
        assert kwargs["env"]["NO_BROWSER"] == "true"
        settings = json.loads((Path(kwargs["cwd"]) / ".gemini" / "settings.json").read_text())
        assert "GEMINI_CLI_SYSTEM_SETTINGS_PATH" not in kwargs["env"]
        assert settings["hooksConfig"]["enabled"] is False
        assert settings["mcp"]["allowed"] == ["pipelineia-no-mcp-server"]
        assert settings["admin"]["mcp"]["enabled"] is False
        assert settings["admin"]["extensions"]["enabled"] is False
        assert (Path(kwargs["cwd"]) / ".gemini" / ".env").read_text() == ""
        assert settings["model"]["maxSessionTurns"] == 1
        assert command[command.index("--model") + 1] == "auto"
        assert "customAliases" not in settings["modelConfigs"]
        assert kwargs["input"] == "Les données du sujet"
        return subprocess.CompletedProcess(command, 0, json.dumps({"response": '{"ok":true}'}), "")
    monkeypatch.setattr(subprocess, "run", run)
    generator = writer._Generator({"llm": {"model": "example-model"}})
    assert generator.generate("Les données du sujet") == {"ok": True}


def test_cli_model_is_independent_of_paid_api_model(monkeypatch):
    calls = []
    monkeypatch.setattr(writer._Generator, "_cli", lambda self, prompt, model: calls.append(model) or {"ok": True})
    generator = writer._Generator({"llm": {"provider": "gemini_cli", "model": "paid-api-model", "cli_model": "flash"}})
    assert generator.generate("texte") == {"ok": True}
    assert calls == ["flash"]


def test_cli_missing_login_fails_before_launching_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path))
    monkeypatch.setattr(writer.shutil, "which", lambda *_: "gemini")
    def never_run(*args, **kwargs):
        raise AssertionError("Aucune tentative de connexion interactive autorisée")
    monkeypatch.setattr(subprocess, "run", never_run)
    with pytest.raises(RuntimeError, match="Connexion Google CLI absente"):
        writer._Generator({"llm": {"provider": "gemini_cli"}}).generate("texte")


def test_browser_provider_does_not_require_api_model_or_key(monkeypatch):
    from pipelineia import browser
    calls = []
    monkeypatch.setattr(browser, "browser_generate", lambda prompt, config: calls.append((prompt, config)) or {"ok": True})
    config = {"llm": {"provider": "gemini_browser"}, "browser": {"channel": "msedge"}}
    assert writer._Generator(config).generate("Texte du sujet") == {"ok": True}
    assert calls == [("Texte du sujet", config)]


def test_empty_articles_fail_before_any_model_request():
    with pytest.raises(ValueError, match="Aucune actualité"):
        writer.write_script([], {})
