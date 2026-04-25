# micro-kairos 完整实现

> 极简版 KAIROS 克隆，用于学习和实验

```python
#!/usr/bin/env python3
"""
micro-kairos: A minimal KAIROS clone for educational purposes.

Usage:
    python micro_kairos.py
"""

import asyncio
import json
import os
import time
import uuid
import hashlib
from dataclasses import dataclass, asdict
from typing import Callable, Any, Optional, List, Dict
from enum import Enum
from collections import defaultdict

# ============================================================================
# Core Data Structures
# ============================================================================

class DecisionType(Enum):
    ACT = "act"
    SLEEP = "sleep"
    DEFER = "defer"

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

@dataclass
class Observation:
    id: str
    timestamp: float
    type: str  # 'file_change', 'command', 'inference'
    content: str
    importance: float = 0.5  # 0-1
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

@dataclass
class BudgetResult:
    status: str  # 'completed', 'deferred', 'timeout', 'error'
    completed_steps: int
    total_steps: int
    elapsed_ms: float
    checkpoint: Optional[Any] = None


# ============================================================================
# Component: Observation Store
# ============================================================================

class ObservationStore:
    """只写日志存储，支持轻量索引"""
    
    def __init__(self, base_dir: str = ".micro-kairos"):
        self.base_dir = base_dir
        self.obs_dir = os.path.join(base_dir, "observations")
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        os.makedirs(self.obs_dir, exist_ok=True)
    
    def _get_today_file(self) -> str:
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.obs_dir, f"{date}.jsonl")
    
    def append(self, obs: Observation) -> bool:
        """只追加写入观察 - 严格写入纪律"""
        filepath = self._get_today_file()
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(obs.to_json() + '\n')
        return True
    
    def query(self, since: Optional[float] = None, 
              pattern: Optional[str] = None,
              limit: int = 100) -> List[Observation]:
        """grep 风格查询（不加载整个文件到内存）"""
        results = []
        
        for filename in sorted(os.listdir(self.obs_dir)):
            if not filename.endswith('.jsonl'):
                continue
                
            filepath = os.path.join(self.obs_dir, filename)
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
                        
                        if len(results) >= limit:
                            return results
                            
                    except json.JSONDecodeError:
                        continue
        
        return results
    
    def get_index(self) -> Dict:
        """获取轻量索引（< 100KB）"""
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
        """生成索引摘要（用于常驻上下文）"""
        index = self.get_index()
        lines = ["# KAIROS 观察索引", ""]
        
        for f in index["files"][-7:]:  # 最近 7 天
            lines.append(f"## {f['date']}")
            lines.append(f"- 观察数: {f['count']}")
            lines.append(f"- 文件: {f['path']}")
            lines.append("")
        
        return '\n'.join(lines)


# ============================================================================
# Component: Budget Executor
# ============================================================================

class BudgetExecutor:
    """预算约束执行器"""
    
    def __init__(self, budget_ms: int = 15000):
        self.budget_ms = budget_ms
    
    async def execute(self, 
                      steps: List[Callable],
                      on_defer: Optional[Callable] = None) -> BudgetResult:
        """执行步骤序列，遵守预算约束"""
        start = time.time()
        completed = 0
        checkpoint = None
        
        for i, step in enumerate(steps):
            elapsed_ms = (time.time() - start) * 1000
            remaining_ms = self.budget_ms - elapsed_ms
            
            # 检查预算
            if remaining_ms <= 0:
                print(f"⏰ 预算耗尽！已完成 {i}/{len(steps)} 步")
                checkpoint = {
                    "completed": i,
                    "remaining": steps[i:],
                    "timestamp": time.time()
                }
                if on_defer:
                    on_defer(checkpoint)
                return BudgetResult(
                    status='deferred',
                    completed_steps=i,
                    total_steps=len(steps),
                    elapsed_ms=elapsed_ms,
                    checkpoint=checkpoint
                )
            
            try:
                # 执行单步
                if asyncio.iscoroutinefunction(step):
                    await step()
                else:
                    step()
                completed += 1
                
            except Exception as e:
                print(f"❌ 步骤 {i} 失败: {e}")
                return BudgetResult(
                    status='error',
                    completed_steps=i,
                    total_steps=len(steps),
                    elapsed_ms=(time.time() - start) * 1000
                )
        
        elapsed_ms = (time.time() - start) * 1000
        return BudgetResult(
            status='completed',
            completed_steps=completed,
            total_steps=len(steps),
            elapsed_ms=elapsed_ms
        )


# ============================================================================
# Component: Simple Consolidator
# ============================================================================

class SimpleConsolidator:
    """简化版记忆整合器"""
    
    def __init__(self, store: ObservationStore):
        self.store = store
        self.min_observations = 10
    
    def should_run(self) -> bool:
        """检查是否应该运行整合"""
        index = self.store.get_index()
        return index["total_observations"] >= self.min_observations
    
    def consolidate(self) -> Dict:
        """简单整合：按主题聚类，提取关键洞察"""
        print("🌙 开始记忆整合...")
        
        # 1. 读取所有观察
        observations = self.store.query(limit=1000)
        
        # 2. 按类型聚类
        by_type = defaultdict(list)
        for obs in observations:
            by_type[obs.type].append(obs)
        
        # 3. 生成摘要
        summary = {
            "timestamp": time.time(),
            "total_observations": len(observations),
            "by_type": {
                t: len(items) for t, items in by_type.items()
            },
            "key_insights": self._extract_insights(observations),
            "patterns": self._find_patterns(observations)
        }
        
        print(f"✅ 整合完成：{len(observations)} 条观察 → {len(summary['key_insights'])} 条洞察")
        return summary
    
    def _extract_insights(self, observations: List[Observation]) -> List[str]:
        """提取关键洞察"""
        insights = []
        
        # 找高频词
        content = ' '.join([obs.content for obs in observations])
        words = content.lower().split()
        word_freq = defaultdict(int)
        for w in words:
            if len(w) > 3:
                word_freq[w] += 1
        
        top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_words:
            insights.append(f"高频主题: {', '.join([w for w, _ in top_words])}")
        
        # 找高重要性观察
        important = [obs for obs in observations if obs.importance > 0.8]
        if important:
            insights.append(f"高重要性事件: {len(important)} 条")
        
        return insights
    
    def _find_patterns(self, observations: List[Observation]) -> List[str]:
        """发现模式"""
        patterns = []
        
        timestamps = [obs.timestamp for obs in observations]
        if timestamps:
            time_range = max(timestamps) - min(timestamps)
            hours = time_range / 3600
            patterns.append(f"观察时间跨度: {hours:.1f} 小时")
        
        return patterns


# ============================================================================
# Component: Tick Scheduler
# ============================================================================

class TickScheduler:
    """Tick 调度器 - KAIROS 核心"""
    
    def __init__(self, interval_ms: int = 5000, budget_ms: int = 15000):
        self.interval = interval_ms / 1000
        self.budget = budget_ms / 1000
        self.counter = 0
        self.evaluator: Optional[Callable[[Tick], Decision]] = None
        
    def register_evaluator(self, evaluator: Callable[[Tick], Decision]):
        """注册 tick 评估函数"""
        self.evaluator = evaluator
        
    async def run(self, max_ticks: Optional[int] = None):
        """主循环"""
        print(f"🚀 KAIROS 启动 (tick={self.interval}s, budget={self.budget}s)")
        
        while max_ticks is None or self.counter < max_ticks:
            tick = Tick(
                timestamp=time.time(),
                counter=self.counter,
                project_hash=self._get_project_hash()
            )
            
            if self.evaluator:
                decision = self.evaluator(tick)
                await self._execute(decision)
            
            self.counter += 1
            await asyncio.sleep(self.interval)
    
    async def _execute(self, decision: Decision):
        """执行决策，遵守预算"""
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
                
                if elapsed > self.budget:
                    print(f"⏰ 警告：行动超时 ({elapsed:.2f}s > {self.budget}s)")
                else:
                    print(f"✅ 完成 ({elapsed:.2f}s)")
                    
            except Exception as e:
                print(f"❌ 错误: {e}")
    
    def _get_project_hash(self) -> str:
        """获取项目状态指纹"""
        files = []
        for root, _, filenames in os.walk('.'):
            for f in filenames:
                if f.endswith('.py'):
                    path = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(path)
                        files.append(f"{path}:{mtime}")
                    except:
                        pass
        
        return hashlib.md5(','.join(files).encode()).hexdigest()[:8]


# ============================================================================
# Main Demo
# ============================================================================

async def main():
    """micro-kairos 演示"""
    
    # 初始化组件
    store = ObservationStore()
    scheduler = TickScheduler(interval_ms=3000, budget_ms=5000)
    consolidator = SimpleConsolidator(store)
    
    # 模拟观察生成
    tick_count = 0
    
    def evaluator(tick: Tick) -> Decision:
        nonlocal tick_count
        tick_count += 1
        
        # 模拟：每 3 个 tick 生成一个观察
        if tick_count % 3 == 0:
            obs = Observation(
                id=str(uuid.uuid4())[:8],
                timestamp=time.time(),
                type='file_change',
                content=f'检测到项目状态变化: {tick.project_hash}',
                importance=0.6
            )
            store.append(obs)
            print(f"📝 记录观察: {obs.id}")
        
        # 模拟：每 10 个 tick 尝试整合
        if tick_count % 10 == 0 and consolidator.should_run():
            return Decision(
                type=DecisionType.ACT,
                action=consolidator.consolidate,
                reason='运行记忆整合'
            )
        
        # 默认睡眠
        return Decision(
            type=DecisionType.SLEEP,
            reason='无高价值行动'
        )
    
    scheduler.register_evaluator(evaluator)
    
    # 运行演示
    print("=" * 50)
    print("micro-kairos 演示")
    print("=" * 50)
    await scheduler.run(max_ticks=20)
    
    # 打印最终索引
    print("\n" + "=" * 50)
    print("最终观察索引:")
    print(store.generate_summary())


if __name__ == "__main__":
    asyncio.run(main())
