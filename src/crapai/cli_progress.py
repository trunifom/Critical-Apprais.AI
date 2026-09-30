"""The progress bar of ``crapai screen`` (plan chapter 15, requirement "always see the progress").

The screening engine reports a :class:`~crapai.screening.engine.Progress` after every record and
batch. :class:`ProgressPrinter` turns it into one of two forms:

* on a **terminal** a single line that is rewritten in place::

      [##########..........]  50 %  5'000/10'000  ok 4'990  errors 10  batch 5/10  ETA 12 min

* **without a terminal** (a pipe, a log file, a scheduler) no rewriting is possible and a bar
  would fill the file with thousands of lines. Instead a plain line is printed every
  ``plain_interval`` seconds, whenever a batch ends, and at the end.

The module writes to a stream it is given (default: standard error, so that ``--json`` output on
standard output stays clean) and knows nothing about the engine beyond the ``Progress`` fields.
It must not import the command-line framework; it only formats.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TextIO

from crapai.cost.duration import format_duration
from crapai.i18n.messages import Messages
from crapai.screening.engine import Progress

BAR_WIDTH = 20
FINAL_STATES = frozenset({"completed", "paused", "interrupted", "failed", "canceled"})


def thousands(number: int) -> str:
    """``12345`` as ``12'345`` (the Swiss notation; unambiguous in every language)."""
    return f"{number:,}".replace(",", "'")


def render_bar(fraction: float, width: int = BAR_WIDTH) -> str:
    """``[####......]`` for a fraction between 0 and 1 (values outside are clamped)."""
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def format_line(progress: Progress, messages: Messages, *, bar: bool = True) -> str:
    """One status line for ``progress`` in the language of ``messages``."""
    total = max(progress.total, 0)
    fraction = progress.done / total if total else 1.0
    eta = (
        messages.text("cli.screen.eta_unknown")
        if progress.eta_s is None or progress.state in FINAL_STATES
        else format_duration(progress.eta_s)
    )
    line = messages.text(
        "cli.screen.bar_line",
        percent=f"{int(fraction * 100):>3}",
        done=thousands(progress.done),
        total=thousands(total),
        ok=thousands(progress.ok),
        errors=thousands(progress.errors),
        batch=min(progress.batch, max(progress.batches, 1)),
        batches=progress.batches,
        cost=f"{progress.cost:.4f}",
        eta=eta,
        workers=progress.concurrency,
    )
    return f"{render_bar(fraction)} {line}" if bar else line


class ProgressPrinter:
    """A callable for ``RunOptions.progress`` that prints the progress.

    Args:
        messages: Texts in the user's language.
        stream: Where to print (default: standard error).
        tty: Force terminal (True) or plain (False) mode; default: ask the stream.
        min_interval: Shortest time between two redraws on a terminal (seconds).
        plain_interval: Time between two lines without a terminal (seconds).
        clock: Monotonic seconds (injectable for tests).
    """

    def __init__(
        self,
        messages: Messages,
        stream: TextIO | None = None,
        *,
        tty: bool | None = None,
        min_interval: float = 0.2,
        plain_interval: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._messages = messages
        self._stream = stream if stream is not None else sys.stderr
        self._tty = self._stream.isatty() if tty is None else tty
        self._min_interval, self._plain_interval = min_interval, plain_interval
        self._clock = clock
        self._last = float("-inf")
        self._last_batch = 0
        self._open = False  # a line is on screen that has not been ended with a newline
        self._width = 0

    def __call__(self, progress: Progress) -> None:
        final = progress.state in FINAL_STATES
        batch_changed = progress.batch != self._last_batch
        now = self._clock()
        due = now - self._last >= (self._min_interval if self._tty else self._plain_interval)
        if not (final or due or (batch_changed and not self._tty)):
            return
        self._last, self._last_batch = now, progress.batch
        line = format_line(progress, self._messages, bar=self._tty)
        try:
            if self._tty:
                padding = " " * max(0, self._width - len(line))
                self._stream.write("\r" + line + padding)
                self._width = len(line)
                self._open = True
                if final:
                    self.close()
            else:
                self._stream.write(line + "\n")
            self._stream.flush()
        except (OSError, ValueError):
            # A closed or broken output must never stop a screening run.
            self._open = False

    def close(self) -> None:
        """End a line that is still open, so later output starts on a new line."""
        if self._open:
            try:
                self._stream.write("\n")
                self._stream.flush()
            except (OSError, ValueError):
                pass
            self._open = False
