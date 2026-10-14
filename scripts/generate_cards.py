"""Generate GitHub profile cards (stats + languages) including private and organization data.

Usage: METRICS_TOKEN=<token> python scripts/generate_cards.py <username>
Only aggregate numbers are printed, so the logs never expose private repository names.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from html import escape

API = "https://api.github.com/graphql"
TOKEN = os.environ["METRICS_TOKEN"]
LOGIN = sys.argv[1] if len(sys.argv) > 1 else "davgo0103"
# notebooks store outputs/images inline, which hugely inflates their byte count
IGNORED_LANGUAGES = {"Jupyter Notebook"}
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# tokyonight
BG, BORDER, TITLE, TEXT, ICON, MUTED = "#1a1b27", "#2b2d42", "#70a5fd", "#38bdae", "#bf91f3", "#a9b1d6"


def graphql(query, variables=None, retries=3):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for attempt in range(retries):
        req = urllib.request.Request(API, body, {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            if "errors" in data and not data.get("data"):
                raise RuntimeError(f"GraphQL errors: {[e.get('type') for e in data['errors']]}")
            return data["data"]
        except Exception as error:  # timeouts / 502s: retry with backoff
            if attempt == retries - 1:
                raise
            print(f"request failed ({type(error).__name__}), retrying")
            time.sleep(2 * (attempt + 1))


def paginate_repos(affiliations, fields, batch=25):
    query = f"""
    query($login: String!, $after: String) {{
      user(login: $login) {{
        repositories(first: {batch}, after: $after, ownerAffiliations: [{affiliations}], affiliations: [{affiliations}]) {{
          totalCount
          pageInfo {{ hasNextPage endCursor }}
          nodes {{ {fields} }}
        }}
      }}
    }}"""
    nodes, after = [], None
    while True:
        repos = graphql(query, {"login": LOGIN, "after": after})["user"]["repositories"]
        nodes += repos["nodes"]
        if not repos["pageInfo"]["hasNextPage"]:
            return repos["totalCount"], nodes
        after = repos["pageInfo"]["endCursor"]


def collect():
    profile = graphql("""
    query($login: String!) {
      user(login: $login) {
        name login createdAt
        pullRequests { totalCount }
        issues { totalCount }
        organizations(first: 1) { totalCount }
        followers { totalCount }
      }
    }""", {"login": LOGIN})["user"]

    # contributionsCollection only spans one year, so query every year since the account was created
    start_year = int(profile["createdAt"][:4])
    now = datetime.now(timezone.utc)
    commits = reviews = 0
    contributed = set()
    for year in range(start_year, now.year + 1):
        to = now.isoformat() if year == now.year else f"{year}-12-31T23:59:59Z"
        cc = graphql("""
        query($login: String!, $from: DateTime!, $to: DateTime!) {
          user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
              totalCommitContributions
              restrictedContributionsCount
              totalPullRequestReviewContributions
              commitContributionsByRepository(maxRepositories: 100) { repository { nameWithOwner } }
            }
          }
        }""", {"login": LOGIN, "from": f"{year}-01-01T00:00:00Z", "to": to})["user"]["contributionsCollection"]
        commits += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
        reviews += cc["totalPullRequestReviewContributions"]
        contributed |= {c["repository"]["nameWithOwner"] for c in cc["commitContributionsByRepository"]}

    all_repo_count, _ = paginate_repos("OWNER, COLLABORATOR, ORGANIZATION_MEMBER", "id", batch=100)
    _, owned = paginate_repos("OWNER", "isFork stargazerCount forkCount languages(first: 20, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }")
    owned = [r for r in owned if not r["isFork"]]

    languages = {}
    for repo in owned:
        for edge in repo["languages"]["edges"]:
            if edge["node"]["name"] in IGNORED_LANGUAGES:
                continue
            lang = languages.setdefault(edge["node"]["name"], {"size": 0, "color": edge["node"]["color"] or MUTED})
            lang["size"] += edge["size"]

    stats = {
        "name": profile["name"] or profile["login"],
        "stars": sum(r["stargazerCount"] for r in owned),
        "forks": sum(r["forkCount"] for r in owned),
        "commits": commits,
        "prs": profile["pullRequests"]["totalCount"],
        "issues": profile["issues"]["totalCount"],
        "reviews": reviews,
        "contributed": len(contributed),
        "repos": all_repo_count,
        "orgs": profile["organizations"]["totalCount"],
    }
    print("stats:", {k: v for k, v in stats.items() if k != "name"})
    print(f"owned non-fork repos: {len(owned)}, languages: {len(languages)}")
    return stats, languages


def fmt(n):
    return f"{n:,}"


ICONS = {  # octicons, 16x16
    "star": "M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25z",
    "commit": "M10.5 7.75a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0zm1.43.75a4.002 4.002 0 01-7.86 0H.75a.75.75 0 110-1.5h3.32a4.001 4.001 0 017.86 0h3.32a.75.75 0 110 1.5h-3.32z",
    "pr": "M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z",
    "issue": "M8 9.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM8 0a8 8 0 100 16A8 8 0 008 0zM1.5 8a6.5 6.5 0 1113 0 6.5 6.5 0 01-13 0z",
    "review": "M1.679 7.932c.412-.621 1.242-1.75 2.366-2.717C5.175 4.242 6.527 3.5 8 3.5c1.473 0 2.824.742 3.955 1.715 1.124.967 1.954 2.096 2.366 2.717a.119.119 0 010 .136c-.412.621-1.242 1.75-2.366 2.717C10.825 11.758 9.473 12.5 8 12.5c-1.473 0-2.824-.742-3.955-1.715C2.92 9.818 2.09 8.69 1.679 8.068a.119.119 0 010-.136zM8 2c-1.981 0-3.67.992-4.933 2.078C1.797 5.169.88 6.423.43 7.1a1.619 1.619 0 000 1.798c.45.678 1.367 1.932 2.637 3.024C4.329 13.008 6.019 14 8 14c1.981 0 3.67-.992 4.933-2.078 1.27-1.091 2.187-2.345 2.637-3.023a1.619 1.619 0 000-1.798c-.45-.678-1.367-1.932-2.637-3.023C11.671 2.992 9.981 2 8 2zm0 8a2 2 0 100-4 2 2 0 000 4z",
    "repo": "M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1V9h-8c-.356 0-.694.074-1 .208V2.5a1 1 0 011-1h8z",
    "fork": "M5 3.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm0 2.122a2.25 2.25 0 10-1.5 0v.878A2.25 2.25 0 005.75 8.5h1.5v2.128a2.251 2.251 0 101.5 0V8.5h1.5a2.25 2.25 0 002.25-2.25v-.878a2.25 2.25 0 10-1.5 0v.878a.75.75 0 01-.75.75h-4.5A.75.75 0 015 6.25v-.878zm3.75 7.378a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm3-8.75a.75.75 0 100-1.5.75.75 0 000 1.5z",
    "org": "M1.5 14.25c0 .138.112.25.25.25H4v-1.25a.75.75 0 01.75-.75h2.5a.75.75 0 01.75.75v1.25h2.25a.25.25 0 00.25-.25V1.75a.25.25 0 00-.25-.25h-8.5a.25.25 0 00-.25.25v12.5zM1.75 16A1.75 1.75 0 010 14.25V1.75C0 .784.784 0 1.75 0h8.5C11.216 0 12 .784 12 1.75v12.5c0 .085-.006.168-.018.25h2.268a.25.25 0 00.25-.25V8.285a.25.25 0 00-.111-.208l-1.055-.703a.75.75 0 11.832-1.248l1.055.703c.487.325.779.871.779 1.456v5.965A1.75 1.75 0 0114.25 16h-3.5a.75.75 0 01-.197-.026c-.099.017-.2.026-.303.026h-3a.75.75 0 01-.75-.75V14h-1v1.25a.75.75 0 01-.75.75h-3zM3 3.75A.75.75 0 013.75 3h.5a.75.75 0 010 1.5h-.5A.75.75 0 013 3.75zM3.75 6a.75.75 0 000 1.5h.5a.75.75 0 000-1.5h-.5zM3 9.75A.75.75 0 013.75 9h.5a.75.75 0 010 1.5h-.5A.75.75 0 013 9.75zM7.75 9a.75.75 0 000 1.5h.5a.75.75 0 000-1.5h-.5zM7 6.75A.75.75 0 017.75 6h.5a.75.75 0 010 1.5h-.5A.75.75 0 017 6.75zM7.75 3a.75.75 0 000 1.5h.5a.75.75 0 000-1.5h-.5z",
}

STYLE = f"""
  .title {{ font: 600 18px 'Segoe UI', Ubuntu, sans-serif; fill: {TITLE}; animation: fadeIn .8s ease-in-out forwards; }}
  .label {{ font: 600 14px 'Segoe UI', Ubuntu, 'Microsoft JhengHei', sans-serif; fill: {TEXT}; }}
  .value {{ font: 700 14px 'Segoe UI', Ubuntu, sans-serif; fill: {TEXT}; }}
  .muted {{ font: 400 11px 'Segoe UI', Ubuntu, 'Microsoft JhengHei', sans-serif; fill: {MUTED}; }}
  .icon {{ fill: {ICON}; }}
  .row {{ opacity: 0; animation: fadeIn .4s ease-in-out forwards; }}
  .grow {{ transform-box: fill-box; transform-origin: left; transform: scaleX(0); animation: grow .9s ease-out forwards; }}
  @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
  @keyframes grow {{ to {{ transform: scaleX(1); }} }}
