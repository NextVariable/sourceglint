# 验证 · Validation

离线测试、独立安装、真实来源访问和实际报告质量分别验收。自动测试通过不代表检索完整，也不代表每个平台当前可访问。

Offline tests, independent installation, live source access and report quality
are separate acceptance levels. Passing tests does not certify complete retrieval
or current access to every platform.

## 本地检查 · Local checks

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check src scripts
.venv/bin/python scripts/check_repository.py
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pip wheel --no-deps . --wheel-dir dist
```

将 wheel 安装到独立环境，从仓库外运行 `scripts/check_installed_runtime.py`，检查安装资源和公开接口。`scripts/verify_first_install.sh` 检查已提交文件的独立安装。

Install the wheel in a separate environment and run
`scripts/check_installed_runtime.py` outside the checkout to check resources and
the public API. `scripts/verify_first_install.sh` checks an export of committed files.

## 实际研究 · Research checks

`RUN_LIVE_TESTS=1` 启用真实网络测试；没有凭据而跳过的项目不算成功访问。可复用的问题保存在 [evals](../evals/retrieval-matrix.json)。实际研究须记录问题、版本、截止日期、来源状态和最终报告，核对相关性、日期、原文依据与反例，并说明缺失的来源和未回答的问题。

`RUN_LIVE_TESTS=1` enables real upstream requests; missing-credential skips are
not successful access. Reusable questions are in
[evals](../evals/retrieval-matrix.json). Record the query, version, cutoff, source
status and final report. Review relevance, dates, source support and
counterexamples, and disclose unavailable sources and unanswered aspects.

## 发布文件 · Distribution checks

执行 `python scripts/check_repository.py --history` 检查当前文件、链接、可达历史与提交身份。运行数据保存在被忽略的 `runs/`，不进入源码包；分享证据文件前应人工检查私人内容和第三方正文。

Run `python scripts/check_repository.py --history` to check files, links, reachable
history and commit identities. Keep run data in ignored `runs/`, outside source
distributions. Review private content and third-party source bodies before sharing
evidence exports.
