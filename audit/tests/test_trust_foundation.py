"""Regression locks for authentication and reproducible deployments."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_auth_guard_has_no_dummy_token_bypass():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "localStorage.getItem('token') || 'dummy'" not in app
    assert "const token = localStorage.getItem('token')" in app


def test_deploy_webhook_requires_exact_git_sha_and_clean_tree():
    webhook = (ROOT / "webhook" / "deploy-webhook.py").read_text(encoding="utf-8")
    assert 'self.headers.get("X-Deploy-SHA"' in webhook
    assert '["git", "status", "--porcelain"]' in webhook
    assert '["git", "merge-base", "--is-ancestor"' in webhook
    assert '["git", "reset", "--hard", deploy_sha]' in webhook
    assert 'deploy_env["BUILD_SHA"] = deploy_sha' in webhook


def test_runtime_images_are_stamped_with_build_sha():
    dockerfiles = (
        ROOT / "backend" / "Dockerfile",
        ROOT / "backend-rust" / "Dockerfile",
        ROOT / "backend-flink" / "Dockerfile",
        ROOT / "services" / "camoufox" / "Dockerfile",
        ROOT / "frontend" / "Dockerfile.v2",
    )
    for dockerfile in dockerfiles:
        source = dockerfile.read_text(encoding="utf-8")
        assert "ARG BUILD_SHA=unknown" in source, dockerfile
        assert 'org.opencontainers.image.revision="${BUILD_SHA}"' in source, dockerfile

    compose = (ROOT / "docker-compose.v2.yml").read_text(encoding="utf-8")
    assert "BUILD_SHA: ${BUILD_SHA:-unknown}" in compose
