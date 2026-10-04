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

首次使用将有限的原生检索与宿主的搜索、推理结合，不要求先配置每个平台的 API Key。宿主按 [SKILL.md](SKILL.md) 操作 JSON-lines 接口。普通 Python 安装包包含引擎所需的配置、Schema 和提示词，但不会替你自动注册宿主 Skill；GitHub 发布不等于已上架 PyPI。

## 输出边界

报告展示原始平台、发布日期、证据摘录、实际检索目标和覆盖缺口。厂商发布信息与独立用户体验分开，反例不会因为没成为摘要结论而从证据摘录中消失。`SUCCESS` 表示流程产出了报告，`research_quality` 则明确研究质量尚未自动认证或存在有限样本。

公开来源能否访问会变化。目录中的 61 个来源是发现机会，不是 61 个已验证连接器。X、Product Hunt、Bluesky 和 Semantic Scholar 的直连需要凭证；网页搜索只能覆盖可索引内容。YouTube 可以尝试读取公开字幕，但字幕可能缺失或读取失败，不提供完整评论。Reddit 可补充公开存档正文与评论，但社区发现和日期覆盖仍有缺口。历史窗口比较尚未实现，不能把近期讨论写成增长趋势。

证据文件保留短摘录，并在实际取到正文时额外保留最多 12,000 字符的正文。历史复测发现 Reddit 日期采样集中、部分主题社区发现失败和结果相关性问题。[本轮检索修复](docs/reviews/2026-10-05-sampling-repair.md)增加了时间分段、日期多样性和社区描述校验；公开接口仍可能限流或失败，因此尚不能保证完整覆盖近 30 天。

真实样例和检查结果见 [最新复测](docs/benchmarks/2026-10-05-competitive-retest.md)。完整技术说明、开发方式和使用命令见 [英文 README](README.md)。许可为 [MIT](LICENSE)。
