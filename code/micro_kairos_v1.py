#!/usr/bin/env python3
"""
micro-kairos v1: 最简 Tick 调度器

这是 KAIROS 的最小可行实现，只包含核心调度循环。
目标：理解 tick 驱动架构的基本原理。

运行: python micro_kairos_v1.py
预期输出: 每 3 秒打印一次 tick 信息，共 10 次
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


# ============================================================================
# 核心数据结构
# ============================================================================

class DecisionType(Enum):
    """决策类型：执行行动 或 睡眠等待"""
    ACT = "act"
    SLEEP = "sleep"


@dataclass
class Tick:
    """心跳：包含当前状态快照"""
    timestamp: float
    counter: int
    project_hash: str


@dataclass
class Decision:
    """评估结果：做什么 + 为什么"""
    type: DecisionType
    action: Optional[Callable] = None
    reason: str = ""


# ============================================================================
# 核心组件：Tick 调度器
# ============================================================================

class TickScheduler:
    """
    KAIROS 的心跳引擎
    
    关键设计决策：
    1. 固定间隔（interval）而非事件驱动 —— 提供可预测的节奏
    2. 预算约束（budget）—— 硬性超时保护
    3. 外部评估器 —— 决策逻辑与调度分离
    """
    
    def __init__(self, interval_ms: int = 3000, budget_ms: int = 5000):
        """
        Args:
            interval_ms: tick 间隔（毫秒），默认 3 秒
            budget_ms: 单次行动预算（毫秒），默认 5 秒
        """
        self.interval = interval_ms / 1000  # 转秒
        self.budget = budget_ms / 1000
        self.counter = 0
        self.evaluator: Optional[Callable[[Tick], Decision]] = None
        
    def register_evaluator(self, evaluator: Callable[[Tick], Decision]):
        """注册评估函数：给定 Tick，返回 Decision"""
        self.evaluator = evaluator
        
    async def run(self, max_ticks: int = 10):
        """主循环"""
        print(f"🚀 KAIROS v1 启动")
        print(f"   tick 间隔: {self.interval}s")
        print(f"   行动预算: {self.budget}s")
        print(f"   计划运行: {max_ticks} 个 tick\n")
        
        while self.counter < max_ticks:
            # 创建当前 tick 上下文
            tick = Tick(
                timestamp=time.time(),
                counter=self.counter,
                project_hash=f"demo-{self.counter}"  # v1 简化
            )
            
            # 评估并执行
            if self.evaluator:
                decision = self.evaluator(tick)
                await self._execute(decision)
            
            self.counter += 1
            await asyncio.sleep(self.interval)
        
        print(f"\n✅ 完成 {max_ticks} 个 tick")
    
    async def _execute(self, decision: Decision):
        """执行决策，监控预算"""
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
                    print(f"   ⏰ 警告: 超时 ({elapsed:.2f}s > {self.budget}s)")
                else:
                    print(f"   ✅ 完成 ({elapsed:.2f}s)")
                    
            except Exception as e:
                print(f"   ❌ 错误: {e}")


# ============================================================================
# 演示：一个简单的评估器
# ============================================================================

def simple_evaluator(tick: Tick) -> Decision:
    """
    示例评估逻辑：
    - 每 3 个 tick 执行一次行动（模拟检测文件变化）
    - 其余时间睡眠
    """
    if tick.counter % 3 == 0:
        # 模拟一个快速行动
        def quick_action():
            print(f"   📁 模拟：扫描项目状态...")
            time.sleep(0.1)  # 模拟 100ms 工作量
        
        return Decision(
            type=DecisionType.ACT,
            action=quick_action,
            reason='定期项目扫描'
        )
    
    return Decision(
        type=DecisionType.SLEEP,
        reason='无高价值行动'
    )


# ============================================================================
# 主程序
# ============================================================================

async def main():
    """v1 演示：让 tick 跑起来"""
    scheduler = TickScheduler(interval_ms=3000, budget_ms=2000)
    scheduler.register_evaluator(simple_evaluator)
    
    await scheduler.run(max_ticks=10)


if __name__ == "__main__":
    asyncio.run(main())
