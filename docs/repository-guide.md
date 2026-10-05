# 仓库目录说明 · Repository guide

使用者从 [README](../README.md) 或[中文说明](../README.zh-CN.md)开始。GitHub 按路径展示文件，以下按用途解释目录。

| 用途 / Purpose | 位置 / Location |
| --- | --- |
| 使用与安装 / Getting started | `README.md`、`README.zh-CN.md` |
| 智能体接入 / Agent integration | `SKILL.md`、`agents/`、`references/` |
| 运行代码 / Runtime code | `src/` |
| 配置与数据契约 / Configuration and contracts | `config/`、`schemas/` |
| 示例与说明 / Examples and documentation | `docs/` |
| 测试、评测与检查 / Tests, evaluations and checks | `tests/`、`evals/`、`scripts/`、`.github/workflows/` |
| 打包 / Packaging | `pyproject.toml`、`setup.py`、`MANIFEST.in` |
| 贡献、版本与许可 / Contributions, changes and license | `CONTRIBUTING.md`、`CHANGELOG.md`、`LICENSE` |

详细职责见[架构说明](architecture.md)。本地研究输出放在被忽略的 `runs/`，使用者无需逐个浏览工程目录。

See [architecture](architecture.md) for detailed ownership. Local research outputs belong in ignored `runs/`; users do not need to browse every implementation directory.
