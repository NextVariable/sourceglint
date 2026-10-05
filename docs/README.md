# Documentation

Start with the [English README](../README.md) or [中文说明](../README.zh-CN.md).
The [Skill entry point](../SKILL.md) describes what the host should do; the
[bridge protocol](../references/host-protocol.md) describes the interactive API.

For source problems, consult the [access matrix](source-access-matrix.md),
[fallback playbook](source-fallback-playbook.md) and [source details](sources/host-web-search.md).
The [live snapshot](source-live-status.json) is dated evidence, not a current probe.

For maintainers, [architecture](architecture.md) defines module ownership and
[validation](validation.md) explains reproducible checks and dated comparisons.
[Examples](examples/2026-10-04/README.md) show real recorded outputs and their limits.
[Design decisions](adr/README.md) record the accepted direction.

Earlier plans remain in the [archive](archive/README.md). Dated files in
`benchmarks/` and `reviews/` describe their own revisions; they are not fresh
certification of the current checkout. Do not mix counts across runs or compare
retrieval rows with synthesized findings. Private raw artifacts belong in ignored
`runs/`, while `evals/` contains reusable public case definitions.
