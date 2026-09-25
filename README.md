# 影视剧组拍摄制作管理平台

面向剧本分场、选角档期、拍摄通告、场地器材、后期特效与杀青结算的一体化剧组管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 剧本管理 | `script` | 剧本 | 剧本编号、剧本名称、题材类型 |
| 分场大纲 | `scene` | 分场表 | 场次编号、所属剧本、场景地点、拍摄难度 |
| 角色选角 | `casting` | 角色 | 角色编号、角色名称、角色类型 |
| 剧组人员 | `crew` | 剧组成员 | 成员编号、姓名、岗位职务 |
| 拍摄通告 | `notice` | 拍摄通告单 | 通告编号、拍摄日期、集合时间 |
| 场地租用 | `location` | 拍摄场地 | 场地编号、场地名称、场地类型 |
| 道具管理 | `prop` | 道具 | 道具编号、道具名称、道具类别 |
| 服装造型 | `costume` | 戏服 | 服装编号、服装名称、角色归属 |
| 化妆造型 | `makeup` | 妆造方案 | 方案编号、角色名称、造型风格 |
| 器材管理 | `equipment` | 拍摄器材 | 器材编号、器材名称、器材类别 |
| 拍摄进度 | `shooting` | 拍摄日 | 拍摄日编号、拍摄日期、拍摄地点 |
| 素材管理 | `footage` | 拍摄素材 | 素材编号、素材类型、拍摄日期 |
| 后期剪辑 | `edit` | 剪辑任务 | 任务编号、所属集数、剪辑师 |
| 特效制作 | `vfx` | 特效镜头 | 镜头编号、所属集数、特效类型 |
| 审片意见 | `review` | 审片记录 | 审片编号、审片轮次、审片人 |
| 预算科目 | `budget` | 预算科目 | 科目编号、科目名称、费用类别 |
| 费用报销 | `expense` | 报销单 | 报销单号、报销人、费用类别 |
| 档期协调 | `schedule` | 演员档期 | 档期编号、演员姓名、经纪公司 |
| 外景许可 | `permit` | 拍摄许可 | 许可编号、许可类型、申请地点 |
| 杀青结算 | `wrap` | 结算单 | 结算单号、结算对象、结算周期 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 分场拍摄难度评估

分场大纲模块内置难度评估规则（`backend/app/services/scene_difficulty.py`）：

- 以单个场次为单位，按「场景地点、日戏夜戏、预计时长（分钟）」计分，映射为
  低 / 中 / 高 / 极高 四档；单场预计时长上限 90 分钟。
- 争议项判定口径：时长超上限、夜戏+外景+长时长组合、日戏夜戏无法识别、
  地点无法判断内外景，命中即标记争议并写明原因。
- 列表、导出、重算共用同一份规则；`GET /api/scene/difficulty-rules` 返回当前口径。
- 场景地点或预计时长缺失时不允许保存，接口会说明具体原因。
- `POST /api/scene/recalculate` 批量重算，单场失败不中断；传 `entry_ids`
  可只重试失败场次。已审核分场冻结评估时的规则版本与结果，阈值调整
  （须同步升 `RULE_VERSION`）不会改写历史数据。
