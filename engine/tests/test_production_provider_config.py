from __future__ import annotations

from pathlib import Path

import pytest

from engine.src.memo_engine import cli, provider_fabric
from engine.src.memo_engine.provider_fabric import ProviderConfigurationError


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "process-memo.yml"


def _accepted_env() -> dict[str, str]:
    return {
        "MEMO_CLOUDFLARE_VISION_MODEL": "@cf/google/gemma-4-26b-a4b-it",
        "MEMO_CLOUDFLARE_STRUCTURER_MODEL": (
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        ),
        "MEMO_CLOUDFLARE_COMPOSITE_VISUAL_ENABLED": "true",
        "CLOUDFLARE_ACCOUNT_ID": "synthetic-account-id",
        "CLOUDFLARE_AI_API_TOKEN": "synthetic-token",
        "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
        "CLOUDFLARE_WORKERS_AI_PLAN_MODE": "free_only",
        "MEMO_APPROVED_PROVIDERS": "groq,cloudflare,mistral",
        "MEMO_VISUAL_PROVIDER_ORDER": "groq,cloudflare,mistral",
        "GROQ_API_KEY": "synthetic-groq-key",
        "GROQ_ZERO_COST_CONFIRMED": "true",
        "GROQ_PLAN_MODE": "free_only",
        "MEMO_GROQ_VISION_MODEL": "qwen/qwen3.8-27b",
        "MISTRAL_SCHOOL_PRIVATE_APPROVED": "false",
        "MEMO_MISTRAL_VISION_MODEL": "pixtral-synthetic",
        "MISTRAL_API_KEY": "synthetic-mistral-key",
        "MISTRAL_ZERO_COST_CONFIRMED": "true",
        "MISTRAL_PLAN_MODE": "free_only",
    }


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("MEMO_CLOUDFLARE_VISION_MODEL", "vars.MEMO_CLOUDFLARE_VISION_MODEL"),
        (
            "MEMO_CLOUDFLARE_STRUCTURER_MODEL",
            "vars.MEMO_CLOUDFLARE_STRUCTURER_MODEL",
        ),
        (
            "MEMO_CLOUDFLARE_COMPOSITE_VISUAL_ENABLED",
            "vars.MEMO_CLOUDFLARE_COMPOSITE_VISUAL_ENABLED",
        ),
    ],
)
def test_process_memo_maps_composite_repository_variables(name, source):
    text = _workflow()
    assert f"{name}: ${{{{ {source} }}}}" in text
    assert "@cf/google/gemma" not in text
    assert "@cf/meta/llama-3.3" not in text


def test_process_memo_keeps_cloudflare_credentials_in_github_secrets():
    text = _workflow()
    assert "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}" in text
    assert "CLOUDFLARE_AI_API_TOKEN: ${{ secrets.CLOUDFLARE_AI_API_TOKEN }}" in text


def test_process_memo_runs_preflight_before_worker():
    text = _workflow()
    preflight = "python -m engine.src.memo_engine.cli validate-provider-config"
    worker = 'python -m engine.src.memo_engine.cli run-job "$MEMO_JOB_ID"'
    assert text.index(preflight) < text.index(worker)


def test_accepted_production_configuration_passes():
    summary = provider_fabric.validate_production_provider_configuration(
        _accepted_env()
    )
    assert summary == {
        "status": "passed",
        "cloudflare_composite_enabled": True,
        "vision_model": "@cf/google/gemma-4-26b-a4b-it",
        "structurer_model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "cloudflare_free_only": True,
        "provider_order": ["groq", "cloudflare", "mistral"],
        "effective_school_private_route": ["groq", "cloudflare", "defer"],
        "mistral_school_private_eligible": False,
    }


@pytest.mark.parametrize(
    "missing_name",
    ["MEMO_CLOUDFLARE_VISION_MODEL", "MEMO_CLOUDFLARE_STRUCTURER_MODEL"],
)
def test_enabled_composite_requires_both_model_ids(missing_name):
    values = _accepted_env()
    values.pop(missing_name)
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_REQUIRED_VALUE_MISSING"


def test_enabled_composite_rejects_invalid_structurer():
    values = _accepted_env()
    values["MEMO_CLOUDFLARE_STRUCTURER_MODEL"] = "@cf/example/not-approved"
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_STRUCTURER_MODEL_INELIGIBLE"


def test_enabled_composite_rejects_invalid_vision_model():
    values = _accepted_env()
    values["MEMO_CLOUDFLARE_VISION_MODEL"] = "@cf/example/not-vision"
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_VISION_MODEL_INELIGIBLE"


