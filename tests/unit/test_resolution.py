"""Settle a disagreement between runs: adjudicate (a master call) and discuss (the models
reconsider in rounds). Not in docs/PROJEKTPLAN.md; requested by the project lead (ADR 0025)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from results_helpers import project_with_run

from crapai.errors import AuthError, ConfigError, StorageError
from crapai.llm.base import Capabilities, LLMResponse
from crapai.llm.mock_provider import MockProvider, answer_json
from crapai.project.workspace import Workspace
from crapai.screening.store import RunStore
from crapai.services import resolution as res
from crapai.services import screening as svc
from crapai.services.results import runs_with_results

# --- fixtures and small helpers -------------------------------------------------------------------


class ScriptedProvider:
    """A provider that answers a fixed sequence of decisions, one per call (full control)."""

    name = "scripted"

    def __init__(self, decisions: list[str], *, model: str = "scripted-model") -> None:
        self.decisions = list(decisions)
        self.model = model
        self.calls = 0

    def count_tokens(self, text: str, model: str) -> int:
        return max(1, len(text) // 4)

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities(context_tokens=128_000, structured_output=True, seed=True)

    async def complete(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        decision = self.decisions[min(self.calls - 1, len(self.decisions) - 1)]
        body = answer_json(request.user, decision=decision)
        return LLMResponse(text=body, model_returned=self.model, tokens_in=10, tokens_out=5)


class BrokenProvider:
    """A provider that always answers unparseable text (deterministic, unlike mock scenario S5)."""

    name = "broken"

    def count_tokens(self, text: str, model: str) -> int:
        return 1

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities(context_tokens=128_000)

    async def complete(self, request):  # type: ignore[no-untyped-def]
        return LLMResponse(text="not a valid JSON answer", model_returned="broken")


class SelectiveAuthErrorProvider:
    """Raises AuthError only for the one record whose title contains ``bad_marker``; answers
    normally (after yielding control, so siblings interleave) for everything else."""

    name = "selective"

    def __init__(self, bad_marker: str) -> None:
        self.bad_marker = bad_marker
        self.calls = 0

    def count_tokens(self, text: str, model: str) -> int:
        return max(1, len(text) // 4)

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities(context_tokens=128_000)

    async def complete(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.bad_marker in request.user:
            raise AuthError("The key was refused", code="E301")
        await asyncio.sleep(0)  # yield so the sibling call can also run before either returns
        body = answer_json(request.user, decision="INCLUDE")
        return LLMResponse(text=body, model_returned="selective", tokens_in=10, tokens_out=5)


def mock_run(workspace: Workspace, scenario: str) -> str:
    """Screen the project with ``scenario`` (mock) and return the new run's id."""
    before = set(runs_with_results(workspace))
    svc.screen_project(
        workspace, svc.RunOptions(provider=MockProvider(scenario), install_signal_handler=False)
    )
    return next(r for r in runs_with_results(workspace) if r not in before)


def two_mock_runs(tmp_path: Path, scenario: str = "S1") -> tuple[Workspace, str, str]:
    workspace = project_with_run(tmp_path, scenario=scenario)
    run_a = runs_with_results(workspace)[0]
    run_b = mock_run(workspace, scenario)
    return workspace, run_a, run_b


def flip_one(workspace: Workspace, run_id: str) -> str:
    """Flip exactly one settled record's decision in ``run_id``; returns its ``study_uid``."""
    return flip_many(workspace, run_id, 1)[0]


def flip_many(workspace: Workspace, run_id: str, count: int) -> list[str]:
    """Flip ``count`` settled records' decisions in ``run_id``; returns their ``study_uid``s."""
    store = RunStore(workspace.runs_dir / run_id)
    chosen = [
        (u, r) for u, r in store.last_results().items() if r.status == "ok" and r.decision
    ][:count]
    assert len(chosen) == count
    for _uid, row in chosen:
        flipped = "EXCLUDE" if row.decision != "EXCLUDE" else "INCLUDE"
        store.append_result(row.model_copy(update={"decision": flipped, "reasoning": "flipped"}))
    return [uid for uid, _ in chosen]


