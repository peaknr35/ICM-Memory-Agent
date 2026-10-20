"""GitHub connector — repo READMEs + recent commits via the gh CLI.
One doc per README, one per commit (message + changed files).
"""
import json
import subprocess


def _gh(path, *args):
    out = subprocess.run(["gh", "api", path, *args], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return json.loads(out.stdout)


def fetch(max_repos=10, commits_per_repo=30):
    repos = _gh("user/repos", "-X", "GET", "-f", "sort=pushed", "-f", "per_page=%d" % max_repos)
    docs = []
    for repo in repos:
        full = repo["full_name"]
        docs.append(dict(
            source="github", source_id=f"repo:{full}", ts=repo.get("pushed_at"),
            title=f"Repo: {full}",
            content=f"{repo.get('description') or ''}\nLanguage: {repo.get('language')}\nUpdated: {repo.get('pushed_at')}",
            metadata={"repo": full, "kind": "repo"},
        ))
        try:
            readme = _gh(f"repos/{full}/readme")
            import base64
            text = base64.b64decode(readme["content"]).decode("utf-8", "replace")
            docs.append(dict(
                source="github", source_id=f"readme:{full}", ts=repo.get("pushed_at"),
                title=f"README: {full}", content=text[:20000],
                metadata={"repo": full, "kind": "readme"},
            ))
        except RuntimeError:
            pass
        try:
            commits = _gh(f"repos/{full}/commits", "-X", "GET", "-f", "per_page=%d" % commits_per_repo)
        except RuntimeError as e:
            print(f"  {full}: commits skipped ({e})")
            continue
        for c in commits:
            msg = c["commit"]["message"]
            docs.append(dict(
                source="github", source_id=f"commit:{full}:{c['sha']}", ts=c["commit"]["author"]["date"],
                title=f"{full}: {msg.splitlines()[0][:100]}",
                content=msg,
                metadata={"repo": full, "kind": "commit", "sha": c["sha"][:10],
                          "author": (c["commit"]["author"] or {}).get("name", "")},
            ))
        print(f"  {full}: README + {len(commits)} commits")
    return docs
