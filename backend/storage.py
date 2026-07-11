"""数据存储可视化 —— .cache 目录清单 / 资产备份 / 缓存清理。

分类口径：
- 资产（asset）：不可再生的用户数据——复盘池、影子样本存档、因子权重、持仓。
  丢了就没了，建议纳入备份。
- 缓存（cache）：可随时删、下次访问自动重建——扫描缓存、资讯雷达缓存。
- 其他（other）：未登记的文件/目录，只展示不操作。
"""

from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")
BEIJING = timezone(timedelta(hours=8))

# 登记表：{相对路径: (类型, 名称, 说明)}
REGISTRY = {
    "reviewpool.json": ("asset", "复盘池", "入池记录与收益跟踪（复盘工作台）"),
    "samples": ("asset", "影子样本存档", "每日候选自动存档——策略表现统计的数据基础"),
    "factor_weights.json": ("asset", "因子权重", "综合分权重配置"),
    "portfolio.json": ("asset", "持仓数据", "「我的持仓」录入的持仓与清仓记录"),
    "myreports": ("asset", "我的研报", "上传的研报文件"),
    "scancache.json": ("cache", "扫描缓存", "候选扫描结果（自动重建）"),
    "radar.json": ("cache", "资讯雷达缓存", "RSS 抓取结果（自动重建）"),
}


def _size_of(path: str) -> tuple[int, int]:
    """(总字节数, 文件数)。文件或目录均可。"""
    if os.path.isfile(path):
        return os.path.getsize(path), 1
    total = files = 0
    for root, _, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                continue
    return total, files


def inventory() -> dict:
    """.cache 清单：登记项 + 未登记项，含大小/文件数/最后更新/绝对路径。"""
    items = []
    seen = set()
    for rel, (kind, name, desc) in REGISTRY.items():
        path = os.path.join(CACHE_DIR, rel)
        seen.add(rel)
        if not os.path.exists(path):
            items.append({"key": rel, "kind": kind, "name": name, "desc": desc,
                          "path": path, "size": 0, "files": 0, "mtime": None, "exists": False})
            continue
        size, files = _size_of(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path), BEIJING).strftime("%Y-%m-%d %H:%M")
        items.append({"key": rel, "kind": kind, "name": name, "desc": desc,
                      "path": path, "size": size, "files": files, "mtime": mtime, "exists": True})
    # 未登记项如实展示（不操作）
    try:
        for n in sorted(os.listdir(CACHE_DIR)):
            if n in seen or n.endswith(".tmp"):
                continue
            path = os.path.join(CACHE_DIR, n)
            size, files = _size_of(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path), BEIJING).strftime("%Y-%m-%d %H:%M")
            items.append({"key": n, "kind": "other", "name": n, "desc": "未登记项（不参与备份/清理）",
                          "path": path, "size": size, "files": files, "mtime": mtime, "exists": True})
    except FileNotFoundError:
        pass
    return {
        "dir": CACHE_DIR,
        "total_size": sum(i["size"] for i in items),
        "asset_size": sum(i["size"] for i in items if i["kind"] == "asset"),
        "items": items,
    }


def backup_zip() -> bytes:
    """把全部「资产」类打包成 zip（内存构建，前端直接下载）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, (kind, _, _) in REGISTRY.items():
            if kind != "asset":
                continue
            path = os.path.join(CACHE_DIR, rel)
            if os.path.isfile(path):
                zf.write(path, rel)
            elif os.path.isdir(path):
                for root, _, names in os.walk(path):
                    for n in names:
                        full = os.path.join(root, n)
                        zf.write(full, os.path.relpath(full, CACHE_DIR))
    return buf.getvalue()


def clear_caches() -> dict:
    """删除「缓存」类文件（自动重建），并清后端内存缓存。返回释放的字节数。"""
    freed = 0
    removed = []
    for rel, (kind, name, _) in REGISTRY.items():
        if kind != "cache":
            continue
        path = os.path.join(CACHE_DIR, rel)
        if os.path.isfile(path):
            try:
                freed += os.path.getsize(path)
                os.remove(path)
                removed.append(name)
            except OSError:
                continue
    try:
        import screener
        screener._CACHE.clear()   # 内存缓存一并清（下次访问重建）
    except Exception:
        pass
    return {"freed": freed, "removed": removed}
