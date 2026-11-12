import pytest

from scripts.draw_topology import (
    _add_role_colors,
    _set_default_text_color,
    _set_start_node_style,
)


def test_default_node_text_color_is_dark_and_preserves_existing_styles():
    mermaid = "graph TD;\n  classDef default fill:#f2f0ff,line-height:1.2"

    result = _set_default_text_color(mermaid)

    assert (
        "classDef default color:#222,fill:#f2f0ff,line-height:1.2"
        in result
    )


def test_default_node_text_color_is_not_duplicated():
    mermaid = "classDef default color:#222,fill:#f2f0ff"

    assert _set_default_text_color(mermaid) == mermaid


def test_missing_default_style_fails_explicitly():
    with pytest.raises(RuntimeError, match="no default class definition"):
        _set_default_text_color("graph TD;\n  A --> B")


def test_start_node_is_not_transparent():
    result = _set_start_node_style("classDef first fill-opacity:0")

    assert (
        "classDef first fill:#dbeafe,stroke:#2563eb,color:#222,fill-opacity:1"
        in result
    )


def test_missing_first_class_fails_explicitly():
    with pytest.raises(RuntimeError, match="no first-node class definition"):
        _set_start_node_style("graph TD;\n  A --> B")


def test_role_colors_cover_each_topology_group():
    result = _add_role_colors("graph TD;\n  ContextBuilder --> DocAnalyst")

    assert "classDef setup fill:#dbeafe,stroke:#2563eb,color:#222" in result
    assert "class ContextBuilder setup" in result
    assert "class RepoInvestigator,DocAnalyst,VisionInspector detectives" in result
    assert "class EvidenceAggregator aggregation" in result
    assert "class JudicialDispatch dispatch" in result
    assert "class Prosecutor,Defense,TechLead judges" in result
    assert "class ChiefJustice justice" in result
    assert "class ErrorReport error" in result
