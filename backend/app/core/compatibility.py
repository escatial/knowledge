"""兼容性补丁

问题：
1. huggingface_hub 0.19.4 没有 is_offline_mode 等旧 API
2. numpy 2.1 把 numpy.core 改名 numpy._core，但 torch 2.10 仍用 numpy.core
3. transformers 5.x 内部依赖这些

修复：在 transformers/torch 加载前 monkey-patch 所有需要的符号。
"""
import os
import logging
import sys

logger = logging.getLogger(__name__)


# 任务 P0: 兼容性补丁——补回被新版 huggingface_hub 移除的旧 API
def _stub_offline(*a, **k):
    return False


def _stub_list_repo_tree(*a, **k):
    return []


def _stub_empty_set():
    return set()


_HF_STUBS = {
    "is_offline_mode": _stub_offline,
    "OfflineModeIsEnabled": _stub_offline,
    "list_repo_tree": _stub_list_repo_tree,
    "hf_hub_url": lambda *a, **k: "",
    "try_to_load_from_cache": lambda *a, **k: None,
    "_CACHED_NO_EXIST": _stub_empty_set(),
    "scan_cache_dir": lambda *a, **k: [],
}


def _patch_numpy_core_compat():
    """numpy 2.1+ 把 numpy.core 改名 numpy._core，但 torch 2.10 仍用 numpy.core
    修复：直接把 numpy.core 替换为 numpy._core（绕过 deprecated wrapper）
    """
    try:
        import numpy
        import numpy._core as _np_core
        # 不管 numpy.core 是否已存在，都替换为 _core 的实际引用
        numpy.core = _np_core
        # 也注入到 sys.modules 让其他 import 找得到
        sys.modules["numpy.core"] = _np_core
        sys.modules["numpy.core.multiarray"] = _np_core.multiarray
        sys.modules["numpy.core.numeric"] = _np_core.numeric
        sys.modules["numpy.core.umath"] = _np_core.umath
        logger.info("[compatibility] patched numpy.core -> numpy._core (forced)")
    except ImportError as e:
        logger.warning(f"[compatibility] numpy patch failed: {e}")


def apply_compatibility_patches():
    """应用兼容性补丁——必须在 import transformers/torch 之前调用"""
    # 0) numpy.core shim（早于 transformers）
    _patch_numpy_core_compat()

    # 1) Patch huggingface_hub 顶层
    try:
        import huggingface_hub
        for name, stub in _HF_STUBS.items():
            if not hasattr(huggingface_hub, name):
                setattr(huggingface_hub, name, stub)
        sys.modules["huggingface_hub"] = huggingface_hub
    except ImportError:
        return

    # 2) Patch huggingface_hub.utils 子模块
    try:
        import huggingface_hub.utils as hf_utils
        for name, stub in _HF_STUBS.items():
            if not hasattr(hf_utils, name):
                setattr(hf_utils, name, stub)
        sys.modules["huggingface_hub.utils"] = hf_utils
    except (ImportError, AttributeError):
        pass

    # 3) Patch huggingface_hub.utils.telemetry 等子模块
    for submodule_name in [
        "huggingface_hub.utils",
        "huggingface_hub.utils.telemetry",
    ]:
        try:
            mod = __import__(submodule_name, fromlist=["*"])
            for name, stub in _HF_STUBS.items():
                if hasattr(mod, name) is False:
                    setattr(mod, name, stub)
        except (ImportError, AttributeError):
            pass


# 自动执行
apply_compatibility_patches()
