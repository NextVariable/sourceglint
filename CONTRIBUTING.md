# 参与开发 · Contributing

需要 Python 3.10+。安装开发依赖后，运行离线测试、代码检查和仓库检查：

Use Python 3.10+. Install development dependencies, then run the offline suite,
linter and repository checks:

```sh
python -m pip install -e '.[dev]'
python -m pytest tests -q
python -m ruff check src scripts
python scripts/check_repository.py
```

CI 在 Python 3.10 和 3.13 上执行这些检查，并验证独立安装的 wheel。修改打包或资源加载时，构建 wheel，在独立环境安装后从仓库外运行 `scripts/check_installed_runtime.py`；配置和数据结构只维护在 `config/` 与 `schemas/`，不要手动修改生成副本。

CI runs these checks on Python 3.10 and 3.13 and tests a separately installed wheel.
For packaging or resource-loading changes, build a wheel, install it in a separate
environment and run `scripts/check_installed_runtime.py` outside the checkout.
Maintain configuration and schemas in `config/` and `schemas/`, never generated copies.

修改来源连接器时，核对查询相关性、发表日期、时间窗口、错误处理和结果映射。`RUN_LIVE_TESTS=1 python -m pytest tests/live -q` 会发出真实网络请求；没有凭据而跳过的测试不算访问成功。研究逻辑修改须保留原文依据、引用链和反例；固定样本测试通过不代表实际研究质量合格。

For connector changes, verify relevance, publication dates, time windows, error
handling and normalization. `RUN_LIVE_TESTS=1 python -m pytest tests/live -q` makes
real upstream requests; missing-credential skips are not successful access.
Research changes must preserve excerpts, citation chains and counterexamples.
Fixture tests do not establish live research quality.

问题报告应提供查询、版本、智能体能力、研究截止日期、来源状态，以及实际和预期结果。提交前移除凭据与私人信息；原始研究文件放在被忽略的 `runs/`。发布审查还应执行 `python scripts/check_repository.py --history`，检查旧文件和提交身份；只清理当前文件不能清除 Git 历史中的内容。

Bug reports should include the query, version, host capabilities, cutoff date,
source status and observed versus expected behavior. Remove secrets and private
information. Keep raw research in ignored `runs/`. Release reviews should also
run `python scripts/check_repository.py --history` to inspect old files and commit
identities; cleaning current files does not remove data from Git history.

入口和目录职责见[架构说明](docs/architecture.md)。技能入口保持简短，详细交互约定放在 `references/`。

See [architecture](docs/architecture.md) for entry points and ownership. Keep Skill
instructions concise and bridge details in `references/`.

对比评测应记录版本、问题、截止日期、智能体能力、凭据配置、检索预算、失败状态与最终结果。比较实际发现，不能只比较检索数量；等待智能体回复的时间不等于运行时延迟，环境证书问题也不等于对手缺陷。公开短摘录、链接和评测元数据，完整第三方内容保留在本地。

Comparisons must record versions, queries, cutoffs, host capabilities, credential
profiles, retrieval budgets, failures and final outcomes. Compare findings as well
as counts. Bridge waiting is not engine latency; environment certificate failures
are not competitor defects. Publish short linked excerpts and evaluation metadata;
keep complete third-party source bodies local.
