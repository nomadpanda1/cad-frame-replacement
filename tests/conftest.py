# -*- coding: utf-8 -*-
"""pytest 配置：把仓库根注入 sys.path，使 `import lib.*` 可用。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
