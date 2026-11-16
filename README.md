# 公共建筑改造范围与能耗绩效数据核验平台

面向财政与学校的改造项目验收后节能绩效数据核验：登记哪些设备/空间属于项目范围、哪些电表读数代表同一计量边界、哪些缺失或交叉覆盖限制比较，并据此签发**可比较 / 受限可比较 / 待复核 / 不可比较**的绩效事实。平台只负责数据核验与发布，**不替代项目审批、预算调剂、拨款、施工安排或设备采购**。

在单项目核验之上，平台还提供**跨项目比较资格与队列构建**：只判断比较范围与证据覆盖，**不据此排名节能效果**。

## 架构

- **前端**：Vue 3 + TypeScript + Vite + Element Plus（`frontend/`）
- **后端**：FastAPI + SQLAlchemy（`backend/`）
- **数据库**：PostgreSQL

核心模块：

| 模块 | 说明 |
| --- | --- |
| 证据受理库 | 审批资料、合同条目、设备/空间清单、验收报告、仪表序列、读数原文、建筑主数据等；保留来源哈希、事件时间、接收时间、签发版本与修订链 |
| 改造范围册 | 合同承诺 / 实装证据 / 验收结论分别登记为候选、已确认、冲突、转移待核的空间/设备覆盖关系 |
| 计量边界册 | 电表、支路、公共管路、建筑区域在基线期/报告期的有效区间、倍率衔接与证据强度；换表断点自动拆分 |
| 绩效事实编译器 | 仅当范围关系与计量边界满足所选核验策略时签发事实；版本链只增不改 |
| 引用簿 | 记录哪些分析/审计视图使用了哪个版本的事实 |
| 比较规则登记 | 登记建筑用途、气候带、占用覆盖、基线长度与允许偏差；规则一经激活不可改写，更严格版本另发新版本 |
| 比较工作区 | 固定一批项目、资料截止点与规则版本，逐对核验比较资格；**不推导未计算的项目对** |
| 全组队列 | 仅在另行求出全组共同交集后开放统一队列；说明哪个项目压缩了整批可用日期 |
| 发布清单 | 冻结每项比较实际使用的项目、日期、限制与分母；新版本说明新增、失效与受限的项目对 |

## 一键启动（Docker Compose）

```bash
docker compose up --build
```

- 前端：http://localhost:8080
- 后端 API / Swagger UI：http://localhost:8000/docs
- 首次启动自动建表并写入覆盖全部验收场景的种子数据（幂等，重复启动不重复写入）

## 本地开发

前置：容器内置 PostgreSQL（127.0.0.1:5432，库/用户/密码 `ccdev`）。

```bash
# 1. 建库（仅首次）
PGPASSWORD=ccdev /opt/postgresql-18/bin/psql -h 127.0.0.1 -U ccdev -d ccdev -c "CREATE DATABASE epv;"

# 2. 后端（http://127.0.0.1:8000，Swagger UI 在 /docs）
cd backend
/opt/python-3.12/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.seed --reset      # 初始化种子数据
.venv/bin/uvicorn app.main:app --reload   # 启动 API

# 3. 前端（http://127.0.0.1:5173，已配置 /api 代理到 8000）
cd frontend
npm install
npm run dev
```

也可将前端构建产物交由后端一体化托管：`cd frontend && npm run build && cp -r dist ../backend/static`，然后只访问 http://127.0.0.1:8000 。

## 测试账号

| 账号 | 密码 | 角色 |
| --- | --- | --- |
| admin | admin123 | 管理员（全部权限） |
| analyst | analyst123 | 分析员（证据受理、编译、登记引用） |
| auditor | auditor123 | 审计查看员（只读 + 登记引用） |

## 验证方式

### 自动化测试（已实际执行，31 项全部通过）

```bash
cd backend
.venv/bin/python -m pytest tests/ -q     # 使用独立测试库 epv_test，不影响开发数据
```

