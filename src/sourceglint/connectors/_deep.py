"""Bounded public-body retrieval. Child comments keep their own dates and URLs.

A failed enrichment never discards already retrieved parent evidence.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import re
from typing import Mapping
from urllib.parse import urlencode, urlparse

from ..pipeline.adapters import RawSourceResult
from ._recency import search_bounds

ARCHIVE = "https://arctic-shift.photon-reddit.com/api"


def subject_query(query):
    """Separate broad research intent from subject for recall-oriented APIs."""
    intent = {
        "workflow",
        "workflows",
        "complaint",
        "complaints",
        "limitations",
        "experiences",
        "feedback",
        "practices",
        "best",
        "recent",
        "hooks",
    }
    terms = re.findall(r"[\w+#.-]+", query)
    selected = [x for x in terms if x.casefold() not in intent]
    return " ".join(selected) or query


def subject_present(item, query):
    terms = subject_query(query).casefold().split()
    text = (
        " ".join(str(item.get(k) or "") for k in ("title", "body", "html_url"))
        .casefold()
        .replace("-", " ")
    )
    for term in terms:
        plural = len(term) > 4 and term.endswith("s") and not term.endswith("ss")
        stem = term[:-1] if plural else term
        pattern = r"(?<!\w)" + re.escape(stem) + (r"s?" if plural else "") + r"(?!\w)"
        if not re.search(pattern, text):
            return False
    return True



def intent_rank(item, query):
    title = str(item.get("title") or "").casefold()
    body = str(item.get("body") or "").casefold()
    intent = set(query.casefold().split()) - set(
        subject_query(query).casefold().split()
    )
    if intent & {"workflow", "workflows", "practices", "hooks"}:
        intent |= {"workflow", "steps", "plan", "review", "test", "skill", "hook"}
    if intent & {"complaint", "complaints", "feedback", "limitations"}:
        intent |= {"bug", "broken", "error", "limit", "regression", "failed"}
    return (
        sum(3 * (word in title) + (word in body) for word in intent),
        int((item.get("reactions") or {}).get("total_count") or 0),
    )


def epoch(value):
    try:
        return (
            datetime.fromtimestamp(float(value), timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (ValueError, TypeError, OverflowError, OSError):
        return ""


def in_window(date, bounds):
    if not date:
        return False
    try:
        value = datetime.fromisoformat(date.replace("Z", "+00:00"))
        return value.tzinfo is not None and (
            not bounds or bounds[0] <= value <= bounds[1]
        )
    except (ValueError, TypeError):
        return False


def issue_results(client, query, plan, request, headers, limitations, limit=20):
    bounds = search_bounds(plan, request)
    qualifier = f" created:{bounds[0].date()}..{bounds[1].date()}" if bounds else ""
    subject = subject_query(query)
    scope = ""
    # Resolve an exact repository-name match rather than guessing a vendor.
    # Repository popularity allocates retrieval, never validates a user claim.
    try:
        url = "https://api.github.com/search/repositories?" + urlencode(
            {"q": subject + " in:name", "per_page": 5, "sort": "stars", "order": "desc"}
        )
        found = client.request(url, headers=headers).json()
        compact = re.sub(r"[^a-z0-9]", "", subject.casefold())
        for repo in (found.get("items") or []) if isinstance(found, dict) else []:
            if not isinstance(repo, dict) or repo.get("fork"):
                continue
            name = str(
                repo.get("name") or str(repo.get("full_name") or "").rsplit("/", 1)[-1]
            )
            if (
                compact
                and re.sub(r"[^a-z0-9]", "", name.casefold()) == compact
                and re.fullmatch(r"[\w.-]+/[\w.-]+", str(repo.get("full_name") or ""))
            ):
                scope = "repo:" + repo["full_name"]
                break
    except Exception as exc:
        limitations.append(
            f"GitHub subject repository discovery unavailable: {type(exc).__name__}"
        )
    if scope:
        intent_words = query.casefold().split()
        keyword = (
            "workflow"
            if any(
                x in intent_words
                for x in ("workflow", "workflows", "hooks", "practices")
            )
            else ""
        )
        search_subject = " ".join(x for x in (scope, keyword) if x)
    else:
        search_subject = subject + " in:title,body"
    items = {}
    for kind in ("is:issue", "is:pull-request"):
        url = "https://api.github.com/search/issues?" + urlencode(
            {
                "q": search_subject + qualifier + " " + kind,
                "per_page": limit,
                "sort": "reactions",
                "order": "desc",
            }
        )
        try:
            payload = client.request(url, headers=headers).json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("items"), list
            ):
                raise ValueError("missing items")
            for row in payload["items"]:
                if (
                    isinstance(row, dict)
                    and row.get("id") is not None
                    and subject_present(row, query)
                    and (
                        not scope
                        or str(row.get("html_url") or "").startswith(
                            "https://github.com/" + scope.removeprefix("repo:") + "/"
                        )
                    )
                ):
                    items[row["id"]] = row
        except Exception as exc:
            limitations.append(f"GitHub {kind} search failed: {type(exc).__name__}")
    ranked = sorted(items.values(), key=lambda x: intent_rank(x, query), reverse=True)
    out = []
    older_threads = []
    if bounds:
        # Recent activity in an old issue is still recent evidence. Searching
        # only newly created threads misses these reports in both old engines.
        url = "https://api.github.com/search/issues?" + urlencode(
            {
                "q": search_subject
                + f" is:issue created:<{bounds[0].date()} updated:{bounds[0].date()}..{bounds[1].date()}",
                "per_page": 5,
                "sort": "updated",
                "order": "desc",
            }
        )
        try:
            payload = client.request(url, headers=headers).json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("items"), list
            ):
                raise ValueError("missing updated items")
            older_threads = [
                x
                for x in payload["items"][:5]
                if isinstance(x, dict)
                and str(x.get("created_at") or "")
                < bounds[0].strftime("%Y-%m-%dT%H:%M:%SZ")
                and x.get("created_at")
            ]
            older_threads = [
                x
                for x in older_threads
                if subject_present(x, query)
                and (
                    not scope
                    or str(x.get("html_url") or "").startswith(
                        "https://github.com/" + scope.removeprefix("repo:") + "/"
                    )
                )
            ]
        except Exception as exc:
            limitations.append(
                f"GitHub recent activity in older threads incomplete: {type(exc).__name__}"
            )
    comment_candidates = []
    for item in ranked[:limit] + older_threads:
        if not isinstance(item, Mapping):
            continue
        date = str(item.get("created_at") or "")
        link = str(item.get("html_url") or "")
        if not date or not link.startswith("https://github.com/"):
            continue
        kind = "pull_request" if item.get("pull_request") else "issue"
        parent = RawSourceResult(
            source="github",
            source_type="post",
            source_native_id=f"{kind}:{item.get('id')}",
            url=link,
            title=str(item.get("title") or ""),
            text=str(item.get("body") or item.get("title") or ""),
            author=str((item.get("user") or {}).get("login") or ""),
            published_at=date,
            query=query,
            query_language=str(request.get("query_language") or ""),
            language=str(request.get("query_language") or "en"),
            market=str(request.get("market") or "global"),
            engagement={"comments": max(0, int(item.get("comments") or 0))},
            raw_metadata={
                "github_kind": kind,
                "github_updated_at": item.get("updated_at"),
                "state": item.get("state"),
                "retrieval_scope": scope or "global_subject_search",
            },
        )
        if in_window(date, bounds):
            out.append(parent)
        elif item not in older_threads:
            continue
        comment_candidates.append(parent)
    # Depth is allocated only to the most active threads, with a fixed budget.
    new_threads = sorted(
        [x for x in comment_candidates if in_window(x.published_at, bounds)],
        key=lambda x: intent_rank({"title": x.title, "body": x.text}, query),
        reverse=True,
    )[:5]
    old_threads = [
        x for x in comment_candidates if not in_window(x.published_at, bounds)
    ][:5]
    for parent in new_threads + old_threads:
        if not parent.engagement.get("comments"):
            continue
        path = urlparse(parent.url).path
        parts = path.strip("/").split("/")
        if len(parts) != 4 or not parts[3].isdigit():
            continue
        # The last page includes the most recent comments; the first page of a
        # long-standing thread can contain years-old replies exclusively.
        page = max(1, (int(parent.engagement.get("comments") or 0) + 29) // 30)
        comments_url = f"https://api.github.com/repos/{parts[0]}/{parts[1]}/issues/{parts[3]}/comments?per_page=30&page={page}"
        try:
            rows = client.request(comments_url, headers=headers).json()
            if not isinstance(rows, list):
                raise ValueError("comments not list")
        except Exception as exc:
            limitations.append(
                f"GitHub comments incomplete for {parent.url}: {type(exc).__name__}"
            )
            continue
        candidates = [
            x
            for x in rows
            if isinstance(x, dict) and in_window(str(x.get("created_at") or ""), bounds)
        ]
        candidates.sort(
            key=lambda x: int((x.get("reactions") or {}).get("total_count") or 0),
            reverse=True,
        )
        for row in candidates[:5]:
            body = str(row.get("body") or "")
            comment_url = str(row.get("html_url") or "")
            if not body or not comment_url.startswith(parent.url + "#issuecomment-"):
                continue
            out.append(
                replace(
                    parent,
                    source_type="comment",
                    source_native_id=f"comment:{row.get('id')}",
                    url=comment_url,
                    text=body,
                    author=str((row.get("user") or {}).get("login") or ""),
                    published_at=str(row["created_at"]),
                    engagement={},
                    raw_metadata={
                        "parent_url": parent.url,
                        "parent_published_at": parent.published_at,
                        "github_kind": "issue_comment",
                    },
                )
            )
    return out


def reddit_archive(client, query, plan, request, parents, limitations, limit=20):
    # Optional enrichment has multiple bounded lanes; repeated retries per lane
    # would multiply latency and load without improving an unavailable archive.
    from ._http import StdlibHttpClient
    if isinstance(client, StdlibHttpClient):
        client = replace(client, max_attempts=1)
    bounds = search_bounds(plan, request)
    terms = [x.casefold() for x in re.findall(r"[A-Za-z0-9]+", query)[:2]]
    parents = [
        x
        for x in parents
        if in_window(x.published_at, bounds)
        and all(
            t
            in (
                x.title
                + " "
                + x.text
                + " "
                + str(x.raw_metadata.get("subreddit") or "")
            ).casefold()
            for t in terms
        )
    ]
    # Observed/explicit communities take priority over inferred names.
    communities = list(request.get("subreddits") or [])
    observed = [str(x.raw_metadata.get("subreddit") or "") for x in parents]
    words = re.findall(r"[A-Za-z0-9]+", subject_query(query))
    prefixes = list(dict.fromkeys(["".join(words[:2]), words[0] if words else ""]))
    for prefix in prefixes[:2]:
        if not prefix:
            continue
        try:
            payload = client.request(
                ARCHIVE + "/subreddits/search?" + urlencode({
                    "subreddit_prefix": prefix, "limit": 5,
                    "sort_type": "subscribers", "sort": "desc",
                }), timeout=10,
            ).json()
            for row in payload.get("data", []):
                name = str(row.get("subreddit") or row.get("display_name") or "")
                context = " ".join(str(row.get(k) or "") for k in
                                   ("title", "description", "public_description"))
                # Prefixes are candidate discovery only: MCPE (Minecraft)
                # must not become a community for an MCP protocol question.
                exact = name.casefold() == prefix.casefold()
                contextual = re.search(r"(?<!\w)" + re.escape(words[0]) + r"(?!\w)", context, re.I) if words else None
                if name.casefold().startswith(prefix.casefold()) and (exact or contextual):
                    communities.append(name)
        except Exception as exc:
            limitations.append(f"Reddit community discovery unavailable: {type(exc).__name__}")
    communities += observed + prefixes
    candidates = {}
    for name in communities:
        if isinstance(name, str) and re.fullmatch(r"(?:r/)?[A-Za-z0-9_]{2,32}", name):
            cleaned = name.removeprefix("r/")
            candidates.setdefault(cleaned.casefold(), cleaned)
    explicit = {str(x).removeprefix("r/").casefold() for x in request.get("subreddits", [])}
    entity = "".join(words[:2]).casefold()
    first = words[0].casefold() if words else ""
    communities = sorted(candidates.values(), key=lambda name: (
        name.casefold() not in explicit,
        name.casefold() != entity,
        name.casefold() != first,
        not name.casefold().startswith(first),
    ))[:3]
    by_id = {x.source_native_id.removeprefix("t3_"): x for x in parents}
    output = list(parents)
    # Partition the window before requesting listings: a single newest-first
    # page cannot represent a busy community's full month.
    windows = [bounds] if bounds else [None]
    if bounds:
        step = (bounds[1] - bounds[0]) / 4
        windows = [(bounds[0] + step * i, bounds[0] + step * (i + 1)) for i in range(4)]
    jobs = [(community, window) for community in communities for window in windows]

    def fetch_listing(job):
        community, window = job
        params = {"subreddit": community, "limit": min(100, max(20, limit * 2)), "sort": "desc"}
        # A topic's dedicated community supplies entity context. Broad
        # communities need server-side keyword filtering before pagination.
        entity = "".join(words[:2]).casefold()
        if entity and entity not in community.casefold():
            params["query"] = subject_query(query)
        if window:
            params.update(after=window[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                          before=window[1].strftime("%Y-%m-%dT%H:%M:%SZ"))
        try:
            try:
                payload = client.request(ARCHIVE + "/posts/search?" + urlencode(params), timeout=10).json()
            except Exception as exc:
                # The archive reports expensive keyword-search timeouts as
                # HTTP 422. A bounded time-stratum listing is still usable.
                if getattr(exc, "status", None) != 422 or "query" not in params:
                    raise
                params.pop("query")
                payload = client.request(ARCHIVE + "/posts/search?" + urlencode(params), timeout=10).json()
                return community, payload, "keyword search timed out; filtered community sample"
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("missing data")
            return community, payload, None
        except Exception as exc:
            return community, {}, type(exc).__name__

    with ThreadPoolExecutor(max_workers=2) as pool:
        pages = list(pool.map(fetch_listing, jobs))
    for community, payload, error in pages:
        if error:
            limitations.append(f"Reddit public archive search r/{community}: {error}")
            if not isinstance(payload.get("data"), list):
                continue
        for row in payload["data"]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "")
            body = str(row.get("selftext") or "")
            if terms and not all(
                t in (title + " " + body + " " + community).casefold() for t in terms
            ):
                continue
            pid = str(row.get("id") or "").removeprefix("t3_")
            date = epoch(row.get("created_utc"))
            permalink = str(row.get("permalink") or "")
            if (
                not pid
                or not in_window(date, bounds)
                or not permalink.startswith("/r/")
                or row.get("author") in ("[deleted]", "[removed]")
            ):
                continue
            record = RawSourceResult(
                source="reddit",
                source_type="post",
                source_native_id="t3_" + pid,
                url="https://www.reddit.com" + permalink,
                title=title,
                text=body if body not in ("[removed]", "[deleted]") else title,
                author=str(row.get("author") or ""),
                published_at=date,
                language=str(request.get("query_language") or "en"),
                query=query,
                query_language=str(request.get("query_language") or ""),
                market=str(request.get("market") or "global"),
                engagement={
                    "upvotes": max(0, int(row.get("score") or 0)),
                    "comments": max(0, int(row.get("num_comments") or 0)),
                },
                raw_metadata={
                    "subreddit": community,
                    "route": "public_archive",
                    "archive_sampling": "time_stratified",
                    "archive_observation_not_live_reddit": True,
                },
            )
            if pid in by_id:
                output = [
                    record if x.source_native_id == "t3_" + pid else x for x in output
                ]
            else:
                output.append(record)
            by_id[pid] = record
    ranked = sorted(output, key=lambda x: (
        intent_rank({"title": x.title, "body": x.text}, query)[0],
        int(x.engagement.get("comments") or 0),
    ), reverse=True)
    # Select across available time strata; this preserves discovered older
    # material without inventing coverage where a stratum returned nothing.
    bins = [[] for _ in windows]
    for item in ranked:
        index = 0
        if bounds:
            date = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
            index = min(3, max(0, int((date - bounds[0]) / step))) if step.total_seconds() else 0
        bins[index].append(item)
    occupied = sum(bool(bucket) for bucket in bins)
    output = []
    selected_days = set()
    while any(bins) and len(output) < limit:
        for bucket in bins:
            if bucket and len(output) < limit:
                # A busy day must not occupy every slot within a stratum.
                index = next((i for i, item in enumerate(bucket)
                              if item.published_at[:10] not in selected_days), 0)
                item = bucket.pop(index)
                selected_days.add(item.published_at[:10])
                output.append(item)
    if bounds and occupied < 4:
        limitations.append("Reddit discovery has empty time strata; month-wide coverage is incomplete")
    # An archive is one observation route, not independent corroboration.
    for parent in output.copy()[:5]:
        pid = parent.source_native_id.removeprefix("t3_")
        params = {"link_id": pid, "limit": 50, "sort": "desc"}
        if bounds:
            params.update(
                after=bounds[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                before=bounds[1].strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        try:
            payload = client.request(
                ARCHIVE + "/comments/search?" + urlencode(params), timeout=10
            ).json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise ValueError("missing comments data")
        except Exception as exc:
            limitations.append(
                f"Reddit archive comments incomplete for {parent.url}: {type(exc).__name__}"
            )
            continue
        candidates = [
            x
            for x in rows
            if isinstance(x, dict)
            and in_window(epoch(x.get("created_utc")), bounds)
            and x.get("body") not in (None, "", "[deleted]", "[removed]")
            and str(x.get("author") or "").casefold() != "automoderator"
        ]
        candidates.sort(
            key=lambda x: (
                len(str(x.get("body") or "")) >= 80,
                int(x.get("score") or 0),
            ),
            reverse=True,
        )
        for row in candidates[:5]:
            cid = str(row.get("id") or "").removeprefix("t1_")
            if not cid or row.get("author") in ("[deleted]", "[removed]"):
                continue
            output.append(
                replace(
                    parent,
                    source_type="comment",
                    source_native_id="t1_" + cid,
                    url=parent.url.rstrip("/") + "/" + cid + "/",
                    text=str(row["body"]),
                    author=str(row.get("author") or ""),
                    published_at=epoch(row.get("created_utc")),
                    engagement={"upvotes": max(0, int(row.get("score") or 0))},
                    raw_metadata={
                        "parent_url": parent.url,
                        "route": "public_archive",
                        "archive_observation_not_live_reddit": True,
                    },
                )
            )
    return output
