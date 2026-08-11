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


def main():
    token = get_token()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    msg = subprocess.check_output(["git", "log", "-1", "--format=%B"], text=True).strip()

    print(f"本地 HEAD : {head}")

    # 父提交取「远端 main」实时 SHA（避免本地/远端 SHA 分叉导致孤儿父节点）。
    # 远端 main 内容与本地 HEAD^ 一致，但其 SHA 才是远端真实对象。
    main_ref = api("GET", "/git/refs/heads/main", token=token)
    parent = main_ref["object"]["sha"]
    print(f"远端 main : {parent}")

    # 1) 父 commit 的 tree
    parent_commit = api("GET", f"/git/commits/{parent}", token=token)
    base_tree = parent_commit["tree"]["sha"]
    print(f"base tree : {base_tree}")

    # 2) 本次 commit 改动的文件
    files = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", head],
        text=True,
    ).splitlines()
    print(f"改动文件  : {files}")

    # 3) 为每个改动文件创建 blob
    tree_entries = []
    for f in files:
        content = subprocess.check_output(["git", "show", f"HEAD:{f}"])
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