单项目核验（11 项）：登录与权限、默认对标只读直接计量、覆盖分析纳入分摊值、未比较清单、序列号冲突与转移待核、基线期换表断点、验收附件替换触发复审与引用阻断、分摊补齐新签发版本、事实溯源完整性、重新编译版本链。

跨项目比较（20 项）：`tests/test_comparisons.py` —— 可比关系不传递、仅登记已计算项目对、共用总表不得当两份独立样本、部分倍率补证只保留对应区间、全组交集与薄弱项目压缩说明、全组队列需显式触发、发布清单冻结分母、项目退出产生失效项目对、切换条件/日期后旧资格作废、来源更正按边上定位且保留原分母、未受影响项目不受影响、公共负荷差异登记为限制、比较边回查、撤回工作区、规则并发发布（草稿标记过期、旧资格不得以新规则发布）、仅管理员可发布规则、未登录拒绝。

### 页面手工验证（种子数据已内置以下场景）

| 验收场景 | 项目 | 验证路径 |
| --- | --- | --- |
| 专属电表直接计量 | PRJ-A | 「绩效事实」对标表：可比较，节能 3,600 kWh / 30% |
| 共用管路分摊 + 资料补齐 | PRJ-B | 严格直接计量 → 不可比较（留在未比较清单）；分摊声明 v1 缺运行时长 → 待复核（历史版本）；v2 补齐后新签发受限可比较 v2（份额 62.5%），旧版本不被改写 |
| 序列号重叠 → 重复覆盖冲突 | PRJ-C / PRJ-D | 「改造范围册」冲突清单：CH-9001 服务区间重叠且物理互斥 → 冲突；事实不可比较 |
| 先后移装、缺移装材料 → 转移待核 | PRJ-E / PRJ-F | PU-3001 区间不重叠 → 转移待核（不升级为重复主张）；事实待复核 |
| 基线期中途换表 | PRJ-G | 「计量边界册」：M-G300→M-G301 断点拆分；跨断点编译 → 不可比较；断点后子区间 → 可比较 |
| 验收附件替换 | PRJ-H | 验收报告 v2 哈希变化 → 当前事实转「复审中」并暂停新引用（引用接口返回 409）；历史引用仍指向 v1 |
| 默认对标只读直接计量 | 全部 | 「绩效事实」对标表默认不含受控分摊；勾选「覆盖分析模式」才纳入分摊值并提示复核成本 |

每项绩效事实点「溯源」可回查：范围证据、计量边界、所选策略、分摊假设、版本链与下游引用。

### 跨项目比较场景（种子数据已内置，入口：左侧「跨项目比较」）

六所学校项目 PRJ-I ~ PRJ-N 与薄弱项目 PRJ-P 覆盖全部比较验收点：

| 验收场景 | 工作区 | 验证路径与预期 |
| --- | --- | --- |
| 可比关系不传递 | WS-SCHOOL-WINTER（I/J/K） | I~J 可比、J~K 可比、**I~K 不可比**（无共同窗口）；不推导甲丙可比 |
| 公共负荷 / 范围差异 | WS-PARTIAL-MULT（K/L） | L 计量含食堂且公共负荷不同 → **受限可比**，差异列入限制而不据此排名 |
| 共用总表重复计样 | WS-SHARED-METER（M/N） | 两项目共用校园总表且无独立读数 → **不可比**，排除区间注明“不得当两份独立样本” |
| 部分倍率补证 | WS-PARTIAL-MULT（K/L） | L 换表前倍率未补证：只有 2024-07-01 后区间进入候选，未补证段列入排除 |
| 全组队列与压缩 | WS-SCHOOL-COHORT（J/K/L/P） | 「全组队列」按钮求出共同交集；P 标为「限制交集」，并说明移除后增加的天数 |
| 项目退出 | 任一工作区 | 工作区详情中点项目标签外的退出操作，或「修改条件」移除项目 → 旧资格作废、需重新核验 |
| 规则并发发布 | WS-SCHOOL-DRAFT + CMP-SCHOOL | admin 在「比较规则」卡片点「发布更严格版本」→ 草稿工作区标记过期，旧资格不得以新规则发布 |
| 来源更正 | 任一工作区 | 点「登记更正」→ 按来源定位受影响比较边；未受影响项目对在重新核验后仍可使用；已发布清单保留原分母 |
| 比较边回查 | 任一比较边「回查」 | 展示双方条件签名、交集如何取得、排除区间、限制与可支持的分析类型，并做重算一致性校验 |

