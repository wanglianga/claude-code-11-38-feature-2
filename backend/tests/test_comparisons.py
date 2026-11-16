"""跨项目比较资格与队列构建验收测试。

覆盖：可比关系不传递、公共负荷重复计样、部分倍率补证、项目退出、规则并发发布、
来源更正按边定位、结果切换条件后重新核验、发布清单冻结分母与差异说明。

注意：本文件按定义顺序执行。破坏性用例（规则发布、项目退出、来源更正）
使用独立工作区或安排在末尾，避免相互污染。
"""

PROJECTS = {}
WORKSPACES = {}


def _pid(client, H, code):
    if not PROJECTS:
        for p in client.get("/api/projects", headers=H).json():
            PROJECTS[p["code"]] = p["id"]
    return PROJECTS[code]


def _active_rule(client, H, code="CMP-SCHOOL"):
    for r in client.get("/api/comparisons/rules", headers=H).json():
        if r["code"] == code and r["status"] == "active":
            return r
    raise AssertionError(f"未找到激活规则 {code}")


def _ws(client, H, code):
    if code not in WORKSPACES:
        for w in client.get("/api/comparisons/workspaces", headers=H).json():
            WORKSPACES[w["code"]] = w
    return WORKSPACES[code]


def _ws_detail(client, H, code):
    return client.get(f"/api/comparisons/workspaces/{_ws(client, H, code)['id']}",
                      headers=H).json()


def _edge(detail, a, b):
    for e in detail["edges"]:
        if {e["project_a_code"], e["project_b_code"]} == {a, b}:
            return e
    raise AssertionError(f"未找到比较边 {a}~{b}")


def _new_workspace(client, H, code, projects, cutoff="2026-06-30T00:00:00Z", rule_code="CMP-SCHOOL"):
    rule = _active_rule(client, H, rule_code)
    r = client.post("/api/comparisons/workspaces", headers=H, json={
        "code": code, "title": code, "rule_id": rule["id"],
        "project_ids": [_pid(client, H, c) for c in projects],
        "material_cutoff": cutoff,
    })
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- 规则


def test_rule_registry_and_draft(client, H):
    rules = client.get("/api/comparisons/rules", headers=H).json()
    codes = {r["code"] for r in rules}
    assert "CMP-SCHOOL" in codes and "CMP-SCHOOL-STRICT" in codes
    r = _active_rule(client, H)
    # 规则登记了建筑用途、气候带、占用覆盖、基线长度与允许偏差
    for key in ("building_use", "climate_zone", "occupancy_profile", "min_baseline_days",
                "max_baseline_days", "date_tolerance_days", "occupancy_cover_min",
                "baseline_length_tolerance_days", "min_common_window_days", "max_area_ratio"):
        assert r[key] is not None
    assert r["status"] == "active"


# ---------------------------------------------------------------- 不传递


def test_comparability_is_not_transitive(client, H):
    d = _ws_detail(client, H, "WS-SCHOOL-WINTER")
    ij = _edge(d, "PRJ-I", "PRJ-J")
    jk = _edge(d, "PRJ-J", "PRJ-K")
    ik = _edge(d, "PRJ-I", "PRJ-K")
    assert ij["level"] == "comparable" and ij["eligible"]
    assert jk["level"] == "comparable" and jk["eligible"]
    # 甲丙没有共同窗口，不得由甲~乙、乙~丙推导为可比
    assert ik["level"] == "blocked" and not ik["eligible"]
    assert any("没有共同可用" in r for r in ik["reasons"])
    # 每条边都带各自的条件签名（不做签名合并）
    for e in (ij, jk, ik):
        assert e["signatures"]["a"]["project_id"] and e["signatures"]["b"]["project_id"]
        assert "window" in e


def test_edges_only_for_registered_pairs(client, H):
    d = _ws_detail(client, H, "WS-SCHOOL-WINTER")
    pairs = {frozenset((e["project_a_code"], e["project_b_code"])) for e in d["edges"]}
    assert pairs == {frozenset(("PRJ-I", "PRJ-J")), frozenset(("PRJ-I", "PRJ-K")),
                     frozenset(("PRJ-J", "PRJ-K"))}
    assert frozenset(("PRJ-I", "PRJ-L")) not in pairs


# ---------------------------------------------------------------- 共用总表 / 公共负荷


