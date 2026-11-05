"""Intégration du pool API sans appel réseau, navigateur ni quota réel."""

from __future__ import annotations

import copy
import json
import logging
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from pipelineia import __main__ as cli
from pipelineia import writer
from pipelineia.config import load_config
from tests.test_writer import ARTICLES, valid_script, verification


@pytest.fixture
def config(tmp_path):
    """Quatre identifiants de secours, avec budget partagé entre leurs appels."""
    return {"project_root": str(tmp_path), "timezone": "Europe/Paris",
            "paths": {"state_db": str(tmp_path / "data/state.sqlite3"),
                      "logs": str(tmp_path / "logs"), "output": str(tmp_path / "output")},
            "llm": {"provider": "api_pool", "model": "configured-gemini-model",
                    "max_requests_per_run": 4, "max_http_attempts_per_run": 8,
                    "daily_request_limit": 12, "max_output_tokens": 3000,
                    "api_pool": [{"id": f"google_{i}", "provider": "gemini",
                                  "api_key_env": f"POOL_TEST_API_KEY_{i}",
                                  "quota_group": f"project_{i}", "free_tier_confirmed": True}
                                 for i in range(1, 5)]},
            "speech": {"provider": "espeak"},
            "video": {"duration_seconds": 60, "formats": {"vertical": {"width": 1080, "height": 1920}}},
            "publishing": {"platforms": []}}


@pytest.fixture
def fake_pool_module(monkeypatch):
    """Remplace exclusivement la frontière pool, tout le rédacteur reste réel."""
    module = types.ModuleType("pipelineia.llm_pool")

    class PoolError(RuntimeError):
        """Message fixe dont le code appelant peut afficher le contenu."""

    class APIPool:
        instances = []
        replies = []
        attempts_per_generate = 1
        fail_after_http = None

        def __init__(self, settings):
            self.config = settings
            self.requests = 0
            self.prompts = []
            self.instances.append(self)

        def generate(self, prompt):
            if self.fail_after_http is not None and self.requests >= self.fail_after_http:
                raise PoolError("Budget HTTP partagé atteint ; aucun autre compte appelé.")
            self.requests += self.attempts_per_generate
            self.prompts.append(prompt)
            value = self.replies.pop(0)
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)

    module.APIPool = APIPool
    module.PoolError = PoolError
    module.readiness = lambda settings: {item["id"]: {"ready": True, "configured": True}
                                        for item in settings["llm"]["api_pool"]}
    monkeypatch.setitem(sys.modules, "pipelineia.llm_pool", module)
    return module


def test_writer_reuses_one_pool_for_draft_and_separate_evidence_verification(config, fake_pool_module, monkeypatch):
    script = valid_script()
    fake_pool_module.APIPool.replies = [script, verification(script)]
    fake_pool_module.APIPool.attempts_per_generate = 2
    for legacy in ("_cli", "_api"):
        monkeypatch.setattr(writer._Generator, legacy, lambda *_: pytest.fail("Aucun fournisseur de repli autorisé"))
    from pipelineia import browser
    monkeypatch.setattr(browser, "browser_generate", lambda *_: pytest.fail("Aucun navigateur autorisé"))
    result = writer.write_script(ARTICLES, config)
    assert result["verification"]["supported"] is True
    assert result["llm_requests"] == 2
    assert len(fake_pool_module.APIPool.instances) == 1
    pool = fake_pool_module.APIPool.instances[0]
    assert pool.config is config
    assert pool.requests == 4  # Deux tentatives HTTP simulées par appel logique.
    assert len(pool.prompts) == 2
    assert "ARTICLES_JSON" in pool.prompts[0]
    assert "SCRIPT_JSON" in pool.prompts[1]
    assert QUOTE_IN_SCRIPT(result) in pool.prompts[1]


def QUOTE_IN_SCRIPT(script):
    """Prélève une preuve contrôlée pour vérifier son passage au vérificateur."""
    return script["scenes"][0]["evidence"][0]["quote"]


