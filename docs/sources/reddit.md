# Reddit

The default runtime discovers public posts through RSS and uses the public
Arctic Shift archive to supplement body text, engagement observations and dated
comments. Optional `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` enable the official
OAuth search route. No browser cookies, login automation or paid services are
needed for the default route.

Archive endpoints are `/api/posts/search` and `/api/comments/search`. Communities
come from explicit request targets, observed relevant posts and a bounded subject
name guess. Discovery samples at most three communities; it cannot guarantee that
an arbitrary subject's best communities have been found. Posts are ranked against
research intent before at most five threads receive a five-comment budget.

Each comment has its own original Reddit permalink, author, body and creation
time. Deleted bodies and moderator boilerplate are excluded. Archive observations
are labeled in raw metadata; they are not current live Reddit measurements or
independent corroboration. An archived body may lag edits or removals. The API has
no uptime guarantee. RSS and archive failures remain visible in coverage warnings.

A relevant RSS item survives archive failure. Unrelated or out-of-window feed
entries receive no enrichment budget. Returned bodies are retained in the raw
export; analysis sees bounded content, while quoted snippets remain capped at
280 characters. The archive is one retrieval route to Reddit evidence, not an
extra source to inflate cross-platform counts.

`RedditAdapter()` requires OAuth unless keyless options are explicitly enabled;
`default_adapter_factory` enables public RSS and archive enrichment for Skill runs.