def test_shared_meter_not_two_independent_samples(client, H):
    d = _ws_detail(client, H, "WS-SHARED-METER")
    e = _edge(d, "PRJ-M", "PRJ-N")
    assert e["level"] == "blocked" and not e["eligible"]
    shared = [x for x in e["exclusions"] if x["scope"] == "shared_meter"]
    assert shared, "应给出共用总表排除区间"
    assert any("独立" in x["reason"] for x in shared)
    assert any("共用总表" in r for r in e["reasons"])
    assert e["inputs"]["shared_meter_windows"]
    # 公共负荷重叠：两项目登记了同一总表，输入快照应当可回查
    assert e["inputs"]["project_a"]["shared_load_keys"] == e["inputs"]["project_b"]["shared_load_keys"]


def test_public_load_difference_is_registered_as_limitation(client, H):
    d = _ws_detail(client, H, "WS-PARTIAL-MULT")
    e = _edge(d, "PRJ-K", "PRJ-L")
    # 公共负荷覆盖不一致必须作为限制登记，而不是被静默忽略
    assert any("公共负荷" in l for l in e["limitations"])
    assert e["signatures"]["a"]["includes_public_load"] != e["signatures"]["b"]["includes_public_load"]


# ---------------------------------------------------------------- 部分倍率


def test_partial_multiplier_only_covered_interval_candidate(client, H):
    d = _ws_detail(client, H, "WS-PARTIAL-MULT")
    e = _edge(d, "PRJ-K", "PRJ-L")
    assert e["level"] == "restricted" and e["eligible"]
    cand = e["window"]["candidate_baseline"]
    assert cand, "应保留补证后的候选区间"
    assert all(x["start"] >= "2024-07-01" for x in cand)
    gaps = [x for x in e["exclusions"] if x["scope"] == "baseline"]
    assert gaps and any("倍率" in x["reason"] or "覆盖" in x["reason"] for x in gaps)
    assert any("食堂" in l for l in e["limitations"])
    assert "ranking" not in e["supported_analysis"]


# ---------------------------------------------------------------- 全组队列


def test_cohort_intersection_and_limiter(client, H):
    d = _ws_detail(client, H, "WS-SCHOOL-COHORT")
    cohort = d["cohort"]
    assert cohort is not None
    members = {m["project_id"] for m in cohort["members"]}
    pid_p = _pid(client, H, "PRJ-P")
    assert pid_p in members
    limiters = {l["project_id"]: l for l in cohort["intersection"]["limiters"]}
    assert pid_p in limiters and limiters[pid_p]["days_gained_if_removed"] > 0
    assert cohort["intersection"]["baseline"]
    assert any("压缩" in r for r in cohort["reasons"])
    statuses = {s["project_code"]: s for s in cohort["project_statuses"]}
    assert statuses["PRJ-P"]["status"] == "limiter"
    # 队列必须带共同交集与每项说明
    assert cohort["members"] and len(cohort["members"]) >= 2
    assert cohort["limitations"]


def test_cohort_requires_explicit_trigger(client, H):
    ws = _ws(client, H, "WS-SCHOOL-DRAFT")
    r = client.post(f"/api/comparisons/workspaces/{ws['id']}/cohort", headers=H)
    assert r.status_code == 409


def test_cohort_rebuild_is_idempotent(client, H):
    ws = _ws(client, H, "WS-SCHOOL-COHORT")
    r1 = client.post(f"/api/comparisons/workspaces/{ws['id']}/cohort", headers=H)
    assert r1.status_code == 200, r1.text
    body = r1.json()
    # 接口直接返回每个项目的队列状态，便于页面展示“谁限制了交集”
    assert body["project_statuses"]
    assert {s["project_code"] for s in body["project_statuses"]} >= {"PRJ-P"}
    assert body["intersection"]["limiters"]
    r2 = client.post(f"/api/comparisons/workspaces/{ws['id']}/cohort", headers=H)
    assert r2.status_code == 200, r2.text
    assert r2.json()["workspace_id"] == ws["id"]
    assert len(r2.json()["members"]) == len(body["members"])


# ---------------------------------------------------------------- 发布清单


def test_publication_freezes_denominator(client, H):
    d = _ws_detail(client, H, "WS-SCHOOL-WINTER")
    pubs = d["publications"]
    assert pubs
    v1 = next(p for p in pubs if p["version"] == 1)
    assert v1["rule_version"] == 1
    assert len(v1["edges_snapshot"]) == 3
    assert v1["material_cutoff"]
    for e in v1["edges_snapshot"]:
        assert e["signatures"] and e["window"] and e["supported_analysis"]
    assert v1["diff_from_previous"]["base_version"] is None
    assert v1["stale"] is False


