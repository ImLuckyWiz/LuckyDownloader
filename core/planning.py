"""
Planning logic for LuckyTwitch Downloader: cut points -> parts -> strategy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.errors import PlanError
from core.i18n import t
from core.timeutil import fmt_hms, parse_time

END_WORDS = {"end", "fin", "final", "finish", "finishes", "finished", "eof"}
FILLER_WORDS = {"till", "until", "to", "hasta", "the", "of", "vod"}


@dataclass(frozen=True)
class Part:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Plan:
    parts: list[Part]
    strategy: str  # "full" or "sections"
    coverage: float  # fraction of the VOD that the parts cover
    duration: float | None


def split_groups(text: str) -> list[list[str]]:
    """Text -> list of groups (separated by ; or newline) of time tokens."""
    groups = []
    for chunk in re.split(r"[;\n]+", text):
        tokens = [t for t in re.split(r"[\s,\-–—]+", chunk.strip()) if t]
        tokens = [t for t in tokens if t.lower() not in FILLER_WORDS]
        if tokens:
            groups.append(tokens)
    return groups


def parse_cut_points(text: str, duration: float | None = None) -> list[Part]:
    """
    "0:00 - 30:00 - 1:30:00 - end"  ->  3 consecutive parts.
    Several groups (separated by ';' or a new line) allow gaps:
    "0:00 - 30:00 ; 2:00:00 - end"  ->  2 parts, the middle is skipped.
    """
    groups = split_groups(text)
    if not groups:
        raise PlanError(t("Write the cut points, e.g.  0:00 - 30:00 - 1:30:00 - end"))

    parts: list[tuple[float, float]] = []
    for g in groups:
        points: list[float] = []
        for tok in g:
            if tok.lower() in END_WORDS:
                if duration is None or duration <= 0:
                    raise PlanError(t("«end» needs the VOD length: press «Get info» first."))
                points.append(duration)
            else:
                points.append(parse_time(tok))  # type: ignore[arg-type]
        if len(points) < 2:
            raise PlanError(
                t("«{group}»: a group needs at least two points (use 0 and end).", group=' '.join(g))
            )
        for a, b in zip(points, points[1:]):
            if duration is not None and duration > 0:
                if a >= duration:
                    raise PlanError(t("{point} is beyond the end of the VOD ({duration}).", point=fmt_hms(a), duration=fmt_hms(duration)))
                if b > duration + 2:
                    raise PlanError(t("{point} is beyond the end of the VOD ({duration}).", point=fmt_hms(b), duration=fmt_hms(duration)))
                b = min(b, duration)
            if b <= a:
                raise PlanError(t("Cut points must increase: {start} → {end}.", start=fmt_hms(a), end=fmt_hms(b)))
            parts.append((a, b))

    parts.sort()
    for (a1, b1), (a2, b2) in zip(parts, parts[1:]):
        if a2 < b1:
            raise PlanError(
                t("Parts overlap: {p1} and {p2}.", p1=f"{fmt_hms(a1)}–{fmt_hms(b1)}", p2=f"{fmt_hms(a2)}–{fmt_hms(b2)}")
            )
    return [Part(i, a, b) for i, (a, b) in enumerate(parts, 1)]


def choose_strategy(
    parts: list[Part], duration: float | None, mode: str = "auto", threshold: float = 0.6
) -> tuple[str, float]:
    """Return (strategy, coverage). mode: auto | full | sections."""
    if not duration or duration <= 0:
        return (mode if mode in ("full", "sections") else "sections"), 1.0
    coverage = sum(p.duration for p in parts) / duration
    if mode in ("full", "sections"):
        return mode, coverage
    return ("full" if coverage >= threshold else "sections"), coverage


def make_plan(
    text: str, duration: float | None, mode: str = "auto", threshold: float = 0.6
) -> Plan:
    parts = parse_cut_points(text, duration)
    strategy, coverage = choose_strategy(parts, duration, mode, threshold)
    return Plan(parts, strategy, coverage, duration)


def insert_cut_point(text: str, cut_t: float, duration: float | None) -> str:
    """Insert a split point into the cut text (used by 'split at this clip')."""
    cut_t = round(cut_t)
    groups = split_groups(text)
    if not groups:
        end = "end" if duration else fmt_hms(cut_t + 1)
        return f"0:00:00 - {fmt_hms(cut_t)} - {end}"

    def val(tok: str) -> float | None:
        if tok.lower() in END_WORDS:
            return duration
        try:
            return parse_time(tok)
        except PlanError:
            return None

    for g in groups:
        vals = [val(tok) for tok in g]
        if None in vals or len(vals) < 2:
            continue
        if vals[0] < cut_t < vals[-1]:  # type: ignore[operator]
            if cut_t in vals:
                return text  # already a cut point exactly there: nothing to add (no duplicate boundary)
            pos = next(i for i, v in enumerate(vals) if v > cut_t)  # type: ignore[operator]
            g.insert(pos, fmt_hms(cut_t))
            break
    else:
        raise PlanError(t("That moment is not inside any of your parts."))
    return "\n".join(" - ".join(g) for g in groups)