# --- disputed_items / resolvable_runs --------------------------------------------------------------


def test_disputed_items_finds_exactly_the_flipped_record(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    uid = flip_one(workspace, run_b)
    items = res.disputed_items(workspace, [run_a, run_b])
    assert [i.study_uid for i in items] == [uid]
    opinions = {o.run_id: o.decision for o in items[0].opinions}
    assert opinions[run_a] != opinions[run_b] and set(opinions) == {run_a, run_b}


def test_disputed_items_needs_at_least_two_runs(tmp_path: Path) -> None:
    workspace, run_a, _run_b = two_mock_runs(tmp_path)
    with pytest.raises(ConfigError) as info:
        res.disputed_items(workspace, [run_a])
    assert info.value.code == "E203"


def test_disputed_items_rejects_an_unknown_run(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    with pytest.raises(ConfigError):
        res.disputed_items(workspace, [run_a, "nope"])


def test_resolvable_runs_excludes_resolution_runs(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    flip_one(workspace, run_b)
    result = res.adjudicate_project(
        workspace, [run_a, run_b], res.ResolutionOptions(provider=ScriptedProvider(["INCLUDE"]))
    )
    assert sorted(res.resolvable_runs(workspace)) == sorted([run_a, run_b])
    assert result.run_id not in res.resolvable_runs(workspace)


# --- adjudicate -------------------------------------------------------------------------------


def test_adjudicate_settles_the_disputed_record(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    uid = flip_one(workspace, run_b)
    result = res.adjudicate_project(
        workspace, [run_a, run_b], res.ResolutionOptions(provider=ScriptedProvider(["UNCERTAIN"]))
    )
    assert result.manifest.kind == "adjudicate" and result.manifest.state == "completed"
    rows = RunStore(workspace.runs_dir / result.run_id).last_results()
    assert set(rows) == {uid}
    row = rows[uid]
    assert row.status == "ok" and row.decision == "UNCERTAIN" and row.rounds_used == 1
    assert set(row.source_decisions) == {run_a, run_b}


def test_adjudicate_needs_a_real_disagreement(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)  # identical runs: nothing to resolve
    with pytest.raises(ConfigError) as info:
        res.adjudicate_project(workspace, [run_a, run_b])
    assert info.value.code == "E203"


def test_adjudicate_a_broken_answer_is_an_error_not_a_label(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    flip_one(workspace, run_b)
    result = res.adjudicate_project(
        workspace, [run_a, run_b], res.ResolutionOptions(provider=BrokenProvider())
    )
    (row,) = RunStore(workspace.runs_dir / result.run_id).last_results().values()
    assert row.status == "parse_error" and row.decision == ""


def test_adjudicate_pauses_on_quota_and_resumes(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    flip_one(workspace, run_b)
    first = res.adjudicate_project(
        workspace, [run_a, run_b], res.ResolutionOptions(provider=MockProvider("S14", after=0))
    )
    assert first.manifest.state == "paused" and first.manifest.last_error["code"] == "E307"
    second = res.adjudicate_project(
        workspace, [run_a, run_b],
        res.ResolutionOptions(resume=first.run_id, provider=ScriptedProvider(["INCLUDE"])),
    )  # fmt: skip
    assert second.resumed and second.manifest.state == "completed"
    assert second.run_id == first.run_id


def test_adjudicate_fails_on_an_auth_error(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    flip_one(workspace, run_b)
    result = res.adjudicate_project(
        workspace, [run_a, run_b], res.ResolutionOptions(provider=MockProvider("S7", after=0))
    )
    assert result.manifest.state == "failed" and result.manifest.last_error["code"] == "E301"


def test_an_abort_does_not_discard_a_sibling_already_in_flight(tmp_path: Path) -> None:
    """Regression test: gather() must wait for every item in the same chunk before reporting an
    _Abort, or a sibling call that was already in flight (and already cost money) gets silently
    dropped with no row and no log line (its task is simply abandoned when gather() returns)."""
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    bad_uid, good_uid = flip_many(workspace, run_b, 2)
    items = {i.study_uid: i for i in res.disputed_items(workspace, [run_a, run_b])}
    assert {bad_uid, good_uid} == set(items)
    provider = SelectiveAuthErrorProvider(bad_marker=items[bad_uid].title)
    result = res.adjudicate_project(
        workspace, [run_a, run_b], res.ResolutionOptions(provider=provider)
    )
    assert result.manifest.state == "failed"
    rows = RunStore(workspace.runs_dir / result.run_id).last_results()
    # The sibling, running concurrently in the same chunk, must still have settled -- not be
    # silently discarded because gather() returned as soon as the other one raised.
    assert good_uid in rows and rows[good_uid].status == "ok"


# --- discuss ------------------------------------------------------------------------------------


def test_discuss_reaches_consensus_in_one_round(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    uid = flip_one(workspace, run_b)
    providers = {run_a: ScriptedProvider(["EXCLUDE"]), run_b: ScriptedProvider(["EXCLUDE"])}
    result = res.discuss_project(
        workspace, [run_a, run_b], res.ResolutionOptions(providers=providers, max_rounds=3)
    )
    row = RunStore(workspace.runs_dir / result.run_id).last_results()[uid]
    assert row.decision == "EXCLUDE" and row.consensus is True and row.rounds_used == 1
    assert row.tie_break == "" and len(row.history) == 2 + 2  # round 0 (x2) + round 1 (x2)


def test_discuss_true_tie_is_no_consensus_regardless_of_setting(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    uid = flip_one(workspace, run_b)
    original = {o.run_id: o.decision for o in res.disputed_items(workspace, [run_a, run_b])[0].opinions}
    providers = {
        run_a: ScriptedProvider([original[run_a]] * 5),  # never budges
        run_b: ScriptedProvider([original[run_b]] * 5),
    }
    result = res.discuss_project(
        workspace, [run_a, run_b],
        res.ResolutionOptions(providers=providers, max_rounds=2, tie_break="majority"),
    )  # fmt: skip
    row = RunStore(workspace.runs_dir / result.run_id).last_results()[uid]
    assert row.decision == "NO_CONSENSUS" and row.consensus is False
    assert row.tie_break == "no_consensus" and row.rounds_used == 2


def test_discuss_majority_wins_with_three_runs(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path, scenario="S1")
    run_a = runs_with_results(workspace)[0]
    run_b = mock_run(workspace, "S1")
    run_c = mock_run(workspace, "S1")
    uid = flip_one(workspace, run_c)  # run_c now disagrees with run_a and run_b
    opinions = {o.run_id: o.decision for o in res.disputed_items(workspace, [run_a, run_b, run_c])[0].opinions}
    providers = {run: ScriptedProvider([opinions[run]] * 5) for run in (run_a, run_b, run_c)}
    result = res.discuss_project(
        workspace, [run_a, run_b, run_c],
        res.ResolutionOptions(providers=providers, max_rounds=1, tie_break="majority"),
    )  # fmt: skip
    row = RunStore(workspace.runs_dir / result.run_id).last_results()[uid]
    assert row.decision == opinions[run_a] == opinions[run_b]
    assert row.tie_break == "majority" and row.consensus is False


def test_discuss_no_consensus_setting_never_picks_a_winner(tmp_path: Path) -> None:
    workspace = project_with_run(tmp_path, scenario="S1")
    run_a = runs_with_results(workspace)[0]
    run_b = mock_run(workspace, "S1")
    run_c = mock_run(workspace, "S1")
    uid = flip_one(workspace, run_c)
    opinions = {o.run_id: o.decision for o in res.disputed_items(workspace, [run_a, run_b, run_c])[0].opinions}
    providers = {run: ScriptedProvider([opinions[run]] * 5) for run in (run_a, run_b, run_c)}
    result = res.discuss_project(
        workspace, [run_a, run_b, run_c],
        res.ResolutionOptions(providers=providers, max_rounds=1, tie_break="no_consensus"),
    )  # fmt: skip
    row = RunStore(workspace.runs_dir / result.run_id).last_results()[uid]
    assert row.decision == "NO_CONSENSUS" and row.tie_break == "no_consensus"


def test_discuss_a_providers_error_keeps_its_previous_opinion(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    uid = flip_one(workspace, run_b)
    opinions = {o.run_id: o.decision for o in res.disputed_items(workspace, [run_a, run_b])[0].opinions}
    providers = {
        run_a: BrokenProvider(),  # always fails to parse: keeps its original opinion
        run_b: ScriptedProvider([opinions[run_b]]),
    }
    result = res.discuss_project(
        workspace, [run_a, run_b], res.ResolutionOptions(providers=providers, max_rounds=1)
    )
    row = RunStore(workspace.runs_dir / result.run_id).last_results()[uid]
    assert any(h.get("run_id") == run_a and "error" in h for h in row.history)
    assert row.decision == "NO_CONSENSUS"  # run_a never moved off its original opinion


# --- reconstructing a participant's own provider, not the current config -------------------------


def test_participant_config_reads_the_runs_own_manifest_not_the_current_config(
    tmp_path: Path,
) -> None:
    workspace = project_with_run(tmp_path)  # scenario S12 (the default)
    run_id = runs_with_results(workspace)[0]
    data = yaml.safe_load(workspace.project_yaml.read_text(encoding="utf-8"))
    data["llm"]["model"] = "S9"  # the project moved on to a different model since
    workspace.project_yaml.write_text(yaml.safe_dump(data), encoding="utf-8")
    participant = res.participant_config(workspace, run_id)
    assert participant.model == "S12"  # not S9: the run's own model, not the live config


# --- validation hardening ------------------------------------------------------------------------


def test_disputed_items_rejects_a_repeated_run_id(tmp_path: Path) -> None:
    workspace, run_a, _run_b = two_mock_runs(tmp_path)
    with pytest.raises(ConfigError) as info:
        res.disputed_items(workspace, [run_a, run_a])
    assert info.value.code == "E203"


def test_discuss_rejects_an_invalid_tie_break_even_without_the_cli(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    flip_one(workspace, run_b)
    with pytest.raises(ConfigError) as info:
        res.discuss_project(workspace, [run_a, run_b], res.ResolutionOptions(tie_break="maybe"))
    assert info.value.code == "E203"


def test_discuss_rejects_fewer_than_one_round(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    flip_one(workspace, run_b)
    with pytest.raises(ConfigError) as info:
        res.discuss_project(workspace, [run_a, run_b], res.ResolutionOptions(max_rounds=0))
    assert info.value.code == "E203"


def test_resume_accepts_the_runs_in_a_different_order(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    flip_one(workspace, run_b)
    first = res.adjudicate_project(
        workspace, [run_a, run_b], res.ResolutionOptions(provider=MockProvider("S14", after=0))
    )
    assert first.manifest.state == "paused"
    # Same two runs, named in the opposite order: still recognised as the same resolution.
    second = res.adjudicate_project(
        workspace, [run_b, run_a],
        res.ResolutionOptions(resume=first.run_id, provider=ScriptedProvider(["INCLUDE"])),
    )  # fmt: skip
    assert second.resumed and second.manifest.state == "completed"


def test_resume_refuses_a_damaged_plan_file(tmp_path: Path) -> None:
    workspace, run_a, run_b = two_mock_runs(tmp_path)
    flip_one(workspace, run_b)
    first = res.adjudicate_project(
        workspace, [run_a, run_b], res.ResolutionOptions(provider=MockProvider("S14", after=0))
    )
    (workspace.runs_dir / first.run_id / res.PLAN_NAME).unlink()
    with pytest.raises(StorageError) as info:
        res.adjudicate_project(
            workspace, [run_a, run_b],
            res.ResolutionOptions(resume=first.run_id, provider=ScriptedProvider(["INCLUDE"])),
        )  # fmt: skip
    assert info.value.code == "E404"
