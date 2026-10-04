"""Bounded verbatim excerpts centered on the topic, with explicit omissions."""
import re

MARKER = '\n[body excerpt: middle omitted]\n'


def select_excerpt(body: str, topic: str, budget: int) -> str:
    if len(body) <= budget:
        return body
    if budget <= len(MARKER) * 2 + 12:
        return body[:max(0, budget)]
    size = (budget - len(MARKER) * 2) // 3
    stop = {"what", "are", "people", "saying", "about", "recently", "tools",
            "the", "and", "for", "with", "from", "how", "does", "have"}
    terms = list(dict.fromkeys(t.casefold() for t in re.findall(r'\w+', topic)
                              if len(t) >= 3 and t.casefold() not in stop))
    positions = []
    # Search the ORIGINAL string: Unicode casefold can change length (ß/İ),
    # so folded offsets cannot safely address the original source.
    frequencies = {t: max(1, len(re.findall(re.escape(t), body, re.I))) for t in terms}
    patterns = list(dict.fromkeys([" ".join(terms)] + terms))
    for term in patterns:
        if not term:
            continue
        for match in list(re.finditer(re.escape(term), body, re.I))[:100]:
            center = (match.start() + match.end()) // 2
            start = max(0, min(len(body) - size, center - size // 2))
            text = body[start:start + size].casefold()
            positions.append((sum(1 / frequencies[t] for t in terms if t in text), start))
    middle = sorted(positions, key=lambda x: (-x[0], x[1]))[0][1] if positions else len(body) // 2 - size // 2
    tail_size = budget - len(MARKER) * 2 - size * 2
    ranges = [(0, size), (middle, middle + size), (len(body) - tail_size, len(body))]
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return MARKER.join(body[a:b] for a, b in merged)[:budget]
