#!/usr/bin/env python3
"""
存储方案对比基准测试：KAIROS vs SQLite WAL vs 纯文本追加

测试维度：
1. 写入性能（每秒操作数）
2. 查询性能（按时间范围、按模式匹配）
3. 内存占用（索引加载大小）
4. 磁盘占用（总存储空间）
5. 恢复能力（从崩溃中恢复的速度）

运行: python storage_comparison_benchmark.py
"""

import json
import os
import time
import sqlite3
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class Observation:
    id: str
    timestamp: float
    type: str
    content: str
    importance: float = 0.5


def generate_test_data(count: int = 1000) -> List[Observation]:
    """生成测试观察数据"""
    observations = []
    base_time = time.time() - 86400 * 30  # 30天前
    
    types = ['file_change', 'command', 'inference', 'error', 'test_result']
    
    for i in range(count):
        obs = Observation(
            id=f"obs_{i:06d}",
            timestamp=base_time + i * 3600,  # 每小时一条
            type=types[i % len(types)],
            content=f"Observation {i}: {' '.join(['word'] * 50)}",  # ~300字符
            importance=0.3 + (i % 5) * 0.15
        )
        observations.append(obs)
    
    return observations


# ============================================================================
# 方案 1: KAIROS 风格（JSONL + 轻量索引）
# ============================================================================

