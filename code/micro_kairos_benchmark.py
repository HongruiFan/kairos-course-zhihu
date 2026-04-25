#!/usr/bin/env python3
"""
micro-kairos benchmark: 数值实验验证

测试项：
1. 索引 vs 完整转录的 Token 占用对比
2. 不同 tick 间隔的 CPU 占用
3. 查询性能：grep 风格 vs 全量加载

运行: python micro_kairos_benchmark.py
"""

import time
import os
import json
import random
import string
from datetime import datetime, timedelta
from typing import List, Dict
import sys

# 模拟 Token 计数（简化版：1 token ≈ 4 字符）
def count_tokens(text: str) -> int:
    return len(text) // 4


def generate_random_content(length: int = 200) -> str:
    """生成指定长度的随机文本（模拟观察内容）"""
    words = ['function', 'api', 'user', 'auth', 'login', 'error', 'fix', 'refactor', 
             'test', 'deploy', 'config', 'database', 'query', 'response', 'request']
    content = []
    while len(' '.join(content)) < length * 4:
        content.append(random.choice(words))
    return ' '.join(content)[:length * 4]


class BenchmarkStore:
    """用于基准测试的存储实现"""
    
    def __init__(self, base_dir: str = ".benchmark-kairos"):
        self.base_dir = base_dir
        self.obs_dir = os.path.join(base_dir, "observations")
        os.makedirs(self.obs_dir, exist_ok=True)
        self.observations: List[Dict] = []
    
    def generate_data(self, days: int = 30, obs_per_day: int = 50):
        """生成模拟观察数据"""
        print(f"📝 生成 {days} 天 × {obs_per_day} 条 = {days * obs_per_day} 条观察...")
        
        for day in range(days):
            date = (datetime.now() - timedelta(days=day)).strftime("%Y-%m-%d")
            filepath = os.path.join(self.obs_dir, f"{date}.jsonl")
            
            with open(filepath, 'w') as f:
                for i in range(obs_per_day):
                    obs = {
                        "id": ''.join(random.choices(string.ascii_lowercase, k=8)),
                        "timestamp": time.time() - day * 86400 - i * 100,
                        "type": random.choice(['file_change', 'command', 'inference']),
                        "content": generate_random_content(200),
                        "importance": random.random()
                    }
                    f.write(json.dumps(obs) + '\n')
                    self.observations.append(obs)
        
        print(f"   ✅ 生成完成，共 {len(self.observations)} 条观察")
    
    def load_full_transcripts(self) -> str:
        """模拟加载完整转录（Naive 实现）"""
        all_content = []
        for obs in self.observations:
            all_content.append(json.dumps(obs))
        return '\n'.join(all_content)
    
    def load_index_only(self) -> str:
        """加载轻量索引（KAIROS 实现）"""
        lines = ["# KAIROS 观察索引", ""]
        
        for filename in sorted(os.listdir(self.obs_dir)):
            if not filename.endswith('.jsonl'):
                continue
            
            filepath = os.path.join(self.obs_dir, filename)
            count = 0
            with open(filepath, 'r') as f:
                for line in f:
                    if line.strip():
                        count += 1
            
            date = filename.replace('.jsonl', '')
            lines.append(f"## {date}")
            lines.append(f"- 观察数: {count}")
            lines.append(f"- 关键事件: {random.choice(['重构', '新增', '修复'])}模块")
            lines.append("")
        
        return '\n'.join(lines)
    
    def query_grep_style(self, pattern: str = "api", limit: int = 10) -> List[Dict]:
        """Grep 风格查询（只加载匹配项）"""
        results = []
        
        for filename in sorted(os.listdir(self.obs_dir)):
            if not filename.endswith('.jsonl'):
                continue
            
            filepath = os.path.join(self.obs_dir, filename)
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        if pattern.lower() in data['content'].lower():
                            results.append(data)
                            if len(results) >= limit:
                                return results
                    except json.JSONDecodeError:
                        continue
        
        return results


