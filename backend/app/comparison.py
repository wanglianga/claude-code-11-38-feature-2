"""跨项目比较资格与队列构建引擎。

边界（重要）：
- 只判断“比较范围”和“证据覆盖”，不据此排名节能效果。结果不支持以节能率高低排序。
- 可比关系**不传递**：仅对工作区中明确登记的项目对逐条计算，绝不由甲~乙、乙~丙推导甲~丙。
  每个项目对各自选取共同可用的日期窗口，因此甲与乙可能在冬季可比、乙与丙在春季可比，
  而甲与丙因没有共同窗口不可比——这不是推导，而是逐对核验的结果。
- 不把共用同一总表的结果当作两份独立样本。
- 电表倍率只有部分基线被补证时，仅对应区间进入候选，其余区间作为缺口排除并说明。

流程：
1. 项目对：为双方选取重叠最大的事实窗口，逐字段比较条件签名（用途/气候带/占用形态/
   食堂与公共负荷/基线长度/日期偏差），求双方计量覆盖与共用总表排除后的候选区间。
2. 全组队列：仅在所有入选项目共同交集上建立；任一薄弱项目会压缩整批的可用日期与覆盖范围，
   需显式触发，并说明被压缩的日期、被排除的项目与限制交集的项目。
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import (
    AuditLog,
    BuildingUse,
    ClimateZone,
    ComparisonCohort,
    ComparisonEdge,
    ComparisonProjectStatus,
    ComparisonPublication,
    ComparisonRule,
    ComparisonSourceAncestry,
    ComparisonWorkspace,
    EdgeLevel,
    MeterCoverageWindow,
    MeteringBoundary,
    OccupancyProfile,
    OccupancyWindow,
    PeriodRole,
    ProjectComparisonProfile,
    RuleStatus,
    ScopeRelation,
    ScopeStatus,
    WorkspaceStatus,
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return _aware(dt).isoformat() if dt else None


def _days(a: datetime, b: datetime) -> int:
    return max(0, int((_aware(b) - _aware(a)).total_seconds() // 86400))


# ---------------------------------------------------------------- 区间工具


@dataclass
class Interval:
    start: datetime
    end: datetime
    meta: dict = field(default_factory=dict)


def merge_intervals(raw: list[Interval]) -> list[Interval]:
    if not raw:
        return []
    ordered = sorted(raw, key=lambda i: (_aware(i.start), _aware(i.end)))
    out = [Interval(_aware(ordered[0].start), _aware(ordered[0].end), dict(ordered[0].meta))]
    for it in ordered[1:]:
        s, e = _aware(it.start), _aware(it.end)
        if s <= out[-1].end:
            if e > out[-1].end:
                out[-1].end = e
        else:
            out.append(Interval(s, e, dict(it.meta)))
    return [i for i in out if i.end > i.start]


def intersect_two(a: list[Interval], b: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    i = j = 0
    while i < len(a) and j < len(b):
        s = max(_aware(a[i].start), _aware(b[j].start))
        e = min(_aware(a[i].end), _aware(b[j].end))
        if e > s:
            out.append(Interval(s, e, {**a[i].meta, **b[j].meta}))
        if _aware(a[i].end) <= _aware(b[j].end):
            i += 1
        else:
            j += 1
    return out


def intersect_all(sets: list[list[Interval]]) -> list[Interval]:
    if not sets:
        return []
    cur = merge_intervals(sets[0])
    for s in sets[1:]:
        cur = intersect_two(cur, merge_intervals(s))
        if not cur:
            break
    return cur


def subtract_intervals(base: list[Interval], cuts: list[Interval]) -> list[Interval]:
    remaining = merge_intervals(base)
    for c in merge_intervals(cuts):
        nxt: list[Interval] = []
        for r in remaining:
            rs, re_ = _aware(r.start), _aware(r.end)
            cs, ce = _aware(c.start), _aware(c.end)
            if ce <= rs or cs >= re_:
                nxt.append(r)
                continue
            if cs > rs:
                nxt.append(Interval(rs, min(cs, re_), r.meta))
            if ce < re_:
                nxt.append(Interval(max(ce, rs), re_, r.meta))
        remaining = nxt
        if not remaining:
            break
    return remaining


def _iv_json(intervals: list[Interval]) -> list[dict]:
    return [{"start": _iso(i.start), "end": _iso(i.end)} for i in intervals]


def _iv_from(items: list[dict] | None) -> list[Interval]:
    return [Interval(datetime.fromisoformat(i["start"]), datetime.fromisoformat(i["end"]))
            for i in (items or [])]


def _iv_days(intervals: list[Interval]) -> int:
    return sum(_days(i.start, i.end) for i in intervals)


def coverage_intervals(db: Session, project_id: int, *, verified_only: bool = True) -> list[Interval]:
    """项目可由可核验读数覆盖的区间（合并）。

    verified_only=True 时只保留真正可核验（读数/倍率已补证）的区间；
    共用总表也覆盖日期，独立性另行检查。
    """
    rows = db.query(MeterCoverageWindow).filter(MeterCoverageWindow.project_id == project_id).all()
    return merge_intervals([Interval(w.valid_from, w.valid_to,
                                     {"meter": w.meter_serial, "independent": w.independent,
                                      "verified": w.verified,
                                      "window_id": w.id, "project_id": project_id})
                            for w in rows
                            if (not verified_only or w.verified)])


def uncovered_exclusions(period: list[Interval], covered: list[Interval], label: str,
                         reason: str) -> tuple[list[Interval], list[dict]]:
    """返回 (可用区间, 被排除缺口)。用于说明哪些日期未进入候选。"""
    usable = intersect_two(period, covered)
    gaps = subtract_intervals(period, covered)
    excluded = [{"scope": label, "start": _iso(g.start), "end": _iso(g.end),
                 "reason": reason, "gap_days": _days(g.start, g.end)}
                for g in gaps if g.end > g.start]
    return usable, excluded


def occupancy_ratio(db: Session, project_id: int, start: datetime, end: datetime) -> float:
    """区间内被占用（开放）时间占比；无占用登记时视为 0（无法证明覆盖）。"""
    start, end = _aware(start), _aware(end)
    total = (end - start).total_seconds()
    if total <= 0:
        return 0.0
    rows = db.query(OccupancyWindow).filter(OccupancyWindow.project_id == project_id).all()
    clipped = intersect_two(merge_intervals([Interval(w.valid_from, w.valid_to) for w in rows]),
                            [Interval(start, end)])
    covered = sum((_aware(i.end) - _aware(i.start)).total_seconds() for i in clipped)
    return round(min(1.0, covered / total), 4)


# ---------------------------------------------------------------- 项目窗口


def _profile(db: Session, project_id: int) -> ProjectComparisonProfile | None:
    return (db.query(ProjectComparisonProfile)
            .filter(ProjectComparisonProfile.project_id == project_id).first())


def _anchor(workspace: ComparisonWorkspace) -> datetime:
    """无已确认范围/边界时的基准日：资料截止点所在年的上一年 1 月 1 日。"""
    cutoff = _aware(workspace.material_cutoff)
    return datetime(cutoff.year - 1, 1, 1, tzinfo=timezone.utc)


def _scope_window(scope: ScopeRelation) -> tuple[datetime, datetime]:
    start = _aware(scope.valid_from) if scope.valid_from else datetime(1970, 1, 1, tzinfo=timezone.utc)
    end = _aware(scope.valid_to) if scope.valid_to else datetime(2100, 1, 1, tzinfo=timezone.utc)
    return start, end


def window_options(db: Session, workspace: ComparisonWorkspace, project_id: int) -> list[dict]:
    """项目可用窗口：读取**已确认的范围关系**与**计量边界**的基线期/报告期区间。

    每个窗口 = 确认范围的服务区间 ∩ 基线边界 ∩ 报告边界，并裁剪到资料截止点之前。
    截止点之后才发生的日期不参与比较（改动截止点必须重新核验）。
    无可用组合时退回工作区基准年窗口。
    """
    cutoff = _aware(workspace.material_cutoff)
    scopes = (
        db.query(ScopeRelation)
        .filter(ScopeRelation.project_id == project_id,
                ScopeRelation.status == ScopeStatus.confirmed)
        .order_by(ScopeRelation.id)
        .all()
    )
    bounds = (
        db.query(MeteringBoundary)
        .filter(MeteringBoundary.project_id == project_id)
        .order_by(MeteringBoundary.id)
        .all()
    )
    base_bounds = [b for b in bounds if b.period_role == PeriodRole.baseline]
    rep_bounds = [b for b in bounds if b.period_role == PeriodRole.reporting]

    out: list[dict] = []
    seen = set()
    for sc in scopes:
        sc_from, sc_to = _scope_window(sc)
        # 只组合关联到该范围（或未关联）的边界，避免交叉出混合窗口
        chain_b = [b for b in base_bounds if b.scope_relation_id in (None, sc.id)]
        chain_r = [b for b in rep_bounds if b.scope_relation_id in (None, sc.id)]
        for bb in chain_b:
            for rb in chain_r:
                bs = min(max(sc_from, _aware(bb.valid_from)), cutoff)
                be = min(sc_to, _aware(bb.valid_to) if bb.valid_to else cutoff, cutoff)
                rs = min(max(sc_from, _aware(rb.valid_from)), cutoff)
                re_ = min(sc_to, _aware(rb.valid_to) if rb.valid_to else cutoff, cutoff)
                if be <= bs or re_ <= rs:
                    continue
                key = (bs, be, rs, re_)
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "source": "scope_boundary",
                    "scope_relation_id": sc.id,
                    "subject_ref": sc.subject_ref,
                    "baseline_boundary_id": bb.id,
                    "reporting_boundary_id": rb.id,
                    "meter_serial": rb.meter_serial,
                    "pipeline_kind": rb.pipeline_kind.value,
                    "baseline": (bs, be),
                    "reporting": (rs, re_),
                })
    if not out:
        a = min(_anchor(workspace), cutoff)
        out.append({"source": "workspace_anchor", "scope_relation_id": None,
                    "subject_ref": None, "baseline_boundary_id": None,
                    "reporting_boundary_id": None, "meter_serial": None,
                    "pipeline_kind": None,
                    "baseline": (a, min(a + timedelta(days=365), cutoff)),
                    "reporting": (min(a + timedelta(days=365), cutoff),
                                  min(a + timedelta(days=730), cutoff))})
    # 优先按窗口长度排序，长窗口更可能形成共同比较区间
    out.sort(key=lambda w: -(_days(*w["baseline"]) + _days(*w["reporting"])))
    return out


def signature_from(db: Session, project_id: int, win: dict) -> dict:
    prof = _profile(db, project_id)
    bs, be = win["baseline"]
    rs, re_ = win["reporting"]
    return {
        "project_id": project_id,
        "source": win["source"],
        "scope_relation_id": win.get("scope_relation_id"),
        "subject_ref": win.get("subject_ref"),
        "meter_serial": win.get("meter_serial"),
        "pipeline_kind": win.get("pipeline_kind"),
        "building_use": prof.building_use.value if prof else None,
        "climate_zone": prof.climate_zone.value if prof else None,
        "occupancy_profile": prof.occupancy_profile.value if prof else None,
        "area_m2": prof.area_m2 if prof else None,
        "includes_dining": prof.includes_dining if prof else None,
        "includes_public_load": prof.includes_public_load if prof else None,
        "shared_load_keys": sorted(prof.shared_load_keys or []) if prof else [],
        "baseline": {"start": _iso(bs), "end": _iso(be), "days": _days(bs, be)},
        "reporting": {"start": _iso(rs), "end": _iso(re_), "days": _days(rs, re_)},
        "occupancy_cover": {
            "baseline": occupancy_ratio(db, project_id, bs, be),
            "reporting": occupancy_ratio(db, project_id, rs, re_),
        },
        "window": {"baseline": (_iso(bs), _iso(be)), "reporting": (_iso(rs), _iso(re_))},
    }


def window_context(db: Session, workspace: ComparisonWorkspace, project_id: int) -> list[tuple[str, int]]:
    """项目窗口引用的来源登记（范围关系 / 边界 / 证据），用于来源血缘。"""
    out: list[tuple[str, int]] = []
    for win in window_options(db, workspace, project_id):
        if win.get("scope_relation_id"):
            out.append(("scope_relation", win["scope_relation_id"]))
        for key in ("baseline_boundary_id", "reporting_boundary_id"):
            if win.get(key):
                out.append(("boundary", win[key]))
    scopes = (db.query(ScopeRelation)
              .filter(ScopeRelation.project_id == project_id,
                      ScopeRelation.status == ScopeStatus.confirmed).all())
    for sc in scopes:
        for eid in (sc.evidence_ids or []):
            out.append(("evidence", eid))
    return list(dict.fromkeys(out))


def project_condition_blockers(rule: ComparisonRule, project_id: int, sig: dict) -> list[dict]:
    """项目自身相对规则的条件缺口（项目对与全组队列共用）。"""
    out: list[dict] = []
    if sig["building_use"] is None:
        out.append({"code": "profile_missing", "project_id": project_id,
                    "reason": "项目缺少比较属性（建筑用途/气候带/占用覆盖）登记"})
        return out
    if rule.building_use is not None and sig["building_use"] != rule.building_use.value:
        out.append({"code": "building_use_mismatch", "project_id": project_id,
                    "reason": f"建筑用途为 {sig['building_use']}，规则要求 {rule.building_use.value}"})
    if rule.climate_zone is not None and sig["climate_zone"] != rule.climate_zone.value:
        out.append({"code": "climate_zone_mismatch", "project_id": project_id,
                    "reason": f"气候带为 {sig['climate_zone']}，规则要求 {rule.climate_zone.value}"})
    if rule.occupancy_profile is not None and sig["occupancy_profile"] != rule.occupancy_profile.value:
        out.append({"code": "occupancy_profile_mismatch", "project_id": project_id,
                    "reason": f"占用形态为 {sig['occupancy_profile']}，规则要求 {rule.occupancy_profile.value}"})
    bdays = sig["baseline"]["days"]
    if bdays < rule.min_baseline_days:
        out.append({"code": "baseline_too_short", "project_id": project_id,
                    "reason": f"基线长度 {bdays} 天，低于规则下限 {rule.min_baseline_days} 天"})
    if bdays > rule.max_baseline_days:
        out.append({"code": "baseline_too_long", "project_id": project_id,
                    "reason": f"基线长度 {bdays} 天，高于规则上限 {rule.max_baseline_days} 天"})
    for period in ("baseline", "reporting"):
        cover = sig["occupancy_cover"][period]
        if cover < rule.occupancy_cover_min:
            label = "基线期" if period == "baseline" else "报告期"
            out.append({"code": "occupancy_cover_low", "project_id": project_id,
                        "reason": f"{label}占用覆盖 {cover:.0%}，低于规则要求 {rule.occupancy_cover_min:.0%}"})
    return out


# ---------------------------------------------------------------- 共用总表


def shared_meter_conflict(db: Session, a_id: int, b_id: int,
                          start: datetime, end: datetime) -> list[dict]:
    """同一表号重叠，且任一方既无可核验独立读数也无可核验分配依据 → 不得当两份独立样本。"""
    start, end = _aware(start), _aware(end)
    a_wins = db.query(MeterCoverageWindow).filter(MeterCoverageWindow.project_id == a_id).all()
    b_wins = db.query(MeterCoverageWindow).filter(MeterCoverageWindow.project_id == b_id).all()
    out: list[dict] = []
    seen = set()
    for wa in a_wins:
        for wb in b_wins:
            if wa.meter_serial != wb.meter_serial:
                continue
            s = max(_aware(wa.valid_from), _aware(wb.valid_from), start)
            e = min(_aware(wa.valid_to), _aware(wb.valid_to), end)
            if e <= s:
                continue
            basis_a = wa.independent or wa.has_allocation_basis
            basis_b = wb.independent or wb.has_allocation_basis
            if basis_a and basis_b:
                continue
            key = (wa.meter_serial, s, e)
            if key in seen:
                continue
            seen.add(key)
            missing = [("项目甲" if not basis_a else ""), ("项目乙" if not basis_b else "")]
            out.append({
                "scope": "shared_meter", "start": _iso(s), "end": _iso(e),
                "meter_serial": wa.meter_serial,
                "reason": (f"甲乙共用总表 {wa.meter_serial}，{'/'.join(m for m in missing if m)}"
                           "缺少可核验的独立读数或分配依据，不能把总表结果作为两份独立样本；"
                           "该区间不进入比较"),
                "gap_days": _days(s, e),
            })
    return out


# ---------------------------------------------------------------- 项目对比较


def _pick_windows(db: Session, workspace: ComparisonWorkspace, a_id: int, b_id: int):
    """为项目对选取双方重叠最大的事实窗口组合（分别计算共同条件，不做传递）。"""
    opts_a = window_options(db, workspace, a_id)
    opts_b = window_options(db, workspace, b_id)
    best = None
    best_score = -1
    combos = []
    for wa in opts_a:
        for wb in opts_b:
            bs = max(wa["baseline"][0], wb["baseline"][0])
            be = min(wa["baseline"][1], wb["baseline"][1])
            rs = max(wa["reporting"][0], wb["reporting"][0])
            re_ = min(wa["reporting"][1], wb["reporting"][1])
            bdays = _days(bs, be) if be > bs else 0
            rdays = _days(rs, re_) if re_ > rs else 0
            score = bdays + rdays
            combos.append({"a": wa, "b": wb,
                           "baseline": (bs, be) if bdays else None,
                           "reporting": (rs, re_) if rdays else None,
                           "score": score})
            if score > best_score:
                best_score = score
                best = combos[-1]
    return best, combos, opts_a, opts_b


def compare_pair(db: Session, rule: ComparisonRule, workspace: ComparisonWorkspace,
                 a_id: int, b_id: int) -> dict:
    """计算单个项目对的比较资格、共同窗口与排除原因。不做节能率排名。"""
    reasons: list[str] = []
    exclusions: list[dict] = []
    limitations: list[str] = []

    best, combos, opts_a, opts_b = _pick_windows(db, workspace, a_id, b_id)
    have_common = bool(best and best["baseline"] and best["reporting"])

    if have_common:
        wa, wb = best["a"], best["b"]
        sig_a = signature_from(db, a_id, wa)
        sig_b = signature_from(db, b_id, wb)
        base_period = [Interval(*best["baseline"])]
        rep_period = [Interval(*best["reporting"])]
    else:
        sig_a = signature_from(db, a_id, opts_a[0])
        sig_b = signature_from(db, b_id, opts_b[0])
        base_period, rep_period = [], []
        reasons.append("双方没有共同可用的基线期与报告期窗口：无法形成项目对比较")

    blockers_a = project_condition_blockers(rule, a_id, sig_a)
    blockers_b = project_condition_blockers(rule, b_id, sig_b)

    # ---- 共同条件（逐字段比较，不做传递推断）
    differences: list[str] = []
    for key, label in (("building_use", "建筑用途"), ("climate_zone", "气候带"),
                       ("occupancy_profile", "占用形态")):
        if sig_a[key] != sig_b[key]:
            differences.append(f"{label}不同（{sig_a[key]} / {sig_b[key]}）：仅能作局部比较，不得视为同质样本")
    if sig_a["includes_dining"] != sig_b["includes_dining"]:
        differences.append("计量边界是否含食堂不一致：范围定义不同，仅限局部比较")
    if sig_a["includes_public_load"] != sig_b["includes_public_load"]:
        differences.append("公共负荷覆盖不一致：需确认是否重复计入，仅限局部比较")
    if sorted(sig_a["shared_load_keys"]) != sorted(sig_b["shared_load_keys"]):
        differences.append("登记的公共负荷清单不一致：跨项目汇总可能重复或漏计公共负荷")
    limitations.extend(differences)

    if have_common:
        off_b = abs(_days(datetime.fromisoformat(sig_a["window"]["baseline"][0]),
                          datetime.fromisoformat(sig_b["window"]["baseline"][0])))
        off_r = abs(_days(datetime.fromisoformat(sig_a["window"]["reporting"][0]),
                          datetime.fromisoformat(sig_b["window"]["reporting"][0])))
        if off_b > rule.date_tolerance_days or off_r > rule.date_tolerance_days:
            differences.append(
                f"双方起算日期偏差超出允许值 {rule.date_tolerance_days} 天（基线 {off_b} 天、报告期 {off_r} 天）："
                "需切换为一致的日期窗口后重新核验")
        len_gap = abs(sig_a["baseline"]["days"] - sig_b["baseline"]["days"])
        if len_gap > rule.baseline_length_tolerance_days:
            differences.append(
                f"基线长度相差 {len_gap} 天，超出规则允许 {rule.baseline_length_tolerance_days} 天：分母不可直接对照")

    if sig_a["area_m2"] and sig_b["area_m2"]:
        ratio = max(sig_a["area_m2"], sig_b["area_m2"]) / max(1e-9, min(sig_a["area_m2"], sig_b["area_m2"]))
        if ratio > rule.max_area_ratio:
            limitations.append(f"面积比 {ratio:.2f} 超出 {rule.max_area_ratio}：面积相近不代表气候暴露与使用强度相近")

    # ---- 覆盖与共用总表
    cov_a = coverage_intervals(db, a_id)
    cov_b = coverage_intervals(db, b_id)
    cov_a_unverified = subtract_intervals(coverage_intervals(db, a_id, verified_only=False), cov_a)
    cov_b_unverified = subtract_intervals(coverage_intervals(db, b_id, verified_only=False), cov_b)
    common = intersect_two(cov_a, cov_b)
    # 仅登记但不可核验的区间（如倍率仅部分补证）明确列为排除
    for pid, tag, unver in ((a_id, "项目甲", cov_a_unverified), (b_id, "项目乙", cov_b_unverified)):
        for iv in unver:
            exclusions.append({
                "scope": "unverified_coverage", "project_id": pid,
                "start": _iso(iv.start), "end": _iso(iv.end),
                "reason": f"{tag}该区间读数/倍率尚未补证，只登记、不进入比较候选",
                "gap_days": _days(iv.start, iv.end),
            })

    span_candidates = []
    if best:
        if best.get("baseline"):
            span_candidates.append(best["baseline"])
        if best.get("reporting"):
            span_candidates.append(best["reporting"])
    if not span_candidates:
        span_candidates = [(_anchor(workspace), _anchor(workspace))]
    span_from = min(p[0] for p in span_candidates)
    span_to = max(p[1] for p in span_candidates)
    shared = shared_meter_conflict(db, a_id, b_id, span_from, span_to)
    shared_cut = [Interval(datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"]))
                  for s in shared]
    common_independent = subtract_intervals(common, shared_cut)
    exclusions.extend(shared)

    base_candidates, base_gaps = uncovered_exclusions(
        base_period, common_independent, "baseline",
        "基线区间缺少双方共同的可核验计量覆盖（含倍率仅部分补证），不进入候选")
    rep_candidates, rep_gaps = uncovered_exclusions(
        rep_period, common_independent, "reporting",
        "报告区间缺少双方共同的可核验计量覆盖，不进入候选")
    exclusions.extend(base_gaps + rep_gaps)

    if base_period and not base_candidates:
        reasons.append("基线期没有双方共同可核验覆盖：无可用候选区间")
    if rep_period and not rep_candidates:
        reasons.append("报告期没有双方共同可核验覆盖：无可用候选区间")
    if base_candidates and _iv_days(base_candidates) < _iv_days(base_period):
        bits = []
        if shared:
            bits.append("共用总表区间")
        bits.append("覆盖/倍率缺口")
        limitations.append(
            f"基线候选区间被压缩为 {_iv_days(base_candidates)}/{_iv_days(base_period)} 天"
            f"（排除{'与'.join(bits)}），结果只代表该局部区间")
    if rep_candidates and _iv_days(rep_candidates) < _iv_days(rep_period):
        limitations.append(
            f"报告候选区间被压缩为 {_iv_days(rep_candidates)}/{_iv_days(rep_period)} 天，结果只代表该局部区间")

    if not any(w.independent for w in db.query(MeterCoverageWindow)
               .filter(MeterCoverageWindow.project_id == a_id).all()) or \
       not any(w.independent for w in db.query(MeterCoverageWindow)
               .filter(MeterCoverageWindow.project_id == b_id).all()):
        limitations.append("一方的计量覆盖仅来自共用总表（无独立读数/分配依据）：结论受限")

    # 共同窗口最短天数（硬性门槛 → 不可比）
    blocked = bool(blockers_a or blockers_b or not have_common
                   or not base_candidates or not rep_candidates)
    if base_period and base_candidates and _iv_days(base_candidates) < rule.min_common_window_days:
        blocked = True
        reasons.append(f"基线共同候选区间仅 {_iv_days(base_candidates)} 天，低于规则要求 {rule.min_common_window_days} 天")
    if rep_period and rep_candidates and _iv_days(rep_candidates) < rule.min_common_window_days:
        blocked = True
        reasons.append(f"报告共同候选区间仅 {_iv_days(rep_candidates)} 天，低于规则要求 {rule.min_common_window_days} 天")

    # 共用总表且无独立依据 → 不得作为两份独立样本（硬性不可比）
    if shared:
        blocked = True
        reasons.append("共用总表区间内缺独立读数/分配依据：不能作为两份独立样本")

    # 共同候选区间的占用覆盖（双方都必须在该区间内实际开放）
    low_occupancy = False
    if base_candidates and rep_candidates:
        for pid, tag in ((a_id, "项目甲"), (b_id, "项目乙")):
            for iv in base_candidates + rep_candidates:
                cover = occupancy_ratio(db, pid, iv.start, iv.end)
                if cover < rule.occupancy_cover_min:
                    low_occupancy = True
                    reasons.append(
                        f"{tag}在共同候选区间 {iv.start.date()}~{iv.end.date()} 的占用覆盖仅 {cover:.0%}，"
                        f"低于规则要求 {rule.occupancy_cover_min:.0%}（可能是假期/停用）")

    if blockers_a:
        reasons.extend(r["reason"] for r in blockers_a)
    if blockers_b:
        reasons.extend(r["reason"] for r in blockers_b)
    if differences and not blocked:
        reasons.append("双方条件签名存在差异：仅能作局部比较，不构成全局排名的一部分")

    if blocked:
        level = EdgeLevel.blocked
    elif differences or low_occupancy or limitations:
        level = EdgeLevel.restricted
    else:
        level = EdgeLevel.comparable

    eligible = level in (EdgeLevel.comparable, EdgeLevel.restricted) and bool(base_candidates and rep_candidates)
    if level == EdgeLevel.blocked:
        eligible = False

    if level == EdgeLevel.comparable:
        reasons.append("双方条件签名一致且存在共同候选区间：可作为该工作区内的比较边（不据此排名）")
        supported = ["pairwise_scope_check", "evidence_coverage_check", "local_scope_compare"]
    elif level == EdgeLevel.restricted:
        reasons.append("存在条件或覆盖限制：只支持在该限制范围内的局部比较，不能外推为全局排名")
        supported = ["pairwise_scope_check", "conditional_local_compare"]
    else:
        supported = ["scope_gap_analysis"]

    return {
        "project_a_id": a_id,
        "project_b_id": b_id,
        "level": level.value,
        "eligible": eligible,
        "signatures": {"a": sig_a, "b": sig_b, "equal": not differences, "differences": differences},
        "window": {
            "baseline": {"start": _iso(base_period[0].start if base_period else None),
                         "end": _iso(base_period[0].end if base_period else None)},
            "reporting": {"start": _iso(rep_period[0].start if rep_period else None),
                          "end": _iso(rep_period[0].end if rep_period else None)},
            "candidate_baseline": _iv_json(base_candidates),
            "candidate_reporting": _iv_json(rep_candidates),
            "considered_windows": [
                {"a_scope": c["a"].get("scope_relation_id"),
                 "b_scope": c["b"].get("scope_relation_id"),
                 "a_meter": c["a"].get("meter_serial"),
                 "b_meter": c["b"].get("meter_serial"),
                 "overlap_days": c["score"]} for c in combos
            ],
        },
        "exclusions": exclusions,
        "limitations": limitations,
        "reasons": reasons,
        "inputs": {
            "coverage_a": _iv_json(cov_a),
            "coverage_b": _iv_json(cov_b),
            "common_intersection": _iv_json(common),
            "common_independent_intersection": _iv_json(common_independent),
            "shared_meter_windows": shared,
            "project_a": sig_a,
            "project_b": sig_b,
            "rule": rule.constraint_signature(),
            "material_cutoff": _iso(workspace.material_cutoff),
        },
        "supported_analysis": supported,
    }


# ---------------------------------------------------------------- 工作区核验


def compute_input_digest(db: Session, workspace: ComparisonWorkspace, rule: ComparisonRule) -> str:
    """输入快照指纹：截止点、项目集、规则版本、项目属性/覆盖/占用与所有事实窗口。"""
    payload = {
        "cutoff": _iso(workspace.material_cutoff),
        "projects": sorted(int(p) for p in (workspace.project_ids or [])),
        "rule": rule.constraint_signature(),
        "profiles": [], "coverage": [], "occupancy": [], "windows": [],
    }
    for pid in sorted(int(p) for p in (workspace.project_ids or [])):
        prof = _profile(db, pid)
        payload["profiles"].append({
            "project_id": pid,
            "use": prof.building_use.value if prof else None,
            "climate": prof.climate_zone.value if prof else None,
            "occupancy": prof.occupancy_profile.value if prof else None,
            "area": prof.area_m2 if prof else None,
            "dining": prof.includes_dining if prof else None,
            "public": prof.includes_public_load if prof else None,
            "shared_load_keys": sorted(prof.shared_load_keys or []) if prof else [],
        })
        for win in window_options(db, workspace, pid):
            payload["windows"].append([pid, win["source"], win.get("scope_relation_id"),
                                       win.get("meter_serial"),
                                       _iso(win["baseline"][0]), _iso(win["baseline"][1]),
                                       _iso(win["reporting"][0]), _iso(win["reporting"][1])])
        for w in db.query(MeterCoverageWindow).filter(
                MeterCoverageWindow.project_id == pid).order_by(MeterCoverageWindow.id):
            payload["coverage"].append([pid, w.meter_serial, _iso(w.valid_from), _iso(w.valid_to),
                                        w.independent, w.has_allocation_basis])
        for o in db.query(OccupancyWindow).filter(
                OccupancyWindow.project_id == pid).order_by(OccupancyWindow.id):
            payload["occupancy"].append([pid, _iso(o.valid_from), _iso(o.valid_to)])
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def revalidate_workspace(db: Session, workspace: ComparisonWorkspace,
                         actor: str = "system") -> ComparisonWorkspace:
    """按工作区冻结的规则版本重新核验全部项目对与全组队列。

    切换用途/日期或规则后重新核验：旧比较边与队列全部清空，不保留上一次的绿色资格。
    """
    rule = db.get(ComparisonRule, workspace.rule_id)
    if rule is None:
        raise ValueError("工作区引用的比较规则不存在")
    if workspace.status == WorkspaceStatus.withdrawn:
        raise ValueError("工作区已撤回，不能重新核验")

    db.query(ComparisonSourceAncestry).filter(
        ComparisonSourceAncestry.workspace_id == workspace.id).delete()
    db.query(ComparisonEdge).filter(ComparisonEdge.workspace_id == workspace.id).delete()
    db.query(ComparisonCohort).filter(ComparisonCohort.workspace_id == workspace.id).delete()
    db.flush()

    pids = [int(p) for p in (workspace.project_ids or [])]
    edges: list[ComparisonEdge] = []
    for i in range(len(pids)):
        for j in range(i + 1, len(pids)):
            res = compare_pair(db, rule, workspace, pids[i], pids[j])
            edge = ComparisonEdge(
                workspace_id=workspace.id,
                project_a_id=res["project_a_id"], project_b_id=res["project_b_id"],
                level=EdgeLevel(res["level"]),
                eligible=res["eligible"], on_global_intersection=False,
                signatures=res["signatures"], window=res["window"],
                exclusions=res["exclusions"], limitations=res["limitations"],
                reasons=res["reasons"], inputs=res["inputs"],
                supported_analysis=res["supported_analysis"],
                rule_version=rule.version,
            )
            edges.append(edge)
    db.add_all(edges)
    db.flush()

    # 来源血缘：记录每边引用的范围/边界/覆盖/占用登记，便于按来源定位比较边
    for edge in edges:
        for pid in (edge.project_a_id, edge.project_b_id):
            for ctx_type, ctx_id in window_context(db, workspace, pid):
                db.add(ComparisonSourceAncestry(
                    workspace_id=workspace.id, edge_id=edge.id, project_id=pid,
                    source_type=ctx_type, source_id=ctx_id))
            for c in db.query(MeterCoverageWindow).filter(
                    MeterCoverageWindow.project_id == pid):
                db.add(ComparisonSourceAncestry(
                    workspace_id=workspace.id, edge_id=edge.id, project_id=pid,
                    source_type="coverage", source_id=c.id))
            for o in db.query(OccupancyWindow).filter(OccupancyWindow.project_id == pid):
                db.add(ComparisonSourceAncestry(
                    workspace_id=workspace.id, edge_id=edge.id, project_id=pid,
                    source_type="occupancy", source_id=o.id))
    db.flush()

    workspace.status = WorkspaceStatus.computed
    workspace.rule_version = rule.version
    workspace.stale_reasons = []
    workspace.computed_at = datetime.now(timezone.utc)
    workspace.input_digest = compute_input_digest(db, workspace, rule)
    db.add(AuditLog(actor=actor, action="revalidate_workspace", entity="comparison_workspace",
                    entity_id=workspace.id,
                    detail={"rule_version": rule.version, "pairs": len(edges),
                            "eligible": sum(1 for e in edges if e.eligible)}))
    db.flush()
    return workspace


def mark_workspace_stale(db: Session, workspace: ComparisonWorkspace, reason: dict,
                         actor: str = "system",
                         keep_edges: bool = False) -> ComparisonWorkspace:
    """把工作区标记为过期；旧资格不再可用。

    keep_edges=True 时保留比较边并逐条标记 stale，便于回查“哪些边因来源更正失效”；
    默认删除旧边与队列（条件/规则变更后必须重新核验）。
    """
    if workspace.status == WorkspaceStatus.withdrawn:
        return workspace
    if keep_edges:
        for e in db.query(ComparisonEdge).filter(
                ComparisonEdge.workspace_id == workspace.id).all():
            e.stale = True
    else:
        db.query(ComparisonSourceAncestry).filter(
            ComparisonSourceAncestry.workspace_id == workspace.id).delete()
        db.query(ComparisonEdge).filter(ComparisonEdge.workspace_id == workspace.id).delete()
    db.query(ComparisonCohort).filter(ComparisonCohort.workspace_id == workspace.id).delete()
    workspace.status = WorkspaceStatus.stale
    workspace.stale_reasons = list(workspace.stale_reasons or []) + [reason]
    db.add(AuditLog(actor=actor, action="workspace_stale", entity="comparison_workspace",
                    entity_id=workspace.id, detail=reason))
    db.flush()
    return workspace


# ---------------------------------------------------------------- 全组队列


def _best_cohort_windows(db: Session, workspace: ComparisonWorkspace, pids: list[int]) -> dict:
    """为全组选择一组事实窗口，使全组共同交集最大（每项目取一个窗口）。"""
    opts = {pid: window_options(db, workspace, pid) for pid in pids}
    combos = list(itertools.product(*[opts[p] for p in pids]))
    if len(combos) > 4096:  # 防御性上限：只考虑每项目最新窗口
        combos = [tuple(opts[p][0] for p in pids)]
    best, best_score, best_intersection = None, -1, None
    for combo in combos:
        wins = dict(zip(pids, combo))
        bset = [[Interval(*wins[p]["baseline"])] for p in pids]
        rset = [[Interval(*wins[p]["reporting"])] for p in pids]
        bi = intersect_all(bset)
        ri = intersect_all(rset)
        score = _iv_days(bi) + _iv_days(ri)
        if score > best_score:
            best_score, best, best_intersection = score, wins, (bi, ri)
    return {"windows": best, "intersection": best_intersection or ([], [])}


def _shared_cuts_for_group(db: Session, pids: list[int]) -> tuple[list[Interval], list[dict]]:
    meter_owners: dict[str, list[int]] = {}
    for pid in pids:
        for w in db.query(MeterCoverageWindow).filter(MeterCoverageWindow.project_id == pid):
            meter_owners.setdefault(w.meter_serial, []).append(pid)
    cuts: list[Interval] = []
    notes: list[dict] = []
    for meter, owners in meter_owners.items():
        if len(owners) < 2:
            continue
        wins_ = (db.query(MeterCoverageWindow)
                 .filter(MeterCoverageWindow.project_id.in_(owners),
                         MeterCoverageWindow.meter_serial == meter).all())
        if all(w.independent or w.has_allocation_basis for w in wins_):
            continue
        s = max(_aware(w.valid_from) for w in wins_)
        e = min(_aware(w.valid_to) for w in wins_)
        if e > s:
            cuts.append(Interval(s, e))
            notes.append({"meter_serial": meter, "projects": sorted(owners),
                          "start": _iso(s), "end": _iso(e),
                          "reason": "共用总表且缺独立读数/分配依据，全组队列剔除该区间"})
    return cuts, notes


def _cohort_intersection(db: Session, workspace: ComparisonWorkspace,
                         pids: list[int]) -> dict:
    chosen = _best_cohort_windows(db, workspace, pids)
    bi, ri = chosen["intersection"]
    cov_all = intersect_all([coverage_intervals(db, p) for p in pids])
    cuts, notes = _shared_cuts_for_group(db, pids)
    return {
        "windows": chosen["windows"],
        "baseline": subtract_intervals(intersect_two(cov_all, bi), cuts),
        "reporting": subtract_intervals(intersect_two(cov_all, ri), cuts),
        "raw_baseline": bi, "raw_reporting": ri,
        "shared_notes": notes,
    }


def build_cohort(db: Session, workspace: ComparisonWorkspace,
                 actor: str = "system") -> ComparisonCohort:
    """全组统一队列：仅在所有项目共同交集上建立，并说明哪个项目压缩了范围。"""
    rule = db.get(ComparisonRule, workspace.rule_id)
    if rule is None:
        raise ValueError("比较规则不存在")
    pids = [int(p) for p in (workspace.project_ids or [])]
    if len(pids) < 2:
        raise ValueError("全组队列至少需要两个项目")

    # 全组条件：每个项目取能形成最大共同交集的那组窗口后，再检查规则条件
    chosen = _best_cohort_windows(db, workspace, pids)
    sigs = {pid: signature_from(db, pid, chosen["windows"][pid]) for pid in pids}
    blockers = {pid: project_condition_blockers(rule, pid, sigs[pid]) for pid in pids}
    members = [pid for pid in pids if not blockers[pid]]
    excluded_projects = [{"project_id": pid, "reasons": [b["reason"] for b in blockers[pid]],
                          "effect": "该项目不满足规则条件，不进入全组队列；若纳入将压缩整批可用范围"}
                         for pid in pids if blockers[pid]]

    limitations: list[str] = []
    reasons: list[str] = []
    intersection = {"baseline": [], "reporting": [], "shared_notes": [], "limiters": [],
                    "raw_baseline": [], "raw_reporting": []}

    if len(members) >= 2:
        res = _cohort_intersection(db, workspace, members)
        intersection.update({
            "baseline": _iv_json(res["baseline"]),
            "reporting": _iv_json(res["reporting"]),
            "raw_baseline": _iv_json(res["raw_baseline"]),
            "raw_reporting": _iv_json(res["raw_reporting"]),
            "shared_notes": res["shared_notes"],
        })
        limitations.extend(n["reason"] for n in res["shared_notes"])
        global_days = _iv_days(res["baseline"]) + _iv_days(res["reporting"])
        limiters: list[dict] = []
        for pid in members:
            rest = [p for p in members if p != pid]
            if len(rest) < 2:
                continue
            alt = _cohort_intersection(db, workspace, rest)
            alt_days = _iv_days(alt["baseline"]) + _iv_days(alt["reporting"])
            if alt_days > global_days:
                limiters.append({"project_id": pid,
                                 "days_gained_if_removed": alt_days - global_days,
                                 "reason": "该项目的覆盖/窗口最薄弱，压缩了整批可用日期与范围"})
        intersection["limiters"] = limiters
        if limiters:
            reasons.append("存在资料薄弱项目压缩全组可用范围：需接受更窄的共同区间，或退回项目对局部比较")
        for pid in members:
            s = sigs[pid]
            limitations.append(
                f"项目 {pid} 窗口：基线 {s['baseline']['start'][:10]}~{s['baseline']['end'][:10]}，"
                f"报告期 {s['reporting']['start'][:10]}~{s['reporting']['end'][:10]}")
        if not res["baseline"] or not res["reporting"]:
            reasons.append("所有项目没有共同的完整基线期与报告期覆盖：不能建立全组统一队列")
        else:
            limitations.append(
                f"全组共同交集：基线 {_iv_days(res['baseline'])} 天、报告期 {_iv_days(res['reporting'])} 天；"
                "未纳入的日期只能用于项目对局部比较")
            reasons.append("已在全部项目的共同覆盖交集上建立统一队列（不构成节能率排名）")
    else:
        reasons.append("满足规则条件的项目不足两个：不能建立全组统一队列")

    if excluded_projects:
        reasons.append("存在不满足规则条件的项目：全组队列不能以其为准，需在项目对层面保留局部比较")

    # 重复触发时先清除旧队列（每个工作区只保留一份当前队列）
    db.query(ComparisonCohort).filter(
        ComparisonCohort.workspace_id == workspace.id).delete()
    db.flush()

    cohort = ComparisonCohort(
        workspace_id=workspace.id,
        intersection=intersection,
        members=[{"project_id": pid, "signature": sigs[pid]} for pid in members],
        excluded_projects=excluded_projects,
        limitations=limitations,
        reasons=reasons,
        rule_version=rule.version,
    )
    db.add(cohort)
    db.flush()

    # 每个项目在全组队列中的状态（入选/排除/限制交集）
    db.query(ComparisonProjectStatus).filter(
        ComparisonProjectStatus.workspace_id == workspace.id).delete()
    limiter_map = {l["project_id"]: l for l in intersection["limiters"]}
    for pid in pids:
        if blockers[pid]:
            db.add(ComparisonProjectStatus(
                workspace_id=workspace.id, project_id=pid, in_cohort=False,
                status="excluded", reasons=[b["reason"] for b in blockers[pid]],
                effect="不满足规则条件，不进入全组队列"))
        elif pid in limiter_map:
            db.add(ComparisonProjectStatus(
                workspace_id=workspace.id, project_id=pid, in_cohort=True,
                status="limiter", reasons=[limiter_map[pid]["reason"]],
                effect=f"该项目的覆盖/窗口最薄弱，压缩整批约 {limiter_map[pid]['days_gained_if_removed']} 天"))
        else:
            db.add(ComparisonProjectStatus(
                workspace_id=workspace.id, project_id=pid, in_cohort=True,
                status="member", reasons=[], effect=""))

    commons_b = _iv_from(cohort.intersection["baseline"])
    commons_r = _iv_from(cohort.intersection["reporting"])
    commons_days_b = _iv_days(commons_b)
    commons_days_r = _iv_days(commons_r)
    for e in db.query(ComparisonEdge).filter(ComparisonEdge.workspace_id == workspace.id).all():
        cand_b = _iv_from(e.window.get("candidate_baseline"))
        cand_r = _iv_from(e.window.get("candidate_reporting"))
        # 只有候选区间“完整覆盖”全组共同交集，才算可进全组汇总；
        # 仅部分重叠（例如薄弱项目的短覆盖）不算。
        coord_b = _iv_days(intersect_two(cand_b, commons_b)) >= commons_days_b
        coord_r = _iv_days(intersect_two(cand_r, commons_r)) >= commons_days_r
        e.on_global_intersection = bool(
            e.eligible and e.project_a_id in members and e.project_b_id in members
            and commons_days_b and commons_days_r and coord_b and coord_r)
    db.flush()
    db.add(AuditLog(actor=actor, action="build_cohort", entity="comparison_workspace",
                    entity_id=workspace.id,
                    detail={"members": len(members), "excluded": len(excluded_projects)}))
    db.flush()
    return cohort


# ---------------------------------------------------------------- 发布与来源更正


def _edge_snapshot(e: ComparisonEdge) -> dict:
    return {
        "edge_id": e.id, "project_a_id": e.project_a_id, "project_b_id": e.project_b_id,
        "level": e.level.value,
        "eligible": e.eligible, "on_global_intersection": e.on_global_intersection,
        "signatures": e.signatures,
        "window": e.window, "exclusions": e.exclusions, "limitations": e.limitations,
        "reasons": e.reasons, "supported_analysis": e.supported_analysis,
    }


def publish_workspace(db: Session, workspace: ComparisonWorkspace,
                      actor: str = "system") -> ComparisonPublication:
    """发布比较清单：冻结项目、日期、限制与分母；新版本说明新增/失效/受限项目对。"""
    if workspace.status in (WorkspaceStatus.stale, WorkspaceStatus.draft, WorkspaceStatus.withdrawn):
        raise ValueError("工作区已过期、撤回或尚未核验，不能发布；请先重新核验")
    rule = db.get(ComparisonRule, workspace.rule_id)
    active_rule = (db.query(ComparisonRule)
                   .filter(ComparisonRule.code == rule.code,
                           ComparisonRule.status == RuleStatus.active)
                   .order_by(ComparisonRule.version.desc()).first())
    if active_rule is not None and rule.version != active_rule.version:
        raise ValueError("工作区冻结的规则版本已被更新版本取代：旧资格不得作为新规则下的结果发布")

    edges = (db.query(ComparisonEdge).filter(ComparisonEdge.workspace_id == workspace.id)
             .order_by(ComparisonEdge.project_a_id, ComparisonEdge.project_b_id).all())
    cohort = db.query(ComparisonCohort).filter(ComparisonCohort.workspace_id == workspace.id).first()

    prev = (db.query(ComparisonPublication).filter(ComparisonPublication.workspace_id == workspace.id)
            .order_by(ComparisonPublication.version.desc()).first())
    prev_map = {(e["project_a_id"], e["project_b_id"]): e
                for e in (prev.edges_snapshot or [])} if prev else {}

    snapshot = [_edge_snapshot(e) for e in edges]
    new_map = {(e["project_a_id"], e["project_b_id"]): e for e in snapshot}
    added, dropped, restricted = [], [], []
    for key, e in new_map.items():
        old = prev_map.get(key)
        if old is None:
            added.append({"pair": list(key), "eligible": e["eligible"]})
        elif old["eligible"] and not e["eligible"]:
            dropped.append({"pair": list(key), "reason": (e["reasons"] or [""])[0]})
        elif e["eligible"] and (e["limitations"] or e["exclusions"]):
            restricted.append({"pair": list(key), "limitations": e["limitations"],
                               "exclusions": e["exclusions"]})
        elif old["eligible"] != e["eligible"] or old["window"] != e["window"]:
            restricted.append({"pair": list(key), "limitations": e["limitations"],
                               "exclusions": e["exclusions"]})
    for key in prev_map:
        if key not in new_map:
            dropped.append({"pair": list(key), "reason": "项目对已移出本工作区或项目退出"})

    version = (prev.version + 1) if prev else 1
    pub = ComparisonPublication(
        workspace_id=workspace.id, version=version, rule_id=workspace.rule_id,
        rule_version=rule.version, project_ids=list(workspace.project_ids or []),
        material_cutoff=workspace.material_cutoff, edges_snapshot=snapshot,
        cohort_snapshot=({"intersection": cohort.intersection, "members": cohort.members,
                          "excluded_projects": cohort.excluded_projects,
                          "limitations": cohort.limitations, "reasons": cohort.reasons}
                         if cohort else None),
        diff_from_previous={"added": added, "dropped": dropped, "restricted": restricted,
                            "base_version": prev.version if prev else None},
        stale=False, published_by=actor,
    )
    db.add(pub)
    workspace.status = WorkspaceStatus.published
    db.flush()
    db.add(AuditLog(actor=actor, action="publish_comparison", entity="comparison_publication",
                    entity_id=pub.id,
                    detail={"workspace_id": workspace.id, "version": version,
                            "added": len(added), "dropped": len(dropped)}))
    db.flush()
    return pub


def mark_source_corrections(db: Session, *, project_ids: list[int], source_ref: str,
                            source_types: list[str] | None = None,
                            source_ids: list[int] | None = None,
                            actor: str = "system") -> dict:
    """资料目录更正：先按来源定位比较边，再重新检查涉及队列。

    - 受更正来源影响的比较边单独标记 stale（不再可用），未受影响的边保留可用。
    - 工作区整体转为 stale（需要重新核验），但保留边与队列以便回查“哪些边失效”。
    - 已发布清单标记 stale 并保留原分母；新清单说明新增/失效/受限项目对。
    """
    pid_set = set(int(p) for p in project_ids)
    type_set = set(source_types or [])
    id_set = set(int(i) for i in (source_ids or []))
    touched_ws: list[int] = []
    affected_edges: list[dict] = []

    for ws in db.query(ComparisonWorkspace).filter(
            ComparisonWorkspace.status.in_((WorkspaceStatus.computed, WorkspaceStatus.published))).all():
        pids = [int(p) for p in (ws.project_ids or [])]
        hit = [p for p in pids if p in pid_set]
        if not hit:
            continue
        edges = db.query(ComparisonEdge).filter(ComparisonEdge.workspace_id == ws.id).all()
        hit_edges: list[dict] = []
        for e in edges:
            same_project = e.project_a_id in pid_set or e.project_b_id in pid_set
            linked = True
            if type_set or id_set:
                # 有更精确来源时，只用来源血缘定位
                anc = (db.query(ComparisonSourceAncestry)
                       .filter(ComparisonSourceAncestry.edge_id == e.id)
                       .all())
                linked = any((not type_set or a.source_type in type_set)
                             and (not id_set or a.source_id in id_set) for a in anc)
            if not (same_project and linked):
                continue
            e.stale = True
            e.stale_reasons = list(e.stale_reasons or []) + [{
                "source_ref": source_ref,
                "projects": sorted({e.project_a_id, e.project_b_id} & pid_set),
                "note": "该比较边引用的来源已更正，需要重新核验",
            }]
            hit_edges.append({"edge_id": e.id, "pair": [e.project_a_id, e.project_b_id]})

        affected_edges.extend({"workspace_id": ws.id, **h} for h in hit_edges)
        # 队列若含更正项目也随之失效（删除，需重新求出交集）
        db.query(ComparisonCohort).filter(
            ComparisonCohort.workspace_id == ws.id).delete()
        ws.status = WorkspaceStatus.stale
        ws.stale_reasons = list(ws.stale_reasons or []) + [{
            "source_ref": source_ref, "projects": sorted(hit),
            "affected_edges": hit_edges,
            "note": "来源更正影响该项目参与的比较边；未受影响的项目对在重新核验后仍可继续使用",
        }]
        touched_ws.append(ws.id)

    pubs_stale: list[dict] = []
    for pub in db.query(ComparisonPublication).filter(ComparisonPublication.stale.is_(False)).all():
        hit = [int(p) for p in (pub.project_ids or []) if int(p) in pid_set]
        if not hit:
            continue
        affected_pair = [e for e in (pub.edges_snapshot or [])
                         if e["project_a_id"] in pid_set or e["project_b_id"] in pid_set]
        if not affected_pair:
            continue
        pub.stale = True
        pub.stale_reasons = list(pub.stale_reasons or []) + [{
            "source_ref": source_ref, "projects": sorted(hit),
            "affected_pairs": [[e["project_a_id"], e["project_b_id"]] for e in affected_pair],
            "note": "来源更正：已发布清单保留原分母，新清单需说明新增/失效/受限项目对",
        }]
        pubs_stale.append({"publication_id": pub.id, "workspace_id": pub.workspace_id,
                           "version": pub.version})

    db.add(AuditLog(actor=actor, action="source_correction", entity="comparison",
                    detail={"source_ref": source_ref, "projects": sorted(pid_set),
                            "stale_workspaces": touched_ws, "stale_publications": pubs_stale,
                            "affected_edges": affected_edges}))
    db.flush()
    return {"stale_workspaces": touched_ws, "stale_publications": pubs_stale,
            "affected_edges": affected_edges}


# ---------------------------------------------------------------- 规则发布


def _rule_values(payload: dict, base: ComparisonRule | None = None) -> dict:
    def pick(key, default):
        return payload[key] if payload.get(key) is not None else (getattr(base, key) if base else default)
    return {
        "building_use": (BuildingUse(payload["building_use"]) if payload.get("building_use")
                         else (base.building_use if base else None)),
        "climate_zone": (ClimateZone(payload["climate_zone"]) if payload.get("climate_zone")
                         else (base.climate_zone if base else None)),
        "occupancy_profile": (OccupancyProfile(payload["occupancy_profile"])
                              if payload.get("occupancy_profile")
                              else (base.occupancy_profile if base else None)),
        "min_baseline_days": int(pick("min_baseline_days", 300)),
        "max_baseline_days": int(pick("max_baseline_days", 430)),
        "date_tolerance_days": int(pick("date_tolerance_days", 7)),
        "occupancy_cover_min": float(pick("occupancy_cover_min", 1.0)),
        "baseline_length_tolerance_days": int(pick("baseline_length_tolerance_days", 30)),
        "min_common_window_days": int(pick("min_common_window_days", 150)),
        "max_area_ratio": float(pick("max_area_ratio", 2.0)),
        "notes": payload.get("notes") or (base.notes if base else ""),
    }


def create_rule(db: Session, payload: dict, actor: str = "system") -> ComparisonRule:
    """登记规则草稿；草稿不参与发布，也不得据其签发更严格版本。"""
    if db.query(ComparisonRule).filter(ComparisonRule.code == payload["code"]).first():
        raise ValueError("规则编码已存在；如需更严格版本请在已激活规则上发布新版本")
    rule = ComparisonRule(code=payload["code"], version=1, status=RuleStatus.draft,
                          created_by=actor, **_rule_values(payload))
    db.add(rule)
    db.flush()
    return rule


def publish_rule(db: Session, old: ComparisonRule, payload: dict,
                 actor: str = "system") -> tuple[ComparisonRule, list[dict]]:
    """发布更严格版本：旧版本 superseded，新版本 active。

    运行中的草稿按原规则完成并明确标记过期，不能把旧资格发布为新规则下的结果。
    """
    if old.status != RuleStatus.active:
        raise ValueError("只有已激活的规则才能发布新版本")
    old.status = RuleStatus.superseded
    db.flush()
    rule = ComparisonRule(code=old.code, version=old.version + 1, status=RuleStatus.active,
                          created_by=actor, **_rule_values(payload, old))
    db.add(rule)
    db.flush()

    stale_ws: list[dict] = []
    ws_rows = (db.query(ComparisonWorkspace)
               .filter(ComparisonWorkspace.rule_id == old.id,
                       ComparisonWorkspace.status.in_((WorkspaceStatus.draft,
                                                       WorkspaceStatus.computed,
                                                       WorkspaceStatus.published))).all())
    for ws in ws_rows:
        mark_workspace_stale(db, ws, {
            "rule_code": old.code, "old_rule_version": old.version,
            "new_rule_version": rule.version,
            "note": "规则已发布更严格版本：本工作区按原规则完成并标记过期，不得以新规则名义发布",
        }, actor=actor)
        stale_ws.append({"workspace_id": ws.id, "code": ws.code, "status": ws.status.value})

    for pub in db.query(ComparisonPublication).filter(
            ComparisonPublication.rule_id == old.id,
            ComparisonPublication.stale.is_(False)).all():
        pub.stale = True
        pub.stale_reasons = list(pub.stale_reasons or []) + [{
            "rule_code": old.code, "old_rule_version": old.version,
            "new_rule_version": rule.version,
            "note": "规则已更新：清单保留原分母，新版本需说明新增/失效/受限项目对",
        }]

    db.add(AuditLog(actor=actor, action="publish_rule", entity="comparison_rule",
                    entity_id=rule.id,
                    detail={"code": old.code, "version": rule.version, "stale_workspaces": stale_ws}))
    db.flush()
    return rule, stale_ws
