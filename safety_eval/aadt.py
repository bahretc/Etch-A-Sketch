"""Section AADT calculator - weighted average by sub-section.

The workbook computes a single representative AADT for a corridor made of
sub-sections of differing length by length-weighting each sub-section's AADT:

    corridor_aadt = sum(len_i * aadt_i) / sum(len_i)

A sub-section is ``(begin_mp, end_mp, aadt)``.  COVID year 2020 should not be
chosen as a representative year (enforced by the caller when picking AADTs).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SubSection:
    begin_mp: float
    end_mp: float
    aadt: float

    @property
    def length(self) -> float:
        return abs(self.end_mp - self.begin_mp)


def weighted_aadt(subsections: list[SubSection]) -> float | None:
    """Length-weighted average AADT across sub-sections."""
    total_len = sum(s.length for s in subsections)
    if total_len <= 0:
        # equal-weight fallback when lengths are unknown/zero
        vals = [s.aadt for s in subsections if s.aadt]
        return sum(vals) / len(vals) if vals else None
    return sum(s.length * s.aadt for s in subsections) / total_len
