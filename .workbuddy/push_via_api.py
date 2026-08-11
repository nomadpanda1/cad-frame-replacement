# -*- coding: utf-8 -*-
"""git 智能端点被重置时的备用推送：通过 GitHub REST API 创建 commit 并更新 main。

完整流程：创建 blob → 基于父 commit 的 tree 创建新 tree → 创建 commit → 更新 ref。
用法（在项目根目录）：
  python .workbuddy/push_via_api.py
之后本地需要：git pull --rebase（丢弃 tree 一致但 SHA 不同的形式重复 commit）。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.request

REPO = "nomadpanda1/cad-frame-replacement"
API = f"https://api.github.com/repos/{REPO}"


def get_token():
    # 兜底：优先从环境变量取（绕过可能崩溃的 Git Credential Manager）
    ev = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if ev:
        return ev.strip()
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input=f"url=https://github.com/{REPO}.git\n\n",
        capture_output=True, text=True, check=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("git credential 没有返回 password/token")


def api(method, path, data=None, token=None):
    url = API + path
    body = json.dumps(data).encode("utf-8") if data else None
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cad-frame-push-script",
    }
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")) if resp.status != 204 else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"HTTP {e.code}: {body[:500]}", file=sys.stderr)
        raise


def _tree_sha(rev):
    return subprocess.check_output(["git", "rev-parse", f"{rev}^{{tree}}"], text=True).strip()


def _find_boundary(head, base_tree):
    """从 HEAD 向父提交回溯，找到 tree 与远端 base_tree 完全相同的本地祖先。

    找不到则返回 None（意味着要全量推送 HEAD 的跟踪文件）。
    """
    c = head
    seen = set()
    while c and c not in seen:
        seen.add(c)
        if _tree_sha(c) == base_tree:
            return c
        parents = subprocess.check_output(
            ["git", "rev-list", "--parents", "-n", "1", c], text=True
        ).split()
        if len(parents) < 2:
            break
        c = parents[1]  # 取第一个父提交继续回溯
    return None


def main():
    token = get_token()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    msg = subprocess.check_output(["git", "log", "-1", "--format=%B"], text=True).strip()
    print(f"本地 HEAD : {head}")

    # 父提交取「远端 main」实时 SHA（避免本地/远端 SHA 分叉导致孤儿父节点）。
    main_ref = api("GET", "/git/refs/heads/main", token=token)
    parent = main_ref["object"]["sha"]
    print(f"远端 main : {parent}")

    parent_commit = api("GET", f"/git/commits/{parent}", token=token)
    base_tree = parent_commit["tree"]["sha"]
    print(f"base tree : {base_tree}")

    # 找本地中 tree 与远端一致的基准祖先；据此计算需要推送的差异文件。
    boundary = _find_boundary(head, base_tree)
    if boundary:
        print(f"本地基准  : {boundary}（tree 已与远端一致）")
        all_changed = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "diff", "--name-only", boundary, head], text=True
        ).splitlines()
        deleted = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "diff", "--name-only",
             "--diff-filter=D", boundary, head], text=True,
        ).splitlines()
        files = [f for f in all_changed if f not in deleted]
    else:
        print("未找到本地基准，改为全量推送 HEAD 的跟踪文件")
        files = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", head], text=True
        ).splitlines()
        deleted = []
    print(f"改动文件  : {files}")
    if deleted:
        print(f"删除文件  : {deleted}")

    # 为每个（非删除）改动文件创建 blob
    tree_entries = []
    for f in files:
        content = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "show", f"HEAD:{f}"])
        blob = api("POST", "/git/blobs",
                   {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
                   token)
        tree_entries.append({
            "path": f.replace("\\", "/"),
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })
        print(f"  blob {f} -> {blob['sha']}")
    # 删除的文件：sha 设为 None 即从树中移除
    for f in deleted:
        tree_entries.append({
            "path": f.replace("\\", "/"),
            "mode": "100644",
            "type": "blob",
            "sha": None,
        })
        print(f"  delete {f}")

    # 4) 创建新 tree（基于父 tree，覆盖改动路径）
    tree = api("POST", "/git/trees", {"base_tree": base_tree, "tree": tree_entries}, token)
    print(f"新 tree   : {tree['sha']}")

    # 5) 创建 commit
    commit = api("POST", "/git/commits",
                 {"message": msg, "parents": [parent], "tree": tree["sha"]},
                 token)
    new_sha = commit["sha"]
    print(f"新 commit : {new_sha}")

    # 6) 更新 main
    api("PATCH", "/git/refs/heads/main", {"sha": new_sha}, token)
    print("已更新远端 main。之后请执行：git pull --rebase")


if __name__ == "__main__":
    main()
