"""Tests for Official-domain classification (Phase 4 §6, §29).

Spoof-coverage matrix (PRD §6):
  * exact domain                       → official
  * subdomain (docs.company.com)       → official
  * company.com.evil.org               → NOT official
  * evilcompany.com                    → NOT official
  * uppercase company.com              → official
  * www.company.com                    → official
  * :8080 port present                 → official
  * GitHub official owner              → official
  * GitHub unrelated repo              → NOT official
  * unknown source                     → NOT official
  * malformed URL                      → NOT official (no crash)
  * tiny single-label rule             → NO false subdomain match
"""
from __future__ import annotations

import pytest

from gtm_intelligence.connectors.official_web import (
    OfficialClassification,
    OfficialDomainClassifier,
    OfficialRule,
    load_official_rules,
    _domain_matches,
    _github_owner_matches,
)


# ---------- Fixtures -----------------------------------------------------


@pytest.fixture
def classifier():
    return OfficialDomainClassifier(
        rules=[
            OfficialRule(
                owner="acme",
                domains=("acme.com", "acme.io"),
                github_owners=("acmehq", "acme-public"),
            ),
            OfficialRule(
                owner="balloon_co",
                domains=("balloon.co.jp",),
                github_owners=(),
            ),
        ]
    )


# ---------- Domain matching internals -----------------------------------


@pytest.mark.parametrize(
    "host,rule,expected",
    [
        ("acme.com", "acme.com", True),           # exact
        ("docs.acme.com", "acme.com", True),       # subdomain
        ("blog.docs.acme.com", "acme.com", True),  # deep subdomain
        ("acme.com.evil.org", "acme.com", False),  # spoof
        ("evilacme.com", "acme.com", False),       # sibling suffix
        ("www.acme.com", "acme.com", True),        # www prefix
        ("acme.com", "Acme.COM", True),            # case-insensitive
        ("ACME.com", "acme.com", True),            # uppercase host
        ("acme.com:8080", "acme.com", True),       # port present →
                                                    # caller passes
                                                    # port-stripped form;
                                                    # match must succeed.
        ("acme.io", "acme.com", False),            # unrelated TLD
    ],
)
def test_domain_matches_label_aligned(host, rule, expected):
    # The matcher is called on already-normalised hosts (port-stripped,
    # lowercase). We feed normalised inputs here.
    normalised_host = host.split(":")[0].lower()
    normalised_rule = rule.lower()
    assert _domain_matches(normalised_host, normalised_rule) is expected


def test_domain_matches_rejects_single_label_rule():
    """A single-label 'com' must NOT match acme.com via subdomain rule."""
    assert _domain_matches("docs.acme.com", "com") is False


def test_domain_matches_rejects_dots_in_rule():
    """Leading dots in the rule are tolerated but trimmed."""
    assert _domain_matches("docs.acme.com", ".acme.com") is True


# ---------- GitHub owner matching ---------------------------------------


def test_github_owner_match_success():
    hit = _github_owner_matches(
        "https://github.com/AcmeHQ/awesome/repo/blob/main/README.md",
        ("acmehq",),
    )
    assert hit is not None
    assert hit[0] == "acmehq"
    assert hit[1] == "AcmeHQ/awesome"


def test_github_owner_case_insensitive():
    hit = _github_owner_matches(
        "https://github.com/acme-public/widget",
        ("Acme-Public",),
    )
    assert hit is not None
    assert hit[0] == "Acme-Public"


def test_github_owner_unrelated_repo():
    assert _github_owner_matches(
        "https://github.com/somerandomuser/anything",
        ("acmehq",),
    ) is None


def test_github_owner_only_repos_not_profiles():
    # github.com/<owner> alone is the profile page; not a repo.
    assert _github_owner_matches(
        "https://github.com/acmehq",
        ("acmehq",),
    ) is None


