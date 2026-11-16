"""种子数据：覆盖全部验收场景。

单项目核验场景：
- PRJ-A 市第一中学照明改造      → 专属电表直接计量（可比较）
- PRJ-B 区政府办公楼空调改造    → 公共管路受控分摊（先待复核，补齐运行时长后新签发版本）
- PRJ-C/PRJ-D 实验小学/第二中学 → 同一序列号重叠声明 → 重复覆盖冲突
- PRJ-E/PRJ-F 图书馆/文化馆     → 同一序列号先后移装、缺移装材料 → 转移待核
- PRJ-G 医院门诊楼              → 基线期中途换表、倍率未衔接 → 断点拆分
- PRJ-H 体育馆                  → 验收附件替换 → 当前事实转复审中、暂停新引用

跨项目比较场景（PRJ-I ~ PRJ-N 为可作比较练习的学校项目）：
- CMP-SCHOOL 规则               → 学校 / 夏热冬冷 / 学期开放，占用覆盖 60% 起
- WS-SCHOOL-DEC                  → 冬季可比（I~J、J~K），I~K 不可比（不传递）
- WS-SCHOOL-APR                  → 春季可比（K~L、L~M），K~M 不可比（不传递）
- WS-COHORT                      → 全组队列：薄弱项目 P 压缩整批可用日期
- WS-SHARED                      → 共用总表：M~N 不得作为两份独立样本
- WS-PARTIAL                     → 部分倍率补证：只有补证区间进入候选
- 发布清单 / 来源更正 / 规则并发发布 场景见 README 与本模块末尾
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

from .compiler import compile_fact, detect_serial_conflicts, register_meter_event
from .comparison import (
    build_cohort,
    create_rule,
    mark_source_corrections,
    publish_rule,
    publish_workspace,
    revalidate_workspace,
)
from .database import Base, SessionLocal, engine
from .models import (
    BuildingUse,
    Citation,
    ClimateZone,
    ComparisonRule,
    ComparisonWorkspace,
    DocType,
    EvidenceDocument,
    EvidenceStatus,
    EvidenceStrength,
    FactStatus,
    MeterCoverageWindow,
    MeteringBoundary,
    OccupancyProfile,
    OccupancyWindow,
    PerformanceFact,
    PeriodRole,
    PipelineKind,
    Project,
    ProjectComparisonProfile,
    RelationKind,
    RuleStatus,
    ScopeRelation,
    ScopeStatus,
    Strategy,
    SubjectType,
    User,
    WorkspaceStatus,
)
from .routers.evidence import source_hash
from .security import hash_password


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def monthly_records(year: int, kwh: float, meter: str, months=range(1, 13)) -> list[dict]:
    recs = []
    for m in months:
        start = datetime(year, m, 1)
        end = datetime(year + 1, 1, 1) if m == 12 else datetime(year, m + 1, 1)
        recs.append({"start": start.isoformat(), "end": end.isoformat(), "kwh": kwh})
    return recs


def add_evidence(db, project_id, doc_type, title, event_time, payload, supersedes: EvidenceDocument | None = None):
    doc = EvidenceDocument(
        project_id=project_id,
        doc_type=doc_type,
        title=title,
        source_hash=source_hash(payload),
        event_time=event_time,
        payload=payload,
    )
    if supersedes is not None:
        supersedes.status = EvidenceStatus.superseded
        doc.version = supersedes.version + 1
        doc.supersedes_id = supersedes.id
    db.add(doc)
    db.flush()
    return doc


def add_scope(db, project_id, kind, subject_type, ref, status, note="",
              serial_no=None, valid_from=None, valid_to=None, evidence_ids=None):
    rel = ScopeRelation(
        project_id=project_id, relation_kind=kind, subject_type=subject_type,
        subject_ref=ref, serial_no=serial_no, status=status, coverage_note=note,
        valid_from=valid_from, valid_to=valid_to, evidence_ids=evidence_ids or [],
    )
    db.add(rel)
    db.flush()
    detect_serial_conflicts(db, rel)
    return rel


def add_boundary(db, project_id, meter, role, start, end, kind=PipelineKind.dedicated,
                 zone="", branch="", strength=EvidenceStrength.strong, evidence_ids=None,
                 scope_relation_id=None):
    b = MeteringBoundary(
        project_id=project_id, meter_serial=meter, branch_name=branch, pipeline_kind=kind,
        zone_name=zone, period_role=role, valid_from=start, valid_to=end,
        multiplier=1.0, evidence_strength=strength, evidence_ids=evidence_ids or [],
        scope_relation_id=scope_relation_id,
    )
    db.add(b)
    db.flush()
    return b


def run(reset: bool = False):
    if reset:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print("已有数据，跳过种子（如需重建请使用 --reset）")
            return

        # ---------- 用户 ----------
        db.add_all([
            User(username="admin", password_hash=hash_password("admin123"),
                 display_name="平台管理员", role="admin"),
            User(username="analyst", password_hash=hash_password("analyst123"),
                 display_name="绩效分析员", role="analyst"),
            User(username="auditor", password_hash=hash_password("auditor123"),
                 display_name="审计查看员", role="auditor"),
        ])

        # ---------- 项目 ----------
        projects = {}
        for code, name, building, org in [
            ("PRJ-A", "市第一中学教学楼照明改造", "市第一中学教学楼", "市教育局"),
            ("PRJ-B", "区政府办公楼中央空调改造", "区政府办公楼主楼", "区机关事务管理局"),
            ("PRJ-C", "实验小学空压系统改造", "实验小学综合楼", "区教育局"),
            ("PRJ-D", "第二中学空压站更新", "第二中学后勤楼", "区教育局"),
            ("PRJ-E", "图书馆水泵系统改造", "市图书馆", "市文旅局"),
            ("PRJ-F", "文化馆水泵系统改造", "市文化馆", "市文旅局"),
            ("PRJ-G", "医院门诊楼空调改造", "医院门诊楼", "市卫健委"),
            ("PRJ-H", "体育馆泳池设备改造", "市体育馆", "市体育局"),
            # ---- 跨项目比较练习：六所学校，覆盖不传递/全组交集/共用总表/部分倍率 ----
            ("PRJ-I", "东湖小学供暖系统改造", "东湖小学教学楼", "区教育局"),
            ("PRJ-J", "南园小学供暖系统改造", "南园小学教学楼", "区教育局"),
            ("PRJ-K", "北岭小学照明与供暖改造", "北岭小学教学楼", "区教育局"),
            ("PRJ-L", "西塘小学照明改造", "西塘小学教学楼", "区教育局"),
            ("PRJ-M", "青禾中学照明改造", "青禾中学教学楼", "区教育局"),
            ("PRJ-N", "临江中学照明改造", "临江中学教学楼", "区教育局"),
        ]:
            p = Project(code=code, name=name, building_name=building, owner_org=org)
            db.add(p)
            db.flush()
            projects[code] = p
        P = {k: v.id for k, v in projects.items()}

        # ================= PRJ-A：专属电表直接计量 =================
        ev_a_contract = add_evidence(db, P["PRJ-A"], DocType.contract_item, "PRJ-A 合同条目",
                                     dt("2024-01-10"), {"items": [{"subject_type": "space", "ref": "教学楼A", "note": "LED 照明整体替换"}]})
        ev_a_list = add_evidence(db, P["PRJ-A"], DocType.equipment_space_list, "PRJ-A 设备空间清单",
                                 dt("2024-03-01"), {"equipment": [{"serial_no": "LED-A-0001", "model": "LED-36W", "space": "教学楼A"}], "spaces": ["教学楼A"]})
        ev_a_accept = add_evidence(db, P["PRJ-A"], DocType.acceptance_report, "PRJ-A 验收报告",
                                   dt("2024-12-20"), {"conclusions": [{"ref": "教学楼A", "result": "pass"}], "attachment_hash": "a1b2c3"})
        ev_a_meter = add_evidence(db, P["PRJ-A"], DocType.meter_serial_record, "PRJ-A 仪表序列",
                                  dt("2024-01-05"), {"meters": [{"serial": "M-A100", "multiplier": 1, "branch": "照明支路", "zone": "教学楼A"}]})
        add_evidence(db, P["PRJ-A"], DocType.meter_reading, "M-A100 2024 读数原文",
                     dt("2025-01-05"), {"meter_serial": "M-A100", "records": monthly_records(2024, 1000.0, "M-A100")})
        add_evidence(db, P["PRJ-A"], DocType.meter_reading, "M-A100 2025 读数原文",
                     dt("2026-01-05"), {"meter_serial": "M-A100", "records": monthly_records(2025, 700.0, "M-A100")})
        add_evidence(db, P["PRJ-A"], DocType.building_master, "教学楼A 建筑主数据",
                     dt("2024-01-01"), {"zones": [{"name": "教学楼A", "area_m2": 8600}]})

        add_scope(db, P["PRJ-A"], RelationKind.contract_commitment, SubjectType.space,
                  "教学楼A", ScopeStatus.confirmed, "合同承诺覆盖教学楼A照明", evidence_ids=[ev_a_contract.id])
        add_scope(db, P["PRJ-A"], RelationKind.installed_evidence, SubjectType.equipment,
                  "LED-A-0001", ScopeStatus.confirmed, "实装 LED 灯具", serial_no="LED-A-0001",
                  valid_from=dt("2024-03-01"), evidence_ids=[ev_a_list.id])
        scope_a = add_scope(db, P["PRJ-A"], RelationKind.acceptance_conclusion, SubjectType.space,
                            "教学楼A", ScopeStatus.confirmed, "验收结论：合格", evidence_ids=[ev_a_accept.id])

        add_boundary(db, P["PRJ-A"], "M-A100", PeriodRole.baseline, dt("2024-01-01"), dt("2025-01-01"),
                     zone="教学楼A", branch="照明支路", evidence_ids=[ev_a_meter.id],
                     scope_relation_id=scope_a.id)
        add_boundary(db, P["PRJ-A"], "M-A100", PeriodRole.reporting, dt("2025-01-01"), dt("2026-01-01"),
                     zone="教学楼A", branch="照明支路", evidence_ids=[ev_a_meter.id],
                     scope_relation_id=scope_a.id)

        fact_a = compile_fact(db, P["PRJ-A"], scope_a.id, Strategy.strict_direct,
                              dt("2024-01-01"), dt("2025-01-01"), dt("2025-01-01"), dt("2026-01-01"),
                              actor="seed")

        # ================= PRJ-B：公共管路受控分摊 =================
        ev_b_contract = add_evidence(db, P["PRJ-B"], DocType.contract_item, "PRJ-B 合同条目",
                                     dt("2024-02-01"), {"items": [{"subject_type": "space", "ref": "办公楼主楼", "note": "中央空调系统改造"}]})
        ev_b_accept = add_evidence(db, P["PRJ-B"], DocType.acceptance_report, "PRJ-B 验收报告",
                                   dt("2024-12-25"), {"conclusions": [{"ref": "办公楼主楼", "result": "pass"}], "attachment_hash": "b9b9b9"})
        add_evidence(db, P["PRJ-B"], DocType.meter_reading, "M-B200 2024 读数原文",
                     dt("2025-01-06"), {"meter_serial": "M-B200", "records": monthly_records(2024, 2000.0, "M-B200")})
        add_evidence(db, P["PRJ-B"], DocType.meter_reading, "M-B200 2025 读数原文",
                     dt("2026-01-06"), {"meter_serial": "M-B200", "records": monthly_records(2025, 1500.0, "M-B200")})
        # 分摊声明 v1：缺少运行时长 → 待复核
        ev_b_decl_v1 = add_evidence(db, P["PRJ-B"], DocType.allocation_declaration, "PRJ-B 公共管路分摊声明 v1",
                                    dt("2025-01-10"), {"pipeline": "冷冻站总管",
                                                       "zones": [{"zone": "办公楼主楼"}, {"zone": "档案馆"}]})

        scope_b = add_scope(db, P["PRJ-B"], RelationKind.acceptance_conclusion, SubjectType.space,
                            "办公楼主楼", ScopeStatus.confirmed, "验收结论：合格", evidence_ids=[ev_b_accept.id])
        add_scope(db, P["PRJ-B"], RelationKind.contract_commitment, SubjectType.space,
                  "办公楼主楼", ScopeStatus.confirmed, "合同承诺", evidence_ids=[ev_b_contract.id])

        add_boundary(db, P["PRJ-B"], "M-B200", PeriodRole.baseline, dt("2024-01-01"), dt("2025-01-01"),
                     kind=PipelineKind.shared, zone="办公楼主楼", branch="冷冻站总管",
                     scope_relation_id=scope_b.id)
        add_boundary(db, P["PRJ-B"], "M-B200", PeriodRole.reporting, dt("2025-01-01"), dt("2026-01-01"),
                     kind=PipelineKind.shared, zone="办公楼主楼", branch="冷冻站总管",
                     scope_relation_id=scope_b.id)

        # 严格直接计量：公共管路 → 不可比较（留在未比较清单）
        compile_fact(db, P["PRJ-B"], scope_b.id, Strategy.strict_direct,
                     dt("2024-01-01"), dt("2025-01-01"), dt("2025-01-01"), dt("2026-01-01"), actor="seed")
        # 受控分摊 v1：缺运行时长 → 待复核
        compile_fact(db, P["PRJ-B"], scope_b.id, Strategy.allocation_runtime,
                     dt("2024-01-01"), dt("2025-01-01"), dt("2025-01-01"), dt("2026-01-01"), actor="seed")
        # 补齐运行时长：分摊声明 v2 → 新签发受控分摊版本（不改写旧版本）
        add_evidence(db, P["PRJ-B"], DocType.allocation_declaration, "PRJ-B 公共管路分摊声明 v2（补齐运行时长）",
                     dt("2025-02-15"), {"pipeline": "冷冻站总管",
                                        "zones": [{"zone": "办公楼主楼", "runtime_hours": 1500},
                                                  {"zone": "档案馆", "runtime_hours": 900}]},
                     supersedes=ev_b_decl_v1)
        compile_fact(db, P["PRJ-B"], scope_b.id, Strategy.allocation_runtime,
                     dt("2024-01-01"), dt("2025-01-01"), dt("2025-01-01"), dt("2026-01-01"), actor="seed")

        # ================= PRJ-C / PRJ-D：序列号重叠 → 重复覆盖冲突 =================
        add_scope(db, P["PRJ-C"], RelationKind.installed_evidence, SubjectType.equipment,
                  "CH-9001", ScopeStatus.confirmed, "实验小学声明空压机 CH-9001",
                  serial_no="CH-9001", valid_from=dt("2024-06-01"), valid_to=dt("2026-01-01"))
        add_scope(db, P["PRJ-D"], RelationKind.installed_evidence, SubjectType.equipment,
                  "CH-9001", ScopeStatus.confirmed, "第二中学声明同一台空压机 CH-9001",
                  serial_no="CH-9001", valid_from=dt("2025-01-01"), valid_to=dt("2026-06-30"))
        scope_c = db.query(ScopeRelation).filter(ScopeRelation.project_id == P["PRJ-C"],
                                                 ScopeRelation.serial_no == "CH-9001").first()
        compile_fact(db, P["PRJ-C"], scope_c.id, Strategy.strict_direct,
                     dt("2024-06-01"), dt("2025-01-01"), dt("2025-01-01"), dt("2026-01-01"), actor="seed")

        # ================= PRJ-E / PRJ-F：先后移装、缺移装材料 → 转移待核 =================
        add_scope(db, P["PRJ-E"], RelationKind.installed_evidence, SubjectType.equipment,
                  "PU-3001", ScopeStatus.confirmed, "图书馆声明水泵 PU-3001（2023~2024.6）",
                  serial_no="PU-3001", valid_from=dt("2023-01-01"), valid_to=dt("2024-06-30"))
        add_scope(db, P["PRJ-F"], RelationKind.installed_evidence, SubjectType.equipment,
                  "PU-3001", ScopeStatus.confirmed, "文化馆声明水泵 PU-3001（2024.7 起）",
                  serial_no="PU-3001", valid_from=dt("2024-07-01"), valid_to=dt("2026-01-01"))
        scope_e = db.query(ScopeRelation).filter(ScopeRelation.project_id == P["PRJ-E"],
                                                 ScopeRelation.serial_no == "PU-3001").first()
        compile_fact(db, P["PRJ-E"], scope_e.id, Strategy.strict_direct,
                     dt("2023-01-01"), dt("2024-01-01"), dt("2024-01-01"), dt("2024-07-01"), actor="seed")

        # ================= PRJ-G：基线期中途换表 =================
        ev_g_meter = add_evidence(db, P["PRJ-G"], DocType.meter_serial_record, "PRJ-G 仪表序列",
                                  dt("2024-01-02"), {"meters": [{"serial": "M-G300", "multiplier": 1, "branch": "空调支路", "zone": "门诊楼"}]})
        ev_g_accept = add_evidence(db, P["PRJ-G"], DocType.acceptance_report, "PRJ-G 验收报告",
                                   dt("2024-12-28"), {"conclusions": [{"ref": "门诊楼", "result": "pass"}], "attachment_hash": "g777"})
        # 读数：旧表 M-G300（1月~6月中），新表 M-G301（6月中~2025 全年）
        add_evidence(db, P["PRJ-G"], DocType.meter_reading, "M-G300 2024 读数原文",
                     dt("2024-07-01"), {"meter_serial": "M-G300", "records":
                                        monthly_records(2024, 800.0, "M-G300", months=range(1, 6)) +
                                        [{"start": "2024-06-01", "end": "2024-06-15", "kwh": 400.0}]})
        add_evidence(db, P["PRJ-G"], DocType.meter_reading, "M-G301 2024 读数原文",
                     dt("2025-01-03"), {"meter_serial": "M-G301", "records":
                                        [{"start": "2024-06-15", "end": "2024-07-01", "kwh": 380.0}] +
                                        monthly_records(2024, 760.0, "M-G301", months=range(7, 13))})
        add_evidence(db, P["PRJ-G"], DocType.meter_reading, "M-G301 2025 读数原文",
                     dt("2026-01-03"), {"meter_serial": "M-G301", "records": monthly_records(2025, 560.0, "M-G301")})

        scope_g = add_scope(db, P["PRJ-G"], RelationKind.acceptance_conclusion, SubjectType.space,
                            "门诊楼", ScopeStatus.confirmed, "验收结论：合格", evidence_ids=[ev_g_accept.id])
        add_boundary(db, P["PRJ-G"], "M-G300", PeriodRole.baseline, dt("2024-01-01"), dt("2025-01-01"),
                     zone="门诊楼", branch="空调支路", evidence_ids=[ev_g_meter.id],
                     scope_relation_id=scope_g.id)
        add_boundary(db, P["PRJ-G"], "M-G301", PeriodRole.reporting, dt("2025-01-01"), dt("2026-01-01"),
                     zone="门诊楼", branch="空调支路", scope_relation_id=scope_g.id)
        # 2024-06-15 换表，倍率无法衔接 → 边界拆分 + 断点
        register_meter_event(db, P["PRJ-G"], "M-G300", "M-G301", dt("2024-06-15"), multiplier_linked=False)

        # 跨越断点的基线期 → 不可比较
        compile_fact(db, P["PRJ-G"], scope_g.id, Strategy.strict_direct,
                     dt("2024-01-01"), dt("2025-01-01"), dt("2025-01-01"), dt("2026-01-01"), actor="seed")
        # 断点之后的子区间 → 可比较
        compile_fact(db, P["PRJ-G"], scope_g.id, Strategy.strict_direct,
                     dt("2024-07-01"), dt("2025-01-01"), dt("2025-07-01"), dt("2026-01-01"), actor="seed")

        # ================= PRJ-H：验收附件替换 =================
        ev_h_meter = add_evidence(db, P["PRJ-H"], DocType.meter_serial_record, "PRJ-H 仪表序列",
                                  dt("2024-01-03"), {"meters": [{"serial": "M-H400", "multiplier": 1, "branch": "泳池设备支路", "zone": "体育馆"}]})
        ev_h_accept_v1 = add_evidence(db, P["PRJ-H"], DocType.acceptance_report, "PRJ-H 验收报告 v1",
                                      dt("2024-12-15"), {"conclusions": [{"ref": "体育馆", "result": "pass"}], "attachment_hash": "h-orig-111"})
        add_evidence(db, P["PRJ-H"], DocType.meter_reading, "M-H400 2024 读数原文",
                     dt("2025-01-04"), {"meter_serial": "M-H400", "records": monthly_records(2024, 500.0, "M-H400")})
        add_evidence(db, P["PRJ-H"], DocType.meter_reading, "M-H400 2025 读数原文",
                     dt("2026-01-04"), {"meter_serial": "M-H400", "records": monthly_records(2025, 380.0, "M-H400")})

        scope_h = add_scope(db, P["PRJ-H"], RelationKind.acceptance_conclusion, SubjectType.space,
                            "体育馆", ScopeStatus.confirmed, "验收结论：合格", evidence_ids=[ev_h_accept_v1.id])
        add_boundary(db, P["PRJ-H"], "M-H400", PeriodRole.baseline, dt("2024-01-01"), dt("2025-01-01"),
                     zone="体育馆", branch="泳池设备支路", evidence_ids=[ev_h_meter.id],
                     scope_relation_id=scope_h.id)
        add_boundary(db, P["PRJ-H"], "M-H400", PeriodRole.reporting, dt("2025-01-01"), dt("2026-01-01"),
                     zone="体育馆", branch="泳池设备支路", scope_relation_id=scope_h.id)

        fact_h = compile_fact(db, P["PRJ-H"], scope_h.id, Strategy.strict_direct,
                              dt("2024-01-01"), dt("2025-01-01"), dt("2025-01-01"), dt("2026-01-01"), actor="seed")
        # 附件替换前已有分析引用 v1
        db.add(Citation(fact_id=fact_h.id, fact_version=fact_h.version, consumer_type="analysis",
                        consumer_name="2025年度公共建筑节能对标分析", purpose="年度对标发布", created_by="analyst"))
        db.flush()
        # 验收附件被替换（哈希变化）→ 当前事实转复审中、暂停新引用；历史版本保留原附件与结论
        from .compiler import apply_evidence_revision
        ev_h_accept_v2 = EvidenceDocument(
            project_id=P["PRJ-H"], doc_type=DocType.acceptance_report, title="PRJ-H 验收报告 v2（附件替换）",
            source_hash=source_hash({"conclusions": [{"ref": "体育馆", "result": "pass"}],
                                     "attachment_hash": "h-replaced-999"}),
            event_time=dt("2025-03-10"),
            payload={"conclusions": [{"ref": "体育馆", "result": "pass"}], "attachment_hash": "h-replaced-999"},
        )
        db.add(ev_h_accept_v2)
        db.flush()
        apply_evidence_revision(db, ev_h_accept_v1, ev_h_accept_v2)

        # ================================================================
        # 跨项目比较层：六所学校 + 比较规则 + 工作区 + 发布清单
        # ================================================================
        seed_comparisons(db, P)

        db.commit()

        # ---------- 汇总输出 ----------
        n_facts = db.query(PerformanceFact).count()
        print(f"种子完成：项目 {len(projects)}，事实 {n_facts}，"
              f"比较规则 {db.query(ComparisonRule).count()}，"
              f"比较工作区 {db.query(ComparisonWorkspace).count()}")
        for f in db.query(PerformanceFact).order_by(PerformanceFact.id).all():
            print(f"  fact#{f.id} project={f.project_id} strategy={f.strategy.value} "
                  f"kind={f.result_kind.value} comp={f.comparability.value} status={f.status.value} v{f.version}")
    finally:
        db.close()


# ---------------------------------------------------------------- 比较层种子


def _school_profile(db, project_id, use, climate, occ, area, dining=False, public=False,
                    shared_load_keys=None, description=""):
    db.add(ProjectComparisonProfile(
        project_id=project_id, building_use=use, climate_zone=climate,
        occupancy_profile=occ, area_m2=area, includes_dining=dining,
        includes_public_load=public, shared_load_keys=shared_load_keys or [],
        description=description,
    ))
    db.flush()


def _occupancy_term(db, project_id, start, end, label):
    db.add(OccupancyWindow(project_id=project_id, valid_from=start, valid_to=end, label=label))
    db.flush()


def _coverage(db, project_id, meter, start, end, *, independent=True,
              has_allocation_basis=False, verified=True, shared_with=None,
              note="", evidence_ids=None):
    db.add(MeterCoverageWindow(
        project_id=project_id, meter_serial=meter, valid_from=start, valid_to=end,
        independent=independent, has_allocation_basis=has_allocation_basis,
        verified=verified, shared_with_project_id=shared_with,
        note=note, evidence_ids=evidence_ids or [],
    ))
    db.flush()


def _comparison_window(db, project_id, subject, meter, base_start, base_end,
                       rep_start, rep_end, note=""):
    """为比较层登记一个已确认范围 + 基线/报告期边界（不签发单项目绩效事实）。"""
    rel = add_scope(db, project_id, RelationKind.acceptance_conclusion, SubjectType.space,
                    subject, ScopeStatus.confirmed, note,
                    valid_from=min(base_start, rep_start), valid_to=max(base_end, rep_end))
    _rel_ev = add_evidence(db, project_id, DocType.acceptance_report, f"{subject} 验收结论",
                           base_end, {"conclusions": [{"ref": subject, "result": "pass"}],
                                      "attachment_hash": f"{meter}-accept"})
    rel.evidence_ids = [_rel_ev.id]
    add_boundary(db, project_id, meter, PeriodRole.baseline, base_start, base_end,
                 zone=subject, branch="供暖/照明支路", scope_relation_id=rel.id,
                 evidence_ids=[_rel_ev.id])
    add_boundary(db, project_id, meter, PeriodRole.reporting, rep_start, rep_end,
                 zone=subject, branch="供暖/照明支路", scope_relation_id=rel.id,
                 evidence_ids=[_rel_ev.id])
    db.flush()
    return rel


def seed_comparisons(db, P):
    """跨项目比较场景种子。

    场景设计（只判断比较范围与证据覆盖，不据此排名节能效果）：
    - I/J 冬季窗口重叠 → 可比；J/K 春季窗口重叠 → 可比；
      I/K 的窗口完全不重叠 → 不可比。不给甲丙推导任何资格（不传递）。
    - K/L：L 的倍率只有部分区间补证 + 计量含食堂 → 受限可比较，只保留补证后区间。
    - M/N：共用同一校园总表且无独立读数/分配依据 → 不可比，不得当两份独立样本。
    - J/K/L/P 全组队列：P 覆盖窗口很短 → 全组交集被压缩，P 标记为限制项目。
    """
    I, J, K, L, M, N = (P["PRJ-I"], P["PRJ-J"], P["PRJ-K"],
                        P["PRJ-L"], P["PRJ-M"], P["PRJ-N"])
    SHARED_LOADS = ["corridor_lighting"]

    # ---- 项目比较属性（学校 / 夏热冬冷 / 学期开放）
    _school_profile(db, I, BuildingUse.school, ClimateZone.hot_summer_cold_winter,
                    OccupancyProfile.term_time, 7200, public=True,
                    shared_load_keys=SHARED_LOADS, description="东湖小学供暖改造，独立电表")
    _school_profile(db, J, BuildingUse.school, ClimateZone.hot_summer_cold_winter,
                    OccupancyProfile.term_time, 8100, public=True,
                    shared_load_keys=SHARED_LOADS, description="南园小学供暖改造，冬季/春季两套资料")
    _school_profile(db, K, BuildingUse.school, ClimateZone.hot_summer_cold_winter,
                    OccupancyProfile.term_time, 7600, public=True,
                    shared_load_keys=SHARED_LOADS, description="北岭小学照明与供暖改造，仅春季资料")
    _school_profile(db, L, BuildingUse.school, ClimateZone.hot_summer_cold_winter,
                    OccupancyProfile.term_time, 6900, dining=True,
                    description="西塘小学照明改造，计量含食堂；换表倍率仅部分补证")
    _school_profile(db, M, BuildingUse.school, ClimateZone.hot_summer_cold_winter,
                    OccupancyProfile.term_time, 9400, public=True,
                    shared_load_keys=["corridor_lighting", "central_hvac"],
                    description="青禾中学照明改造，与临江中学共用校园总表")
    _school_profile(db, N, BuildingUse.school, ClimateZone.hot_summer_cold_winter,
                    OccupancyProfile.term_time, 8800, public=True,
                    shared_load_keys=["corridor_lighting", "central_hvac"],
                    description="临江中学照明改造，与青禾中学共用校园总表，无独立读数")

    # ---- 占用区间（学期开放；寒暑假未占用）
    terms = [
        (dt("2022-09-01"), dt("2023-01-15"), "2022 秋季学期"),
        (dt("2023-02-15"), dt("2023-07-05"), "2023 春季学期"),
        (dt("2023-09-01"), dt("2024-01-15"), "2023 秋季学期"),
        (dt("2024-02-15"), dt("2024-07-05"), "2024 春季学期"),
        (dt("2024-09-01"), dt("2025-01-15"), "2024 秋季学期"),
        (dt("2025-02-15"), dt("2025-07-05"), "2025 春季学期"),
        (dt("2025-09-01"), dt("2026-01-15"), "2025 秋季学期"),
        (dt("2026-02-15"), dt("2026-03-15"), "2026 春季学期"),
    ]
    for pid in (I, J, K, L, M, N):
        for s, e, lab in terms:
            _occupancy_term(db, pid, s, e, lab)

    # ---- 比较窗口（窗口互不重叠是“不传递”的关键）
    # I：仅冬季窗口（2022-11 ~ 2024-10）
    _comparison_window(db, I, "东湖小学教学楼", "M-I500",
                       dt("2022-11-01"), dt("2023-10-31"),
                       dt("2023-11-01"), dt("2024-10-31"),
                       "冬季口径窗口（仅此一套资料）")
    # J：冬季窗口 + 春季窗口
    _comparison_window(db, J, "南园小学教学楼", "M-J500",
                       dt("2022-11-05"), dt("2023-10-31"),
                       dt("2023-11-05"), dt("2024-10-31"),
                       "冬季口径窗口")
    _comparison_window(db, J, "南园小学教学楼", "M-J500",
                       dt("2024-03-01"), dt("2025-02-28"),
                       dt("2025-03-01"), dt("2026-02-28"),
                       "春季口径窗口")
    # K：仅春季窗口（与 I 完全不重叠）
    _comparison_window(db, K, "北岭小学教学楼", "M-K500",
                       dt("2024-03-03"), dt("2025-03-02"),
                       dt("2025-03-03"), dt("2026-03-04"),
                       "春季口径窗口（仅此一套资料）")
    # L：春季窗口，换表倍率仅 2024-07-01 之后补证
    _comparison_window(db, L, "西塘小学教学楼", "M-L600",
                       dt("2024-03-05"), dt("2025-03-04"),
                       dt("2025-03-05"), dt("2026-03-06"),
                       "春季口径窗口；换表前倍率未补证")
    # M/N：春季窗口，共用总表
    _comparison_window(db, M, "青禾中学教学楼", "M-SHARED900",
                       dt("2024-03-02"), dt("2025-03-01"),
                       dt("2025-03-02"), dt("2026-03-01"),
                       "照明改造，校园共用总表")
    _comparison_window(db, N, "临江中学教学楼", "M-SHARED900",
                       dt("2024-03-02"), dt("2025-03-01"),
                       dt("2025-03-02"), dt("2026-03-01"),
                       "照明改造，校园共用总表（无独立读数）")

    # ---- 薄弱项目 P：窗口与 J/K/L 对齐，但计量覆盖只有两段短区间
    p = Project(code="PRJ-P", name="河湾小学照明改造", building_name="河湾小学教学楼",
                owner_org="区教育局")
    db.add(p)
    db.flush()
    _school_profile(db, p.id, BuildingUse.school, ClimateZone.hot_summer_cold_winter,
                    OccupancyProfile.term_time, 5400, public=True,
                    shared_load_keys=SHARED_LOADS,
                    description="照明改造，资料薄弱：仅两段短覆盖")
    _comparison_window(db, p.id, "河湾小学教学楼", "M-P700",
                       dt("2024-03-01"), dt("2025-02-28"),
                       dt("2025-03-01"), dt("2026-02-28"),
                       "春季口径窗口；覆盖区间很短")
    for s, e, lab in terms:
        _occupancy_term(db, p.id, s, e, lab)

    # ---- 计量覆盖
    _coverage(db, I, "M-I500", dt("2022-11-01"), dt("2024-10-31"), note="独立电表，全程覆盖")
    _coverage(db, J, "M-J500", dt("2022-11-05"), dt("2026-02-28"), note="独立电表，全程覆盖")
    _coverage(db, K, "M-K500", dt("2024-03-03"), dt("2026-03-04"), note="独立电表，全程覆盖")
    # L：换表前倍率未补证 → 只有 2024-07-01 之后进入候选
    _coverage(db, L, "M-L600", dt("2024-03-05"), dt("2024-06-30"),
              independent=False, verified=False,
              note="换表前倍率未补证：仅登记，不进入候选")
    _coverage(db, L, "M-L600", dt("2024-07-01"), dt("2026-03-06"), independent=True,
              verified=True, note="换表后倍率由校验记录补证：仅该区间进入候选")
    # M/N：共用总表，均无独立读数/分配依据
    _coverage(db, M, "M-SHARED900", dt("2024-03-02"), dt("2026-03-01"),
              independent=False, shared_with=N, note="校园共用总表，无独立读数")
    _coverage(db, N, "M-SHARED900", dt("2024-03-02"), dt("2026-03-01"),
              independent=False, shared_with=M, note="校园共用总表，无独立读数")
    # P：仅两段短覆盖，压缩全组交集
    _coverage(db, p.id, "M-P700", dt("2024-09-01"), dt("2025-02-28"),
              note="独立电表，但覆盖仅到 2025-02-28")
    _coverage(db, p.id, "M-P700", dt("2025-09-01"), dt("2025-12-31"),
              note="第二段覆盖止于 2025-12-31")

    # 已有项目的覆盖登记
    _coverage(db, P["PRJ-A"], "M-A100", dt("2024-01-01"), dt("2026-01-01"), note="专属电表")
    _coverage(db, P["PRJ-B"], "M-B200", dt("2024-01-01"), dt("2026-01-01"),
              independent=False, has_allocation_basis=True,
              note="公共管路，按分摊声明取得份额")

    # ---- 比较规则 v1（active）
    rule = ComparisonRule(
        code="CMP-SCHOOL", version=1, status=RuleStatus.active,
        building_use=BuildingUse.school, climate_zone=ClimateZone.hot_summer_cold_winter,
        occupancy_profile=OccupancyProfile.term_time,
        min_baseline_days=150, max_baseline_days=430, date_tolerance_days=30,
        occupancy_cover_min=0.5, baseline_length_tolerance_days=45,
        min_common_window_days=120, max_area_ratio=2.0,
        notes="学校项目跨校比较：只判断比较范围与证据覆盖，不据此排名节能效果",
        created_by="seed",
    )
    db.add(rule)
    db.flush()

    # ---- 工作区 1：I/J/K 冬季 vs 春季；I~K 不可比（不传递）→ 发布 v1
    ws_winter = ComparisonWorkspace(
        code="WS-SCHOOL-WINTER", title="学校比较：冬季与春季两套窗口（I/J/K）",
        rule_id=rule.id, rule_version=1, project_ids=[I, J, K],
        material_cutoff=dt("2026-06-30"), status=WorkspaceStatus.draft, created_by="seed",
    )
    db.add(ws_winter)
    db.flush()
    revalidate_workspace(db, ws_winter, actor="seed")
    publish_workspace(db, ws_winter, actor="seed")

    # ---- 工作区 2：K/L 部分倍率补证 → 受限可比较
    ws_partial = ComparisonWorkspace(
        code="WS-PARTIAL-MULT", title="部分倍率补证比较（K/L）",
        rule_id=rule.id, rule_version=1, project_ids=[K, L],
        material_cutoff=dt("2026-06-30"), status=WorkspaceStatus.draft, created_by="seed",
    )
    db.add(ws_partial)
    db.flush()
    revalidate_workspace(db, ws_partial, actor="seed")
    publish_workspace(db, ws_partial, actor="seed")

    # ---- 工作区 3：共用总表 M/N → 不可比（不得当两份独立样本）
    ws_shared = ComparisonWorkspace(
        code="WS-SHARED-METER", title="共用总表比较（M/N）",
        rule_id=rule.id, rule_version=1, project_ids=[M, N],
        material_cutoff=dt("2026-06-30"), status=WorkspaceStatus.draft, created_by="seed",
    )
    db.add(ws_shared)
    db.flush()
    revalidate_workspace(db, ws_shared, actor="seed")
    publish_workspace(db, ws_shared, actor="seed")

    # ---- 工作区 4：全组队列（J/K/L/P）→ P 压缩整批交集
    ws_cohort = ComparisonWorkspace(
        code="WS-SCHOOL-COHORT", title="全组统一队列（J/K/L/P）",
        rule_id=rule.id, rule_version=1, project_ids=[J, K, L, p.id],
        material_cutoff=dt("2026-06-30"), status=WorkspaceStatus.draft, created_by="seed",
    )
    db.add(ws_cohort)
    db.flush()
    revalidate_workspace(db, ws_cohort, actor="seed")
    build_cohort(db, ws_cohort, actor="seed")

    # ---- 工作区 5：草稿（规则并发发布演示）
    ws_draft = ComparisonWorkspace(
        code="WS-SCHOOL-DRAFT", title="待发布草稿（规则并发发布演示）",
        rule_id=rule.id, rule_version=1, project_ids=[I, J],
        material_cutoff=dt("2026-06-30"), status=WorkspaceStatus.draft, created_by="seed",
    )
    db.add(ws_draft)
    db.flush()
    revalidate_workspace(db, ws_draft, actor="seed")
    ws_draft.status = WorkspaceStatus.draft  # 保留草稿状态，供规则发布场景演示

    # ---- 更严格规则草稿（供“发布更严格占用覆盖要求”演示）
    strict = ComparisonRule(
        code="CMP-SCHOOL-STRICT", version=1, status=RuleStatus.draft,
        building_use=BuildingUse.school, climate_zone=ClimateZone.hot_summer_cold_winter,
        occupancy_profile=OccupancyProfile.term_time,
        min_baseline_days=300, max_baseline_days=430, date_tolerance_days=7,
        occupancy_cover_min=0.85, baseline_length_tolerance_days=30,
        min_common_window_days=180, max_area_ratio=1.5,
        notes="更严格的占用覆盖要求（草稿）：占用覆盖不低于 85%",
        created_by="seed",
    )
    db.add(strict)
    db.flush()

if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