def test_project_exit_and_new_publication_diff(client, H):
    ws = _new_workspace(client, H, "WS-EXIT-TEST", ["PRJ-J", "PRJ-K", "PRJ-L"])
    assert len(ws["edges"]) == 3
    r = client.post(f"/api/comparisons/workspaces/{ws['id']}/publish", headers=H)
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 1

    pid_l = _pid(client, H, "PRJ-L")
    r = client.delete(f"/api/comparisons/workspaces/{ws['id']}/projects/{pid_l}", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "stale" and pid_l not in body["project_ids"]

    r = client.post(f"/api/comparisons/workspaces/{ws['id']}/compute", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "computed"
    r = client.post(f"/api/comparisons/workspaces/{ws['id']}/publish", headers=H)
    assert r.status_code == 201, r.text
    pub = r.json()
    assert pub["version"] == 2 and pub["diff_from_previous"]["base_version"] == 1
    dropped_pairs = {tuple(x["pair"]) for x in pub["diff_from_previous"]["dropped"]}
    assert dropped_pairs, "项目退出应产生失效项目对"
    # 原 v1 冻结分母不变
    pubs = client.get(f"/api/comparisons/publications?workspace_id={ws['id']}", headers=H).json()
    v1 = next(p for p in pubs if p["version"] == 1)
    assert len(v1["edges_snapshot"]) == 3


# ---------------------------------------------------------------- 条件切换重验


def test_changing_conditions_invalidates_previous_green(client, H):
    ws = _new_workspace(client, H, "WS-REVALIDATE-TEST", ["PRJ-J", "PRJ-K"])
    assert any(e["level"] == "comparable" for e in ws["edges"])

    r = client.patch(f"/api/comparisons/workspaces/{ws['id']}", headers=H, json={
        "project_ids": [_pid(client, H, "PRJ-J"), _pid(client, H, "PRJ-K"),
                        _pid(client, H, "PRJ-L")],
        "reason": "切换日期/项目后重新核验",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "stale"
    assert body["edges"] == [], "条件变更后不得保留上一次的绿色资格"
    assert body["cohort"] is None
    assert body["stale_reasons"]

    assert client.post(f"/api/comparisons/workspaces/{ws['id']}/publish",
                       headers=H).status_code == 409

    r = client.post(f"/api/comparisons/workspaces/{ws['id']}/compute", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "computed"
    assert r.json()["edges"]


def test_cutoff_change_must_revalidate(client, H):
    ws = _new_workspace(client, H, "WS-CUTOFF-TEST", ["PRJ-J", "PRJ-K"])
    r = client.patch(f"/api/comparisons/workspaces/{ws['id']}", headers=H, json={
        "material_cutoff": "2025-06-30T00:00:00Z",
    })
    assert r.json()["status"] == "stale"
    assert any("cutoff" in (s.get("changed") or []) for s in r.json()["stale_reasons"])


# ---------------------------------------------------------------- 来源更正


def test_source_correction_targets_edges_and_preserves_publication(client, H):
    ws = _ws(client, H, "WS-SHARED-METER")
    before = client.get(f"/api/comparisons/publications?workspace_id={ws['id']}",
                        headers=H).json()
    assert before
    pid_m = _pid(client, H, "PRJ-M")
    cov_ids = [c["id"] for c in client.get(
        f"/api/comparisons/coverage?project_id={pid_m}", headers=H).json()]

    r = client.post("/api/comparisons/corrections", headers=H, json={
        "project_ids": [pid_m], "source_ref": "correction:shared-meter-M",
        "source_types": ["coverage"], "source_ids": cov_ids,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert ws["id"] in body["stale_workspaces"]
    assert body["stale_publications"]
    # 先按来源定位比较边
    assert body["affected_edges"]
    assert all(p in body["affected_edges"][0]["pair"] for p in [_pid(client, H, "PRJ-M")])

    d = client.get(f"/api/comparisons/workspaces/{ws['id']}", headers=H).json()
    assert d["status"] == "stale"
    assert all(e["stale"] for e in d["edges"])

    after = client.get(f"/api/comparisons/publications?workspace_id={ws['id']}",
                       headers=H).json()
    oldest = next(p for p in after if p["version"] == before[-1]["version"])
    assert oldest["edges_snapshot"] == before[-1]["edges_snapshot"], "已发布清单保留原分母"
    assert oldest["stale"] is True and oldest["stale_reasons"]


def test_source_correction_of_unrelated_project_keeps_edges(client, H):
    ws = _ws(client, H, "WS-PARTIAL-MULT")
    before = client.get(f"/api/comparisons/workspaces/{ws['id']}", headers=H).json()
    assert before["status"] != "stale"
    r = client.post("/api/comparisons/corrections", headers=H, json={
        "project_ids": [_pid(client, H, "PRJ-A")], "source_ref": "correction:unrelated-A",
    })
    assert r.status_code == 200
    assert ws["id"] not in r.json()["stale_workspaces"]
    after = client.get(f"/api/comparisons/workspaces/{ws['id']}", headers=H).json()
    assert after["status"] != "stale"
    assert len(after["edges"]) == len(before["edges"])


# ---------------------------------------------------------------- 回查


def test_edge_trace_reconstruction(client, H):
    d = _ws_detail(client, H, "WS-PARTIAL-MULT")
    e = _edge(d, "PRJ-K", "PRJ-L")
    t = client.get(f"/api/comparisons/edges/{e['id']}/trace", headers=H).json()
    assert t["inputs"]["project_a"] and t["inputs"]["project_b"]
    assert "common_intersection" in t["inputs"]
    assert t["exclusions"] and t["supported_analysis"]
    assert t["recomputed_matches"] is True
    assert t["rule"]["code"] == "CMP-SCHOOL"
    assert "不构成节能效果排名" in t["note"]


def test_withdraw_workspace(client, H):
    ws = _new_workspace(client, H, "WS-WITHDRAW-TEST", ["PRJ-J", "PRJ-K"])
    r = client.post(f"/api/comparisons/workspaces/{ws['id']}/withdraw", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    assert client.post(f"/api/comparisons/workspaces/{ws['id']}/compute",
                       headers=H).status_code == 409


# ---------------------------------------------------------------- 规则并发发布（末尾）


def test_stricter_rule_publish_marks_running_draft_stale(client, H):
    # 使用独立规则 code，避免污染其他用例依赖的 CMP-SCHOOL
    r = client.post("/api/comparisons/rules", headers=H, json={
        "code": "CMP-STRICT-TEST", "occupancy_cover_min": 0.5,
        "notes": "并发发布测试 v1",
    })
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["status"] == "draft"

    # 草稿规则不得直接据其发布新版本
    r = client.post(f"/api/comparisons/rules/{v1['id']}/publish", headers=H, json={
        "code": "CMP-STRICT-TEST", "occupancy_cover_min": 0.9})
    assert r.status_code == 409

    # 直接构造一个使用 v1 的工作区（需要 v1 激活）：先手工作为 seed 已有的 active 规则建区，
    # 另用独立规则走“激活 → 更严格发布”的完整链路
    ws = _new_workspace(client, H, "WS-RULE-CONCURRENT-TEST", ["PRJ-J", "PRJ-K"])
    active = _active_rule(client, H)
    r = client.post(f"/api/comparisons/rules/{active['id']}/publish", headers=H, json={
        "code": "CMP-SCHOOL", "occupancy_cover_min": 0.95,
        "notes": "更严格：占用覆盖不低于 95%",
    })
    # 该工作区绑定的是 CMP-SCHOOL v1，应被标记过期
    assert r.status_code == 201, r.text
    new_rule = r.json()
    assert new_rule["version"] == 2 and new_rule["occupancy_cover_min"] == 0.95
    assert "WS-RULE-CONCURRENT-TEST" in {s["code"] for s in new_rule["stale_workspaces"]}

    rules = client.get("/api/comparisons/rules", headers=H).json()
    old = next(x for x in rules if x["code"] == "CMP-SCHOOL" and x["version"] == 1)
    assert old["status"] == "superseded"

    d = client.get(f"/api/comparisons/workspaces/{ws['id']}", headers=H).json()
    assert d["status"] == "stale"
    assert any("规则已发布更严格版本" in (x.get("note") or "") for x in d["stale_reasons"])
    # 旧资格不得以新规则名义发布
    assert client.post(f"/api/comparisons/workspaces/{ws['id']}/publish",
                       headers=H).status_code == 409

    # 已发布清单保留原分母并标记规则更新
    pubs = client.get(f"/api/comparisons/publications?workspace_id={_ws(client, H, 'WS-SCHOOL-WINTER')['id']}",
                      headers=H).json()
    assert pubs
    assert all(len(p["edges_snapshot"]) > 0 for p in pubs)
    assert any(p["stale"] for p in pubs)


def test_cannot_publish_rule_from_draft(client, H):
    rules = client.get("/api/comparisons/rules", headers=H).json()
    draft = next(r for r in rules if r["code"] == "CMP-SCHOOL-STRICT")
    r = client.post(f"/api/comparisons/rules/{draft['id']}/publish", headers=H, json={
        "code": "CMP-SCHOOL-STRICT", "occupancy_cover_min": 0.9,
    })
    assert r.status_code == 409


def test_only_admin_can_publish_rule(client):
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    active = _active_rule(client, h)
    resp = client.post(f"/api/comparisons/rules/{active['id']}/publish", headers=h, json={
        "code": "CMP-SCHOOL", "occupancy_cover_min": 0.99})
    assert resp.status_code == 403


def test_comparison_requires_auth(client):
    assert client.get("/api/comparisons/workspaces").status_code == 401
