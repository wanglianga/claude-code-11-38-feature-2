"""验收场景端到端测试：专属电表 / 共用管路分摊 / 序列号重叠与移装 / 基线期换表 / 附件替换 / 分摊补齐。"""

PROJECTS = {}


def _pid(client, H, code):
    if not PROJECTS:
        for p in client.get("/api/projects", headers=H).json():
            PROJECTS[p["code"]] = p["id"]
    return PROJECTS[code]


def test_login(client):
    r = client.post("/api/auth/login", json={"username": "auditor", "password": "auditor123"})
    assert r.status_code == 200 and r.json()["role"] == "auditor"
    r = client.post("/api/auth/login", json={"username": "auditor", "password": "wrong"})
    assert r.status_code == 401


def test_benchmark_defaults_to_direct_metering(client, H):
    rows = client.get("/api/analysis/benchmark", headers=H).json()
    assert rows and all(r["result_kind"] == "direct_metering" for r in rows)
    codes = {r["project_code"] for r in rows}
    assert "PRJ-A" in codes and "PRJ-G" in codes
    a = next(r for r in rows if r["project_code"] == "PRJ-A")
    assert a["baseline_kwh"] == 12000.0 and a["reporting_kwh"] == 8400.0
    assert a["savings_kwh"] == 3600.0 and a["comparability"] == "comparable"


def test_benchmark_include_allocated_for_coverage_analysis(client, H):
    rows = client.get("/api/analysis/benchmark?include_allocated=true", headers=H).json()
    alloc = [r for r in rows if r["result_kind"] == "controlled_allocation"]
    assert len(alloc) == 1 and alloc[0]["project_code"] == "PRJ-B"
    assert alloc[0]["comparability"] == "restricted_comparable"
    assert alloc[0]["assumptions"]["share"] == 0.625


def test_uncompared_list(client, H):
    rows = client.get("/api/analysis/uncompared", headers=H).json()
    by_code = {r["project_code"]: r for r in rows}
    assert by_code["PRJ-B"]["comparability"] == "incomparable"      # 公共管路不能直接计量
    assert by_code["PRJ-C"]["comparability"] == "incomparable"      # 重复覆盖冲突
    assert by_code["PRJ-E"]["comparability"] == "pending_review"    # 转移待核


def test_serial_conflict_and_transfer_pending(client, H):
    conflicts = client.get("/api/scope/conflicts", headers=H).json()
    dup = [c for c in conflicts if c["conflict_type"] == "duplicate_coverage"]
    trf = [c for c in conflicts if c["conflict_type"] == "transfer_pending"]
    assert any(c["serial_no"] == "CH-9001" for c in dup)
    assert any(c["serial_no"] == "PU-3001" for c in trf)
    # 转移待核不得升级为重复主张
    tr = next(c for c in trf if c["serial_no"] == "PU-3001")
    assert "不升级" in tr["detail"]["reason"] or "转移待核" in tr["detail"]["reason"]


def test_meter_replacement_breakpoint(client, H):
    pid = _pid(client, H, "PRJ-G")
    events = client.get(f"/api/boundaries/meter-events?project_id={pid}", headers=H).json()
    assert len(events) == 1 and events[0]["multiplier_linked"] is False
    bounds = client.get(f"/api/boundaries?project_id={pid}", headers=H).json()
    baseline = [b for b in bounds if b["period_role"] == "baseline"]
    assert len(baseline) == 2  # 断点拆分为新旧两段
    facts = client.get(f"/api/facts?project_id={pid}", headers=H).json()
    spanning = [f for f in facts if f["baseline_start"].startswith("2024-01-01")]
    assert spanning and all(f["comparability"] == "incomparable" for f in spanning)
    sub = [f for f in facts if f["baseline_start"].startswith("2024-07-01") and f["status"] == "current"]
    assert sub and sub[0]["comparability"] == "comparable"


def test_acceptance_attachment_replacement(client, H):
    pid = _pid(client, H, "PRJ-H")
    facts = client.get(f"/api/facts?project_id={pid}", headers=H).json()
    assert facts[0]["status"] == "under_review" and facts[0]["block_new_citations"] is True
    # 复审中事实禁止新引用
    r = client.post("/api/citations", headers=H,
                    json={"fact_id": facts[0]["id"], "consumer_type": "analysis",
                          "consumer_name": "测试", "purpose": "应被拒绝"})
    assert r.status_code == 409
    # 修订链完整：v1 superseded、v2 active、哈希不同
    ev = client.get(f"/api/evidence?project_id={pid}&doc_type=acceptance_report", headers=H).json()
    by_ver = {e["version"]: e for e in ev}
    assert by_ver[1]["status"] == "superseded" and by_ver[2]["status"] == "active"
    assert by_ver[1]["source_hash"] != by_ver[2]["source_hash"]
    # 替换前的历史引用仍指向 v1
    cits = client.get(f"/api/citations?fact_id={facts[0]['id']}", headers=H).json()
    assert cits and cits[0]["fact_version"] == 1


def test_allocation_supplement_issues_new_version(client, H):
    pid = _pid(client, H, "PRJ-B")
    facts = client.get(f"/api/facts?project_id={pid}&result_kind=controlled_allocation", headers=H).json()
    by_ver = {f["version"]: f for f in facts}
    # v1 待复核被保留为历史版本，v2 受限可比较为当前版本 —— 补齐资料只新签发，不改写
    assert by_ver[1]["comparability"] == "pending_review" and by_ver[1]["status"] == "superseded"
    assert by_ver[2]["comparability"] == "restricted_comparable" and by_ver[2]["status"] == "current"
    assert by_ver[2]["assumptions"]["declaration_version"] == 2


def test_fact_trace_completeness(client, H):
    facts = client.get("/api/facts?project_id=1", headers=H).json()
    trace = client.get(f"/api/facts/{facts[0]['id']}/trace", headers=H).json()
    for key in ("fact", "scope_relation", "scope_evidence", "boundary", "strategy",
                "assumptions", "version_chain", "citations", "meter_events"):
        assert key in trace
    assert trace["scope_evidence"] and trace["boundary"]["meter_serial"] == "M-A100"


def test_compile_new_fact_and_version_chain(client, H):
    # 对 PRJ-H 重新编译（验收附件替换后重新签发）→ 产生 v2 当前版本，v1 转历史
    pid = _pid(client, H, "PRJ-H")
    rels = client.get(f"/api/scope/relations?project_id={pid}", headers=H).json()
    scope_id = rels[0]["id"]
    r = client.post("/api/facts/compile", headers=H, json={
        "project_id": pid, "scope_relation_id": scope_id, "strategy": "strict_direct",
        "baseline_start": "2024-01-01T00:00:00Z", "baseline_end": "2025-01-01T00:00:00Z",
        "reporting_start": "2025-01-01T00:00:00Z", "reporting_end": "2026-01-01T00:00:00Z",
    })
    assert r.status_code == 201, r.text
    new_fact = r.json()
    assert new_fact["version"] == 2 and new_fact["status"] == "current"
    assert new_fact["comparability"] == "comparable"
    facts = client.get(f"/api/facts?project_id={pid}", headers=H).json()
    v1 = next(f for f in facts if f["version"] == 1)
    assert v1["status"] == "superseded"  # 历史版本保留原结论


def test_write_permission_guard(client):
    r = client.post("/api/auth/login", json={"username": "auditor", "password": "auditor123"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    resp = client.post("/api/projects", headers=h, json={
        "code": "PRJ-X", "name": "x", "building_name": "x", "owner_org": "x"})
    assert resp.status_code == 403
