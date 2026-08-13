"""Static contracts for the Overview authoring and annotation interface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_overview_exposes_real_lavish_style_targets_and_source_routing():
    composer = (ROOT / "frontend/src/components/ViewPromptBar.tsx").read_text(encoding="utf-8")
    widgets = (ROOT / "frontend/src/components/ViewWidgets.tsx").read_text(encoding="utf-8")

    assert "Connected API" in composer
    assert "Agent harness" in composer
    assert "Copy grounded brief" in composer
    assert "views.validateCandidate" in composer
    assert "views.author" in composer
    assert "data-annotation-target" in widgets
    assert "Queue note" in widgets


def test_integrations_include_openrouter_and_generic_openai_compatible():
    catalog = (ROOT / "frontend/src/utils/providerCatalog.ts").read_text(encoding="utf-8")
    assert "id: 'openrouter'" in catalog
    assert "id: 'openai_compatible'" in catalog
    assert "default_model" in catalog
