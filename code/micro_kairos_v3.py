#!/usr/bin/env python3
"""
micro-kairos v3: 完整实现（添加记忆整合）

在 v2 的基础上，增加四重门记忆整合器（Consolidator）。
目标：理解 AutoDream 的触发机制、文件锁和 4 阶段整合流程。

运行: python micro_kairos_v3.py
预期输出: 完整的 tick → 观察 → 整合循环
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, List, Dict, Tuple
from collections import defaultdict


# ============================================================================
# 核心数据结构（v1/v2 继承）
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


@dataclass
class Observation:
    id: str
    timestamp: float
    type: str
    content: str
    importance: float = 0.5
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


# ============================================================================
# 组件：观察存储（v2 继承）
# ============================================================================

class ObservationStore:
    """只写日志存储"""
    
    def __init__(self, base_dir: str = ".micro-kairos"):
        self.base_dir = base_dir
        self.obs_dir = os.path.join(base_dir, "observations")
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        os.makedirs(self.obs_dir, exist_ok=True)
    
    def _get_today_file(self) -> str:
        date = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.obs_dir, f"{date}.jsonl")
    
    def append(self, obs: Observation) -> bool:
        """只追加写入观察 —— 严格写入纪律"""
        filepath = self._get_today_file()
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(obs.to_json() + '\n')
        return True
    
    def query(self, since: Optional[float] = None, 
              pattern: Optional[str] = None,
              limit: int = 100) -> List[Observation]:
        """grep 风格查询"""
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
                        
                        if since and data['timestamp'] < since:
                            continue
                        
                        if pattern and pattern.lower() not in data['content'].lower():
                            continue
                        
                        results.append(Observation(**data))
                        
                        if len(results) >= limit:
                            return results
                            
                    except json.JSONDecodeError:
                        continue
        
        return results
    
    def get_index(self) -> Dict:
        """获取轻量索引"""
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


# ============================================================================
# 新增：文件锁（mtime-based，源自 consolidationLock.ts）
# ============================================================================

@dataclass
class ConsolidationLock:
    """
    文件锁实现 —— mtime 即状态
    
    关键设计：
    - 锁文件的 mtime = lastConsolidatedAt（实际时间戳）
    - 文件内容 = 持有者 PID
    - 失败后可回滚 mtime（允许重试）
    """
    lock_file: str
    stale_ms: int = 60 * 60 * 1000  # 1小时过期
    
    def read_last_consolidated_at(self) -> float:
        """mtime of lock file = lastConsolidatedAt"""
        try:
            return os.path.getmtime(self.lock_file)
        except FileNotFoundError:
            return 0.0
    
    def try_acquire(self) -> Optional[float]:
        """
        尝试获取锁
        
        返回: 之前的 mtime（用于回滚），或 None（获取失败）
        """
        prior_mtime = self.read_last_consolidated_at()
        
        # 检查锁是否被持有
        if time.time() - prior_mtime < self.stale_ms:
            # 简化版：实际应检查 PID 是否存活
            return None
        
        # 写入当前时间（创建或更新文件）
        with open(self.lock_file, 'w') as f:
            f.write(str(os.getpid()))
        
        return prior_mtime
    
    def rollback(self, prior_mtime: float) -> None:
        """失败后的回滚：恢复 mtime"""
        if prior_mtime == 0:
            try:
                os.remove(self.lock_file)
            except FileNotFoundError:
                pass
        else:
            # 恢复修改时间（允许重试）
            os.utime(self.lock_file, (prior_mtime, prior_mtime))


# ============================================================================
# 新增：记忆整合器（四重门 + 4阶段流程）
# ============================================================================

class Consolidator:
    """
    简化版 AutoDream 实现
    
    核心特性：
    1. 四重门触发检查（时间、扫描节流、会话、锁）
    2. 4阶段整合流程（Orient → Gather → Consolidate → Prune）
    3. mtime-based 文件锁（可回滚）
    """
    
    def __init__(self, store: ObservationStore, lock_file: str):
        self.store = store
        self.lock = ConsolidationLock(lock_file)
        
        # 配置（源自 autoDream.ts）
        self.config = {
            'min_hours': 0.001,        # 演示用：实际应为 24
            'min_sessions': 3,         # 演示用：实际应为 5
            'scan_interval_ms': 5000   # 演示用：实际应为 10分钟
        }
        self.last_scan_at = 0
    
    def should_run(self) -> Tuple[bool, str]:
        """
        四重门检查
        
        返回: (是否应该运行, 原因)
        """
        # Gate 1: 时间门
        last_at = self.lock.read_last_consolidated_at()
        hours_since = (time.time() - last_at) / 3600
        if hours_since < self.config['min_hours']:
            return False, f"时间未达标（{hours_since:.4f}h < {self.config['min_hours']}h）"
        
        # Gate 2: 扫描节流门
        since_scan = (time.time() * 1000) - self.last_scan_at
        if since_scan < self.config['scan_interval_ms']:
            return False, "扫描过于频繁"
        
        self.last_scan_at = time.time() * 1000
        
        # Gate 3: 会话门
        index = self.store.get_index()
        session_count = index.get("total_observations", 0)
        if session_count < self.config['min_sessions']:
            return False, f"会话数不足（{session_count} < {self.config['min_sessions']}）"
        
        return True, "通过前三重门"
    
    def consolidate(self) -> Dict:
        """
        4阶段整合流程（源自 consolidationPrompt.ts）
        
        Phase 1: Orient - 了解现有结构
        Phase 2: Gather - 收集新信息
        Phase 3: Consolidate - 写入/更新记忆
        Phase 4: Prune and Index - 更新索引
        """
        # Gate 4: 文件锁门
        prior_mtime = self.lock.try_acquire()
        if prior_mtime is None:
            return {"status": "locked", "error": "其他进程正在整合"}
        
        try:
            print("\n🌙 ========== 开始记忆整合 ==========")
            
            # Phase 1: Orient
            print("  [Phase 1] Orient: 了解现有结构")
            index = self.store.get_index()
            print(f"    - 发现 {index['total_observations']} 条历史观察")
            
            # Phase 2: Gather
            print("  [Phase 2] Gather: 收集新信息")
            observations = self.store.query(limit=1000)
            print(f"    - 读取 {len(observations)} 条观察")
            
            # Phase 3: Consolidate
            print("  [Phase 3] Consolidate: 分析模式")
            by_type = defaultdict(list)
            for obs in observations:
                by_type[obs.type].append(obs)
            
            insights = self._extract_insights(observations)
            print(f"    - 提取 {len(insights)} 条洞察")
            
            # Phase 4: Prune and Index
            print("  [Phase 4] Prune: 更新索引")
            
            summary = {
                "timestamp": time.time(),
                "status": "completed",
                "total_observations": len(observations),
                "by_type": {t: len(items) for t, items in by_type.items()},
                "insights": insights
            }
            
            print("  ✅ ========== 整合完成 ==========\n")
            return summary
            
        except Exception as e:
            # 失败时回滚锁
            self.lock.rollback(prior_mtime)
            return {"status": "error", "error": str(e)}
    
    def _extract_insights(self, observations: List[Observation]) -> List[str]:
        """提取关键洞察（简化版）"""
        insights = []
        
        # 高频词分析
        content = ' '.join([obs.content for obs in observations])
        words = content.lower().split()
        word_freq = defaultdict(int)
        for w in words:
            if len(w) > 3:
                word_freq[w] += 1
        
        top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:3]
        if top_words:
            insights.append(f"高频主题: {', '.join([w for w, _ in top_words])}")
        
        # 高重要性事件
        important = [obs for obs in observations if obs.importance > 0.5]
        if important:
            insights.append(f"重要事件: {len(important)} 条")
        
        return insights


# ============================================================================
# 组件：Tick 调度器（v1/v2 继承）
# ============================================================================

class TickScheduler:
    def __init__(self, interval_ms: int = 2000, budget_ms: int = 5000):
        self.interval = interval_ms / 1000
        self.budget = budget_ms / 1000
        self.counter = 0
        self.evaluator: Optional[Callable[[Tick], Decision]] = None
        
    def register_evaluator(self, evaluator: Callable[[Tick], Decision]):
        self.evaluator = evaluator
        
    async def run(self, max_ticks: int = 20):
        print(f"🚀 KAIROS v3 启动（完整版）")
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
# 演示：完整的 KAIROS 循环
# ============================================================================

def create_evaluator(store: ObservationStore, consolidator: Consolidator):
    """创建完整的评估器：观察 + 整合"""
    tick_count = 0
    
    def evaluator(tick: Tick) -> Decision:
        nonlocal tick_count
        tick_count += 1
        
        # 每 2 个 tick 生成观察
        if tick_count % 2 == 0:
            def record_and_check():
                # 记录观察
                obs = Observation(
                    id=str(uuid.uuid4())[:8],
                    timestamp=time.time(),
                    type='file_change',
                    content=f'Tick {tick.counter}: 项目状态变化 #{tick_count//2}',
                    importance=0.6
                )
                store.append(obs)
                print(f"   📝 记录观察: {obs.id}")
                
                # 检查是否应该整合
                should_run, reason = consolidator.should_run()
                if should_run:
                    print(f"   🔍 整合检查通过: {reason}")
            
            return Decision(
                type=DecisionType.ACT,
                action=record_and_check,
                reason='记录状态并检查整合条件'
            )
        
        # 每 5 个 tick 尝试整合（演示用）
        if tick_count % 5 == 0:
            should_run, reason = consolidator.should_run()
            if should_run:
                return Decision(
                    type=DecisionType.ACT,
                    action=consolidator.consolidate,
                    reason='运行记忆整合'
                )
            else:
                return Decision(
                    type=DecisionType.SLEEP,
                    reason=f'整合条件不满足: {reason}'
                )
        
        return Decision(
            type=DecisionType.SLEEP,
            reason='等待下一次观察'
        )
    
    return evaluator


# ============================================================================
# 主程序
# ============================================================================

async def main():
    """v3 演示：完整的 tick → 观察 → 整合循环"""
    
    # 初始化组件
    store = ObservationStore()
    lock_file = os.path.join(store.base_dir, ".consolidate-lock")
    consolidator = Consolidator(store, lock_file)
    
    scheduler = TickScheduler(interval_ms=1500, budget_ms=3000)
    scheduler.register_evaluator(create_evaluator(store, consolidator))
    
    # 运行
    await scheduler.run(max_ticks=15)
    
    # 最终统计
    print("\n" + "=" * 40)
    print("最终状态:")
    index = store.get_index()
    print(f"  - 总观察数: {index['total_observations']}")
    print(f"  - 锁文件: {lock_file}")
    if os.path.exists(lock_file):
        mtime = os.path.getmtime(lock_file)
        print(f"  - 最后整合: {datetime.fromtimestamp(mtime)}")


if __name__ == "__main__":
    asyncio.run(main())