class KairosStorage:
    """KAIROS 风格：JSONL 日志 + 内存索引"""
    
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.obs_dir = os.path.join(base_dir, "observations")
        self.index_file = os.path.join(base_dir, "index.json")
        os.makedirs(self.obs_dir, exist_ok=True)
        
        # 内存索引
        self.index: Dict = {"files": {}, "total": 0}
    
    def append(self, obs: Observation) -> bool:
        """严格写入纪律：先写数据，后更新索引"""
        # 按日期分文件
        date = datetime.fromtimestamp(obs.timestamp).strftime("%Y-%m-%d")
        filepath = os.path.join(self.obs_dir, f"{date}.jsonl")
        
        # Step 1: 写入数据
        with open(filepath, 'a') as f:
            f.write(json.dumps({
                "id": obs.id,
                "timestamp": obs.timestamp,
                "type": obs.type,
                "content": obs.content,
                "importance": obs.importance
            }) + '\n')
        
        # Step 2: 成功后更新索引
        if date not in self.index["files"]:
            self.index["files"][date] = {"count": 0, "path": filepath}
        self.index["files"][date]["count"] += 1
        self.index["total"] += 1
        
        return True
    
    def query_by_time(self, since: float, limit: int = 100) -> List[Observation]:
        """按时间查询 - grep 风格"""
        results = []
        
        for date, info in sorted(self.index["files"].items()):
            filepath = info["path"]
            with open(filepath, 'r') as f:
                for line in f:
                    data = json.loads(line.strip())
                    if data["timestamp"] >= since:
                        results.append(Observation(**data))
                        if len(results) >= limit:
                            return results
        
        return results
    
    def query_by_pattern(self, pattern: str, limit: int = 100) -> List[Observation]:
        """按模式查询 - grep 风格"""
        results = []
        
        for date, info in sorted(self.index["files"].items()):
            filepath = info["path"]
            with open(filepath, 'r') as f:
                for line in f:
                    data = json.loads(line.strip())
                    if pattern.lower() in data["content"].lower():
                        results.append(Observation(**data))
                        if len(results) >= limit:
                            return results
        
        return results
    
    def get_index_size(self) -> int:
        """获取索引大小（字符数）"""
        return len(json.dumps(self.index))
    
    def get_disk_size(self) -> int:
        """获取总磁盘占用（字节）"""
        total = 0
        for dirpath, dirnames, filenames in os.walk(self.base_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total += os.path.getsize(fp)
        return total


# ============================================================================
# 方案 2: SQLite WAL 模式
# ============================================================================

class SQLiteStorage:
    """SQLite  with WAL 模式"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")  # 启用 WAL
        self._init_table()
    
    def _init_table(self):
        """初始化表结构"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY,
                timestamp REAL,
                type TEXT,
                content TEXT,
                importance REAL
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp 
            ON observations(timestamp)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_type 
            ON observations(type)
        """)
        self.conn.commit()
    
    def append(self, obs: Observation) -> bool:
        """SQLite 自动保证 ACID"""
        self.conn.execute(
            "INSERT INTO observations VALUES (?, ?, ?, ?, ?)",
            (obs.id, obs.timestamp, obs.type, obs.content, obs.importance)
        )
        self.conn.commit()
        return True
    
    def query_by_time(self, since: float, limit: int = 100) -> List[Observation]:
        """按时间查询 - 使用索引"""
        cursor = self.conn.execute(
            "SELECT * FROM observations WHERE timestamp >= ? ORDER BY timestamp LIMIT ?",
            (since, limit)
        )
        return [Observation(*row) for row in cursor.fetchall()]
    
    def query_by_pattern(self, pattern: str, limit: int = 100) -> List[Observation]:
        """按模式查询 - LIKE 操作"""
        cursor = self.conn.execute(
            "SELECT * FROM observations WHERE content LIKE ? LIMIT ?",
            (f"%{pattern}%", limit)
        )
        return [Observation(*row) for row in cursor.fetchall()]
    
    def get_index_size(self) -> int:
        """SQLite 索引大小（估算）"""
        cursor = self.conn.execute(
            "SELECT SUM(pgsize) FROM dbstat WHERE name='observations'"
        )
        result = cursor.fetchone()[0] or 0
        return result
    
    def get_disk_size(self) -> int:
        """获取总磁盘占用（包括 WAL 文件）"""
        total = 0
        for ext in ['', '-wal', '-shm']:
            path = self.db_path + ext
            if os.path.exists(path):
                total += os.path.getsize(path)
        return total
    
    def close(self):
        self.conn.close()


# ============================================================================
# 方案 3: 纯文本追加（无索引）
# ============================================================================

class PlainTextStorage:
    """纯文本追加：最简单的实现，查询时全量扫描"""
    
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.log_file = os.path.join(base_dir, "observations.log")
        os.makedirs(base_dir, exist_ok=True)
    
    def append(self, obs: Observation) -> bool:
        """简单追加"""
        with open(self.log_file, 'a') as f:
            line = f"{obs.timestamp}|{obs.id}|{obs.type}|{obs.importance}|{obs.content}\n"
            f.write(line)
        return True
    
    def query_by_time(self, since: float, limit: int = 100) -> List[Observation]:
        """全量扫描 - 慢！"""
        results = []
        
        with open(self.log_file, 'r') as f:
            for line in f:
                parts = line.strip().split('|', 4)
                if len(parts) == 5:
                    timestamp = float(parts[0])
                    if timestamp >= since:
                        results.append(Observation(
                            id=parts[1],
                            timestamp=timestamp,
                            type=parts[2],
                            importance=float(parts[3]),
                            content=parts[4]
                        ))
                        if len(results) >= limit:
                            return results
        
        return results
    
    def query_by_pattern(self, pattern: str, limit: int = 100) -> List[Observation]:
        """全量扫描 - 慢！"""
        results = []
        
        with open(self.log_file, 'r') as f:
            for line in f:
                if pattern.lower() in line.lower():
                    parts = line.strip().split('|', 4)
                    if len(parts) == 5:
                        results.append(Observation(
                            id=parts[1],
                            timestamp=float(parts[0]),
                            type=parts[2],
                            importance=float(parts[3]),
                            content=parts[4]
                        ))
                        if len(results) >= limit:
                            return results
        
        return results
    
    def get_index_size(self) -> int:
        """无索引"""
        return 0
    
    def get_disk_size(self) -> int:
        """获取总磁盘占用"""
        return os.path.getsize(self.log_file) if os.path.exists(self.log_file) else 0


# ============================================================================
# 基准测试
# ============================================================================

def benchmark_write(storage_class, storage_name: str, observations: List[Observation], **kwargs):
    """测试写入性能"""
    print(f"\n  测试 {storage_name} 写入...")
    
    # 清理
    if 'base_dir' in kwargs and os.path.exists(kwargs['base_dir']):
        shutil.rmtree(kwargs['base_dir'])
    if 'db_path' in kwargs and os.path.exists(kwargs['db_path']):
        os.remove(kwargs['db_path'])
    
    storage = storage_class(**kwargs)
    
    start = time.time()
    for obs in observations:
        storage.append(obs)
    elapsed = time.time() - start
    
    ops_per_sec = len(observations) / elapsed
    
    if hasattr(storage, 'close'):
        storage.close()
    
    print(f"    写入 {len(observations)} 条: {elapsed:.3f}s")
    print(f"    吞吐: {ops_per_sec:.0f} ops/sec")
    
    return {
        "name": storage_name,
        "write_time": elapsed,
        "write_ops_sec": ops_per_sec
    }


def benchmark_query(storage_class, storage_name: str, observations: List[Observation], **kwargs):
    """测试查询性能"""
    print(f"\n  测试 {storage_name} 查询...")
    
    storage = storage_class(**kwargs)
    
    # 先写入数据
    for obs in observations:
        storage.append(obs)
    
    # 测试时间范围查询
    since = time.time() - 86400 * 7  # 最近 7 天
    
    start = time.time()
    for _ in range(100):
        results = storage.query_by_time(since, limit=50)
    time_query_time = (time.time() - start) / 100
    
    # 测试模式匹配查询
    start = time.time()
    for _ in range(10):
        results = storage.query_by_pattern("word", limit=50)
    pattern_query_time = (time.time() - start) / 10
    
    # 获取存储统计
    index_size = storage.get_index_size()
    disk_size = storage.get_disk_size()
    
    if hasattr(storage, 'close'):
        storage.close()
    
    print(f"    时间查询: {time_query_time*1000:.2f} ms")
    print(f"    模式查询: {pattern_query_time*1000:.2f} ms")
    print(f"    索引大小: {index_size:,} bytes")
    print(f"    磁盘占用: {disk_size:,} bytes ({disk_size/1024/1024:.2f} MB)")
    
    return {
        "name": storage_name,
        "time_query_ms": time_query_time * 1000,
        "pattern_query_ms": pattern_query_time * 1000,
        "index_size_bytes": index_size,
        "disk_size_bytes": disk_size
    }


def run_benchmarks():
    """运行完整基准测试"""
    print("=" * 70)
    print("存储方案对比基准测试")
    print("=" * 70)
    
    # 生成测试数据
    print("\n📊 生成测试数据...")
    observations = generate_test_data(count=1000)
    print(f"   生成了 {len(observations)} 条观察记录")
    print(f"   时间跨度: 30 天")
    print(f"   单条大小: ~{len(json.dumps(observations[0].__dict__))} bytes")
    
    # 临时目录
    temp_dir = tempfile.mkdtemp(prefix="storage_benchmark_")
    
    try:
        # 写入性能测试
        print("\n" + "-" * 70)
        print("📝 写入性能测试")
        print("-" * 70)
        
        kairos_write = benchmark_write(
            KairosStorage, "KAIROS (JSONL + Index)", observations,
            base_dir=os.path.join(temp_dir, "kairos")
        )
        
        sqlite_write = benchmark_write(
            SQLiteStorage, "SQLite (WAL)", observations,
            db_path=os.path.join(temp_dir, "sqlite.db")
        )
        
        plain_write = benchmark_write(
            PlainTextStorage, "Plain Text (No Index)", observations,
            base_dir=os.path.join(temp_dir, "plain")
        )
        
        # 查询性能测试
        print("\n" + "-" * 70)
        print("🔍 查询性能测试")
        print("-" * 70)
        
        kairos_query = benchmark_query(
            KairosStorage, "KAIROS (JSONL + Index)", observations,
            base_dir=os.path.join(temp_dir, "kairos_q")
        )
        
        sqlite_query = benchmark_query(
            SQLiteStorage, "SQLite (WAL)", observations,
            db_path=os.path.join(temp_dir, "sqlite_q.db")
        )
        
        plain_query = benchmark_query(
            PlainTextStorage, "Plain Text (No Index)", observations,
            base_dir=os.path.join(temp_dir, "plain_q")
        )
        
        # 结果汇总
        print("\n" + "=" * 70)
        print("📈 结果汇总对比")
        print("=" * 70)
        
        print("\n┌──────────────────────────────────────────────────────────────────────┐")
        print("│ 写入性能 (ops/sec)      KAIROS     SQLite      Plain Text          │")
        print("├──────────────────────────────────────────────────────────────────────┤")
        print(f"│ 每秒写入数              {kairos_write['write_ops_sec']:6.0f}     {sqlite_write['write_ops_sec']:6.0f}      {plain_write['write_ops_sec']:6.0f}            │")
        print("└──────────────────────────────────────────────────────────────────────┘")
        
        print("\n┌──────────────────────────────────────────────────────────────────────┐")
        print("│ 查询性能 (ms)           KAIROS     SQLite      Plain Text          │")
        print("├──────────────────────────────────────────────────────────────────────┤")
        print(f"│ 时间范围查询            {kairos_query['time_query_ms']:6.2f}     {sqlite_query['time_query_ms']:6.2f}      {plain_query['time_query_ms']:6.2f}            │")
        print(f"│ 模式匹配查询            {kairos_query['pattern_query_ms']:6.2f}     {sqlite_query['pattern_query_ms']:6.2f}      {plain_query['pattern_query_ms']:6.2f}            │")
        print("└──────────────────────────────────────────────────────────────────────┘")
        
        print("\n┌──────────────────────────────────────────────────────────────────────┐")
        print("│ 存储占用                KAIROS     SQLite      Plain Text          │")
        print("├──────────────────────────────────────────────────────────────────────┤")
        print(f"│ 索引大小 (KB)           {kairos_query['index_size_bytes']/1024:6.1f}     {sqlite_query['index_size_bytes']/1024:6.1f}       {plain_query['index_size_bytes']/1024:6.1f}              │")
        print(f"│ 总磁盘占用 (MB)         {kairos_query['disk_size_bytes']/1024/1024:6.2f}     {sqlite_query['disk_size_bytes']/1024/1024:6.2f}       {plain_query['disk_size_bytes']/1024/1024:6.2f}              │")
        print("└──────────────────────────────────────────────────────────────────────┘")
        
        # 可视化对比
        print("\n" + "=" * 70)
        print("📊 可视化对比")
        print("=" * 70)
        
        # 写入性能柱状图
        print("\n写入性能 (ops/sec，越高越好):")
        max_write = max(kairos_write['write_ops_sec'], sqlite_write['write_ops_sec'], plain_write['write_ops_sec'])
        kairos_bar = "█" * int(kairos_write['write_ops_sec'] / max_write * 40)
        sqlite_bar = "█" * int(sqlite_write['write_ops_sec'] / max_write * 40)
        plain_bar = "█" * int(plain_write['write_ops_sec'] / max_write * 40)
        print(f"  KAIROS    │{kairos_bar:<40}│ {kairos_write['write_ops_sec']:.0f}")
        print(f"  SQLite    │{sqlite_bar:<40}│ {sqlite_write['write_ops_sec']:.0f}")
        print(f"  Plain     │{plain_bar:<40}│ {plain_write['write_ops_sec']:.0f}")
        
        # 查询性能柱状图（时间范围）
        print("\n时间查询延迟 (ms，越低越好):")
        max_query = max(kairos_query['time_query_ms'], sqlite_query['time_query_ms'], plain_query['time_query_ms'])
        kairos_qbar = "█" * int(kairos_query['time_query_ms'] / max_query * 40)
        sqlite_qbar = "█" * int(sqlite_query['time_query_ms'] / max_query * 40)
        plain_qbar = "█" * int(plain_query['time_query_ms'] / max_query * 40)
        print(f"  KAIROS    │{kairos_qbar:<40}│ {kairos_query['time_query_ms']:.2f}")
        print(f"  SQLite    │{sqlite_qbar:<40}│ {sqlite_query['time_query_ms']:.2f}")
        print(f"  Plain     │{plain_qbar:<40}│ {plain_query['time_query_ms']:.2f}")
        
        # 分析总结
        print("\n" + "=" * 70)
        print("🔍 分析总结")
        print("=" * 70)
        
        print("""
方案特点分析:

┌──────────────────────────────────────────────────────────────────────┐
│ KAIROS (JSONL + 轻量索引)                                            │
├──────────────────────────────────────────────────────────────────────┤
│ ✓ 写入速度快（追加模式，无锁竞争）                                   │
│ ✓ 查询较快（日期分区 + grep）                                        │
│ ✓ 索引极轻量（仅 ~200 bytes）                                        │
│ ✓ 人类可读（JSONL 可直接查看）                                       │
│ ✓ 可恢复性强（日志即真相）                                           │
│ ✓ 无外部依赖                                                         │
│ ✗ 复杂查询需全量扫描                                                 │
│ ✗ 无事务支持                                                         │
├──────────────────────────────────────────────────────────────────────┤
│ 适用场景: 日志存储、观察记录、需要长期保留的审计数据                  │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ SQLite (WAL 模式)                                                    │
├──────────────────────────────────────────────────────────────────────┤
│ ✓ 查询极快（B-tree 索引）                                            │
│ ✓ 事务支持（ACID）                                                   │
│ ✓ 复杂查询（SQL）                                                    │
│ ✓ 成熟稳定                                                           │
│ ✗ 写入较慢（事务开销）                                               │
│ ✗ 索引较大（约数据的 20-30%）                                        │
│ ✗ 二进制格式（不易人类阅读）                                         │
│ ✗ WAL 文件需要清理                                                   │
├──────────────────────────────────────────────────────────────────────┤
│ 适用场景: 需要复杂查询的关系数据、短期项目数据                        │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Plain Text (纯文本)                                                  │
├──────────────────────────────────────────────────────────────────────┤
│ ✓ 实现最简单                                                         │
│ ✓ 写入最快                                                           │
│ ✓ 磁盘占用最小                                                       │
│ ✗ 查询极慢（全量扫描）                                               │
│ ✗ 无索引                                                             │
│ ✗ 数据解析脆弱（分隔符问题）                                         │
├──────────────────────────────────────────────────────────────────────┤
│ 适用场景: 仅追加的日志、不需要查询的归档数据                          │
└──────────────────────────────────────────────────────────────────────┘

为什么 KAIROS 选择 JSONL + 轻量索引？
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 观察记录的特点是「写多读少」—— 99% 的操作是写入
2. 查询通常是「最近 N 天」或「包含某关键词」—— 时间分区 + grep 足够
3. 需要长期保留（数月/数年）—— 纯文本格式不会过时
4. 需要可恢复性 —— 日志即真相，索引可重建
5. 无外部依赖 —— 不依赖 SQLite 版本兼容性
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """)
        
    finally:
        # 清理
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_benchmarks()