比较工作区的核心约束（页面顶部亦提示）：

- **只判断比较范围与证据覆盖，不排名节能效果**；
- 可比关系**不传递**：只逐对登记，不由甲~乙、乙~丙推导甲~丙；
- 共用总表且缺独立读数/分配依据时，**不得作为两份独立样本**；
- 倍率只覆盖部分区间时，**仅对应区间进入候选**；
- 切换用途/日期/项目/规则后，已选项目**必须重新核验**，不保留上一次的绿色资格。

### 跨项目比较 API 验证示例

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s "http://127.0.0.1:8000/api/comparisons/rules" -H "Authorization: Bearer $TOKEN"
curl -s "http://127.0.0.1:8000/api/comparisons/workspaces" -H "Authorization: Bearer $TOKEN"
curl -s "http://127.0.0.1:8000/api/comparisons/workspaces/1" -H "Authorization: Bearer $TOKEN"   # 边 + 队列 + 发布清单
curl -s "http://127.0.0.1:8000/api/comparisons/edges/3/trace" -H "Authorization: Bearer $TOKEN"  # 单边回查
curl -s -X POST "http://127.0.0.1:8000/api/comparisons/workspaces/4/cohort" -H "Authorization: Bearer $TOKEN"  # 求全组交集
```

### 页面手工验证步骤（已实际执行）

```bash
# 后端
cd backend && .venv/bin/python -m app.seed --reset && .venv/bin/uvicorn app.main:app --port 8000
# 前端（另一终端）
cd frontend && npm run dev
```

1. 打开 http://localhost:5173 ，用 `admin / admin123` 登录；
2. 左侧「跨项目比较」：确认 WS-SCHOOL-WINTER 中 I~K 为「不可比」、其余两条为「可比」；
3. 打开 WS-SCHOOL-COHORT，点「全组队列」，确认 PRJ-P 显示「限制交集」；
4. 在任一比较边点「回查」，核对双方输入、交集、排除区间与支持的分析；
5. 以 admin 在「比较规则」卡片发布更严格版本，确认 WS-SCHOOL-DRAFT 变为「已过期」且不能发布。

### API 验证示例

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s "http://127.0.0.1:8000/api/analysis/benchmark" -H "Authorization: Bearer $TOKEN"            # 默认只读直接计量
curl -s "http://127.0.0.1:8000/api/analysis/benchmark?include_allocated=true" -H "Authorization: Bearer $TOKEN"  # 覆盖分析纳入分摊
curl -s "http://127.0.0.1:8000/api/analysis/uncompared" -H "Authorization: Bearer $TOKEN"           # 未比较清单
curl -s "http://127.0.0.1:8000/api/facts/4/trace" -H "Authorization: Bearer $TOKEN"                 # 分摊事实溯源
```

## 目录结构

```
backend/
  app/
    main.py          # FastAPI 入口（含可选静态托管）
    models.py        # 证据/范围/边界/事实/引用/冲突/换表/比较规则/工作区/比较边/队列/发布模型
    compiler.py      # 绩效事实编译器与领域规则
    comparison.py    # 跨项目比较资格与队列构建引擎（不排名节能效果）
    seed.py          # 验收场景种子数据（幂等）
    routers/         # auth/projects/evidence/scope/boundaries/facts/citations/analysis/comparisons
  tests/             # 31 项场景测试（独立测试库）
frontend/
  src/views/         # 工作台/证据库/范围册/边界册/事实/事实溯源/跨项目比较/引用簿
docker-compose.yml   # db + backend + frontend 一键启动
```
