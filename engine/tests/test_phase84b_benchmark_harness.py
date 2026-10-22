from engine.src.memo_engine.phase84b_benchmark import select_mistral_vision_model, synthetic_fixtures


def test_synthetic_pack_is_bounded_and_contains_no_private_material():
    fixtures = synthetic_fixtures()
    assert [item["id"] for item in fixtures] == [
        "numeric_working", "probability_tree", "venn_diagram", "question_vs_solution"
    ]
    assert len(fixtures) == 4
    assert all(len(item["image"]) < 100_000 for item in fixtures)
    assert all(item["question_ref"] for item in fixtures)


def test_mistral_selection_prefers_modest_current_account_visible_model():
    cards = [
        {"id": "mistral-large-2512", "vision_declared": True, "deprecated": False},
        {"id": "ministral-8b-2512", "vision_declared": True, "deprecated": False},
        {"id": "ministral-3b-2512", "vision_declared": True, "deprecated": False},
        {"id": "pixtral-old", "vision_declared": True, "deprecated": True},
    ]
    selected, candidates = select_mistral_vision_model(cards)
    assert selected == "ministral-3b-2512"
    assert "pixtral-old" not in candidates


def test_mistral_selection_never_invents_an_unlisted_model():
    selected, candidates = select_mistral_vision_model([
        {"id": "text-only-model", "vision_declared": False, "deprecated": False}
    ])
    assert selected is None
    assert candidates == []
