"""Learner-controlled hint ladder: Nudge -> Hint -> Explain -> Show the solution.

The ladder only moves up when the learner asks (escalate). It resets when the
local diagnostic changes to a different problem (for example, a syntax error
was fixed). Pure Python, no UI, so it is easy to test.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

STAGES = ("nudge", "hint", "explain", "solution")
LABELS = {"nudge": "Nudge", "hint": "Hint", "explain": "Explain",
          "solution": "Show solution", "technique": "New technique"}


def code_hash(code: str) -> str:
    return hashlib.sha1(code.encode("utf-8", "replace")).hexdigest()


@dataclass
class HintRecord:
    stage: str
    text: str
    code_hash: str


class HelpSession:
    def __init__(self):
        self.reset()

    def reset(self):
        self.stage_index = 0
        self.records: list[HintRecord] = []
        self.signature: str | None = None
        self.topic: str | None = None
        self.attempt_logged = False
        self.fixed = False

    @property
    def stage(self) -> str:
        return STAGES[self.stage_index]

    @property
    def can_escalate(self) -> bool:
        return self.stage_index < len(STAGES) - 1

    def escalate(self) -> bool:
        if not self.can_escalate:
            return False
        self.stage_index += 1
        return True

    def note_signature(self, sig: str) -> str | None:
        """Call on every check/ask. Returns the previous signature if the problem changed."""
        prev = self.signature
        if prev is None:
            self.signature = sig
            return None
        if prev == sig:
            return None
        self.reset()
        self.signature = sig
        return prev

    def outcome(self) -> dict:
        """What happened in this problem so far (read this before a reset)."""
        return {"topic": self.topic, "stage": self.stage, "helped": bool(self.records),
                "attempt_logged": self.attempt_logged, "fixed": self.fixed}

    def record(self, stage: str, code: str, text: str):
        self.records.append(HintRecord(stage, text, code_hash(code)))

    def is_repeat(self, code: str, stage: str) -> bool:
        """True if the learner asks again at the same step without changing anything."""
        return bool(self.records) and self.records[-1].stage == stage \
            and self.records[-1].code_hash == code_hash(code)

    def last_text(self) -> str:
        return self.records[-1].text if self.records else ""

    def recent(self, n: int = 3) -> list[str]:
        return [f"[{LABELS.get(r.stage, r.stage)}] {r.text[:400]}" for r in self.records[-n:]]
