# Sourceglint

输入一个主题，发现近期出现的工具、讨论、需求和用户反馈，保留日期、原始链接和证据摘录。默认回溯约 30 天；只有明确要求时才补产品或 GTM 判断。

这是一个由宿主 Agent 操作的早期研究 Skill。宿主需要具备网页搜索、推理和交互式终端能力。模型账号、宿主用量和平台凭证由使用者自己提供，项目不提供代查账号，也不是无人值守的信息监控服务。

## 安装

```sh
git clone https://github.com/NextVariable/sourceglint.git
cd sourceglint
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

需要 Python 3.10 或以上。保留完整目录，按宿主支持的方式将其作为 Skill 加载；例如 Codex 可以使用 `~/.codex/skills/sourceglint`。随后告诉宿主：“使用这里的 Sourceglint，研究过去 30 天的某个主题。”

首次使用复用宿主的搜索和推理，不要求先配置每个平台的 API Key。宿主按 [SKILL.md](SKILL.md) 操作 JSON-lines 接口。普通 Python 安装包包含引擎所需的配置、Schema 和提示词，但不会替你自动注册宿主 Skill；GitHub 发布不等于已上架 PyPI。

## 输出边界

报告展示原始平台、发布日期、证据摘录、实际检索目标和覆盖缺口。厂商发布信息与独立用户体验分开，反例不会因为没成为摘要结论而从证据摘录中消失。`SUCCESS` 表示流程产出了报告，`research_quality` 则明确研究质量尚未自动认证或存在有限样本。

公开来源能否访问会变化。目录中的 61 个来源是发现机会，不是 61 个已验证连接器。X、Product Hunt、Bluesky 和 Semantic Scholar 的直连需要凭证；网页搜索只能覆盖可索引内容。YouTube 元数据不等于完整字幕或评论，Reddit RSS 不提供完整评论深度。历史窗口比较尚未实现，不能把近期讨论写成增长趋势。

真实样例和检查结果见 [验收记录](docs/phase7-evaluation.md)。完整技术说明、开发方式和使用命令见 [英文 README](README.md)。许可为 [MIT](LICENSE)。
