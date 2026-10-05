# Sourceglint

**找到近期信息，也保留判断它的依据。**

输入一个主题，研究最近约 30 天出现的工具、实际做法、讨论和用户反馈，保留原始日期、链接与可复用的证据文件。只有明确要求时才补充产品或 GTM 建议。

[English](README.md) · [真实样例](docs/examples/2026-10-04/README.md) · [来源与权限](docs/source-access-matrix.md) · [验证记录](docs/validation.md) · [参与开发](CONTRIBUTING.md)

## 使用

告诉你的 Agent：

> 用 Sourceglint 研究最近 30 天 Claude Code 的实际工作流、新工具、用户抱怨和反例。保留原文链接、日期，给我可继续分析的证据文件。

报告区分来源中的观察、模型推断和覆盖缺口。证据文件保留来源 ID、原始链接、发表日期和原文节选。厂商发布内容不会自动变成独立用户体验，一条讨论也不会被包装成市场趋势。可以先查看[实际报告](docs/examples/2026-10-04/discovery.md)。

## 安装

需要 Python 3.10+，以及支持网页搜索、推理和交互式终端的宿主 Agent。Codex 可以安装到尚未占用的 Skill 目录：

```sh
git clone https://github.com/NextVariable/sourceglint.git ~/.codex/skills/sourceglint
cd ~/.codex/skills/sourceglint
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m sourceglint doctor
```

随后让宿主使用 Sourceglint。必须保留完整仓库，单独复制 `SKILL.md` 无法运行。Windows 使用 `.venv\Scripts\python.exe`。其他宿主需要相同的交互能力，尚未逐个验证兼容性。`doctor` 只检查本地准备情况，不证明平台当下可访问。

## 能力与边界

默认把 GitHub、Reddit、Hacker News 和 YouTube 的有限原生检索，与宿主的公开网页搜索结合。无需先配齐各平台密钥；宿主模型和工具的费用、额度由使用者承担。项目不提供模型账号，也不是无人值守的监控服务。

GitHub 可以读取仓库、问题及有独立日期的评论；HN 可以读取文章和评论；Reddit 可以补充公开存档正文及评论；YouTube 尝试读取公开字幕，不下载媒体。限流、存档缺失、语言覆盖与主题相关性仍会影响结果。来源目录是路由提示，不能当成全部已跑通的连接器。详见[访问矩阵](docs/source-access-matrix.md)与[降级说明](docs/source-fallback-playbook.md)。

`SUCCESS` 只表示生成了报告，不认证完整性或研究质量。无法核实日期的材料会被过滤，缺少的渠道和未回答的问题应当保留。历史窗口比较尚未实现，因此不能把近期讨论写成增长趋势。定时监控不属于默认范围。

证据文件保留短摘录，实际取得正文时另保留最多 12,000 字符的原文节选并标注省略。伴随的 `.raw.jsonl` 保存筛选前材料，不等于已验证结论。浏览器 Cookie 导入及付费来源需要授权。详细运行方式见[英文说明](README.md#how-it-works)和[宿主协议](references/host-protocol.md)。

## 项目状态


[验证入口](docs/validation.md)集中记录主题矩阵、真实竞品比较、修复与安装检查，保留每次测试的版本和限制。自动化测试、安装成功、真实检索和最终报告质量分别验收。[目录与架构](docs/architecture.md)说明文件职责，[文档导航](docs/README.md)区分当前用法和历史档案。普通 wheel 安装引擎，不自动注册宿主 Skill；GitHub 发布也不等于上架 PyPI。许可为 [MIT](LICENSE)。
