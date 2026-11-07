"""Keep browser caches ABI-safe and avoid repeating expensive CI setup."""

from pathlib import Path

CI = (Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text()


def step(name):
    marker = f"      - name: {name}\n"
    assert marker in CI, f"Missing CI step: {name}"
    return CI.split(marker, 1)[1].split("\n      - ", 1)[0]


def test_runner_is_pinned_and_total_minutes_are_bounded():
    assert "runs-on: ubuntu-24.04" in CI
    assert "timeout-minutes: 15" in CI


def test_browser_cache_separates_os_arch_and_both_playwright_versions():
    metadata = step("Resolve browser cache identity")
    assert "/etc/os-release" in metadata
    assert "os=$ID-$VERSION_ID" in metadata
    assert 'require("playwright-core/package.json").version' in metadata
    assert 'createRequire(require.resolve("@e2e-dev/web"))' in metadata
    assert 'engineRequire("playwright-core/package.json").version' in metadata
    cache = step("Cache Playwright browsers")
    assert "browsers-v2-${{ steps.browsers.outputs.os }}-${{ runner.arch }}-" in cache
    assert "${{ steps.browsers.outputs.regressions }}-${{ steps.browsers.outputs.journeys }}" in cache
    # Partial restores may cross versions, never OS releases or architectures.
    assert "restore-keys: browsers-v2-${{ steps.browsers.outputs.os }}-${{ runner.arch }}-" in cache


def test_both_downloads_are_skipped_only_for_an_exact_cache_hit():
    for name, command in (
        ("Install regression browsers", "node node_modules/playwright-core/cli.js install webkit chromium"),
        ("Install e2e engine browsers", "./node_modules/.bin/e2e-web install webkit chromium"),
    ):
        download = step(name)
        assert "if: steps.playwright-cache.outputs.cache-hit != 'true'" in download
        assert command in download
    dependencies = step("Install browser OS dependencies")
    assert "if:" not in dependencies  # Binaries are cached, system packages are not.
    assert "install-deps webkit chromium" in dependencies
    assert "--with-deps" not in CI  # Do not invoke apt again for each browser set.
    assert "uv --project schedule-tools sync --locked" in CI


def test_all_four_browsers_launch_before_the_expensive_suite():
    preflight = step("Check browser launches")
    assert 'require("playwright-core")' in preflight
    assert 'createRequire(require.resolve("@e2e-dev/web"))' in preflight
    assert 'engineRequire("playwright-core")' in preflight
    assert '["webkit", "chromium"]' in preflight
    assert ".launch({ timeout: 10_000 })" in preflight
    assert "await browser.close()" in preflight
    assert "timeout-minutes: 1" in preflight
    assert CI.index("name: Check browser launches") < CI.index("name: Run full verification")
    assert "run: just check" in step("Run full verification")
