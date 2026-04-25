#!/usr/bin/env python3
"""
Mock GrowthBook 实战演练

模拟远程开关控制，体验 KAIROS 的优雅降级机制。

运行:
    # 终端 1: 启动 Mock GrowthBook 服务器
    python mock_growthbook_server.py
    
    # 终端 2: 运行 KAIROS 客户端
    python mock_growthbook_client.py
    
    # 交互: 在服务器终端输入命令切换开关状态
"""

import json
import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime


# =============================================================================
# Mock GrowthBook 服务器
# =============================================================================

class MockGrowthBookState:
    """模拟 GrowthBook 状态存储"""
    
    def __init__(self):
        # 初始状态：所有开关开启
        self.features = {
            "tengu_kairos": True,           # KAIROS 主开关
            "tengu_kairos_brief": True,     # Brief 工具权限
            "tengu_onyx_plover": True,      # AutoDream 配置
            "tengu_scratch": True,          # Scratchpad 功能
        }
        
        # 配置值（AutoDream 参数）
        self.configs = {
            "tengu_onyx_plover": {
                "min_hours": 24,
                "min_sessions": 5,
            }
        }
        
        # 变更日志
        self.change_log = []
        
        # 统计
        self.request_count = 0
        self.last_request_time = None
    
    def toggle(self, feature: str) -> bool:
        """切换开关状态"""
        if feature in self.features:
            self.features[feature] = not self.features[feature]
            self._log_change(feature, self.features[feature])
            return True
        return False
    
    def set(self, feature: str, value: bool) -> bool:
        """设置开关状态"""
        if feature in self.features:
            old_value = self.features[feature]
            self.features[feature] = value
            if old_value != value:
                self._log_change(feature, value)
            return True
        return False
    
    def emergency_kill(self):
        """紧急关闭所有功能"""
        for feature in self.features:
            if self.features[feature]:
                self.features[feature] = False
                self._log_change(feature, False, reason="EMERGENCY_KILL")
    
    def _log_change(self, feature: str, value: bool, reason: str = "manual"):
        """记录变更"""
        self.change_log.append({
            "timestamp": datetime.now().isoformat(),
            "feature": feature,
            "new_value": value,
            "reason": reason
        })
        status = "🟢 ON" if value else "🔴 OFF"
        print(f"\n[Switch Event] {feature} -> {status} ({reason})")
    
    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "features": self.features,
            "configs": self.configs,
            "request_count": self.request_count,
            "last_request": self.last_request_time,
            "uptime": time.time() - START_TIME
        }


# 全局状态
STATE = MockGrowthBookState()
START_TIME = time.time()


class GrowthBookHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""
    
    def log_message(self, format, *args):
        """禁用默认日志，使用自定义格式"""
        pass
    
    def do_GET(self):
        """处理 GET 请求（获取开关状态）"""
        STATE.request_count += 1
        STATE.last_request_time = datetime.now().isoformat()
        
        # 模拟网络延迟
        time.sleep(0.05)
        
        # 模拟偶尔的失败（5% 概率）
        if hash(time.time()) % 20 == 0:
            self.send_error(503, "Service Unavailable")
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        response = {
            "features": STATE.features,
            "configs": STATE.configs,
            "fetchedAt": int(time.time() * 1000)
        }
        
        self.wfile.write(json.dumps(response).encode())
    
    def do_POST(self):
        """处理 POST 请求（管理员控制）"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode()
        
        try:
            command = json.loads(body)
            action = command.get('action')
            feature = command.get('feature')
            value = command.get('value')
            
            if action == 'toggle':
                success = STATE.toggle(feature)
            elif action == 'set':
                success = STATE.set(feature, value)
            elif action == 'emergency_kill':
                STATE.emergency_kill()
                success = True
            else:
                success = False
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": success,
                "features": STATE.features
            }).encode())
            
        except Exception as e:
            self.send_error(400, str(e))


def run_server(port=8765):
    """运行 Mock GrowthBook 服务器"""
    server = HTTPServer(('localhost', port), GrowthBookHandler)
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║           Mock GrowthBook Server                                 ║
║           远程开关控制实战演练                                    ║
╚══════════════════════════════════════════════════════════════════╝

🚀 服务器启动于 http://localhost:{port}

📋 可用开关:
   • tengu_kairos       - KAIROS 主开关
   • tengu_kairos_brief - Brief 工具权限
   • tengu_onyx_plover  - AutoDream 配置
   • tengu_scratch      - Scratchpad 功能

⌨️  交互命令 (在此终端输入):
   toggle <feature>     - 切换指定开关
   kill                 - 紧急关闭所有功能
   status               - 查看当前状态
   help                 - 显示帮助

💡 提示: 启动客户端 (在另一个终端):
   python mock_growthbook_client.py

""")
    
    # 启动交互式命令线程
    def command_loop():
        while True:
            try:
                cmd = input("\n[gb] > ").strip().lower()
                
                if cmd == 'quit' or cmd == 'exit':
                    print("👋 关闭服务器...")
                    server.shutdown()
                    break
                
                elif cmd == 'status':
                    print("\n📊 当前状态:")
                    for feature, value in STATE.features.items():
                        status = "🟢 ON" if value else "🔴 OFF"
                        print(f"   {feature:25s} {status}")
                    print(f"\n📈 统计:")
                    print(f"   请求次数: {STATE.request_count}")
                    print(f"   运行时间: {time.time() - START_TIME:.0f}s")
                
                elif cmd == 'help':
                    print("""
可用命令:
  toggle <feature>  - 切换开关状态
  kill              - 紧急关闭所有功能
  status            - 显示当前状态
  help              - 显示此帮助
  quit/exit         - 关闭服务器

示例:
  toggle tengu_kairos
  kill
  status
""")
                
                elif cmd.startswith('toggle '):
                    feature = cmd[7:].strip()
                    if STATE.toggle(feature):
                        pass  # toggle 方法会打印状态
                    else:
                        print(f"❌ 未知开关: {feature}")
                        print(f"   可用: {', '.join(STATE.features.keys())}")
                
                elif cmd == 'kill':
                    print("🚨 紧急关闭所有功能!")
                    STATE.emergency_kill()
                
                elif cmd == '':
                    pass
                
                else:
                    print(f"❓ 未知命令: {cmd}")
                    print("   输入 'help' 查看可用命令")
                    
            except KeyboardInterrupt:
                print("\n👋 关闭服务器...")
                server.shutdown()
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
    
    cmd_thread = threading.Thread(target=command_loop, daemon=True)
    cmd_thread.start()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