def test_github_owner_no_match_returns_none():
    assert _github_owner_matches("https://example.com/acmehq/widget", ("acmehq",)) is None


# ---------- Classifier --------------------------------------------------


def test_classify_exact_official(classifier):
    out = classifier.classify_url("https://acme.com/pricing")
    assert out.is_official is True
    assert out.owner == "acme"
    assert out.matched_kind == "domain"
    assert out.matched_value == "acme.com"


def test_classify_subdomain_official(classifier):
    out = classifier.classify_url("https://docs.acme.com/article")
    assert out.is_official is True
    assert out.owner == "acme"
    assert out.matched_value == "acme.com"


def test_classify_spoof_suffix_is_not_official(classifier):
    out = classifier.classify_url("https://acme.com.evil.org/page")
    assert out.is_official is False
    assert out.owner is None


def test_classify_sibling_suffix_is_not_official(classifier):
    out = classifier.classify_url("https://evilacme.com/pricing")
    assert out.is_official is False


def test_classify_uppercase_host_is_official(classifier):
    out = classifier.classify_url("HTTPS://ACME.COM/path")
    assert out.is_official is True
    assert out.owner == "acme"


def test_classify_www_prefix_is_official(classifier):
    out = classifier.classify_url("https://www.acme.com/")
    assert out.is_official is True
    assert out.owner == "acme"


def test_classify_with_port_is_official(classifier):
    out = classifier.classify_url("https://acme.com:8443/docs")
    assert out.is_official is True


def test_classify_unknown_is_not_official(classifier):
    out = classifier.classify_url("https://news.ycombinator.com/item?id=123")
    assert out.is_official is False
    assert out.owner is None


def test_classify_empty_url_does_not_crash(classifier):
    assert classifier.classify_url("").is_official is False
    assert classifier.classify_url("not a url").is_official is False


def test_classify_github_official_owner(classifier):
    out = classifier.classify_url("https://github.com/AcmeHQ/awesome/releases/v1")
    assert out.is_official is True
    assert out.owner == "acme"
    assert out.matched_kind == "github"
    assert out.matched_value == "AcmeHQ/awesome"


def test_classify_github_unrelated_repo(classifier):
    out = classifier.classify_url("https://github.com/acme-evil-fork/widget")
    assert out.is_official is False


def test_classify_github_repo_takes_precedence_when_owner_matches(classifier):
    """If a URL lives under github.com AND its owner is a verified owner,
    we report github (more specific) — not the empty domain fallback."""

    out = classifier.classify_url("https://github.com/acme-public/widget")
    assert out.is_official is True
    assert out.matched_kind == "github"


def test_classify_jp_subdomain(classifier):
    out = classifier.classify_url("https://docs.balloon.co.jp/")
    assert out.is_official is True
    assert out.owner == "balloon_co"


# ---------- loader ------------------------------------------------------


def test_load_official_rules_from_yaml_text():
    yaml_text = """
        - owner: acme
          domains: [acme.com]
          github_owners: [acmehq]
        - owner: balloon_co
          domains: [balloon.co.jp]
    """
    rules = load_official_rules(yaml_text=yaml_text)
    assert len(rules) == 2
    assert rules[0].owner == "acme"
    assert rules[0].domains == ("acme.com",)
    assert rules[0].github_owners == ("acmehq",)
    assert rules[1].owner == "balloon_co"
    assert rules[1].github_owners == ()


def test_load_official_rules_drops_malformed_entries():
    yaml_text = """
        - owner: ok
          domains: [ok.com]
        - owner: ""
          domains: [bad.com]
        - not_a_dict
        - owner: ok2
          domains: [ok2.com]
    """
    rules = load_official_rules(yaml_text=yaml_text)
    assert len(rules) == 2
    assert [r.owner for r in rules] == ["ok", "ok2"]


def test_load_official_rules_rejects_non_list_root():
    with pytest.raises(ValueError):
        load_official_rules(yaml_text="owner: acme")
