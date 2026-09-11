# 校园活动管理系统 V1.0

> 实验一 · 基于工程意图的软件迭代开发
> 小组：林翔宇、王泰然、唐佳涵

## 一、项目定位

学校需要一个校园活动管理系统，为活动组织和学生参与提供信息化支持。
初始业务方向只有三条：支持用户注册登录、学生能够了解和参与校园活动、
活动组织教师能够发布和管理校园活动。

V1.0 不追求功能数量，目标是**把「教师发布活动 → 学生浏览并报名」这条基本业务
闭环真实跑通**，并保持结构清晰、可继续迭代。

## 二、技术栈

| 层次 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | —— |
| Web 框架 | Flask | 轻量、无构建链，便于逐步迭代 |
| ORM | Flask-SQLAlchemy | 数据访问与约束集中定义 |
| 会话 | Flask-Login | 登录态与角色权限校验 |
| 数据库 | SQLite | 单文件，零外部服务依赖 |
| 前端 | Jinja2 模板 + 原生 CSS/JS | 服务端渲染，不引入打包工具 |

## 三、运行方式

```bash
# 1. 创建并激活虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库（建表 + 写入活动分类）
python -m app.seed

# 4. 启动
python run.py
```

浏览器访问 <http://127.0.0.1:5000/>

数据库文件位于 `instance/campus.db`，已被 `.gitignore` 排除，不会进入版本库。

`python -m app.seed` 会幂等写入 5 个活动分类、6 个演示账号与 3 个示例活动。
演示账号的登录口令统一为 `Demo@2026`，角色分布如下：

| 账号 | 姓名 | 角色 |
|---|---|---|
| `wangtairan` | 王泰然 | 活动组织教师 |
| `tangjiahan` | 唐佳涵 | 活动组织教师 |
| `linxiangyu` | 林翔宇 | 学生 |
| `chenjiahe` | 陈嘉禾 | 学生 |
| `zhaoyiming` | 赵一鸣 | 学生 |
| `sunxiao` | 孙晓 | 学生 |

## 四、验证方式

```bash
python -m unittest discover -s tests -v
```

共 30 条断言，覆盖 TEST-01 ~ TEST-06 六条用例及"服务重启后数据仍存在"的完成依据。
每条用例使用独立的临时数据库，只通过 HTTP 接口访问系统。
详细结果见 `docs/04-验证报告.md`。

## 五、目录结构

```
campus-activity-system/
├── app/
│   ├── __init__.py          应用工厂
│   ├── extensions.py        db / login_manager 等扩展实例
│   ├── models.py            数据模型与业务状态定义
│   ├── seed.py              初始化活动分类
│   ├── decorators.py        角色权限装饰器
│   ├── services/            业务规则（活动、报名）
│   ├── auth/                注册 / 登录 / 登出
│   ├── activities/          活动发布、管理、浏览
│   ├── registrations/       报名、取消、报名名单
│   ├── templates/           Jinja2 模板
│   └── static/css/          样式
├── docs/                    需求分析、工程意图、设计、验证报告
├── tests/                   业务规则验证脚本
├── config.py
├── run.py
└── requirements.txt
```

## 六、文档索引

| 文档 | 内容 |
|---|---|
| `docs/01-需求分析.md` | 业务问题、用户目标、REQ-01~06、需求取舍 |
| `docs/02-工程意图.md` | 建设目的、本轮范围、重要约束、完成依据 |
| `docs/03-软件设计.md` | 总体结构、核心业务流程、数据设计、关键决策 |
| `docs/04-验证报告.md` | TEST-01~06 验证结果与缺陷修复记录 |

## 七、版本管理说明

项目从建立初期即纳入 Git 管理，按「模块逐步成形」的节奏提交，
每次提交对应一个可说明的增量。

按本次任务要求，代码**未推送到公网托管平台**，版本记录保存在工作目录的
本地仓库中；如需迁移到 Gitee / GitHub，只需执行：

```bash
git remote add origin <仓库地址>
git push -u origin main
```

## 八、安全约定

- 密码使用 Werkzeug 哈希存储，**任何位置不留明文**
- 密钥通过环境变量 `SECRET_KEY` 注入，仓库内只保留开发用默认值
- 不提交 `.env`、密钥文件与真实个人隐私数据
