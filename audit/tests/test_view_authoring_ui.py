"""Static contracts for the Overview authoring and annotation interface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_overview_exposes_real_lavish_style_targets_and_source_routing():
    composer = (ROOT / "frontend/src/components/ViewPromptBar.tsx").read_text(encoding="utf-8")
    widgets = (ROOT / "frontend/src/components/ViewWidgets.tsx").read_text(encoding="utf-8")

    assert "Connected API" in composer
    assert "Agent harness" in composer
    assert "Copy grounded brief" in composer
    assert "views.createProposal" in composer
    assert "views.openProposal(view.id)" in composer
    assert "views.grounding(view.id)" in composer
    assert "ready_to_apply" in composer
    assert "Current result" in composer and "Proposed result" in composer
    assert "Generate proposal" in composer
    assert "Apply reviewed proposal" in composer
    assert "views.author(view.id" in composer
    assert "views.author(view.id, {\n          source: 'connection'" not in composer
    assert "views.author" in composer
    assert "queryKey: ['view-open-proposal', view.id]" in composer
    assert "enabled: !activeJobId" in composer
    assert "enabled: source === 'harness' && !activeJobId" not in composer
    assert "data-annotation-target" in widgets
    assert "Queue note" in widgets


def test_integrations_include_openrouter_and_generic_openai_compatible():
    catalog = (ROOT / "frontend/src/utils/providerCatalog.ts").read_text(encoding="utf-8")
    assert "id: 'openrouter'" in catalog
    assert "id: 'openai_compatible'" in catalog
    assert "default_model" in catalog
