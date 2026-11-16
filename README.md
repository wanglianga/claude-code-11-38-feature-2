# 公共建筑改造范围与能耗绩效数据核验平台

面向财政与学校的改造项目验收后节能绩效数据核验：登记哪些设备/空间属于项目范围、哪些电表读数代表同一计量边界、哪些缺失或交叉覆盖限制比较，并据此签发**可比较 / 受限可比较 / 待复核 / 不可比较**的绩效事实。平台只负责数据核验与发布，**不替代项目审批、预算调剂、拨款、施工安排或设备采购**。

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

### 自动化测试（已实际执行，11 项全部通过）

```bash
cd backend
.venv/bin/python -m pytest tests/ -q     # 使用独立测试库 epv_test，不影响开发数据
```

覆盖：登录与权限、默认对标只读直接计量、覆盖分析纳入分摊值、未比较清单、序列号冲突与转移待核、基线期换表断点、验收附件替换触发复审与引用阻断、分摊补齐新签发版本、事实溯源完整性、重新编译版本链。

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
    models.py        # 证据/范围/边界/事实/引用/冲突/换表事件模型
    compiler.py      # 绩效事实编译器与领域规则
    seed.py          # 验收场景种子数据（幂等）
    routers/         # auth/projects/evidence/scope/boundaries/facts/citations/analysis
  tests/             # 11 项场景测试（独立测试库）
frontend/
  src/views/         # 工作台/证据库/范围册/边界册/事实/事实溯源/引用簿
docker-compose.yml   # db + backend + frontend 一键启动
```