def test_editorial_retry_keeps_same_pool_and_does_not_reset_http_budget(config, fake_pool_module, monkeypatch):
    script = valid_script()
    rejected = verification(script)
    rejected["checks"][0]["supported"] = False
    fake_pool_module.APIPool.replies = [script, rejected, script, verification(script)]
    monkeypatch.setattr(writer.time, "sleep", lambda _: None)
    result = writer.write_script(ARTICLES, config)
    assert result["llm_requests"] == 4
    assert len(fake_pool_module.APIPool.instances) == 1
    assert fake_pool_module.APIPool.instances[0].requests == 4


def test_writer_logical_request_limit_is_not_reset_for_each_call(config, fake_pool_module):
    config["llm"]["max_requests_per_run"] = 2
    fake_pool_module.APIPool.replies = [{"one": True}, {"two": True}]
    fake_pool_module.APIPool.attempts_per_generate = 2
    generator = writer._Generator(config)
    assert generator.generate("premier") == {"one": True}
    assert generator.generate("deuxième") == {"two": True}
    with pytest.raises(writer.WriterError, match="Budget"):
        generator.generate("troisième")
    assert generator.requests == 2
    assert len(fake_pool_module.APIPool.instances) == 1
    assert generator.pool.requests == 4


def test_http_budget_error_stops_editorial_pipeline_without_new_pool(config, fake_pool_module):
    fake_pool_module.APIPool.replies = [valid_script()]
    fake_pool_module.APIPool.attempts_per_generate = 2
    fake_pool_module.APIPool.fail_after_http = 2
    with pytest.raises(writer.WriterError, match="Budget HTTP partagé"):
        writer.write_script(ARTICLES, config)
    assert len(fake_pool_module.APIPool.instances) == 1
    assert fake_pool_module.APIPool.instances[0].requests == 2
    assert len(fake_pool_module.APIPool.instances[0].prompts) == 1


def test_pool_quota_error_is_exposed_safely_and_no_verifier_is_called(config, fake_pool_module):
    fake_pool_module.APIPool.replies = [fake_pool_module.PoolError("Tous les projets Gemini sont indisponibles.")]
    with pytest.raises(writer.WriterError, match="Tous les projets Gemini"):
        writer.write_script(ARTICLES, config)
    assert len(fake_pool_module.APIPool.instances) == 1
    assert fake_pool_module.APIPool.instances[0].requests == 1


def test_doctor_pool_readiness_requires_no_browser_cli_or_network(config, fake_pool_module, monkeypatch, caplog):
    for index in range(1, 5):
        monkeypatch.setenv(f"POOL_TEST_API_KEY_{index}", f"secret-api-key-value-{index}")
    monkeypatch.setattr(cli, "ffmpeg_binary", lambda: "ffmpeg-local")
    process = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(cli.subprocess, "run", process)
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/local/espeak" if command in {"espeak", "espeak-ng"} else None)
    fake_pool_module.readiness = Mock(wraps=fake_pool_module.readiness)
    with caplog.at_level(logging.INFO):
        assert cli.doctor(config) == 0
    fake_pool_module.readiness.assert_called_once_with(config)
    process.assert_called_once_with(["ffmpeg-local", "-version"], capture_output=True, timeout=20)
    assert len(fake_pool_module.APIPool.instances) == 0
    assert "google_1" in caplog.text and "google_4" in caplog.text
    assert "secret-api-key-value" not in caplog.text


def test_doctor_reports_missing_pool_credentials_without_generating(config, fake_pool_module, monkeypatch):
    fake_pool_module.readiness = lambda _: {"google_1": {"ready": False, "missing": "POOL_TEST_API_KEY_1"}}
    monkeypatch.setattr(cli, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: Mock(returncode=0))
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/local/espeak")
    assert cli.doctor(config) == 2
    assert fake_pool_module.APIPool.instances == []


def test_config_accepts_api_pool_without_browser_settings_or_credentials(config, tmp_path, monkeypatch):
    config.pop("browser", None)
    for index in range(1, 5):
        monkeypatch.delenv(f"POOL_TEST_API_KEY_{index}", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    result = load_config(path)
    assert result["llm"]["provider"] == "api_pool"
    assert "browser" not in result
    assert len(result["llm"]["api_pool"]) == 4
