# Sourceglint

**近30天跨平台信息研究 Skill。**

[English](README.md) · [真实样例](docs/examples/2026-10-04/README.md) · [文档导航](docs/README.md)

信息散在社交平台、社区、官网和论文里，同一个热点反复出现，旧讨论混进搜索结果，有价值的新工具、需求和反馈却容易被漏掉。Sourceglint 帮助产品经理、GTM 和科技学习者围绕一个问题，了解近期发生了什么、大家在讨论什么，以及哪些信息值得继续研究。

输入一个主题或问题，它会回溯最近30天，通过可用渠道搜集信息、合并重复内容，整理成带日期和原始链接的报告，并提供可以继续交给 AI 分析的证据文件。需要产品判断或 GTM 行动建议时，在问题中明确提出。

## 可以研究什么

| 用途 | 示例问题 |
| --- | --- |
| 产品需求与反馈 | AI 会议助手的用户最近在夸什么、抱怨什么？有哪些反复出现的需求？ |
| 市场与竞品研究 | 最近日本 AI 会议助手市场有哪些竞品和变化？日本用户在讨论什么？ |
| 科技学习 | 最近 AI 视频领域出现了哪些新工具、技术进展和实际玩法？ |

安装后，直接告诉智能体：

> 用 Sourceglint 研究最近30天 AI 视频领域的新工具和用户反馈，保留日期、原始链接和反例。

## 安装

需要 Python 3.10+，以及支持网页搜索、推理和交互式终端的智能体。以 Codex 为例，在尚未占用的技能目录中安装：

```sh
git clone https://github.com/NextVariable/sourceglint-skill.git ~/.codex/skills/sourceglint
cd ~/.codex/skills/sourceglint
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m sourceglint doctor
```

然后让智能体使用 Sourceglint。请保留完整仓库，单独复制 `SKILL.md` 无法运行。Windows 请使用 `.venv\Scripts\python.exe`。检查命令确认本地配置是否就绪，来源当下是否可访问则以实际研究为准。

## 输出与覆盖范围

你会得到带来源的报告，以及保存链接、日期和原文节选的证据文件。报告区分厂商陈述、用户体验与推断，保留反例，并说明未访问到的来源或材料不足的地方。

默认结合 GitHub、Reddit、Hacker News、YouTube 的公开检索与智能体网页搜索，并在可用时尝试补充讨论、评论或字幕。无需先配齐各平台密钥，智能体自身的工具费用和额度由使用者承担。

检索是有限采样，覆盖受访问权限、限流、语言和主题影响。报告生成成功不代表信息已全部覆盖，也不能直接证明市场需求。目前不支持历史窗口增长比较，不提供默认的定时监控。

## 进一步了解

- [真实研究样例](docs/examples/2026-10-04/README.md)
- [来源访问](docs/source-access-matrix.md)与[降级方式](docs/source-fallback-playbook.md)
- [智能体集成与证据导出](references/host-protocol.md)
- [验证记录](docs/validation.md)
- [仓库目录说明](docs/repository-guide.md)与[参与开发](CONTRIBUTING.md)

采用 [MIT 许可](LICENSE)。
