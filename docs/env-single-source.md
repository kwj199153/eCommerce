# 环境单一真源（r388）

> 一句话：**本仓的 Python 只有一份 —— `backend/.venv`（3.12）。**
> 任何启动器、脚本、文档里出现的第二个解释器都是缺陷，不是选择。

---

## 1. 为什么必须统一（不是洁癖，是三件已经发生的事）

### 1.1 本地服务跑 3.11，CI 和线上跑 3.12

| 位置 | Python | 出处 |
|---|---|---|
| `backend/Dockerfile` | **3.12** | `FROM python:3.12-slim` |
| `.github/workflows/ci.yml` | **3.12** | `PYTHON_VERSION: "3.12"` |
| `backend/.venv` | **3.12.14** | `pyvenv.cfg`（uv 建） |
| `start-backend.bat` / `start-celery.bat`（改前） | **3.11.15** | `D:\work\anaconda\anaconda3\envs\reactAgents\python.exe` |

差一个 minor，症状不是崩，而是「**测试全绿、线上炸**」或「**服务能起、测试全红**」，
且两边都不像自己改坏的。本仓已有一次真实代价：r354 之前所有 pytest 都跑在
conda 3.11 上，而线上是 3.12。

### 1.2 生成器与产物已经 drift（这条比上面更狠）

`start-celery.bat` 是 `gen-start-celery-bat.py` 生成的。但 P0-2 日志治理
（`LOG_SINK_ROLE`，让 worker / beat 各写自己的文件）当时是**手工**改进 bat 的，
**没有回写生成器**。

⇒ 任何人跑一次 `python gen-start-celery-bat.py`，就会把 P0-2 的修复连同
「为什么 loguru 不是多进程安全」的 5 行实测记录（两份 gz 解压 md5 全等、
均 738,001 行）一起**静默抹掉**，且 git diff 看起来只是「重新生成了一下」。

r388 已把这段回写进真源，并加了双向同源门禁（见 §3 I2）。

### 1.3 有脚本借了第四套解释器

