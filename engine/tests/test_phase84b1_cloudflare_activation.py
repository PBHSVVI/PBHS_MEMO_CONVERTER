import json

from engine.src.memo_engine import phase84b1_cloudflare_activation as activation
from engine.src.memo_engine.provider_fabric import CLOUDFLARE_FREE_VISION_MODELS


def test_model_selection_uses_only_visible_approved_free_vision_models():
    selected, eligible = activation.select_free_vision_model([
        {"id": "@cf/qwen/qwen3.8-27b", "vision_declared": True},
        {"id": "@cf/google/gemma-4-26b-a4b-it", "vision_declared": True},
        {"id": "@cf/paid/example", "vision_declared": True},
        {"id": "@cf/text/example", "vision_declared": False},
    ])
    assert selected == "@cf/google/gemma-4-26b-a4b-it"
    assert eligible == ["@cf/google/gemma-4-26b-a4b-it", "@cf/qwen/qwen3.8-27b"]
    assert set(eligible) <= CLOUDFLARE_FREE_VISION_MODELS


def test_unlisted_or_nonvision_models_are_never_selected():
    assert activation.select_free_vision_model([
        {"id": "@cf/paid/example", "vision_declared": True},
        {"id": "@cf/text/example", "vision_declared": False},
    ]) == (None, [])


def test_allowlisted_vision_model_does_not_depend_on_incomplete_catalogue_badge():
    assert activation.select_free_vision_model([
        {"id": "@cf/google/gemma-4-26b-a4b-it", "vision_declared": False},
    ])[0] == "@cf/google/gemma-4-26b-a4b-it"


def test_model_card_parser_accepts_current_name_and_nested_property_shapes():
    assert activation._model_id({"name": "@cf/qwen/qwen3.8-27b"}) == "@cf/qwen/qwen3.8-27b"
    assert activation._model_id({"properties": {"name": "@cf/google/gemma-4-26b-a4b-it"}}) == "@cf/google/gemma-4-26b-a4b-it"
    assert activation._vision_declared({"task": {"name": "image-to-text"}}) is True


def test_safe_error_projection_excludes_credentials():
    payload = {"errors": [{"code": 7003, "message": "No route for that URI"}]}
    assert activation._safe_errors(payload) == [{"code": 7003, "message": "No route for that URI"}]
    redacted = activation._safe_message("Authorization: Bearer should never be emitted")
    assert redacted == "Cloudflare returned a redacted credential-related message."
    assert "Bearer" not in json.dumps({"message": redacted})
