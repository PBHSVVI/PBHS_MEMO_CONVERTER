from engine.src.memo_engine.canonical import _content_segments, _marking_text


def test_teacher_content_override_replaces_segments_and_preserves_source_ref():
    source = [{
        "text": "old question and working",
        "source_ref": {"file_id": "source_1", "page": 2},
    }]
    question = {
        "content_override": {
            "correction_id": "corr-content",
            "question_text": "Corrected question",
            "solution_lines": ["First corrected step", "Final answer"],
        },
        "teacher_marking_text": "3A calculation\n1A answer",
    }

    result = _content_segments(question, source)

    assert [segment["text"] for segment in result] == [
        "Corrected question", "First corrected step", "Final answer",
    ]
    assert all(segment["source_ref"] == source[0]["source_ref"] for segment in result)
    assert all(segment["teacher_correction_id"] == "corr-content" for segment in result)
    assert _marking_text(question, {"marking_text": "old"}) == "3A calculation\n1A answer"


def test_source_content_is_unchanged_without_confirmed_override():
    source = [{"text": "original"}]
    assert _content_segments({}, source) is source
    assert _marking_text({}, {"marking_text": "old marks"}) == "old marks"


def test_item_tree_renders_teacher_content_and_marking():
    from engine.src.memo_engine.canonical import _build_item_tree

    question = {
        "question_id": "11.2.1",
        "source_block_index": 0,
        "printed_marks": 2,
        "computed_shorthand_marks": 2,
        "mark_calculation_mode": "additive",
        "mark_points": [
            {
                "count": 1, "code": "M", "descriptor": "method",
                "semantic": "method", "source": "1M method",
            },
            {
                "count": 1, "code": "A", "descriptor": "final answer",
                "semantic": "answer", "source": "1A final answer",
            },
        ],
        "teacher_marking_text": "1M method\n1A final answer",
        "content_override": {
            "correction_id": "corr-content",
            "question_text": "Corrected question wording",
            "solution_lines": ["Corrected method", "The final answer is 42"],
        },
    }
    source_ref = {"file_id": "source_1", "page": 1}
    issues = []
    items = _build_item_tree(
        11,
        {"11.2.1": question},
        {"11.2.1": [{"text": "old source", "source_ref": source_ref}]},
        {0: {"marking_text": "old marking"}},
        {},
        issues,
    )

    leaf = items[0]["children"][0]
    blocks = leaf["alternatives"][0]["blocks"]
    assert [block["text"] for block in blocks] == [
        "Corrected question wording", "Corrected method", "The final answer is 42",
    ]
    assert leaf["marks"] == {"observed": 2, "computed": 2, "status": "match"}
    assert len(leaf["alternatives"][0]["marking_points"]) == 2
    assert issues == []
