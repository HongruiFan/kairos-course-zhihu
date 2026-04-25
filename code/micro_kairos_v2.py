#!/usr/bin/env python3
"""
micro-kairos v2: 添加观察日志存储

在 v1 的基础上，增加只写日志存储（ObservationStore）。
目标：理解"严格写入纪律"和轻量索引设计。

运行: python micro_kairos_v2.py
预期输出: tick 运行，观察被记录到 .micro-kairos/observations/ 目录
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, List, Dict


# ============================================================================
# 核心数据结构（v1 继承）
# ============================================================================

class DecisionType(Enum):
    ACT = "act"
    SLEEP = "sleep"


@dataclass
class Tick:
    timestamp: float
    counter: int
    project_hash: str


@dataclass
class Decision:
    type: DecisionType
    action: Optional[Callable] = None
    reason: str = ""


# ============================================================================
# 新增：观察数据类型
# ============================================================================

@dataclass
class Observation:
    """
    观察记录：KAIROS 的"记忆原子"
    
    设计要点：
    - 不可变（创建后不改）
    - 自包含（含完整上下文）
    - 可序列化（JSON）
    """
    id: str
    timestamp: float
    type: str  # 'file_change', 'command', 'inference', 'user_action'
    content: str
    importance: float = 0.5  # 0-1，用于后续优先级排序
    
    def to_json(self) -> str:
        """序列化为 JSONL 行"""
        return json.dumps(asdict(self), ensure_ascii=False)


# ============================================================================
# 新增：观察存储（核心学习点）
# ============================================================================

class ObservationStore:
    """
    只写日志存储 —— KAIROS 记忆系统的核心设计
    
    关键原则：
    1. 严格写入纪律（Strict Write Discipline）
       - 先写数据，成功后更新索引
       - 确保索引永远指向有效数据
    
    2. 只追加（Append-only）
       - 观察一旦写入，永不修改
       - 删除通过"标记过时"实现，不物理删除
    
    3. 轻量索引
       - 索引只存指针（~150字符/条），不存内容
       - 原始转录永不加载到上下文
    """
    
    def __init__(self, base_dir: str = ".micro-kairos"):
        self.base_dir = base_dir
        self.obs_dir = os.path.join(base_dir, "observations")
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """确保目录存在"""
        os.makedirs(self.obs_dir, exist_ok=True)
    
    def _get_today_file(self) -> str:
        """获取今天的观察日志文件路径"""
        date = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.obs_dir, f"{date}.jsonl")
    
    def append(self, obs: Observation) -> bool:
        """
        只追加写入观察 —— 严格写入纪律的核心
        
        流程：
        1. 将观察序列化为 JSON
        2. 追加写入当日日志文件
        3. 返回成功状态（调用者可在成功后更新索引）
        
        注意：这里没有索引更新，那是调用者的责任
        """
        filepath = self._get_today_file()
        
        # 关键：'a' 模式 = 原子追加，不会破坏已有数据
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(obs.to_json() + '\n')
        
        # 严格写入纪律：文件写入成功后，才返回 True
        # 调用者应该在返回 True 后更新索引
        return True
    
    def query(self, since: Optional[float] = None, 
              pattern: Optional[str] = None,
              limit: int = 100) -> List[Observation]:
        """
        查询观察 —— grep 风格（不加载整个文件到内存）
        
        设计约束：
        - 逐行读取，不一次性加载整个文件
        - 支持时间过滤和模式匹配
        - 达到 limit 立即返回（控制内存）
        """
        results = []
        
        # 按文件名排序（日期顺序）
        for filename in sorted(os.listdir(self.obs_dir)):
            if not filename.endswith('.jsonl'):
                continue
            
            filepath = os.path.join(self.obs_dir, filename)
            
            # 逐行读取 —— 关键设计：不加载整个文件
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        
                        # 时间过滤
                        if since and data['timestamp'] < since:
                            continue
                        
                        # 模式匹配（简单 grep）
                        if pattern and pattern.lower() not in data['content'].lower():
                            continue
                        
                        results.append(Observation(**data))
                        
                        # 达到限制立即返回
                        if len(results) >= limit:
                            return results
                            
                    except json.JSONDecodeError:
                        # 损坏的行，跳过
                        continue
        
        return results
    
    def get_index(self) -> Dict:
        """
        获取轻量索引（< 100KB 设计目标）
        
        返回统计信息，不返回实际内容。
        这是 KAIROS 的常驻上下文内容。
        """
        index = {
            "files": [],
            "total_observations": 0,
            "last_updated": time.time()
        }
        
        for filename in sorted(os.listdir(self.obs_dir)):
            if not filename.endswith('.jsonl'):
                continue
            
            filepath = os.path.join(self.obs_dir, filename)
            count = 0
            
            with open(filepath, 'r') as f:
                for line in f:
                    if line.strip():
                        count += 1
            
            index["files"].append({
                "date": filename.replace('.jsonl', ''),
                "count": count,
                "path": filepath
            })
            index["total_observations"] += count
        
        return index
    
    def generate_summary(self) -> str:
        """生成索引摘要（模拟 MEMORY.md 的内容）"""
        index = self.get_index()
        lines = ["# KAIROS 观察索引", ""]
        
        # 只显示最近 7 天（控制上下文大小）
        for f in index["files"][-7:]:
            lines.append(f"## {f['date']}")
            lines.append(f"- 观察数: {f['count']}")
            lines.append("")
        
        lines.append(f"总计: {index['total_observations']} 条观察")
        return '\n'.join(lines)


# ============================================================================
# 核心组件：Tick 调度器（v1 继承，简化版）
# ============================================================================

class TickScheduler:
    def __init__(self, interval_ms: int = 3000, budget_ms: int = 5000):
        self.interval = interval_ms / 1000
        self.budget = budget_ms / 1000
        self.counter = 0
        self.evaluator: Optional[Callable[[Tick], Decision]] = None
        
    def register_evaluator(self, evaluator: Callable[[Tick], Decision]):
        self.evaluator = evaluator
        
    async def run(self, max_ticks: int = 15):
        print(f"🚀 KAIROS v2 启动（带观察存储）")
        print(f"   tick 间隔: {self.interval}s")
        print(f"   计划运行: {max_ticks} 个 tick\n")
        
        while self.counter < max_ticks:
            tick = Tick(
                timestamp=time.time(),
                counter=self.counter,
                project_hash=f"tick-{self.counter}"
            )
            
            if self.evaluator:
                decision = self.evaluator(tick)
                await self._execute(decision)
            
            self.counter += 1
            await asyncio.sleep(self.interval)
        
        print(f"\n✅ 完成 {max_ticks} 个 tick")
    
    async def _execute(self, decision: Decision):
        start = time.time()
        
        if decision.type == DecisionType.SLEEP:
            print(f"💤 Tick {self.counter}: {decision.reason}")
            return
        
        if decision.action:
            print(f"⚡ Tick {self.counter}: 执行行动")
            try:
                result = decision.action()
                if asyncio.iscoroutine(result):
                    await result
                elapsed = time.time() - start
                print(f"   ✅ 完成 ({elapsed:.2f}s)")
            except Exception as e:
                print(f"   ❌ 错误: {e}")


# ============================================================================
# 演示：评估器 + 观察存储
# ============================================================================

def create_evaluator(store: ObservationStore):
    """创建使用观察存储的评估器"""
    tick_count = 0
    
    def evaluator(tick: Tick) -> Decision:
        nonlocal tick_count
        tick_count += 1
        
        # 每 2 个 tick 生成一个观察
        if tick_count % 2 == 0:
            def record_observation():
                # 创建观察
                obs = Observation(
                    id=str(uuid.uuid4())[:8],
                    timestamp=time.time(),
                    type='file_change',
                    content=f'Tick {tick.counter}: 检测到项目状态变化',
                    importance=0.6
                )
                
                # 严格写入纪律：写入成功后，打印确认
                success = store.append(obs)
                if success:
                    print(f"   📝 记录观察: {obs.id}")
            
            return Decision(
                type=DecisionType.ACT,
                action=record_observation,
                reason='记录项目状态变化'
            )
        
        return Decision(
            type=DecisionType.SLEEP,
            reason='无新状态需要记录'
        )
    
    return evaluator


# ============================================================================
# 主程序
# ============================================================================

async def main():
    """v2 演示：tick + 观察存储"""
    
    # 初始化存储
    store = ObservationStore()
    
    # 初始化调度器
    scheduler = TickScheduler(interval_ms=2000, budget_ms=1000)
    scheduler.register_evaluator(create_evaluator(store))
    
    # 运行
    await scheduler.run(max_ticks=10)
    
    # 展示结果
    print("\n" + "=" * 40)
    print("观察存储统计:")
    print(store.generate_summary())
    
    # 展示查询功能
    print("\n" + "=" * 40)
    print("查询示例（含 '项目' 的观察）:")
    results = store.query(pattern="项目", limit=3)
    for obs in results:
        print(f"  - [{obs.id}] {obs.content}")


if __name__ == "__main__":
    asyncio.run(main())
