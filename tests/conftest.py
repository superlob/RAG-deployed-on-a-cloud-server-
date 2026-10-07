"""pytest 全局配置：live 测试默认跳过（需 RUN_LIVE_TESTS=1 显式开启）"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_LIVE_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="需要真实外部服务，设置 RUN_LIVE_TESTS=1 才运行")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
