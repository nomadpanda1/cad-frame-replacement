# -*- coding: utf-8 -*-
"""从 Windows 凭据管理器(wincred)读取 GitHub PAT（target=git:https://github.com）。
仅使用 ctypes 调 advapi32!CredReadW（.NET 运行时编译被安全策略拦截，不可用）。
把 token 打印到 stdout，由调用方用 $() 捕获，不落盘。
"""
import ctypes
import ctypes.wintypes as wt


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR),
        ("LastWritten", wt.FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]


advapi32 = ctypes.windll.advapi32
advapi32.CredReadW.argtypes = [
    wt.LPCWSTR, wt.DWORD, wt.DWORD,
    ctypes.POINTER(ctypes.POINTER(CREDENTIAL)),
]
advapi32.CredReadW.restype = wt.BOOL
advapi32.CredFree.argtypes = [ctypes.POINTER(CREDENTIAL)]
advapi32.CredFree.restype = None
advapi32.CredEnumerateW.argtypes = [
    wt.LPCWSTR, wt.DWORD, ctypes.POINTER(wt.DWORD),
    ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(CREDENTIAL))),
]
advapi32.CredEnumerateW.restype = wt.BOOL
advapi32.CredFree.argtypes = [ctypes.POINTER(CREDENTIAL)]


def read_one(target):
    pcred = ctypes.POINTER(CREDENTIAL)()
    ok = advapi32.CredReadW(target, 1, 0, ctypes.byref(pcred))
    if not ok:
        return None
    try:
        size = pcred.contents.CredentialBlobSize
        blob = ctypes.string_at(pcred.contents.CredentialBlob, size)
        return blob.decode("utf-16-le").rstrip("\x00")
    finally:
        advapi32.CredFree(pcred)


def enumerate_github():
    pcount = wt.DWORD(0)
    pparr = ctypes.POINTER(ctypes.POINTER(CREDENTIAL))()
    ok = advapi32.CredEnumerateW(None, 0, ctypes.byref(pcount), ctypes.byref(parr))
    if not ok:
        return None
    try:
        for i in range(pcount.value):
            cred = parr[i].contents
            tname = cred.TargetName or ""
            if "github.com" in tname.lower():
                size = cred.CredentialBlobSize
                blob = ctypes.string_at(cred.CredentialBlob, size)
                return blob.decode("utf-16-le").rstrip("\x00")
    finally:
        advapi32.CredFree(parr)
    return None


def main():
    token = read_one("git:https://github.com") or read_one("github.com") or enumerate_github()
    if not token:
        raise SystemExit("未能从 wincred 读取 GitHub 凭据")
    print(token)


if __name__ == "__main__":
    main()