def benchmark_token_usage():
    """实验 1: Token 占用对比"""
    print("\n" + "=" * 60)
    print("实验 1: 索引 vs 完整转录的 Token 占用对比")
    print("=" * 60)
    
    store = BenchmarkStore()
    store.generate_data(days=30, obs_per_day=50)
    
    # 方案 A: 加载完整转录
    print("\n📊 方案 A: 加载完整转录...")
    start = time.time()
    full_content = store.load_full_transcripts()
    full_tokens = count_tokens(full_content)
    full_time = time.time() - start
    print(f"   Token 数: {full_tokens:,}")
    print(f"   加载时间: {full_time:.3f}s")
    
    # 方案 B: 加载轻量索引
    print("\n📊 方案 B: 加载轻量索引...")
    start = time.time()
    index_content = store.load_index_only()
    index_tokens = count_tokens(index_content)
    index_time = time.time() - start
    print(f"   Token 数: {index_tokens:,}")
    print(f"   加载时间: {index_time:.3f}s")
    
    # 方案 C: 索引 + 按需加载
    print("\n📊 方案 C: 索引 + 按需加载 (grep 'api')...")
    start = time.time()
    matches = store.query_grep_style(pattern="api", limit=10)
    match_content = json.dumps(matches)
    match_tokens = count_tokens(match_content)
    total_tokens = index_tokens + match_tokens
    query_time = time.time() - start
    print(f"   匹配数: {len(matches)} 条")
    print(f"   匹配内容 Token: {match_tokens:,}")
    print(f"   总计 Token: {total_tokens:,}")
    print(f"   查询时间: {query_time:.3f}s")
    
    # 结果汇总
    print("\n" + "-" * 60)
    print("结果汇总:")
    print(f"   完整转录: {full_tokens:,} tokens")
    print(f"   轻量索引: {index_tokens:,} tokens")
    print(f"   索引+按需: {total_tokens:,} tokens")
    print(f"   节省比例: {(1 - total_tokens / full_tokens) * 100:.1f}%")
    print(f"   内存效率提升: {full_tokens / total_tokens:.1f}×")
    print("-" * 60)
    
    # 清理
    import shutil
    shutil.rmtree(store.base_dir, ignore_errors=True)


def benchmark_tick_interval():
    """实验 2: 不同 tick 间隔的 CPU 占用"""
    print("\n" + "=" * 60)
    print("实验 2: Tick 间隔的 CPU 占用对比")
    print("=" * 60)
    
    # 清理并重新创建
    import shutil
    store = BenchmarkStore()
    shutil.rmtree(store.base_dir, ignore_errors=True)
    os.makedirs(store.obs_dir, exist_ok=True)
    
    store.generate_data(days=7, obs_per_day=50)  # 较少的测试数据
    
    intervals = [0.1, 0.5, 1.0, 3.0, 5.0]  # 秒
    duration = 10  # 每个测试运行 10 秒
    
    print(f"\n⏱️  测试时长: {duration} 秒/配置")
    print("   数据规模: 350 条观察")
    print()
    
    results = []
    
    for interval in intervals:
        print(f"   测试间隔 {interval}s...", end=' ', flush=True)
        
        start_time = time.time()
        tick_count = 0
        cpu_work_time = 0
        
        while time.time() - start_time < duration:
            tick_start = time.time()
            
            # 模拟 tick 工作：扫描文件 + 简单评估
            _ = store.load_index_only()
            _ = store.query_grep_style(pattern="function", limit=5)
            
            work_time = time.time() - tick_start
            cpu_work_time += work_time
            tick_count += 1
            
            # 睡眠到下一个 tick
            sleep_time = interval - work_time
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        total_time = time.time() - start_time
        cpu_percent = (cpu_work_time / total_time) * 100
        ticks_per_sec = tick_count / total_time
        
        results.append({
            'interval': interval,
            'cpu': cpu_percent,
            'ticks_per_sec': ticks_per_sec,
            'total_ticks': tick_count
        })
        
        print(f"✅ CPU: {cpu_percent:.2f}%, Ticks: {tick_count}")
    
    # 结果表格
    print("\n" + "-" * 60)
    print(f"{'Tick 间隔':<12} {'CPU 占用':<12} {'每秒 Tick':<12} {'总 Ticks':<12}")
    print("-" * 60)
    
    for r in results:
        print(f"{r['interval']:<12.1f}s {r['cpu']:<12.2f}% {r['ticks_per_sec']:<12.2f} {r['total_ticks']:<12}")
    
    print("-" * 60)
    
    # 可视化
    print("\n📈 CPU 占用可视化:")
    max_cpu = max(r['cpu'] for r in results)
    
    for r in results:
        bar_len = int((r['cpu'] / max_cpu) * 40)
        bar = "█" * bar_len
        print(f"{r['interval']:>5.1f}s │{bar:<40}│ {r['cpu']:>5.2f}%")
    
    # 清理
    import shutil
    shutil.rmtree(store.base_dir, ignore_errors=True)


