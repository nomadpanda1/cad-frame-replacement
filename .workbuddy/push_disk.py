# -*- coding: utf-8 -*-
"""从磁盘直接推送指定文件到远端 main（base_tree 模式，绕开损坏的本地 git）。

动机：本地 .git 对象库损坏（HEAD 的 tree/parent 缺失），git status/show/ls-tree 全部不可用。
但本仓库常态就是用 GitHub REST API 推送（智能 HTTP 被封），推送只依赖远端 tree，
不依赖本地 git。本脚本直接读取磁盘文件内容构造 blob，叠加到远端 main 当前 tree 上。

安全性：base_tree 模式 = 新 tree 以远端当前 tree 为基底，仅替换命令行指定的文件。
其余任何远端文件原样保留，绝不误删/误覆盖。

用法：
  python push_disk.py verify lib/finder.py run_skill.py
  python push_disk.py push   "feat: 修复 SW 网格型标题栏字段错位 + --dwg 路径补 validators" lib/finder.py run_skill.py
"""
import base64
import difflib
import json
import os
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import get_gh_token  # wincred 读取 GitHub PAT

REPO = "nomadpanda1/cad-frame-replacement"
API = f"https://api.github.com/repos/{REPO}"


def get_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    # 优先按 target 精确读取（enumerate_github 有 parr/pparr 笔误，避开）
    return (get_gh_token.read_one("git:https://github.com")
            or get_gh_token.read_one("github.com")
            or get_gh_token.enumerate_github())


def api(method, path, data=None, token=None):
    url = API + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cad-frame-push-disk",
    }
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 204:
                return {}
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:800]}", file=sys.stderr)
        raise


def get_remote_base_tree(token):
    main_ref = api("GET", "/git/refs/heads/main", token=token)
    parent = main_ref["object"]["sha"]
    parent_commit = api("GET", f"/git/commits/{parent}", token=token)
    base_tree = parent_commit["tree"]["sha"]
    t = api("GET", f"/git/trees/{base_tree}?recursive=1", token=token)
    if t.get("truncated"):
        raise SystemExit("远端 tree 被截断，需分块推送")
    remote = {e["path"]: e["sha"] for e in t.get("tree", []) if e.get("type") == "blob"}
    return parent, base_tree, remote


def get_remote_blob(token, sha):
    b = api("GET", f"/git/blobs/{sha}", token=token)
    return base64.b64decode(b["content"])


def verify(token, files):
    parent, base_tree, remote = get_remote_base_tree(token)
    print(f"远端 main : {parent}\nbase tree : {base_tree}\n")
    any_diff = False
    for f in files:
        f_norm = f.replace("\\", "/")
        local_bytes = open(f, "rb").read()
        if f_norm not in remote:
            print(f"## {f_norm}: 远端不存在（将作为新增文件）")
            any_diff = True
            continue
        remote_bytes = get_remote_blob(token, remote[f_norm])
        if remote_bytes == local_bytes:
            print(f"## {f_norm}: 与远端完全一致（无需改动）")
        else:
            any_diff = True
            rl = remote_bytes.decode("utf-8", errors="replace").splitlines()
            ll = local_bytes.decode("utf-8", errors="replace").splitlines()
            print(f"## {f_norm}: 与远端存在差异（远端 {len(rl)} 行 / 本地 {len(ll)} 行）")
            for line in difflib.unified_diff(rl, ll, "remote", "local", lineterm=""):
                print("   " + line)
    return any_diff


def push(token, msg, files):
    parent, base_tree, remote = get_remote_base_tree(token)
    entries = []
    for f in files:
        f_norm = f.replace("\\", "/")
        content = open(f, "rb").read()
        blob = api("POST", "/git/blobs",
                   {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"}, token)
        entries.append({"path": f_norm, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  blob {f_norm} -> {blob['sha']}")
        time.sleep(0.4)
    tree = api("POST", "/git/trees", {"base_tree": base_tree, "tree": entries}, token)
    print(f"新 tree  : {tree['sha']}")
    commit = api("POST", "/git/commits",
                 {"message": msg, "parents": [parent], "tree": tree["sha"]}, token)
    print(f"新 commit: {commit['sha']}")
    api("PATCH", "/git/refs/heads/main", {"sha": commit["sha"]}, token)
    print("已更新远端 main（仅改动指定文件，其余原样保留）。")


def main():
    token = get_token()
    if not token:
        raise SystemExit("缺少 GITHUB_TOKEN 且 wincred 读取失败")
    args = sys.argv[1:]
    if not args:
        raise SystemExit("用法: push_disk.py [verify|push <msg>] file1 [file2 ...]")
    mode = args[0]
    if mode == "verify":
        verify(token, args[1:])
    elif mode == "push":
        if len(args) < 3:
            raise SystemExit("push 需提供 commit message 与至少一个文件")
        push(token, args[1], args[2:])
    else:
        raise SystemExit(f"未知模式: {mode}")


if __name__ == "__main__":
    main()