def test_enabled_composite_requires_zero_cost_confirmation():
    values = _accepted_env()
    values["CLOUDFLARE_ZERO_COST_CONFIRMED"] = "false"
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_ZERO_COST_UNCONFIRMED"


def test_enabled_composite_requires_free_only_plan():
    values = _accepted_env()
    values["CLOUDFLARE_WORKERS_AI_PLAN_MODE"] = "paid"
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_PLAN_NOT_FREE_ONLY"


@pytest.mark.parametrize("credential", ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_API_TOKEN"])
def test_enabled_composite_requires_cloudflare_credentials(credential):
    values = _accepted_env()
    values.pop(credential)
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_REQUIRED_VALUE_MISSING"


def test_enabled_composite_requires_cloudflare_approval():
    values = _accepted_env()
    values["MEMO_APPROVED_PROVIDERS"] = "groq,mistral"
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_CLOUDFLARE_NOT_APPROVED"


def test_enabled_composite_requires_cloudflare_in_provider_order():
    values = _accepted_env()
    values["MEMO_VISUAL_PROVIDER_ORDER"] = "groq,mistral"
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_ROUTE_INCOMPLETE"


def test_enabled_composite_requires_cloudflare_after_groq():
    values = _accepted_env()
    values["MEMO_VISUAL_PROVIDER_ORDER"] = "cloudflare,groq,mistral"
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_ROUTE_ORDER_INVALID"


def test_mistral_remains_school_private_ineligible():
    values = _accepted_env()
    registry = provider_fabric.default_provider_registry(values)
    assert provider_fabric.provider_ineligibility_reason(
        registry["mistral"],
        task_type=provider_fabric.TASK_VISUAL_INTERPRETATION,
        privacy_classification=provider_fabric.PRIVACY_SCHOOL_PRIVATE,
        env=values,
    ) == "privacy_ineligible"


def test_preflight_rejects_mistral_private_approval():
    values = _accepted_env()
    values["MISTRAL_SCHOOL_PRIVATE_APPROVED"] = "true"
    with pytest.raises(ProviderConfigurationError) as caught:
        provider_fabric.validate_production_provider_configuration(values)
    assert caught.value.code == "PROVIDER_CONFIG_MISTRAL_PRIVATE_ENABLED"


def test_disabled_composite_does_not_require_composite_configuration():
    summary = provider_fabric.validate_production_provider_configuration({
        "MEMO_CLOUDFLARE_COMPOSITE_VISUAL_ENABLED": "false",
        "MISTRAL_SCHOOL_PRIVATE_APPROVED": "false",
        "MEMO_VISUAL_PROVIDER_ORDER": "groq,cloudflare,mistral",
    })
    assert summary["status"] == "passed"
    assert summary["cloudflare_composite_enabled"] is False


def test_accepted_registry_exposes_free_cloudflare_composite():
    values = _accepted_env()
    cloudflare = provider_fabric.default_provider_registry(values)["cloudflare"]
    assert cloudflare.enabled is True
    assert "composite_visual" in cloudflare.capabilities
    assert cloudflare.plan_mode == provider_fabric.FREE_ONLY_PLAN_MODE
    assert cloudflare.requires_paid_plan is False
    assert cloudflare.automatic_overage_possible is False


def test_accepted_effective_route_is_groq_cloudflare_then_defer():
    summary = provider_fabric.validate_production_provider_configuration(
        _accepted_env()
    )
    assert summary["effective_school_private_route"] == [
        "groq", "cloudflare", "defer"
    ]


def test_preflight_does_not_invoke_provider_adapters(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("provider adapter must not run during configuration preflight")

    monkeypatch.setattr(provider_fabric, "groq_visual_adapter", forbidden)
    monkeypatch.setattr(provider_fabric, "cloudflare_composite_visual_adapter", forbidden)
    monkeypatch.setattr(provider_fabric, "mistral_visual_adapter", forbidden)
    assert provider_fabric.validate_production_provider_configuration(
        _accepted_env()
    )["status"] == "passed"


def test_cli_preflight_logs_no_credentials(monkeypatch, capsys):
    values = _accepted_env()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert cli.main(["memo-engine", "validate-provider-config"]) == 0
    output = capsys.readouterr()
    combined = output.out + output.err
    assert values["CLOUDFLARE_ACCOUNT_ID"] not in combined
    assert values["CLOUDFLARE_AI_API_TOKEN"] not in combined
    assert values["GROQ_API_KEY"] not in combined
    assert "effective_school_private_route" in combined