def benchmark_query_performance():
    """实验 3: 查询性能对比"""
    print("\n" + "=" * 60)
    print("实验 3: 查询性能对比 (Grep 风格 vs 全量加载)")
    print("=" * 60)
    
    # 清理并重新创建
    import shutil
    store = BenchmarkStore()
    shutil.rmtree(store.base_dir, ignore_errors=True)
    os.makedirs(store.obs_dir, exist_ok=True)
    
    store.generate_data(days=30, obs_per_day=50)
    
    test_pattern = "api"
    iterations = 100
    
    # 方案 A: 全量加载后过滤
    print(f"\n📊 方案 A: 全量加载 + 内存过滤...")
    start = time.time()
    for _ in range(iterations):
        all_obs = []
        for filename in sorted(os.listdir(store.obs_dir)):
            if not filename.endswith('.jsonl'):
                continue
            with open(os.path.join(store.obs_dir, filename), 'r') as f:
                for line in f:
                    if line.strip():
                        all_obs.append(json.loads(line))
        matches = [o for o in all_obs if test_pattern in o['content'].lower()][:10]
    full_time = (time.time() - start) / iterations
    print(f"   平均耗时: {full_time * 1000:.2f} ms/查询")
    print(f"   内存占用: ~{len(all_obs)} 条观察全量加载")
    
    # 方案 B: Grep 风格（逐行读取，提前终止）
    print("\n📊 方案 B: Grep 风格（逐行读取）...")
    start = time.time()
    for _ in range(iterations):
        matches = store.query_grep_style(pattern=test_pattern, limit=10)
    grep_time = (time.time() - start) / iterations
    print(f"   平均耗时: {grep_time * 1000:.2f} ms/查询")
    print(f"   内存占用: 仅 {len(matches)} 条匹配结果")
    
    # 结果
    print("\n" + "-" * 60)
    speedup = full_time / grep_time
    print(f"性能提升: {speedup:.1f}×")
    print(f"内存效率: 减少 ~{len(all_obs) - len(matches)} 条观察的内存占用")
    print("-" * 60)
    
    # 清理
    import shutil
    shutil.rmtree(store.base_dir, ignore_errors=True)


def main():
    """运行所有基准测试"""
    print("\n" + "╔" + "=" * 58 + "╗")
    print("║" + " " * 15 + "micro-kairos 基准测试" + " " * 22 + "║")
    print("║" + " " * 10 + "验证 KAIROS 设计决策的数值实验" + " " * 16 + "║")
    print("╚" + "=" * 58 + "╝")
    
    benchmark_token_usage()
    benchmark_tick_interval()
    benchmark_query_performance()
    
    print("\n" + "=" * 60)
    print("✅ 所有基准测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
