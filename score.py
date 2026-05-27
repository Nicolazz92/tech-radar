"""score.py — impact formula and label-derived signals.

Formula v1.1:
    impact = (1 + links_count) * severity^2 / max(fix_cost_h, cost_floor)

Why squared severity:
    Linear severity rewards triviality. With (sev / cost) a sev=1/cost=0.5 hack
    (impact 2.0) beats a sev=9/cost=8 load-bearing fix (impact 1.125). Squaring
    keeps the {1, 3, 9} anchors actually anchoring: sev=9 outranks sev=3 unless
    the cost ratio exceeds 9.
"""
from __future__ import annotations
import math


def compute_impact(severity, fix_cost_h, links_count, cost_floor=1.0):
    if severity is None or fix_cost_h is None:
        return None
    try:
        s = float(severity)
        c = float(fix_cost_h)
    except (TypeError, ValueError):
        return None
    if s <= 0 or c <= 0:
        return None
    return round((1 + links_count) * s * s / max(c, cost_floor), 3)


def priority_from_labels(labels, label_map):
    if not labels:
        return 1
    for lab in labels:
        weight = label_map.get(lab.lower()) or label_map.get(lab)
        if weight:
            return weight
    return 1


def effort_from_labels(labels, label_map):
    if not labels:
        return None
    for lab in labels:
        hours = label_map.get(lab.lower()) or label_map.get(lab)
        if hours:
            return hours
    return None


def business_value_from_labels(labels, label_map):
    if not labels:
        return 1
    for lab in labels:
        v = label_map.get(lab.lower()) or label_map.get(lab)
        if v:
            return v
    return 1


def engagement_score(comments, reactions_total, days_old):
    days = max(days_old, 1)
    raw = (comments + reactions_total) / days
    return round(math.log10(raw + 1), 3)


def deadline_days(milestone_due_iso, now_dt):
    if not milestone_due_iso:
        return None
    try:
        import datetime
        due = datetime.datetime.fromisoformat(milestone_due_iso.replace("Z", "+00:00"))
        return max(0, (due - now_dt).days)
    except Exception:
        return None
