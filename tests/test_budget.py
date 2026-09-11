"""Spend accounting for the paid extraction path.

Two ledgers guard the OpenAI bill. ``SpendBudget`` is the per-run ledger:
it reserves each request's worst-case cost before the call and settles it
against the reported usage afterwards, so an interrupted or untrustworthy
run charges itself the reservation rather than over-spending.
``MonthlySpendBudget`` is the durable one — a git branch holding each
month's cap and the runs charged against it, driven by the
``schedules budget`` CLI. Both fail closed: a malformed ledger, an
unapproved cap, or a missing credential stops the run instead of
silently downgrading it.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import api_usage_result, extraction_api_request
from schedules.paths import PROMPT_PATH
from schedules.providers import openai_provider
from schedules.schema import EXTRACTION_SCHEMA


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_api_budget_requires_positive_finite_limit(tmp_path, limit) -> None:
    with pytest.raises(ValueError, match="positive"):
        openai_provider.SpendBudget(tmp_path / "budget.json", limit)


def test_api_budget_stops_before_sending_unaffordable_request(tmp_path, monkeypatch) -> None:
    def unexpected_call(*args):
        pytest.fail("An unaffordable request reached the API")

    monkeypatch.setattr(openai_provider, "call_api", unexpected_call)
    with pytest.raises(ValueError, match="exhausted"):
        openai_provider.budgeted_call(extraction_api_request(), tmp_path / "call", 1,
                                     openai_provider.SpendBudget(tmp_path / "budget.json", 0.01))


def test_api_budget_reserves_before_call_and_settles_conservatively(tmp_path, monkeypatch) -> None:
    path = tmp_path / "budget.json"
    request = extraction_api_request()
    maximum = openai_provider.api_reservation_microusd(request)

    def call(*args):
        reservation = json.loads(path.read_text())["requests"][0]
        assert reservation["status"] == "reserved"
        assert reservation["charged_microusd"] == maximum
        return api_usage_result()

    monkeypatch.setattr(openai_provider, "call_api", call)
    budget = openai_provider.SpendBudget(path, 1)
    openai_provider.budgeted_call(request, tmp_path / "call", 1, budget)
    item = json.loads(path.read_text())["requests"][0]
    assert item["charged_microusd"] == 6500  # Full input rate, even for cached tokens.
    assert item["status"] == "completed"
    with pytest.raises(ValueError, match="already settled"):
        budget.settle(item["id"], api_usage_result())


@pytest.mark.parametrize("result", [
    {"status": "timeout"}, api_usage_result(-1, 5), api_usage_result(True, 5), api_usage_result(None, 5),
])
def test_api_budget_keeps_reservation_without_trustworthy_usage(tmp_path, result) -> None:
    budget = openai_provider.SpendBudget(tmp_path / "budget.json", 1)
    identifier = budget.reserve(extraction_api_request())
    budget.settle(identifier, result)
    item = json.loads(budget.path.read_text())["requests"][0]
    assert item["charged_microusd"] == item["reserved_microusd"]


def test_api_budget_retains_interrupted_reservation_and_rejects_limit_reset(tmp_path, monkeypatch) -> None:
    path = tmp_path / "budget.json"
    maximum = openai_provider.api_reservation_microusd(extraction_api_request())
    limit = (maximum + 1) / 1_000_000

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(openai_provider, "call_api", interrupt)
    with pytest.raises(KeyboardInterrupt):
        openai_provider.budgeted_call(extraction_api_request(), tmp_path / "call", 1,
                                     openai_provider.SpendBudget(path, limit))
    with pytest.raises(ValueError, match="exhausted"):
        openai_provider.SpendBudget(path, limit).reserve(extraction_api_request())
    with pytest.raises(ValueError, match="differs"):
        openai_provider.SpendBudget(path, 10).reserve(extraction_api_request())


@pytest.mark.parametrize("result", [
    api_usage_result(1_000_000, 10), api_usage_result(model="unexpected-model"),
    api_usage_result(service_tier="priority"),
])
def test_api_accounting_error_blocks_later_calls(tmp_path, result) -> None:
    budget = openai_provider.SpendBudget(tmp_path / "budget.json", 10)
    identifier = budget.reserve(extraction_api_request())
    with pytest.raises(ValueError, match="price reservation"):
        budget.settle(identifier, result)
    assert json.loads(budget.path.read_text())["blocked"] is True
    with pytest.raises(ValueError, match="blocked"):
        budget.reserve(extraction_api_request())


def test_concurrent_api_requests_cannot_overbook_budget(tmp_path) -> None:
    path = tmp_path / "budget.json"
    maximum = openai_provider.api_reservation_microusd(extraction_api_request())
    limit = (maximum + 1) / 1_000_000

    def reserve(_):
        try:
            return openai_provider.SpendBudget(path, limit).reserve(extraction_api_request())
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as workers:
        identifiers = list(workers.map(reserve, range(8)))
    assert sum(identifier is not None for identifier in identifiers) == 1
    assert len(json.loads(path.read_text())["requests"]) == 1


@pytest.fixture
def monthly_budget(tmp_path):
    remote = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    def git(*args, cwd=tmp_path):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "--bare", "--initial-branch=main", str(remote))
    git("clone", str(remote), str(repo))
    git("config", "user.name", "Budget test", cwd=repo)
    git("config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "baseline.txt").write_text("baseline\n")
    git("add", "baseline.txt", cwd=repo)
    git("commit", "-m", "Baseline", cwd=repo)
    git("push", "origin", "main", cwd=repo)
    budget = openai_provider.MonthlySpendBudget(repo, 1)
    return budget, git, remote


def test_monthly_accounting_requires_explicit_initialization(monthly_budget):
    budget, git, remote = monthly_budget
    with pytest.raises(ValueError, match="initialization"):
        budget.reserve("2026-09", "1-1")
    budget.initialize()
    with pytest.raises(ValueError, match="must not be reset"):
        budget.initialize()
    before = git("rev-parse", "HEAD", cwd=budget.repo_root)
    receipt = budget.reserve("2026-09", "1-1")
    assert receipt["limit_microusd"] == 1_000_000
    assert git("rev-parse", "HEAD", cwd=budget.repo_root) == before
    assert git("status", "--porcelain", cwd=budget.repo_root) == ""
    assert git("rev-parse", "refs/heads/main", cwd=remote) == before


def test_monthly_budget_retains_interrupted_runs_and_survives_new_instances(monthly_budget):
    budget, _, _ = monthly_budget
    budget.initialize()
    receipt = budget.reserve("2026-09", "1-1")
    restarted = openai_provider.MonthlySpendBudget(budget.repo_root, 1)
    with pytest.raises(ValueError, match="exhausted"):
        restarted.reserve("2026-09", "2-1")
    with pytest.raises(ValueError, match="already has"):
        restarted.reserve("2026-09", "1-1")
    restarted.settle(receipt, budget.repo_root / "missing-run-ledger.json")
    assert restarted._load()[1]["months"]["2026-09"]["runs"]["1-1"]["charged_microusd"] == 1_000_000
    assert restarted.reserve("2026-10", "3-1")["limit_microusd"] == 1_000_000
    assert set(restarted._load()[1]["months"]) == {"2026-09", "2026-10"}


def test_monthly_settlement_releases_only_recorded_unspent_allowance(monthly_budget, tmp_path):
    budget, _, _ = monthly_budget
    budget.initialize()
    receipt = budget.reserve("2026-09", "1-1")
    ledger = tmp_path / "run.json"
    ledger.write_text(json.dumps({"limit_microusd": 1_000_000, "requests": [
        {"id": "request", "reserved_microusd": 300_000, "charged_microusd": 250_000, "status": "completed"},
    ]}))
    budget.settle(receipt, ledger)
    with pytest.raises(ValueError, match="already settled"):
        budget.settle(receipt, ledger)
    assert budget.reserve("2026-09", "2-1")["limit_microusd"] == 750_000
    with pytest.raises(ValueError, match="exhausted"):
        budget.reserve("2026-09", "3-1")


@pytest.mark.parametrize("ledger", [
    {"limit_microusd": 1_000_000, "requests": [{"charged_microusd": -1}]},
    {"limit_microusd": 1_000_000, "requests": [{"charged_microusd": 2_000_000}]},
    {"limit_microusd": 1_000_000, "requests": [], "blocked": True},
    {"limit_microusd": 10_000_000, "requests": []},
    {"limit_microusd": 1_000_000, "requests": ["malformed"]},
    {"limit_microusd": 1_000_000, "requests": [{"id": "request", "reserved_microusd": 300_000, "charged_microusd": 0, "status": "reserved"}]},
])
def test_invalid_run_accounting_blocks_later_months(monthly_budget, tmp_path, ledger):
    budget, _, _ = monthly_budget
    budget.initialize()
    receipt = budget.reserve("2026-09", "1-1")
    path = tmp_path / "run.json"
    path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="blocked"):
        budget.settle(receipt, path)
    with pytest.raises(ValueError, match="blocked"):
        budget.reserve("2026-10", "2-1")


def test_monthly_approval_cannot_silently_reset_existing_limit(monthly_budget):
    budget, _, _ = monthly_budget
    budget.initialize()
    budget.reserve("2026-09", "1-1", 0.5)
    changed = openai_provider.MonthlySpendBudget(budget.repo_root, 10)
    with pytest.raises(ValueError, match="differs"):
        changed.reserve("2026-09", "2-1")


def test_concurrent_budget_writers_cannot_both_reserve_the_last_allowance(monthly_budget, monkeypatch):
    budget, _, _ = monthly_budget
    budget.initialize()
    competing = openai_provider.MonthlySpendBudget(budget.repo_root, 1)
    original_save = budget._save

    def race(parent, state, message):
        competing.reserve("2026-09", "2-1")
        original_save(parent, state, message)

    monkeypatch.setattr(budget, "_save", race)
    with pytest.raises(ValueError, match="no paid call is authorized"):
        budget.reserve("2026-09", "1-1")
    assert set(competing._load()[1]["months"]["2026-09"]["runs"]) == {"2-1"}


# ---- the durable monthly ledger, through the CLI ---------------------------


@pytest.mark.parametrize("problem", ["exhausted", "missing", "blocked", "malformed", "missing_key", "missing_approval"])
def test_unavailable_monthly_allowance_creates_free_only_receipt_without_ledger_write(monthly_budget, monkeypatch, tmp_path, problem):
    from click.testing import CliRunner
    from schedules.cli import _budget_month, cli
    budget, git, remote = monthly_budget
    month = _budget_month()
    monkeypatch.setattr("schedules.cli.REPO_ROOT", budget.repo_root)
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-call")
    if problem != "missing":
        budget.initialize()
    if problem == "exhausted":
        budget.reserve(month, "1-1")
    elif problem in {"blocked", "malformed"}:
        parent, state = budget._load()
        state["blocked"] = True if problem == "blocked" else "invalid"
        budget._save(parent, state, "Test unavailable accounting")
    elif problem == "missing_key":
        monkeypatch.delenv("OPENAI_API_KEY")
    elif problem == "missing_approval":
        monkeypatch.delenv("SCHEDULES_MONTHLY_BUDGET_USD")
    before = git("ls-remote", "origin", "refs/heads/schedule-budget", cwd=budget.repo_root)
    output = tmp_path / "free-run"
    runner = CliRunner()
    result = runner.invoke(cli, ["budget", "reserve", "--run-id", "2-1", "--output", str(output)])
    assert result.exit_code == 0, result.output
    receipt = json.loads((output / "reservation.json").read_text())
    assert receipt["status"] == "unavailable" and receipt["limit_microusd"] == 0
    assert json.loads((output / "budget.json").read_text()) == {"limit_microusd": 0, "requests": []}
    assert runner.invoke(cli, ["budget", "settle", "--directory", str(output)]).exit_code == 0
    assert git("ls-remote", "origin", "refs/heads/schedule-budget", cwd=budget.repo_root) == before
    with pytest.raises(ValueError, match="positive API budget"):
        openai_provider.SpendBudget(output / "budget.json", 0)


def test_uncertain_remote_reservation_keeps_full_charge(monthly_budget, monkeypatch, tmp_path):
    from click.testing import CliRunner
    from schedules.cli import cli
    budget, git, remote = monthly_budget
    budget.initialize()
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-call")
    monkeypatch.setattr("schedules.cli._monthly_budget", lambda *args: budget)
    original = budget.reserve
    def uncertain(month, run_id):
        original(month, run_id)
        raise RuntimeError("Remote push result unavailable")
    monkeypatch.setattr(budget, "reserve", uncertain)
    output = tmp_path / "uncertain"
    runner = CliRunner()
    assert runner.invoke(cli, ["budget", "reserve", "--run-id", "2-1", "--output", str(output)]).exit_code == 0
    before = git("rev-parse", "schedule-budget", cwd=remote)
    assert runner.invoke(cli, ["budget", "settle", "--directory", str(output)]).exit_code == 0
    assert git("rev-parse", "schedule-budget", cwd=remote) == before
    state = json.loads(git("show", "schedule-budget:budget.json", cwd=remote))
    reservation = next(iter(state["months"].values()))["runs"]["2-1"]
    assert reservation == {"reserved_microusd": 1000000, "charged_microusd": 1000000, "status": "reserved"}


@pytest.mark.parametrize("ledger", [{"limit_microusd": 0, "requests": [{}]}, {"limit_microusd": 1, "requests": []}, {"limit_microusd": False, "requests": []}])
def test_free_only_settlement_rejects_any_requests_or_invalid_limit(tmp_path, monkeypatch, ledger):
    from click.testing import CliRunner
    from schedules.cli import cli
    (tmp_path / "reservation.json").write_text(json.dumps({"status": "unavailable", "limit_microusd": 0}))
    (tmp_path / "budget.json").write_text(json.dumps(ledger))
    monkeypatch.setattr("schedules.cli._monthly_budget", lambda *args: pytest.fail("Free settlement must not contact durable ledger"))
    assert CliRunner().invoke(cli, ["budget", "settle", "--directory", str(tmp_path)]).exit_code != 0


def test_authorized_cli_reservation_and_settlement_keep_existing_accounting(monthly_budget, monkeypatch, tmp_path):
    from click.testing import CliRunner
    from schedules.cli import cli
    budget, git, remote = monthly_budget
    budget.initialize()
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-call")
    monkeypatch.setattr("schedules.cli._monthly_budget", lambda *args: budget)
    output = tmp_path / "authorized"
    runner = CliRunner()
    result = runner.invoke(cli, ["budget", "reserve", "--run-id", "2-1", "--output", str(output)])
    assert result.exit_code == 0, result.output
    receipt = json.loads((output / "reservation.json").read_text())
    assert receipt["status"] == "reserved" and receipt["limit_microusd"] == 1000000
    assert runner.invoke(cli, ["budget", "settle", "--directory", str(output)]).exit_code == 0
    state = json.loads(git("show", "schedule-budget:budget.json", cwd=remote))
    assert state["months"][receipt["month"]]["runs"]["2-1"]["charged_microusd"] == 0


@pytest.mark.parametrize("allowance", ["zero", "missing_key", "missing_ledger"])
def test_valid_pdf_requires_paid_authority_before_render_or_request(tmp_path, monkeypatch, north_beach_pair, allowance):
    _, components = north_beach_pair
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-not-a-key")
    monkeypatch.setenv("SCHEDULES_API_BUDGET_FILE", str(tmp_path / "budget.json"))
    monkeypatch.setenv("SCHEDULES_API_BUDGET_USD", "0" if allowance == "zero" else "1")
    if allowance == "missing_key":
        monkeypatch.delenv("OPENAI_API_KEY")
    elif allowance == "missing_ledger":
        monkeypatch.delenv("SCHEDULES_API_BUDGET_FILE")
    ledger = b'{"limit_microusd":0,"requests":[]}'
    (tmp_path / "budget.json").write_bytes(ledger)
    def forbidden(*args, **kwargs):
        pytest.fail("Paid authority must be checked before rendering or building an API request")
    monkeypatch.setattr(openai_provider, "render_source_pages", forbidden)
    monkeypatch.setattr(openai_provider, "source_request", forbidden)
    monkeypatch.setattr(openai_provider, "budgeted_call", forbidden)
    with pytest.raises(ValueError, match="positive API budget|OPENAI_API_KEY|SCHEDULES_API_BUDGET_FILE"):
        openai_provider.extract(components[0]["document"], PROMPT_PATH.read_text(), EXTRACTION_SCHEMA)
    assert (tmp_path / "budget.json").read_bytes() == ledger


def test_month_specific_cap_expires_without_changing_default(monkeypatch):
    from schedules.cli import _monthly_budget
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "5")
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", '{"2026-09":6}')
    assert _monthly_budget("2026-09").limit == 6000000
    assert _monthly_budget("2026-10").limit == 5000000
    assert _monthly_budget("2027-09").limit == 5000000
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", "")
    assert _monthly_budget("2026-09").limit == 5000000


@pytest.mark.parametrize("override", ['[]', '{"2026-09":true}', '{"2026-09":4}', '{"2026-13":6}', '{"2026-09":NaN}'])
def test_invalid_month_cap_override_fails_closed(monkeypatch, override):
    import click
    from schedules.cli import _monthly_budget
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "5")
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", override)
    with pytest.raises(click.ClickException):
        _monthly_budget("2026-09")


def test_explicit_cap_increase_preserves_all_runs_and_nonforce_history(monthly_budget, monkeypatch, tmp_path):
    from click.testing import CliRunner
    from schedules.cli import _budget_month, cli
    budget, git, remote = monthly_budget
    budget.initialize()
    month = _budget_month()
    budget.reserve(month, "1-1")
    before, state = budget._load()
    monkeypatch.setattr("schedules.cli.REPO_ROOT", budget.repo_root)
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "1")
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", json.dumps({month: 2}))
    runner = CliRunner()
    arguments = ["budget", "increase", "--month", month, "--from-usd", "1", "--to-usd", "2"]
    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    after = git("rev-parse", "schedule-budget", cwd=remote)
    assert git("rev-parse", "schedule-budget^", cwd=remote) == before
    updated = json.loads(git("show", "schedule-budget:budget.json", cwd=remote))
    expected = json.loads(json.dumps(state))
    expected["months"][month]["limit_microusd"] = 2000000
    assert updated == expected
    assert runner.invoke(cli, arguments).exit_code != 0
    assert git("rev-parse", "schedule-budget", cwd=remote) == after
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-sent")
    output = tmp_path / "increased-run"
    assert runner.invoke(cli, ["budget", "reserve", "--run-id", "2-1", "--output", str(output)]).exit_code == 0
    assert json.loads((output / "reservation.json").read_text())["limit_microusd"] == 1000000


@pytest.mark.parametrize("problem", ["missing", "blocked", "wrong_prior", "decrease", "approval_mismatch", "other_month"])
def test_cap_increase_refuses_without_modifying_ledger(monthly_budget, monkeypatch, problem):
    from click.testing import CliRunner
    from schedules.cli import _budget_month, cli
    budget, git, remote = monthly_budget
    budget.initialize()
    month = _budget_month()
    if problem != "missing":
        budget.reserve(month, "1-1")
    if problem == "blocked":
        parent, state = budget._load()
        state["blocked"] = True
        budget._save(parent, state, "Test blocked cap")
    before = git("rev-parse", "schedule-budget", cwd=remote)
    monkeypatch.setattr("schedules.cli.REPO_ROOT", budget.repo_root)
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "1")
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", json.dumps({month: 2}))
    arguments = ["budget", "increase", "--month", "2000-01" if problem == "other_month" else month,
                 "--from-usd", "0.5" if problem == "wrong_prior" else "1", "--to-usd",
                 "0.5" if problem == "decrease" else "3" if problem == "approval_mismatch" else "2"]
    assert CliRunner().invoke(cli, arguments).exit_code != 0
    assert git("rev-parse", "schedule-budget", cwd=remote) == before


def _pacific_month_clock(monkeypatch):
    """Freeze the clock at 2026-09-30 23:30 Pacific (2026-10-01 06:30 UTC)."""
    from datetime import datetime, timezone
    from schedules import _time

    instant = datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr(_time, "datetime", _Clock)
    # Any UTC clock the CLI might still read is frozen at the same instant, so
    # the assertions below turn on the time zone rather than on today's date.
    monkeypatch.setattr("schedules.cli.datetime", _Clock, raising=False)
    assert _time.pacific_today().isoformat() == "2026-09-30"
    return instant


def test_monthly_cap_uses_the_pacific_calendar_month(monkeypatch):
    from schedules.cli import _monthly_budget
    instant = _pacific_month_clock(monkeypatch)
    assert instant.strftime("%Y-%m") == "2026-10"
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "5")
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", '{"2026-09":6}')
    assert _monthly_budget().limit == 6000000


def test_budget_reservation_records_the_pacific_month(monthly_budget, monkeypatch, tmp_path):
    from click.testing import CliRunner
    from schedules.cli import cli
    budget, _, _ = monthly_budget
    budget.initialize()
    _pacific_month_clock(monkeypatch)
    monkeypatch.setattr("schedules.cli.REPO_ROOT", budget.repo_root)
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-call")
    output = tmp_path / "pacific-run"
    result = CliRunner().invoke(cli, ["budget", "reserve", "--run-id", "2-1", "--output", str(output)])
    assert result.exit_code == 0, result.output
    receipt = json.loads((output / "reservation.json").read_text())
    assert receipt["status"] == "reserved"
    assert receipt["month"] == "2026-09"
    assert set(budget._load()[1]["months"]) == {"2026-09"}


@pytest.mark.parametrize("credentials", ["present", "absent"])
@pytest.mark.parametrize("variable, value", [
    ("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", "{not json"),
    ("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", '{"2026-09": 0.5}'),
    ("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", "[]"),
    ("SCHEDULES_MONTHLY_BUDGET_USD", "one dollar"),
    ("SCHEDULES_MONTHLY_BUDGET_USD", "-1"),
])
def test_malformed_budget_configuration_stops_the_run(monthly_budget, monkeypatch, tmp_path, variable, value, credentials):
    """A typo in an operator-set variable must never downgrade a run to free-only.

    A missing API key is a reason to run free-only, not a reason to stop
    checking the operator's configuration.
    """
    from click.testing import CliRunner
    from schedules.cli import cli
    budget, _, _ = monthly_budget
    budget.initialize()
    monkeypatch.setattr("schedules.cli.REPO_ROOT", budget.repo_root)
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-call")
    if credentials == "absent":
        monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "1")
    monkeypatch.setenv(variable, value)
    output = tmp_path / "malformed"
    result = CliRunner().invoke(cli, ["budget", "reserve", "--run-id", "2-1", "--output", str(output)])
    assert result.exit_code != 0
    assert variable in result.output
    assert not output.exists()


def test_unset_budget_variables_still_reserve_a_free_only_run(monthly_budget, monkeypatch, tmp_path):
    """Unset or empty is "no approval", not a malformed value."""
    from click.testing import CliRunner
    from schedules.cli import cli
    budget, _, _ = monthly_budget
    budget.initialize()
    monkeypatch.setattr("schedules.cli.REPO_ROOT", budget.repo_root)
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-call")
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_USD", "")
    monkeypatch.setenv("SCHEDULES_MONTHLY_BUDGET_OVERRIDES", "")
    output = tmp_path / "free-only"
    result = CliRunner().invoke(cli, ["budget", "reserve", "--run-id", "2-1", "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert json.loads((output / "reservation.json").read_text())["status"] == "unavailable"
