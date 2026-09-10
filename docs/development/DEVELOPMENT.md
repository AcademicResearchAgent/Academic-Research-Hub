# 团队开发指南

## 1. 准备源码

```powershell
python scripts/prepare_sources.py
python scripts/prepare_sources.py --check
```

准备脚本读取 `sources.lock.json`，首次拉取上游，切到精确提交后应用 `patches/`。再次执行不会清除已有修改；遇到不同版本且目录有修改时会停止。上游默认检出为 detached HEAD，可自行创建功能分支。主仓库忽略 `reference/`，跨同事传递的改动必须导出到 `patches/`，不能只留在参考目录。

UI 使用 Svelte 5 + TypeScript，服务端为 Python；引擎也为 Python。开发前请先看实际架构。

## 2. 修改产品配置

修改 `configs/workstation/research-copy.json` 和 `configs/workstation/SOUL.md`。不要在旧 `deploy/hermes/` 路径创建第二份配置。远端脚本仍读取 `research-copy.json` 与 `research-SOUL.md`，由打包脚本映射名称：

```powershell
python scripts/package_deploy.py
```

产物位于 `.build/deploy/`，包含清单及必要脚本，不含服务器凭据，也不会自动上传。SOUL 对应 Agent 身份，模型设置里的每请求身份规则由 `apply-workstation-identity.py` 同步。

## 3. 开发界面和后端

源码入口是 `reference/open-webui/src` 与 `backend/open_webui`。建议在 WSL2 / Linux 的独立工作副本中开发；使用 Node.js 22、Python 3.11。不要在生产容器里编辑源文件。

先按上游 `backend/requirements.txt` 安装独立 Python 环境，配置自己的开发数据目录和模型接口，然后启动后端。以下命令在仓库根目录的 Bash 中执行：

```bash
python3.11 -m venv .local/webui-venv
.local/webui-venv/bin/pip install -r reference/open-webui/backend/requirements.txt
mkdir -p .local/webui-data
export DATA_DIR="$PWD/.local/webui-data"
export WEBUI_NAME='科研智能体工作站'
export CORS_ALLOW_ORIGIN='http://localhost:5173'
# OPENAI_API_BASE_URL / OPENAI_API_KEY 使用独立开发接口，通过环境变量配置。
# 首次开发可保持默认初始化流程，在自己的本地数据库建立管理员。
cd reference/open-webui/backend
../../../.local/webui-venv/bin/uvicorn open_webui.main:app --host 127.0.0.1 --port 8080 --reload
```

另开终端启动前端：

```bash
cd reference/open-webui
npm ci --force
npm run dev -- --host 127.0.0.1
```

上游 `npm run dev` 自带 `--host`，追加本地绑定参数用于本机开发。模型连接及其他设置在本地管理页配置，不沿用生产 `access.json` 或数据库。首次安装需下载依赖和 Pyodide；以上为根据锁定源码提供的启动步骤，本次未执行完整依赖安装与双服务启动验收。

完整 UI 镜像可使用上游 Dockerfile 构建（需要 Docker、联网和足够的构建内存）：

```bash
docker build --build-arg USE_SLIM=true --build-arg BUILD_HASH=0a7c15832fb30b1903753e83f81dc7d27e5b0944 -t haudi-workstation-ui:dev -f reference/open-webui/Dockerfile reference/open-webui
```

构建后先在独立端口和数据目录验收登录、中文界面、身份介绍和真实聊天，再制定切换计划。本次没有把未经完整构建验证的镜像上线。

## 4. 保存并提交源码定制

现有补丁可从产品配置重新生成：

```powershell
python scripts/render_product_patches.py
```

该命令只生成补丁，不修改检出目录。它从锁定上游文件读取基线；如果你要新增页面逻辑，需要相应扩展生成脚本，或手工维护补丁。不要在存在未导出的功能改动时直接覆盖补丁。修改配置后，先用旧补丁反向还原对应检出，再生成和应用新补丁；先检查 `git diff` 并保存自己的其他修改，禁止用 `reset --hard` 清理同事的改动。