"""


def card(width, height, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
<title>{escape(title)}</title>
<style>{STYLE}</style>
<rect x="0.5" y="0.5" rx="4.5" width="{width - 1}" height="{height - 1}" fill="{BG}" stroke="{BORDER}"/>
<text x="25" y="35" class="title">{escape(title)}</text>
{body}
</svg>
"""


def stats_svg(s):
    rows = [
        ("star", "Total Stars", s["stars"]),
        ("commit", "Total Commits", s["commits"]),
        ("pr", "Pull Requests", s["prs"]),
        ("issue", "Issues", s["issues"]),
        ("review", "PR Reviews", s["reviews"]),
        ("fork", "Forks Received", s["forks"]),
        ("repo", "Contributed to", s["contributed"]),
        ("repo", "Repositories", s["repos"]),
        ("org", "Organizations", s["orgs"]),
    ]
    body = []
    for i, (icon, label, value) in enumerate(rows):
        col, line = divmod(i, 5)
        x, y = 25 + col * 240, 70 + line * 26
        body.append(
            f'<g class="row" style="animation-delay:{150 + i * 120}ms" transform="translate({x},{y})">'
            f'<svg class="icon" viewBox="0 0 16 16" width="16" height="16" y="-13"><path fill-rule="evenodd" d="{ICONS[icon]}"/></svg>'
            f'<text x="25" class="label">{label}:</text><text x="200" class="value" text-anchor="end">{fmt(value)}</text></g>'
        )
    body.append(f'<text x="470" y="200" class="muted" text-anchor="end">含私人 repo 與組織 · lifetime</text>')
    return card(495, 215, f"{s['name']}'s GitHub Stats", "\n".join(body))


