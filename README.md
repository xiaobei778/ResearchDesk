# ResearchDesk · 开源科研工作台

本地运行、自选模型的中文科研与数学建模工作台。将资料、讨论、代码、计算结果、文稿和修改记录放在同一个项目里。

Local-first research and mathematical modeling workbench. Bring your own model API, review generated code, reproduce calculations, and export drafts.

**当前版本：0.3.0，公开测试版。** 适合个人本机使用；生成质量仍需人工审阅，不承诺论文录用、竞赛成绩或研究结论正确。

## 能做什么

- **自配 API**：支持 Chat Completions、Responses、Anthropic Messages 三种协议；规划、代码、写作、审稿可分别选择模型。第三方网关与本地模型需满足协议，参数兼容性需实测。
- **项目工作流**：40 个模板，覆盖科研探索、建模竞赛、已有资料成文、开题、综述、课程作业和技术交底；51 份可编辑步骤指导语。
- **材料和文献**：读取 PDF、DOCX、TXT、MD、CSV、JSON、BIB；通过 Crossref 查询候选文献元数据并记录来源。
- **实际计算**：生成 Python 代码，经用户审阅确认后运行，保存日志、指标与文件哈希。区分上传数据、仿真与演示。
- **文稿和图件**：Markdown 编辑预览，基础 Word/PDF 导出，SVG 流程图编辑和 PNG 导出。
- **过程管理**：步骤重做、修改提案确认、版本预览与恢复、冲突检查和项目打包。
- **本机问卷**：实际填答、CSV 导入/导出；没有线上互助或自动编造答卷。

## 快速开始

需要 Python 3.10+。优先在 Windows 上使用；其他平台的完整兼容性尚未验证。

从本仓库下载源码 ZIP 并解压，或使用 Git 克隆。打开项目目录的终端：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

浏览器打开 <http://127.0.0.1:18765/>。依赖安装后，也可双击 `启动科研工作台.bat`。

已有 Python 虚拟环境时，可以直接执行：

```bash
python -m pip install -r requirements.txt
python app.py
```

更换端口或不自动打开浏览器：

```bash
python app.py --port 18766 --no-browser
```

## 第一次使用

1. 先体验“本地零费用演示”：不调用模型，使用演示文字和实际运行的排队仿真。
2. 到“API 与模型”填写服务地址、协议、模型 ID 和自己的 API Key。保存配置不会调用模型。
3. 创建项目、上传题目和资料，再启动流程；模型请求会把相应项目材料发送到你配置的接口，费用取决于服务商。
4. 审阅阶段产物。代码须确认后执行；检查实际指标与日志，再推进写作和导出。
5. 对缺数据、失败或尚未运行的步骤补充材料或修改方案，不把演示结果当成实际研究结果。

## 数据与密钥

项目数据默认在 `data/`。关闭服务后备份整个目录，或通过 `--data-dir` 指定单独的数据目录：

```bash
python app.py --data-dir ./my-research-data
```

Windows 下优先使用当前用户的 DPAPI 加密保存 API Key；加密不可用时只在当前进程内存保留，重启后需重新填写。数据、备份、凭据与个人项目不属于本仓库发布内容。向他人分享项目包前，请自行检查其中的资料和执行记录。

## 已知限制

- 当前是本机单用户应用，仅监听 `127.0.0.1`；没有公网账户、团队租户隔离或支付系统。
- 代码运行于普通本机子进程，**不是系统级沙箱**。只有代码审阅和执行确认、超时等限制；请只执行自己理解并认可的代码。
- 文献检索返回候选元数据，不自动获取全文，也不能证明文献适用性。扫描 PDF 暂无 OCR。
- Word/PDF 为基础导出，复杂公式、表格和正式投稿版式需要进一步编辑；尚未集成完整 LaTeX 编译链或专业仿真求解器。
- 当前数值图是基础指标展示。自动化测试使用本地假 API 验证协议与流程，不能替代真实模型的科研质量评测。
- 不与第三方商业科研软件关联；不是其官方客户端，也不保证兼容其私有 Skill 或后台服务。

## 开发与测试

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

测试使用临时目录、本机假 API 和真实子进程计算，不需要付费模型 Key。

```text
researchdesk/    应用后端、模型适配、工作流与导出
static/          本地网页界面
catalog/         本应用的工作流配置
skills/          可编辑的科研步骤指导语
tests/           流程、协议、版本和数据处理测试
docs/            来源说明与第三方依赖信息
```

欢迎通过 Issues 提交可复现的问题，通过 Pull Requests 提交改进。请勿在公开 Issues 中粘贴 API Key、个人论文材料或未经许可的数据；参见 [贡献说明](CONTRIBUTING.md)。

## 许可与来源

采用 [MIT License](LICENSE)，允许依条款使用、修改、分发和商业化，须保留版权与许可声明。第三方依赖、模型服务和数据有各自条款，见 [依赖说明](docs/THIRD_PARTY.md)。应用的实现与公开内容边界见 [来源说明](docs/PROVENANCE.md)。