手工维护模式可从项目根目录导出相对于锁定 HEAD 的全部已跟踪修改，避免 PowerShell 重定向改变 UTF-8 编码：

```powershell
git -C reference/open-webui diff --binary --output=../../patches/open-webui/0001-workstation-copy.patch HEAD
git -C reference/hermes-agent diff --binary --output=../../patches/hermes-agent/0001-workstation-identity.patch HEAD
```

新文件先 `git add -N <path>` 以纳入 diff；不要混入凭据、运行数据或依赖目录。手工补丁与生成脚本同时存在时，要同步生成逻辑，防止后续生成丢失功能修改。审查主仓库的配置、补丁和脚本，再交给同事执行准备命令复现。

## 5. 引擎开发

使用独立 `HERMES_HOME`、工作目录、模型密钥和端口。按固定源码的 `pyproject.toml` / `uv.lock` 安装；工具逻辑在 `tools/`，提示组装在 `agent/`，API 会话在 `gateway/`。生产身份补丁只去掉默认品牌介绍，未重命名 Python 包、API 模型 ID 或工具标识。

论文检索业务建议从一个数据库适配器、统一题录结构及获取证据开始，写有真实失败情形的测试，再接入 Agent 工具。不把检索提示词扩写等同于检索服务实现。

## 6. 当前生产维护入口

现有 SSH 工具 `deploy/hermes/remote.py`、`upload.py` 绑定了维护者本机的 Windows SSH 程序及 `haudi-hermes-server` 别名，新同事需要管理员授权自己的 SSH 公钥。不要复制维护者私钥。这些是现有服务器维护工具，不是通用新机安装器。

| 动作 | 现有脚本 |
| --- | --- |
| 更新产品设置及科研身份 | `configure-research-copy.py` |
| 更新默认介绍及每请求身份规则 | `apply-workstation-identity.py`、`deploy-workstation-identity.sh` |
| 当前生产 UI 的编译产物补丁构建 | `build-research-copy.py` |
| 切换现有 UI 镜像 | `deploy-research-copy.sh`，自动保存时间戳回退容器；仍绑定当前服务器路径 |
| 安装和配置文档检索 | `install-retrieval-model.py`、`configure-retrieval.py`，步骤见附件修复记录 |
| 配置及聊天验证 | `verify-research-copy.sh`、`verify-workstation-identity.sh` |
| 论文能力探测 | `probe-*.sh`，部分会调用付费模型 |
| 历史排障 | `inspect-*`、`check-*`、`fix-*` 等，逐个阅读，不批量执行 |

`bootstrap`、公开端口、批量账号录入、下载管理员凭据等脚本属于有独立前提的一次性操作，不应作为新同事入门命令。开发仓库不保存生产密钥、账号库和材料。

## 7. 合并与验收

团队远程仓库为 `https://github.com/AcademicResearchAgent/Academic-Research-Hub`，目前尚未建立 CI。使用功能分支提交 PR，不将私有材料加入版本管理。提交前至少运行源码校验和部署打包；UI 逻辑改动还需上游类型检查、完整构建和浏览器验收，Agent 工具改动需对应行为测试。源码补丁能应用不等于产品功能已经全部验收。

本次已验证固定提交及补丁的重复应用、部署材料打包、Python 语法和中文 JSON，并单独编译通过 4 个修改的 Svelte 组件。轻量前端验证可复现为：

```powershell
npm install --prefix .build/source-check --ignore-scripts --no-audit --no-fund svelte@5.53.10
node scripts/check_source_patches.mjs
```

此检查不解析整个应用的依赖图，也不替代 TypeScript 检查和完整构建。

上游许可和版权文件随源码保留。当前 UI 品牌修改按现有小规模部署例外处理；扩大终端用户规模时需重新核对许可条件，不能把移除产品标识当作变更软件著作权。
