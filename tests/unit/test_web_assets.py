"""Web asset loading tests."""

from app.web.assets import console_html


def test_console_html_is_read_from_disk() -> None:
    html = console_html()
    assert "Proxmox API Emulator" in html
    assert 'id="catalog-drawer"' in html
    assert "catalog-drawer" in html
    assert 'id="catalog-coverage"' in html
    assert "Implementation coverage" in html
    for required_id in (
        "method-desc",
        "catalog-meta",
        "stat-runtime",
        "stat-catalog",
        "stat-cluster-name",
        "stat-nodes",
        "stat-qemu",
        "stat-lxc",
        "implemented-only",
        "btn-contract-apply",
        "btn-catalog-refresh",
    ):
        assert f'id="{required_id}"' in html, required_id
    assert "Apply as runtime" in html
    assert "CONTRACT_SNAPSHOT" in html
    assert 'id="help-drawer"' in html
    assert 'id="help-badge"' in html
    assert 'id="data-badge"' in html
    assert 'id="data-drawer"' in html
    assert 'id="data-panel"' in html
    assert 'id="ui-modal"' in html
