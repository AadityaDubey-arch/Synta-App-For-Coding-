"""Per-topic skill profile, learning path and (consent-gated) storage.

Only topic counters, the chosen level and consent are stored. Your code is never saved.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import config

TOPICS = ("syntax_types", "control_flow", "functions_scope",
          "data_structures", "debugging", "problem_solving")
TOPIC_LABELS = {
    "syntax_types": "Syntax and types",
    "control_flow": "Control flow",
    "functions_scope": "Functions and scope",
    "data_structures": "Data structures",
    "debugging": "Debugging",
    "problem_solving": "Problem solving",
}
STUDY_FOCUS = {
    "syntax_types": "Predict the type of each expression, and practise str/int/float conversion (int(), str()) "
                    "and comparing values of the same type.",
    "control_flow": "Trace loops by hand: write the value of the loop variable on every pass; "
                    "practise range() boundaries, break and continue.",
    "functions_scope": "Write small functions that return values (not just print), then predict what "
                       "local and global variables hold.",
    "data_structures": "Practise lists, dicts, tuples and sets: which one fits, and what changes in place.",
    "debugging": "Read the traceback bottom-up, then print intermediate values to find where reality "
                 "and your expectation diverge.",
    "problem_solving": "Plan in plain words first, then list edge cases (empty input, one item) "
                       "before writing code.",
}
LEVELS = ("beginner", "intermediate", "advanced")
CREDIT = {"nudge": 1.0, "hint": 0.8, "explain": 0.5, "solution": 0.25}


def band_for(mastery: float | None) -> str:
    if mastery is None:
        return "unassessed"
    if mastery >= 0.70:
        return "solid"
    if mastery >= 0.45:
        return "practice"
    return "learn"


@dataclass
class PathItem:
    topic: str
    label: str
    mastery: float | None
    band: str
    focus: str


class LearnerProfile:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.data_dir() / "profile.json"
        self.asked_consent = False
        self.consent = False
        self.level = "beginner"
        self.topics = {t: {"correct": 0.0, "attempts": 0.0} for t in TOPICS}
        self.diagnostic: dict | None = None

    # ---- storage -----------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "LearnerProfile":
        prof = cls(path)
        try:
            data = json.loads(prof.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return prof
        prof.asked_consent = True
        prof.consent = bool(data.get("consent", False))
        if data.get("level") in LEVELS:
            prof.level = data["level"]
        for t in TOPICS:
            row = (data.get("topics") or {}).get(t) or {}
            prof.topics[t] = {"correct": float(row.get("correct", 0)), "attempts": float(row.get("attempts", 0))}
        prof.diagnostic = data.get("diagnostic")
        return prof

    def save(self) -> bool:
        if not self.consent:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "consent": True, "level": self.level, "topics": self.topics,
                "diagnostic": self.diagnostic}, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def set_consent(self, yes: bool):
        self.asked_consent = True
        self.consent = yes
        if yes:
            self.save()
        else:
            self._delete_file()

    def _delete_file(self):
        try:
            self.path.unlink()
        except OSError:
            pass

    def forget(self):
        """Delete everything stored and reset the in-memory profile."""
        self._delete_file()
        self.asked_consent = True
        self.consent = False
        self.level = "beginner"
        self.topics = {t: {"correct": 0.0, "attempts": 0.0} for t in TOPICS}
        self.diagnostic = None

    # ---- evidence ----------------------------------------------------------
    def set_level(self, level: str):
        if level in LEVELS:
            self.level = level
            self.save()

    def mastery(self, topic: str) -> float | None:
        row = self.topics[topic]
        if row["attempts"] <= 0:
            return None
        return (row["correct"] + 1.0) / (row["attempts"] + 2.0)    # Laplace-smoothed

    def apply_diagnostic(self, results: dict[str, tuple[int, int]]):
        """results: topic -> (correct, total). A fresh diagnostic re-baselines each topic."""
        for t, (c, n) in results.items():
            if t in self.topics and n > 0:
                self.topics[t] = {"correct": float(c), "attempts": float(n)}
        self.diagnostic = {"date": time.strftime("%Y-%m-%d"),
                           "questions": sum(n for _, n in results.values())}
        self.save()

    def log_attempt(self, topic: str):
        if topic in self.topics:
            self.topics[topic]["attempts"] += 1
            self.save()

    def log_success(self, topic: str, stage: str):
        """Credit depends on how much help was needed (earlier rung = more credit)."""
        if topic in self.topics:
            self.topics[topic]["correct"] += CREDIT.get(stage, 0.25)
            self.save()

    # ---- using the profile -------------------------------------------------
    def rows(self) -> list[PathItem]:
        out = []
        for t in TOPICS:
            m = self.mastery(t)
            out.append(PathItem(t, TOPIC_LABELS[t], m, band_for(m), STUDY_FOCUS[t]))
        return out

    def path_items(self) -> list[PathItem]:
        """Topics that are not yet solid, weakest first. Solid topics are skipped (no re-teaching)."""
        ranked = []
        for i, item in enumerate(self.rows()):
            if item.band != "solid":
                ranked.append((item.mastery if item.mastery is not None else 0.5, i, item))
        ranked.sort(key=lambda r: (r[0], r[1]))
        return [r[2] for r in ranked]

    def next_step_text(self) -> str:
        items = self.path_items()
        if not items:
            return "All six topics look solid. Try the Advanced level and harder problems."
        first = items[0]
        return f"Next to practise: {first.label}. {first.focus}"

    def recommended_level(self) -> str | None:
        vals = [m for m in (self.mastery(t) for t in TOPICS) if m is not None]
        if not vals:
            return None
        avg = sum(vals) / len(vals)
        return "advanced" if avg >= 0.70 else "intermediate" if avg >= 0.45 else "beginner"

    def prompt_summary(self) -> str:
        """Short text for the AI. Topic names only: no name, no code, no history."""
        rows = self.rows()
        solid = [r.label for r in rows if r.band == "solid"]
        weak = [r.label for r in rows if r.band in ("learn", "practice")]
        unknown = [r.label for r in rows if r.band == "unassessed"]
        if not solid and not weak:
            return ""
        parts = []
        if solid:
            parts.append("strong (do not re-teach): " + ", ".join(solid))
        if weak:
            parts.append("needs work: " + ", ".join(weak))
        if unknown:
            parts.append("not assessed: " + ", ".join(unknown))
        return "; ".join(parts)