`backend/scripts/probe_248_inject.py` 曾写死
`C:\Users\...\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
—— 那套是工具链自带的，不是本仓的。探针跑在哪个环境取决于「谁先装的」。

---

## 2. 「是否所有项目都用这个环境？」——不是，也不该是

实测本机（`D:\ai` 下）：

| 项目 | Python 环境 | 说明 |
|---|---|---|
| **eCommerce** | `backend/.venv`（uv / 3.12.14） | **本文档的对象** |
| stable-diffusion-webui | `venv/` | 自带，与训练栈绑定 |
| 其余（eCore / eEducation / selection-translator / 创业指挥官 / 合规风控安全员 / 空间助理 / 经营 / 网站管理员 / 项目审查员 …） | 无 Python venv | 纯 Node / 静态站 |

conda 下另有 7 个环境：`chapter2`、`chapter4`、`fastapi`、`graphrag`、
`langsmith-notebook`、`pytorch`、`reactAgents` —— 这些是**教程/早期项目**的，
`reactAgents` 当年被拿来当 eCommerce 的运行环境，属于历史借用。

**结论（这是要记住的判断）**：

- 「所有项目共用一个环境」是**反模式**。两个项目要 `pydantic` 的不同大版本时，
  谁后装谁赢，另一项目静默半坏。
- 正确模型是 **一仓一 venv**，跨项目共享只共享「解释器版本号」这一个事实，
  不共享 site-packages。
- 所以本次统一**只统本仓**：eCommerce 的所有入口指向 `backend/.venv`。
  conda 里那 7 个环境不碰 —— 它们服务别的项目。

### 2.1 历史探针（`.workbuddy/probes/`）怎么处置

那里有二十几个 2026 年早期的探针，写死了 `reactAgents` 或 `.workbuddy/binaries`
的解释器。**不改**——它们记录的是当年那次执行的客观环境，改了等于篡改证据；
而且 `.workbuddy/` 是 gitignored，不进仓、不参与门禁。

但要记住一条：**重跑历史探针会用错环境**。要复用其中某段逻辑，先把它抄进新探针
并把解释器改成 `sys.executable` 或 `backend/.venv`，别原地跑。

---

## 3. 单一真源的不变式（已门禁化）

门禁文件：`backend/tests/test_env_single_source.py`（6 条，反向注入 6/6）。

| 编号 | 不变式 | 抓住什么回退 |
|---|---|---|
| **I0** | 仓根启动器清单必须精确等于已知集合 | 新增 `.bat` 却没人确认它用哪个解释器 |
| **I1** | 每个 `set "PY=..."` 必须**精确**等于 `%~dp0backend\.venv\Scripts\python.exe` | 写回 conda 路径、写死盘符 |
| **I2** | 生成器 TEXT 与产物 bat 的关键行**双向**一致 | ①只改 bat（drift）②只改生成器（产物过期） |
| **I2b** | `LOG_SINK_ROLE=worker/beat` 必须两边都在 | P0-2 日志治理回归 |
| **I3** | `backend/scripts/*.py` 不得出现外部解释器绝对路径 | 借 `.workbuddy` / `anaconda` 的解释器 |
| **I4** | Node 大版本在 `.nvmrc` / `engines` / `Dockerfile` / `ci.yml` 四处一致 | Node 悄悄漂到 24（本地过、CI 挂） |

### 3.1 Node 这半的状态

| 位置 | 版本 | 声明方式 |
|---|---|---|
| `frontend/.nvmrc` | **22** | r388 新增 |
| `frontend/package.json` `engines.node` | `>=22.0.0 <23` | r388 新增 |
| `frontend/Dockerfile` | `node:22-alpine` | 原有 |
| `.github/workflows/ci.yml` | `NODE_VERSION: "22"` | 原有 |
| 本机 `node -v` | 22.22.2 | — |

改前这四处**事实上**一致，但**没有一处**是声明式的 —— 换台机器、换个 nvm 档位就会漂，
而漂了只表现为「本地 build 过、CI build 挂」（或反过来），归因成本极高。


判据形态的讲究（都是踩过的）：

- **走 AST 取 `TEXT` 常量**，不扫生成器源码：源码里反斜杠是双写的（`\\.venv`），
  扫源码永远和产物对不上，会得到「假失配 → 人肉改坏」。
- **锚定正则 `^set "PY=`**，不用「文件里含 anaconda」：注释里**必须**能写
  「为什么不用 conda」，字符串判据会把这段解释判成违规（本仓 r374 M8 同款陷阱）。
- **I0 用精确集合而不是 `len > 0`**：一个都没匹配到时 I1 是**全绿**的，
  「> 0」防得住空跑，防不住「少扫了」。

用 `%~dp0` 而不是绝对路径的理由：`%~dp0` 是「本文件所在目录」，换盘、换用户名、
clone 到另一台机器都不用改；绝对路径则把「这台机器」焊进了仓库。

---

## 4. 怎么重建 `backend/.venv`（换机 / 删坏了）

```bat
cd /d D:\ai\eCommerce
uv venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

装完先跑自检（等于把「启动 / Celery / 测试」三件事各验一遍）：

```bat
cd backend
.venv\Scripts\python.exe ..\.workbuddy\probes\env_unify_probe.py
```

期望末行：`RESULT: PASS  venv 足以承担 启动/Celery/测试 三件事`
（其中 `openapi paths=240`；`app.routes` 只有 38 是正常的 —— FastAPI 0.141+
把 `include_router` 改成了懒展开的 `_IncludedRouter` 句柄，详见
`backend/requirements.txt` 里那段版本上界注释。）

---

## 5. 怎么确认「服务跑的是我改的代码」

`GET /health` 返回 200 **不能**证明这一点 —— 旧进程占着 8000 端口时，
新进程（`run_dev.py`）会打印一行然后**主动不启动**（防 Windows 幽灵双绑），
而 `/health` 一直由旧进程答。

判据要用「只有新代码才会出现的东西」：

```bat
curl -s localhost:8000/openapi.json | findstr /C:"onboarding"
```

r387 起应有命中（`/api/v1/onboarding/sample-data`）。0 命中 ⇒ 跑的是旧代码，
`taskkill /PID <pid> /T /F`（**必须带 `/T`**，reload 是父→reloader→worker 三层）。
