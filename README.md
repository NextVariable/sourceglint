# Sourceglint

**把最近 30 天的信息，变成有出处、可继续研究的材料。**

用一个主题，发现近期的新工具、实际工作流、讨论和用户反馈。每条发现保留原始链接与发表日期，报告区分来源陈述、推断和未找到的内容，并提供可复用的证据文件。

[查看真实样例](docs/examples/2026-10-04/discovery.md) · [来源与访问方式](docs/source-access-matrix.md) · [使用协议](references/host-protocol.md)

[![自动检查](https://github.com/NextVariable/sourceglint/actions/workflows/tests.yml/badge.svg)](https://github.com/NextVariable/sourceglint/actions/workflows/tests.yml)
[![MIT 开源许可](https://img.shields.io/badge/许可-MIT-blue.svg)](LICENSE)

## 这样使用

安装后，直接告诉你的智能体：

> 用 Sourceglint 研究最近 30 天 Claude Code 的实际工作流、新工具、用户抱怨和反例。保留原始链接、日期，给我可继续分析的证据文件。

也可以研究某个产品、技术或消费主题。需要产品判断或行动建议时，在问题中明确说明；默认先整理信息和依据。

你会得到一份带来源的报告，以及保存来源标识、链接、日期和原文节选的证据文件。材料不足时，报告会说明缺口；厂商宣传与用户体验会分别呈现，同一条讨论中的多次回复也不会被当作多个独立用户。

## 安装

需要 Python 3.10+，以及支持网页搜索、推理和交互式终端的智能体。以 Codex 为例，在尚未占用的技能目录中安装：

```sh
git clone https://github.com/NextVariable/sourceglint.git ~/.codex/skills/sourceglint
cd ~/.codex/skills/sourceglint
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m sourceglint doctor
```

然后让智能体使用 Sourceglint。请保留完整仓库，单独复制 `SKILL.md` 无法运行。Windows 请将 Python 路径换为 `.venv\Scripts\python.exe`。检查命令确认本地配置是否就绪；平台当下是否可访问，以实际研究结果为准。

## 运行与导出

一般由智能体启动并回答检索、推理请求。手动集成时可以使用：

```sh
.venv/bin/python -m sourceglint 'Claude Code 工作流' \
  --model sourceglint.host_stdio:build_model \
  --host-sources-stdio --registry config/sources-hybrid.yaml \
  --ledger runs/my-research/evidence.jsonl --json
```

该命令需要智能体参与，会等待搜索和推理响应。每次研究使用新的证据路径；添加 `--decision-support` 可启用明确要求的决策建议。其他智能体的接入方式见[交互协议](references/host-protocol.md)，兼容性需要按其工具能力验证。

## 能找到什么

默认结合 GitHub、Reddit、Hacker News、YouTube 的公开检索与智能体的网页搜索。GitHub 和 Hacker News 可读取讨论及评论；Reddit 会尝试补充公开存档内容；YouTube 会尝试读取公开字幕。无需先配齐所有平台密钥，智能体自身的工具费用和额度由使用者承担。

检索是有限采样，限流、存档缺失、语言和主题都会影响覆盖。无法核实发表日期的材料会被排除，未访问到的来源会明确标注。目前不支持历史窗口增长比较，也不提供默认的定时监控。报告生成成功不代表信息已全部覆盖。

导出的证据保留短摘录及最多 12,000 字符的正文节选，省略内容会标明。伴随的 `.raw.jsonl` 文件包含筛选前材料，分享前请检查其中是否有私人内容。更多来源选择见[访问说明](docs/source-access-matrix.md)和[降级说明](docs/source-fallback-playbook.md)。

## 进一步了解

[文档导航](docs/README.md) · [验证记录](docs/validation.md) · [架构说明](docs/architecture.md) · [参与开发](CONTRIBUTING.md)

采用 [MIT 许可](LICENSE)。
