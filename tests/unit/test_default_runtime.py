from __future__ import annotations

from sourceglint.application.runtime import default_adapter_factory
from sourceglint.connectors.authorized_sources import ProductHuntAdapter, XAdapter


def test_default_runtime_wires_x_token_from_environment(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "x-test-token")
    adapter = default_adapter_factory("x", {})
    assert isinstance(adapter, XAdapter)
    assert adapter.bearer_token == "x-test-token"


def test_default_runtime_wires_product_hunt_token_from_environment(monkeypatch):
    monkeypatch.setenv("PRODUCT_HUNT_TOKEN", "ph-test-token")
    adapter = default_adapter_factory("product_hunt", {})
    assert isinstance(adapter, ProductHuntAdapter)
    assert adapter.token == "ph-test-token"


def test_default_runtime_returns_credential_gated_adapters_without_secrets(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("PRODUCT_HUNT_TOKEN", raising=False)
    assert isinstance(default_adapter_factory("x", {}), XAdapter)
    assert isinstance(default_adapter_factory("product_hunt", {}), ProductHuntAdapter)
