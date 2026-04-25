#!/usr/bin/env python3
"""
Mock GrowthBook 客户端 - KAIROS 实战演练

演示 KAIROS 如何根据远程开关状态优雅降级。

使用方法:
1. 先启动服务器: python mock_growthbook_server.py
2. 再运行客户端: python mock_growthbook_client.py
3. 在服务器终端切换开关，观察客户端行为
"""

import json
import time
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict


class SystemState(Enum):
    """系统状态"""
    FULLY_OPERATIONAL = "fully_operational"      # 所有功能正常
    DEGRADED = "degraded"                         # 部分功能受限
    EMERGENCY_STOP = "emergency_stop"            # 紧急停止
    OFFLINE = "offline"                           # 离线模式（无法连接）


@dataclass
class KairosContext:
    """KAIROS 运行时上下文"""
    kairos_enabled: bool
    brief_enabled: bool
    autodream_enabled: bool
    scratch_enabled: bool
    last_check: float
    consecutive_failures: int


class GrowthBookClient:
    """GrowthBook 客户端（模拟 KAIROS 中的实现）"""
    
    def __init__(self, server_url: str = "http://localhost:8765"):
        self.server_url = server_url
        self.cache: Optional[Dict] = None
        self.cache_time: float = 0
        self.cache_ttl: float = 60  # 缓存 60 秒
        
        # 失败回退：如果无法连接，使用最后已知状态或安全默认值
        self.fallback_features = {
            "tengu_kairos": False,        # 安全默认：关闭
            "tengu_kairos_brief": False,
            "tengu_onyx_plover": False,
            "tengu_scratch": False,
        }
    
    def fetch_features(self) -> Optional[Dict]:
        """
        获取远程开关状态
        
        实际源码位置: main.tsx 中的 GrowthBook 初始化
        """
        try:
            # 模拟网络请求
            req = urllib.request.Request(
                self.server_url,
                headers={'Accept': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=2.0) as response:
                data = json.loads(response.read().decode())
                
                # 更新缓存
                self.cache = data.get('features', {})
                self.cache_time = time.time()
                
                return self.cache
                
        except urllib.error.URLError as e:
            print(f"⚠️  无法连接 GrowthBook: {e}")
            return None
        except Exception as e:
            print(f"⚠️  获取特性失败: {e}")
            return None
    
    def is_enabled(self, feature: str) -> bool:
        """
        检查特性是否启用
        
        带缓存和失败回退
        """
        # 检查缓存是否过期
        if time.time() - self.cache_time > self.cache_ttl:
            fresh = self.fetch_features()
            if fresh is not None:
                self.cache = fresh
        
        # 使用缓存或回退
        features = self.cache if self.cache is not None else self.fallback_features
        return features.get(feature, False)


class KairosRuntime:
    """
    KAIROS 运行时（模拟核心系统）
    
    展示如何根据远程开关状态调整行为
    """
    
    def __init__(self):
        self.gb_client = GrowthBookClient()
        self.context = KairosContext(
            kairos_enabled=False,
            brief_enabled=False,
            autodream_enabled=False,
            scratch_enabled=False,
            last_check=0,
            consecutive_failures=0
        )
        self.state = SystemState.OFFLINE
        self.observation_count = 0
        self.tick_count = 0
    
    def check_remote_switches(self) -> bool:
        """
        检查远程开关状态
        
        对应源码: main.tsx:1050-1100
        """
        print("\n🔍 检查远程开关状态...")
        
        # 获取所有开关状态
        self.context.kairos_enabled = self.gb_client.is_enabled("tengu_kairos")
        self.context.brief_enabled = self.gb_client.is_enabled("tengu_kairos_brief")
        self.context.autodream_enabled = self.gb_client.is_enabled("tengu_onyx_plover")
        self.context.scratch_enabled = self.gb_client.is_enabled("tengu_scratch")
        self.context.last_check = time.time()
        
        # 确定系统状态
        if not self.context.kairos_enabled:
            if self.state != SystemState.EMERGENCY_STOP:
                print("🚨 KAIROS 主开关关闭！进入紧急停止模式")
                self.state = SystemState.EMERGENCY_STOP
        elif not all([
            self.context.brief_enabled,
            self.context.autodream_enabled,
            self.context.scratch_enabled
        ]):
            if self.state != SystemState.DEGRADED:
                print("⚠️  部分功能受限，进入降级模式")
                self.state = SystemState.DEGRADED
        else:
            if self.state != SystemState.FULLY_OPERATIONAL:
                print("✅ 所有开关开启，系统全功能运行")
                self.state = SystemState.FULLY_OPERATIONAL
        
        return self.context.kairos_enabled
    
    def on_tick(self) -> None:
        """
        Tick 处理（模拟 proactive/tickHandler.ts）
        """
        self.tick_count += 1
        
        print(f"\n{'='*60}")
        print(f"🕐 Tick #{self.tick_count} | 状态: {self.state.value}")
        print(f"{'='*60}")
        
        # 每 5 个 tick 检查一次远程开关
        if self.tick_count % 5 == 0:
            self.check_remote_switches()
        
        # 根据当前状态执行不同逻辑
        if self.state == SystemState.EMERGENCY_STOP:
            self._handle_emergency_stop()
        elif self.state == SystemState.DEGRADED:
            self._handle_degraded_mode()
        elif self.state == SystemState.FULLY_OPERATIONAL:
            self._handle_full_operation()
        else:
            self._handle_offline()
    
    def _handle_emergency_stop(self) -> None:
        """紧急停止模式：只记录观察，不采取任何行动"""
        print("🛑 [EMERGENCY STOP]")
        print("   • 继续记录观察（写入本地）")
        print("   • ❌ 禁用所有主动行为")
        print("   • ❌ 禁用 Brief 工具")
        print("   • ❌ 禁用 AutoDream")
        
        # 仍然记录观察，但不主动行动
        self.observation_count += 1
        print(f"   • 观察 #{self.observation_count} 已记录（本地）")
        
        # 等待远程开关恢复
        print("   • 等待 tengu_kairos 重新开启...")
    
    def _handle_degraded_mode(self) -> None:
        """降级模式：核心功能可用，部分功能受限"""
        print("⚡ [DEGRADED MODE]")
        
        # 检查具体哪些功能可用
        if self.context.brief_enabled:
            print("   • ✅ Brief 工具: 可用")
        else:
            print("   • ❌ Brief 工具: 禁用")
        
        if self.context.autodream_enabled:
            print("   • ✅ AutoDream: 可用")
        else:
            print("   • ❌ AutoDream: 禁用（观察只记录不整合）")
        
        if self.context.scratch_enabled:
            print("   • ✅ Scratchpad: 可用")
        else:
            print("   • ❌ Scratchpad: 禁用")
        
        # 执行有限的功能
        self.observation_count += 1
        print(f"   • 观察 #{self.observation_count} 已记录")
        
        # 如果 Brief 可用，可以发送通知
        if self.context.brief_enabled and self.tick_count % 3 == 0:
            print("   • 📤 发送 Brief 通知给用户")
    
    def _handle_full_operation(self) -> None:
        """全功能模式"""
        print("🚀 [FULL OPERATIONAL]")
        print("   • ✅ 所有功能正常运行")
        print("   • ✅ Brief 工具: 可用")
        print("   • ✅ AutoDream: 可用")
        print("   • ✅ Scratchpad: 可用")
        
        # 正常记录观察
        self.observation_count += 1
        print(f"   • 观察 #{self.observation_count} 已记录")
        
        # 模拟主动行为
        if self.tick_count % 3 == 0:
            print("   • 🤖 评估高价值行动...")
            print("   • 💡 检测到模式，建议重构")
        
        # 模拟 Brief 通知
        if self.tick_count % 5 == 0:
            print("   • 📤 发送 Brief 通知")
        
        # 模拟 AutoDream 检查
        if self.tick_count % 10 == 0:
            print("   • 🌙 检查 AutoDream 条件...")
            print("   • ⏰ 距离上次整合 20h，还需 4h")
    
    def _handle_offline(self) -> None:
        """离线模式：无法连接远程服务器"""
        print("📴 [OFFLINE MODE]")
        print("   • ⚠️  无法连接 GrowthBook")
        print("   • 🛡️  使用安全默认值（所有功能关闭）")
        print("   • 📝 本地观察继续记录")
        
        self.observation_count += 1
        print(f"   • 观察 #{self.observation_count} 已记录（本地）")
        print("   • 🔄 将在下次 tick 重试连接...")
    
    def print_status(self) -> None:
        """打印当前状态"""
        print(f"\n{'='*60}")
        print("📊 KAIROS 运行时状态")
        print(f"{'='*60}")
        print(f"系统状态: {self.state.value}")
        print(f"总 Tick 数: {self.tick_count}")
        print(f"观察记录数: {self.observation_count}")
        print(f"\n远程开关状态:")
        print(f"  tengu_kairos:       {'🟢 ON' if self.context.kairos_enabled else '🔴 OFF'}")
        print(f"  tengu_kairos_brief: {'🟢 ON' if self.context.brief_enabled else '🔴 OFF'}")
        print(f"  tengu_onyx_plover:  {'🟢 ON' if self.context.autodream_enabled else '🔴 OFF'}")
        print(f"  tengu_scratch:      {'🟢 ON' if self.context.scratch_enabled else '🔴 OFF'}")
        print(f"\n最后检查: {time.strftime('%H:%M:%S', time.localtime(self.context.last_check))}")


def main():
    """主函数 - 交互式演练"""
    
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           KAIROS 远程开关实战演练                                 ║
║           体验优雅降级机制                                        ║
╚══════════════════════════════════════════════════════════════════╝

📚 概念说明:
   GrowthBook 是 Anthropic 使用的远程特性开关系统。
   它允许在不发布新版本的情况下，动态开启/关闭功能。
   
   这是安全关键设计:
   • 发现严重 bug → 远程关闭功能
   • 紧急情况 → 一键停止所有 KAIROS 实例
   • 渐进发布 → 先给 1% 用户开启

🎮 操作说明:
   1. 确保服务器已启动: python mock_growthbook_server.py
   2. 在此终端观察 KAIROS 行为
   3. 在服务器终端输入命令切换开关:
      - toggle tengu_kairos     (关闭主开关)
      - toggle tengu_kairos_brief (关闭 Brief)
      - kill                     (紧急停止)
      - status                   (查看状态)
   4. 观察客户端如何优雅降级

按 Enter 开始演练（或 Ctrl+C 退出）...
""")
    
    try:
        input()
    except KeyboardInterrupt:
        print("\n👋 退出")
        return
    
    # 创建运行时
    runtime = KairosRuntime()
    
    print("\n🚀 启动 KAIROS 运行时...")
    print("（每 2 秒一个 tick，按 Ctrl+C 停止）\n")
    
    try:
        while True:
            runtime.on_tick()
            
            # 每 5 个 tick 打印一次完整状态
            if runtime.tick_count % 5 == 0:
                runtime.print_status()
            
            time.sleep(2)
            
    except KeyboardInterrupt:
        print(f"\n\n{'='*60}")
        print("📊 演练总结")
        print(f"{'='*60}")
        print(f"总运行时间: {runtime.tick_count * 2} 秒")
        print(f"总 Tick 数: {runtime.tick_count}")
        print(f"观察记录数: {runtime.observation_count}")
        print(f"最终状态: {runtime.state.value}")
        print("\n💡 关键洞察:")
        print("   • 远程开关可以在运行时动态控制功能")
        print("   • 系统会优雅降级，而不是崩溃")
        print("   • 观察日志始终记录，即使功能被关闭")
        print("   • 这是'安全关键'设计的实际体现")
        print("\n👋 演练结束")


if __name__ == "__main__":
    main()