def languages_svg(languages, limit=8):
    top = sorted(languages.items(), key=lambda kv: kv[1]["size"], reverse=True)[:limit]
    total = sum(v["size"] for _, v in top) or 1
    width, bar_w = 380, 330
    body = [f'<mask id="bar"><rect x="25" y="52" width="{bar_w}" height="8" rx="4" fill="#fff"/></mask>', '<g mask="url(#bar)" class="grow">']
    x = 25.0
    for name, v in top:
        w = bar_w * v["size"] / total
        body.append(f'<rect x="{x:.2f}" y="52" width="{w + 0.5:.2f}" height="8" fill="{v["color"]}"/>')
        x += w
    body.append("</g>")
    for i, (name, v) in enumerate(top):
        col, line = i % 2, i // 2
        px, py = 25 + col * 175, 88 + line * 24
        body.append(
            f'<g class="row" style="animation-delay:{300 + i * 100}ms" transform="translate({px},{py})">'
            f'<circle cx="5" cy="-5" r="5" fill="{v["color"]}"/>'
            f'<text x="16" class="label" style="fill:{MUTED}">{escape(name)} <tspan class="value" style="font-weight:400">{100 * v["size"] / total:.1f}%</tspan></text></g>'
        )
    height = 88 + ((len(top) + 1) // 2) * 24 + 4
    return card(width, height, "Most Used Languages", "\n".join(body))


def main():
    stats, languages = collect()
    for filename, content in (("metrics.stats.svg", stats_svg(stats)), ("metrics.languages.svg", languages_svg(languages))):
        with open(os.path.join(OUT_DIR, filename), "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        print(f"wrote {filename}")


if __name__ == "__main__":
    main()
