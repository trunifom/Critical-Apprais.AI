"""The screening engine against the mock provider's scenarios (plan chapters 9, 28, 33.2)."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
from screening_helpers import fast_settings, make_config, make_engine, make_items

from crapai.cost.pricing import Price
from crapai.errors import StorageError
from crapai.llm.base import Capabilities, LLMResponse
from crapai.llm.mock_provider import MockProvider
from crapai.screening.engine import MIN_RECORDS_FOR_RATE, Progress, RunAbort
from crapai.screening.store import BatchInfo, ResultRow, RunState


def statuses(engine) -> Counter[str]:  # type: ignore[no-untyped-def]
    return Counter(r.status for r in engine.store.last_results().values())


# --- the ordinary run -----------------------------------------------------------------------------


def test_verify_batch_catches_a_missing_result_in_a_partial_batch(tmp_path: Path) -> None:
    """Regression test: a batch stopped mid-way (``info.done < len(batch)``) used to skip disk
    verification entirely (the check only ran for a *complete* batch) -- exactly the moment a
    torn or lost write is most likely. ``info.done`` only ever grows after a line was actually
    written (single-writer lock in ``_commit``), so a shortfall against disk must still fail."""
    engine = make_engine(tmp_path, MockProvider("S1"))
    batch = make_items(4)
    offset = engine.store.results_size()
    engine.store.append_result(
        ResultRow(
            study_uid=batch[0].uid, run_id=engine.manifest.run_id, status="ok", decision="INCLUDE"
        )
    )
    # Claim 2 records were processed in this batch, but only 1 actually made it to disk.
    info = BatchInfo(index=0, size=len(batch), done=2, ok=2, errors=0)
    with pytest.raises(RunAbort) as excinfo:
        engine._verify_batch(info, batch, offset)
    assert excinfo.value.state == RunState.FAILED
    assert info.status == "failed" and "1 result(s) missing" in info.note


def test_verify_batch_of_a_partial_batch_passes_when_disk_matches_done(tmp_path: Path) -> None:
    """The flip side: a partial batch where disk matches the counted 'done' must still be
    accepted as 'partial', not fail just for being incomplete."""
    engine = make_engine(tmp_path, MockProvider("S1"))
    batch = make_items(4)
    offset = engine.store.results_size()
    engine.store.append_result(
        ResultRow(
            study_uid=batch[0].uid, run_id=engine.manifest.run_id, status="ok", decision="INCLUDE"
        )
    )
    info = BatchInfo(index=0, size=len(batch), done=1, ok=1, errors=0)
    engine._verify_batch(info, batch, offset)  # must not raise
    assert info.status == "partial" and "1 of 4" in info.note


async def test_a_clean_run_screens_every_record_in_verified_batches(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S1"))
    summary = await engine.run(make_items(25))
    assert summary.state == "completed" and summary.by_status == {"ok": 25} and summary.done == 25
    manifest = engine.store.load_manifest()
    assert manifest.state == "completed" and manifest.finished_at
    assert [b["status"] for b in manifest.batches] == ["verified"] * 3
    assert [b["size"] for b in manifest.batches] == [10, 10, 5]
    assert manifest.counts["done"] == 25 and manifest.counts["ok"] == 25
    assert len(engine.store.read_results()) == 25


async def test_the_decision_comes_from_the_answer(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S1"))
    items = make_items(6, marker={1: "EXCLUDE_ME", 4: "UNSURE_ME"})
    await engine.run(items)
    results = engine.store.last_results()
    assert [results[i.uid].decision for i in items] == [
        "INCLUDE", "EXCLUDE", "INCLUDE", "INCLUDE", "UNCERTAIN", "INCLUDE",
    ]  # fmt: skip
    first = results["u00000"]
    assert (
        first.prompt_hash.startswith("sha256:") and first.schema_version >= 1 and first.consistent
    )


async def test_an_empty_list_completes_at_once(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S1"))
    summary = await engine.run([])
    assert summary.state == "completed" and summary.total == 0


async def test_records_with_an_ok_result_are_not_sent_again(tmp_path: Path) -> None:
    items = make_items(12)
    provider = MockProvider("S1")
    engine = make_engine(tmp_path, provider, already_ok={i.uid for i in items[:5]})
    summary = await engine.run(items)
    assert summary.done == 7 and provider.calls == 7
    assert engine.store.load_manifest().sessions[-1]["skipped_ok"] == 5


async def test_progress_is_reported_and_ends_with_the_final_state(tmp_path: Path) -> None:
    seen: list[Progress] = []
    engine = make_engine(tmp_path, MockProvider("S1"), progress=seen.append)
    await engine.run(make_items(15))
    assert seen[-1].done == 15 and seen[-1].total == 15 and seen[-1].state == "completed"
    assert seen[-1].batches == 2 and all(p.done <= p.total for p in seen)
    assert [p.done for p in seen] == sorted(p.done for p in seen)


async def test_cost_is_summed_from_the_price(tmp_path: Path) -> None:
    engine = make_engine(
        tmp_path, MockProvider("S1"), price=Price(input_per_1k=1.0, output_per_1k=2.0)
    )
    summary = await engine.run(make_items(4))
    rows = engine.store.read_results()
    assert summary.cost == pytest.approx(sum(r.cost or 0 for r in rows)) and summary.cost > 0
    assert engine.store.load_manifest().usage["cost"] == pytest.approx(summary.cost, abs=1e-5)


# --- failure scenarios ----------------------------------------------------------------------------


async def test_s2_rate_limits_are_waited_out_and_nothing_is_lost(tmp_path: Path) -> None:
    engine = make_engine(
        tmp_path, MockProvider("S2", burst=5), settings=fast_settings(max_retries=8)
    )
    summary = await engine.run(make_items(20))
    assert summary.by_status == {"ok": 20}


async def test_s3_every_seventh_call_fails_but_the_retry_saves_the_record(tmp_path: Path) -> None:
    provider = MockProvider("S3")
    engine = make_engine(tmp_path, provider)
    summary = await engine.run(make_items(30))
    assert summary.by_status == {"ok": 30} and provider.calls > 30
    assert all(r.attempts >= 1 for r in engine.store.read_results())


async def test_s4_records_that_always_time_out_become_api_errors(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S4"))
    summary = await engine.run(make_items(40))
    assert summary.state == "completed"
    assert summary.by_status.get("api_error", 0) > 0 and summary.by_status["ok"] > 0
    bad = [r for r in engine.store.read_results() if r.status == "api_error"]
    assert {r.error_code for r in bad} == {"E305"} and all(r.decision == "" for r in bad)


async def test_s5_broken_json_is_a_parse_error_never_a_label(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S5"))
    summary = await engine.run(make_items(40))
    assert summary.by_status.get("parse_error", 0) > 0
    for row in engine.store.read_results():
        if row.status == "parse_error":
            assert row.decision == "" and row.error_code == "E304" and "parse_retry" in row.flags


async def test_s6_a_cut_off_answer_is_asked_again_with_a_higher_limit(tmp_path: Path) -> None:
    provider = MockProvider("S6")
    engine = make_engine(tmp_path, provider)
    summary = await engine.run(make_items(30))
    assert summary.by_status.get("ok", 0) > 0 and summary.by_status.get("truncated", 0) > 0
    limits = {r.max_output_tokens for r in provider.requests}
    assert len(limits) == 2 and max(limits) == 2 * min(limits)


async def test_s7_a_refused_key_stops_the_run_as_failed_with_e301(tmp_path: Path) -> None:
    provider = MockProvider("S7", after=6)
    engine = make_engine(tmp_path, provider, settings=fast_settings(concurrency=1))
    summary = await engine.run(make_items(30))
    assert summary.state == "failed" and summary.last_error["code"] == "E301"
    manifest = engine.store.load_manifest()
    assert manifest.state == "failed" and manifest.last_error["code"] == "E301"
    assert len(engine.store.read_results()) == 6  # nothing was written for the refused record
    assert provider.calls == 7


async def test_s8_a_request_slower_than_the_time_limit_is_an_error_not_a_hang(
    tmp_path: Path,
) -> None:
    provider = MockProvider("S8", delay_s=0.2)
    engine = make_engine(tmp_path, provider, settings=fast_settings(timeout_s=0.05, max_retries=1))
    summary = await asyncio.wait_for(engine.run(make_items(4)), timeout=20)
    assert summary.by_status == {"api_error": 4}


async def test_s10_empty_answers_are_parse_errors(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S10"))
    summary = await engine.run(make_items(40))
    assert summary.by_status.get("parse_error", 0) > 0


async def test_s11_refused_content_is_an_api_error_with_e306_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path, MockProvider("S11"))
    summary = await engine.run(make_items(40))
    assert summary.state == "completed"
    codes = {r.error_code for r in engine.store.read_results() if r.status == "api_error"}
    assert codes == {"E306"}


async def test_s12_contradicting_answers_are_kept_but_flagged(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S12"))
    await engine.run(make_items(30))
    rows = engine.store.read_results()
    flagged = [r for r in rows if r.consistent is False]
    assert flagged and all("inconsistent" in r.flags and r.status == "ok" for r in flagged)
    assert any(r.consistent for r in rows)


async def test_s13_quotes_that_are_not_in_the_record_are_flagged(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S13"))
    await engine.run(make_items(30))
    flagged = [r for r in engine.store.read_results() if r.quote_unverified]
    assert flagged and all("quote_unverified" in r.flags for r in flagged)


async def test_s15_a_changing_model_name_is_a_warning(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S15"), settings=fast_settings(concurrency=1))
    summary = await engine.run(make_items(12))
    assert any("different model names" in w for w in summary.warnings)
    assert any("model_changed" in r.flags for r in engine.store.read_results())


# --- stopping and resuming ------------------------------------------------------------------------


async def test_s14_used_up_credit_pauses_with_e307_and_resume_finishes(tmp_path: Path) -> None:
    items = make_items(30)
    engine = make_engine(
        tmp_path, MockProvider("S14", after=12), settings=fast_settings(concurrency=1)
    )
    summary = await engine.run(items)
    assert summary.state == "paused" and summary.last_error["code"] == "E307"
    done = engine.store.last_results()
    assert len(done) == 12
    # The money arrives: a new session with a working provider continues where it stopped.
    again = make_engine(
        tmp_path, MockProvider("S1"), already_ok={u for u, r in done.items() if r.is_ok}
    )
    summary = await again.run(items)
    assert summary.state == "completed"
    final = again.store.last_results()
    assert len(final) == 30 and all(r.is_ok for r in final.values())
    assert [
        len([r for r in again.store.read_results() if r.study_uid == i.uid]) for i in items
    ] == [1] * 30


async def test_a_failed_record_is_tried_again_on_resume_and_the_last_line_wins(
    tmp_path: Path,
) -> None:
    items = make_items(28)
    first = make_engine(tmp_path, MockProvider("S4"))
    await first.run(items)
    failed = {u for u, r in first.store.last_results().items() if not r.is_ok}
    assert failed
    ok = {u for u, r in first.store.last_results().items() if r.is_ok}
    second = make_engine(tmp_path, MockProvider("S1"), already_ok=ok)
    summary = await second.run(items)
    assert summary.session_done == len(failed) and summary.done == 28  # cumulative
    assert all(r.is_ok for r in second.store.last_results().values())


async def test_pause_from_outside_finishes_the_records_in_flight_and_stops_in_paused(
    tmp_path: Path,
) -> None:
    store_holder: dict[str, object] = {}
    calls = {"n": 0}

    def control() -> str | None:
        calls["n"] += 1
        return "pause" if calls["n"] >= 2 else None

    engine = make_engine(
        tmp_path,
        MockProvider("S9", delay_s=0.3),
        settings=fast_settings(concurrency=2, batch_size=50, stop_grace_seconds=5.0),
        control=control,
    )
    store_holder["e"] = engine
    summary = await engine.run(make_items(40))
    assert summary.state == "paused" and summary.stop_reason == "pause requested"
    assert 0 < summary.done < 40
    rows = engine.store.read_results()
    assert len({r.study_uid for r in rows}) == len(rows) == summary.done  # no record twice
    assert engine.store.load_manifest().batches[0]["status"] == "partial"


async def test_stop_from_outside_is_interrupted(tmp_path: Path) -> None:
    engine = make_engine(
        tmp_path,
        MockProvider("S9", delay_s=0.3),
        settings=fast_settings(concurrency=2, batch_size=50),
        control=lambda: "stop",
    )
    summary = await engine.run(make_items(30))
    assert summary.state == "interrupted"


class SlowFlakyProvider:
    """Every call is a parse error, after a fixed delay (so a stop can land mid-batch)."""

    name = "mock"

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    def count_tokens(self, text: str, model: str) -> int:
        return max(1, len(text) // 4)

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities(context_tokens=128_000)

    async def complete(self, request: object) -> LLMResponse:
        await asyncio.sleep(self.delay_s)
        return LLMResponse(text="not valid json", model_returned="mock")


async def test_a_user_requested_stop_is_not_overwritten_by_an_automatic_error_pause(
    tmp_path: Path,
) -> None:
    """Regression test: a batch cut short by the user's own stop, whose few finished records
    happen to be all errors, must stay 'interrupted' (the user's reason) -- not get silently
    turned into an automatic 'paused: too many failures' (E308) by the error-rate check."""
    calls = {"n": 0}

    def control() -> str | None:
        calls["n"] += 1
        return "stop" if calls["n"] >= 2 else None

    engine = make_engine(
        tmp_path,
        SlowFlakyProvider(delay_s=0.3),
        settings=fast_settings(
            concurrency=2, batch_size=50, max_batch_error_rate=0.1, stop_grace_seconds=5.0
        ),
        control=control,
    )
    summary = await engine.run(make_items(40))
    assert summary.state == "interrupted" and summary.stop_reason == "stop requested"
    assert MIN_RECORDS_FOR_RATE <= summary.done < 40
    assert summary.errors == summary.done  # every completed record was a parse error


async def test_requests_still_running_after_the_grace_time_are_cancelled_and_not_written(
    tmp_path: Path,
) -> None:
    engine = make_engine(
        tmp_path,
        MockProvider("S9", delay_s=3.0),
        settings=fast_settings(
            concurrency=2, batch_size=50, stop_grace_seconds=0.0, timeout_s=10.0
        ),
        control=lambda: "stop",
    )
    summary = await asyncio.wait_for(engine.run(make_items(10)), timeout=20)
    assert summary.state == "interrupted" and engine.store.read_results() == []


async def test_cancelling_the_task_writes_the_interrupted_state(tmp_path: Path) -> None:
    engine = make_engine(
        tmp_path, MockProvider("S9", delay_s=0.3), settings=fast_settings(batch_size=50)
    )
    task = asyncio.create_task(engine.run(make_items(30)))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.store.load_manifest().state == "interrupted"


# --- safety rules ---------------------------------------------------------------------------------


async def test_too_many_failures_in_one_batch_pause_the_run_before_the_next_batch(
    tmp_path: Path,
) -> None:
    engine = make_engine(
        tmp_path,
        MockProvider("S4"),
        settings=fast_settings(max_batch_error_rate=0.05, max_retries=0),
    )
    summary = await engine.run(make_items(60))
    assert summary.state == "paused" and summary.last_error["code"] == "E308"
    manifest = engine.store.load_manifest()
    assert len(manifest.batches) == 1 and manifest.batches[0]["status"] == "verified"
    assert "failed" in manifest.stop_reason


async def test_the_circuit_breaker_pauses_after_failures_in_a_row(tmp_path: Path) -> None:
    provider = MockProvider("S14", after=0)  # every call fails, but as a quota error -> paused E307
    engine = make_engine(
        tmp_path, provider, settings=fast_settings(concurrency=1, max_consecutive_errors=3)
    )
    summary = await engine.run(make_items(30))
    assert summary.state == "paused"
    bad = MockProvider("S11")  # refused records; breaker must count them
    items = make_items(60, marker={n: "x" for n in range(60)})
    engine = make_engine(
        tmp_path / "b",
        bad,
        settings=fast_settings(concurrency=1, max_consecutive_errors=2, batch_size=60),
    )
    summary = await engine.run(items)
    if summary.state == "paused":
        assert summary.last_error["code"] == "E308" and "in a row" in summary.stop_reason


async def test_the_cost_limit_pauses_the_run_with_e308(tmp_path: Path) -> None:
    engine = make_engine(
        tmp_path,
        MockProvider("S1"),
        settings=fast_settings(concurrency=1, max_cost=0.01),
        price=Price(input_per_1k=0.001, output_per_1k=0.001),
    )
    summary = await engine.run(make_items(40))
    assert summary.state == "paused" and summary.last_error["code"] == "E308"
    assert 0 < summary.done < 40 and summary.cost <= 0.01 + 1e-9


async def test_a_record_longer_than_the_context_is_marked_too_long_without_a_call(
    tmp_path: Path,
) -> None:
    class Small(MockProvider):
        def capabilities(self, model: str):  # type: ignore[no-untyped-def]
            return super().capabilities(model).__class__(context_tokens=2500)

    provider = Small("S1")
    items = make_items(3)
    items[1] = items[1].__class__(items[1].uid, "long", "word " * 5000)
    engine = make_engine(tmp_path, provider)
    summary = await engine.run(items)
    assert summary.by_status == {"ok": 2, "too_long": 1} and provider.calls == 2


async def test_a_disk_error_while_saving_stops_the_run_as_failed_with_a_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine(tmp_path, MockProvider("S1"), settings=fast_settings(concurrency=1))
    real = engine.store.append_result
    count = {"n": 0}

    def flaky(row: ResultRow) -> None:
        count["n"] += 1
        if count["n"] == 4:
            raise StorageError("disk full", code="E403")
        real(row)

    monkeypatch.setattr(engine.store, "append_result", flaky)
    summary = await engine.run(make_items(20))
    assert summary.state == "failed" and summary.last_error["code"] == "E403"
    assert len(engine.store.read_results()) == 3
    assert engine.store.load_manifest().state == "failed"


async def test_a_lost_project_lock_stops_the_run(tmp_path: Path) -> None:
    from crapai.errors import StorageError as LockError

    def heartbeat() -> None:
        raise LockError("lock lost", code="E501")

    engine = make_engine(
        tmp_path,
        MockProvider("S9", delay_s=0.3),
        settings=fast_settings(heartbeat_seconds=0.0, concurrency=1, batch_size=50),
        heartbeat=heartbeat,
    )
    summary = await engine.run(make_items(30))
    assert summary.state == "failed" and summary.done < 30


async def test_an_unexpected_bug_in_one_record_does_not_end_the_run(tmp_path: Path) -> None:
    class Buggy(MockProvider):
        async def complete(self, request):  # type: ignore[no-untyped-def]
            if (
                "Study 3 " in request.user
                or request.user.count("Study 3")
                and "number 3 " in request.user
            ):
                raise RuntimeError("boom")
            return await super().complete(request)

    engine = make_engine(tmp_path, Buggy("S1"))
    summary = await engine.run(make_items(8))
    assert summary.done == 8 and summary.by_status.get("api_error") == 1
    bad = next(r for r in engine.store.read_results() if r.status == "api_error")
    assert bad.error_code in ("E999", "E305") and "boom" not in bad.error_message


async def test_nothing_of_the_record_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    engine = make_engine(tmp_path, MockProvider("S5"))
    await engine.run(make_items(20, marker={2: "SECRET-ABSTRACT-WORDS"}))
    assert "SECRET-ABSTRACT-WORDS" not in caplog.text


async def test_the_result_file_is_valid_json_lines_with_one_uid_per_line(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, MockProvider("S3"), settings=fast_settings(concurrency=5))
    await engine.run(make_items(50))
    lines = engine.store.results_path.read_text(encoding="utf-8").splitlines()
    uids = [json.loads(line)["study_uid"] for line in lines]
    assert len(uids) == 50 and len(set(uids)) == 50


def test_the_default_config_builds_a_builder() -> None:
    assert make_config().screening.output_format == "structured"
    assert RunState.COMPLETED.value == "completed"


async def test_after_a_resume_progress_and_manifest_count_the_whole_run(tmp_path: Path) -> None:
    """79'000 of 80'000 stays true after the resume: counts are cumulative, not per session."""
    items = make_items(30)
    first = make_engine(
        tmp_path, MockProvider("S14", after=12), settings=fast_settings(concurrency=1)
    )
    await first.run(items)
    done = {u for u, r in first.store.last_results().items() if r.is_ok}
    seen: list[Progress] = []
    second = make_engine(tmp_path, MockProvider("S1"), already_ok=done, progress=seen.append)
    summary = await second.run(items)
    assert summary.total == 30 and summary.done == 30 and summary.session_done == 18
    assert summary.by_status == {"ok": 30}
    assert seen[0].total == 30 and seen[0].done >= 12 and seen[-1].done == 30 and seen[-1].ok == 30
    counts = second.store.load_manifest().counts
    assert counts["total"] == 30 and counts["done"] == 30 and counts["ok"] == 30
