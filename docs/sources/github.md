# GitHub

The default runtime searches newly created repositories and GitHub issues/PRs,
then retrieves bounded comment samples. It also searches recently active older
issues and retains only comments whose own publication dates are in the window.

Repository creation is page metadata, not a release. Issue/PR bodies and comments
are community claims (T2), even though the transport is GitHub's official API.
Every comment preserves its `#issuecomment-ID` URL and its own `created_at`.
`updated_at` helps discover activity; it never replaces a publication date.

The connector uses documented REST endpoints: `/search/repositories`,
`/search/issues` and `/repos/{owner}/{repo}/issues/{number}/comments`. Issue and PR
searches are partitioned explicitly. An exact repository-name match is resolved when available, and returned URLs
are checked against that repository scope. Subject presence is checked against returned
material; query intent influences which candidates receive the comment budget.

Per query: up to 20 repositories, 20 issue/PR bodies, five newly created threads
and five older threads enriched with up to five comments each. Comment retrieval
uses the last page, so old threads do not spend their budget on their oldest
replies. This is a sample, not complete thread coverage. Partial enrichment is
reported without throwing away usable parent evidence.

The runtime uses `GITHUB_TOKEN` or existing `gh auth token --hostname github.com`
authentication, otherwise the anonymous API tier. The adapter receives the token
through constructor injection and never logs or persists it. Search limits differ
from ordinary REST rate limits; upstream throttling remains a real limitation.

`GitHubAdapter()` keeps its repository-only low-level default for compatibility;
`default_adapter_factory` enables discussion retrieval for actual Skill runs.
Releases, review comments on PR diffs and repository content crawling are not
implemented by this connector.
