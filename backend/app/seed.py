"""种子数据：覆盖全部验收场景。

场景映射：
- PRJ-A 市第一中学照明改造      → 专属电表直接计量（可比较）
- PRJ-B 区政府办公楼空调改造    → 公共管路受控分摊（先待复核，补齐运行时长后新签发版本）
- PRJ-C/PRJ-D 实验小学/第二中学 → 同一序列号重叠声明 → 重复覆盖冲突
- PRJ-E/PRJ-F 图书馆/文化馆     → 同一序列号先后移装、缺移装材料 → 转移待核
- PRJ-G 医院门诊楼              → 基线期中途换表、倍率未衔接 → 断点拆分
- PRJ-H 体育馆                  → 验收附件替换 → 当前事实转复审中、暂停新引用
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

from .compiler import compile_fact, detect_serial_conflicts, register_meter_event
from .database import Base, SessionLocal, engine
from .models import (
    Citation,
    DocType,
    EvidenceDocument,
    EvidenceStatus,
    EvidenceStrength,
    FactStatus,
    MeteringBoundary,
    PerformanceFact,
    PeriodRole,
    PipelineKind,
    Project,
    RelationKind,
    ScopeRelation,
    ScopeStatus,
    Strategy,
    SubjectType,
    User,
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
                 zone="", branch="", strength=EvidenceStrength.strong, evidence_ids=None):
    b = MeteringBoundary(
        project_id=project_id, meter_serial=meter, branch_name=branch, pipeline_kind=kind,
        zone_name=zone, period_role=role, valid_from=start, valid_to=end,
        multiplier=1.0, evidence_strength=strength, evidence_ids=evidence_ids or [],
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
                     zone="教学楼A", branch="照明支路", evidence_ids=[ev_a_meter.id])
        add_boundary(db, P["PRJ-A"], "M-A100", PeriodRole.reporting, dt("2025-01-01"), dt("2026-01-01"),
                     zone="教学楼A", branch="照明支路", evidence_ids=[ev_a_meter.id])

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
                     kind=PipelineKind.shared, zone="办公楼主楼", branch="冷冻站总管")
        add_boundary(db, P["PRJ-B"], "M-B200", PeriodRole.reporting, dt("2025-01-01"), dt("2026-01-01"),
                     kind=PipelineKind.shared, zone="办公楼主楼", branch="冷冻站总管")

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
                     zone="门诊楼", branch="空调支路", evidence_ids=[ev_g_meter.id])
        add_boundary(db, P["PRJ-G"], "M-G301", PeriodRole.reporting, dt("2025-01-01"), dt("2026-01-01"),
                     zone="门诊楼", branch="空调支路")
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
                     zone="体育馆", branch="泳池设备支路", evidence_ids=[ev_h_meter.id])
        add_boundary(db, P["PRJ-H"], "M-H400", PeriodRole.reporting, dt("2025-01-01"), dt("2026-01-01"),
                     zone="体育馆", branch="泳池设备支路")

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

        db.commit()

        # ---------- 汇总输出 ----------
        n_facts = db.query(PerformanceFact).count()
        print(f"种子完成：项目 {len(projects)}，事实 {n_facts}")
        for f in db.query(PerformanceFact).order_by(PerformanceFact.id).all():
            print(f"  fact#{f.id} project={f.project_id} strategy={f.strategy.value} "
                  f"kind={f.result_kind.value} comp={f.comparability.value} status={f.status.value} v{f.version}")
    finally:
        db.close()


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
