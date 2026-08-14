# -*- coding: utf-8 -*-
"""精准推送：仅把给定文件叠加到远端当前 main 的 tree 上（base_tree 模式）。
用法：GITHUB_TOKEN=xxx python .workbuddy/push_files.py file1 file2 ...
用于 git 智能 HTTP 被代理封死时的备用推送。远端 main 作为父提交与新 tree 的 base。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

REPO = "nomadpanda1/cad-frame-replacement"
API = f"https://api.github.com/repos/{REPO}"


def api(method, path, data=None, token=None):
    url = API + path
    body = json.dumps(data).encode("utf-8") if data else None
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cad-frame-push-files",
    }
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")) if resp.status != 204 else {}
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:500]}", file=sys.stderr)
        raise


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("缺少 GITHUB_TOKEN 环境变量")
    files = sys.argv[1:]
    if not files:
        raise SystemExit("用法: push_files.py file1 [file2 ...]")

    msg = subprocess.check_output(["git", "log", "-1", "--format=%B"], text=True).strip()
    # 父提交取远端 main 实时 SHA
    main_ref = api("GET", "/git/refs/heads/main", token=token)
    parent = main_ref["object"]["sha"]
    parent_commit = api("GET", f"/git/commits/{parent}", token=token)
    base_tree = parent_commit["tree"]["sha"]
    print(f"远端 main : {parent}")
    print(f"base tree : {base_tree}")

    tree_entries = []
    for f in files:
        f = f.replace("\\", "/")
        content = subprocess.check_output(["git", "-c", "core.quotepath=false", "show", f"HEAD:{f}"])
        blob = api("POST", "/git/blobs",
                   {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"}, token)
        tree_entries.append({"path": f, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  blob {f} -> {blob['sha']}")
        # 礼貌节流：避免突发大量 blob 触发 GitHub 二级限流(429)
        time.sleep(0.4)

    tree = api("POST", "/git/trees", {"base_tree": base_tree, "tree": tree_entries}, token)
    print(f"新 tree   : {tree['sha']}")
    commit = api("POST", "/git/commits",
                 {"message": msg, "parents": [parent], "tree": tree["sha"]}, token)
    new_sha = commit["sha"]
    print(f"新 commit : {new_sha}")
    api("PATCH", "/git/refs/heads/main", {"sha": new_sha}, token)
    print("已更新远端 main。本地与远端现存在 SHA 分叉（tree 一致），用户机器执行 git pull --rebase 收敛即可。")


if __name__ == "__main__":
    main()
