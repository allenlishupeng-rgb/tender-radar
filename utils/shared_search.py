"""Avoid several colleagues launching the same expensive scan simultaneously."""
from threading import Lock
from crawlers.runner import run_search_with_status

_search_lock = Lock()


class SearchBusyError(RuntimeError):
    pass


def run_shared_search(**kwargs):
    if not _search_lock.acquire(blocking=False):
        raise SearchBusyError('已有同事正在搜索，请稍后刷新查看共享结果。')
    try:
        return run_search_with_status(**kwargs)
    finally:
        _search_lock.release()
