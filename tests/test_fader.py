import math

import pytest

from bester_ytm.fader import FADE_STEP_SECONDS, Fader, equal_power_gains
from bester_ytm.mpv_ipc import MpvIpcError


def make_clock(values: list[float]):
    remaining = list(values)

    def clock() -> float:
        return remaining.pop(0)

    return clock


def test_equal_power_gains_endpoints_and_midpoint() -> None:
    assert equal_power_gains(0.0) == (1.0, 0.0)

    outgoing_mid, incoming_mid = equal_power_gains(0.5)
    assert outgoing_mid == pytest.approx(math.sqrt(2) / 2)
    assert incoming_mid == pytest.approx(math.sqrt(2) / 2)

    outgoing_end, incoming_end = equal_power_gains(1.0)
    assert outgoing_end == pytest.approx(0.0, abs=1e-12)
    assert incoming_end == pytest.approx(1.0)


def test_equal_power_gains_clamps_progress() -> None:
    assert equal_power_gains(-0.5) == equal_power_gains(0.0)
    assert equal_power_gains(1.5) == equal_power_gains(1.0)


def test_run_applies_scaled_gains_with_injected_clock() -> None:
    gain_calls: list[tuple[float, float]] = []
    sleeps: list[float] = []
    fader = Fader(
        duration_seconds=1.0,
        apply_gains=lambda outgoing, incoming: gain_calls.append((outgoing, incoming)),
        get_master_volume=lambda: 80.0,
        clock=make_clock([0.0, 0.25, 0.5, 0.75, 1.0]),
        sleep=sleeps.append,
    )

    fader.run()

    assert len(gain_calls) == 4
    for (outgoing, incoming), progress in zip(gain_calls, [0.25, 0.5, 0.75, 1.0], strict=True):
        expected_outgoing, expected_incoming = equal_power_gains(progress)
        assert outgoing == pytest.approx(80.0 * expected_outgoing)
        assert incoming == pytest.approx(80.0 * expected_incoming)
    assert sleeps == [FADE_STEP_SECONDS] * 3
    assert fader.progress == 1.0
    assert not fader.is_active
    assert fader.failure_reason is None


def test_run_rereads_master_volume_every_step() -> None:
    masters = [100.0, 50.0]
    gain_calls: list[tuple[float, float]] = []
    fader = Fader(
        duration_seconds=1.0,
        apply_gains=lambda outgoing, incoming: gain_calls.append((outgoing, incoming)),
        get_master_volume=lambda: masters.pop(0),
        clock=make_clock([0.0, 0.5, 1.0]),
        sleep=lambda seconds: None,
    )

    fader.run()

    half_gain = math.sqrt(2) / 2
    assert gain_calls[0] == (
        pytest.approx(100.0 * half_gain),
        pytest.approx(100.0 * half_gain),
    )
    assert gain_calls[1] == (pytest.approx(0.0, abs=1e-9), pytest.approx(50.0))


def test_run_records_failure_and_stops_when_apply_gains_raises() -> None:
    def failing_apply_gains(outgoing: float, incoming: float) -> None:
        raise MpvIpcError("incoming deck is gone")

    fader = Fader(
        duration_seconds=1.0,
        apply_gains=failing_apply_gains,
        get_master_volume=lambda: 100.0,
        clock=make_clock([0.0, 0.25, 0.5]),
        sleep=lambda seconds: None,
    )

    fader.run()

    assert fader.failure_reason == "incoming deck is gone"
    assert not fader.is_active
    assert fader.progress == pytest.approx(0.25)


def test_cancel_mid_run_stops_the_ramp() -> None:
    gain_calls: list[tuple[float, float]] = []
    fader = Fader(
        duration_seconds=1.0,
        apply_gains=lambda outgoing, incoming: gain_calls.append((outgoing, incoming)),
        get_master_volume=lambda: 100.0,
        clock=make_clock([0.0, 0.25, 0.5, 0.75, 1.0]),
        sleep=lambda seconds: fader.cancel(),
    )

    fader.run()

    assert len(gain_calls) == 1
    assert not fader.is_active
    assert fader.progress < 1.0
    assert fader.failure_reason is None


def test_cancel_before_start_never_raises() -> None:
    fader = Fader(
        duration_seconds=1.0,
        apply_gains=lambda outgoing, incoming: None,
        get_master_volume=lambda: 100.0,
    )

    fader.cancel()


def test_zero_duration_completes_in_one_step() -> None:
    gain_calls: list[tuple[float, float]] = []
    fader = Fader(
        duration_seconds=0.0,
        apply_gains=lambda outgoing, incoming: gain_calls.append((outgoing, incoming)),
        get_master_volume=lambda: 100.0,
        clock=make_clock([0.0, 0.0]),
        sleep=lambda seconds: None,
    )

    fader.run()

    assert gain_calls == [(pytest.approx(0.0, abs=1e-12), pytest.approx(100.0))]
    assert fader.progress == 1.0
    assert not fader.is_active
