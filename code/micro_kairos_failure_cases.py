#!/usr/bin/env python3
"""
micro-kairos failure case: 违反严格写入纪律的后果演示

这个文件故意展示"错误的做法"，用于教学目的。
运行此文件，观察数据不一致是如何产生的。

对比文件: micro_kairos_v2.py (正确实现)
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from typing import List, Dict


@dataclass
class Observation:
    id: str
    timestamp: float
    type: str
    content: str
    importance: float = 0.5
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class BrokenObservationStore:
    """
    ❌ 错误实现：违反严格写入纪律
    
    问题：先更新索引，再写入数据
    后果：如果写入失败，索引指向不存在的数据
    """
    
    def __init__(self, base_dir: str = ".broken-kairos"):
        self.base_dir = base_dir
        self.obs_dir = os.path.join(base_dir, "observations")
        self.index_file = os.path.join(base_dir, "index.json")
        self._ensure_dirs()
        
        # 内存中的索引
        self.index: Dict = {"observations": [], "last_updated": None}
        self._load_index()
    
    def _ensure_dirs(self):
        os.makedirs(self.obs_dir, exist_ok=True)
    
    def _load_index(self):
        """加载索引"""
        if os.path.exists(self.index_file):
            with open(self.index_file, 'r') as f:
                self.index = json.load(f)
    
    def _save_index(self):
        """保存索引到磁盘"""
        with open(self.index_file, 'w') as f:
            json.dump(self.index, f, indent=2)
    
    def append_broken(self, obs: Observation) -> bool:
        """
        ❌ 错误顺序：先更新索引，再写入数据
        
        这就像先记账，再收钱——如果钱没收成，账就是错的
        """
        print(f"\n  [Broken] 开始添加观察: {obs.id}")
        
        # Step 1: 先更新内存索引 ❌ 错误！
        print(f"    Step 1: 更新内存索引")
        self.index["observations"].append({
            "id": obs.id,
            "file": f"{obs.id}.json",
            "timestamp": obs.timestamp
        })
        self.index["last_updated"] = time.time()
        
        # Step 2: 保存索引到磁盘 ❌ 错误！
        print(f"    Step 2: 保存索引到磁盘")
        self._save_index()
        
        # Step 3: 写入观察数据（这里可能失败！）
        print(f"    Step 3: 尝试写入观察数据...")
        
        # 模拟各种失败场景
        filepath = os.path.join(self.obs_dir, f"{obs.id}.json")
        
        # 模拟场景 A: 磁盘已满
        # raise IOError("磁盘已满 [模拟错误]")
        
        # 模拟场景 B: 权限错误
        # raise PermissionError("权限拒绝 [模拟错误]")
        
        # 模拟场景 C: 进程被杀死（SIGKILL）
        # os._exit(1)  # 无法捕获的强制退出
        
        # 正常写入（演示时启用）
        with open(filepath, 'w') as f:
            f.write(obs.to_json())
        
        print(f"    ✅ 观察 {obs.id} 添加成功")
        return True
    
    def query_by_index(self, obs_id: str) -> Dict:
        """
        通过索引查询观察
        
        问题：如果写入失败，这里会返回"找不到文件"错误
        """
        # 在索引中查找
        entry = None
        for obs in self.index["observations"]:
            if obs["id"] == obs_id:
                entry = obs
                break
        
        if not entry:
            return {"error": "Observation not found in index"}
        
        # 尝试读取文件
        filepath = os.path.join(self.obs_dir, entry["file"])
        
        if not os.path.exists(filepath):
            # ❌ 这就是问题！索引说有，但文件不存在
            return {
                "error": "DATA INCONSISTENCY",
                "index_entry": entry,
                "file_path": filepath,
                "problem": "索引指向的文件不存在！"
            }
        
        with open(filepath, 'r') as f:
            return json.load(f)
    
    def get_stats(self) -> Dict:
        """获取存储统计"""
        index_count = len(self.index["observations"])
        
        # 统计实际文件数
        actual_files = 0
        for f in os.listdir(self.obs_dir):
            if f.endswith('.json'):
                actual_files += 1
        
        return {
            "index_count": index_count,
            "actual_files": actual_files,
            "consistent": index_count == actual_files
        }


def simulate_crash_scenario():
    """
    场景模拟：系统在处理第 3 个观察时崩溃
    """
    print("=" * 60)
    print("场景模拟：违反严格写入纪律的后果")
    print("=" * 60)
    
    # 清理环境
    import shutil
    base_dir = ".broken-kairos-demo"
    if os.path.exists(base_dir):
        shutil.rmtree(base_dir)
    
    store = BrokenObservationStore(base_dir)
    
    # 创建 3 个观察
    observations = [
        Observation(str(uuid.uuid4())[:8], time.time(), "file_change", "修改了 main.py"),
        Observation(str(uuid.uuid4())[:8], time.time(), "command", "运行了 tests"),
        Observation(str(uuid.uuid4())[:8], time.time(), "error", "发现了一个 bug"),
    ]
    
    print("\n📋 准备添加 3 个观察:")
    for i, obs in enumerate(observations, 1):
        print(f"   {i}. {obs.id}: {obs.content}")
    
    # 添加前两个（成功）
    print("\n📝 添加观察 1...")
    store.append_broken(observations[0])
    
    print("\n📝 添加观察 2...")
    store.append_broken(observations[1])
    
    # 添加第 3 个时模拟崩溃
    print("\n📝 添加观察 3...")
    print("   (模拟系统崩溃：在更新索引后，写入数据前)")
    
    # 手动执行"错误"的步骤
    obs = observations[2]
    print(f"    Step 1: 更新内存索引 ✓")
    store.index["observations"].append({
        "id": obs.id,
        "file": f"{obs.id}.json",
        "timestamp": obs.timestamp
    })
    
    print(f"    Step 2: 保存索引到磁盘 ✓")
    store._save_index()
    
    print(f"    Step 3: 尝试写入观察数据... 💥 CRASH!")
    print(f"       [模拟错误] IOError: 磁盘已满")
    print(f"       程序异常退出，观察 {obs.id} 的数据未被写入！")
    
    # 不写入文件，模拟崩溃
    
    # 显示不一致状态
    print("\n" + "=" * 60)
    print("💥 系统崩溃后的状态分析")
    print("=" * 60)
    
    stats = store.get_stats()
    print(f"\n📊 存储统计:")
    print(f"   索引记录数: {stats['index_count']}")
    print(f"   实际文件数: {stats['actual_files']}")
    print(f"   一致性: {'✅ 正常' if stats['consistent'] else '❌ 数据不一致!'}")
    
    print(f"\n🔍 详细检查每个观察:")
    for obs in observations:
        result = store.query_by_index(obs.id)
        status = "✅ 正常" if "error" not in result else "❌ 损坏"
        print(f"\n   观察 {obs.id}: {status}")
        if "error" in result:
            print(f"      错误: {result['error']}")
            print(f"      问题: {result['problem']}")
    
    # 展示修复过程
    print("\n" + "=" * 60)
    print("🔧 修复：严格写入纪律（正确做法）")
    print("=" * 60)
    print("""
正确的顺序应该是：

    Step 1: 写入观察数据到临时文件
            ↓
    Step 2: 原子重命名（保证数据持久化）
            ↓
    Step 3: 数据确认写入成功后，再更新索引
            ↓
    Step 4: 保存索引

这样即使第 3 步失败，索引也不会被污染，
系统重启后可以从日志重建索引。
""")
    
    # 清理
    shutil.rmtree(base_dir, ignore_errors=True)


def compare_correct_vs_broken():
    """
    对比正确与错误的实现
    """
    print("\n" + "=" * 60)
    print("📚 正确 vs 错误：严格写入纪律对比")
    print("=" * 60)
    
    print("""
┌─────────────────────────────────────────────────────────────┐
│ ❌ 错误做法（Broken）                                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 更新内存索引                                            │
│  2. 保存索引到磁盘                                          │
│  3. 写入观察数据  ← 可能失败！                              │
│                                                             │
│  如果第 3 步失败：                                          │
│  • 索引指向不存在的数据                                     │
│  • 查询返回 "文件不存在"                                    │
│  • 系统处于不一致状态                                       │
│  • 难以恢复（不知道哪些索引是脏的）                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ ✅ 正确做法（Strict Write Discipline）                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 写入观察数据到临时文件                                  │
│  2. fsync() 确保数据落盘                                    │
│  3. 原子重命名（temp → final）                              │
│  4. 更新内存索引  ← 只有第 3 步成功才执行                   │
│  5. 保存索引                                                │
│                                                             │
│  如果第 1-3 步失败：                                        │
│  • 临时文件可以被清理                                       │
│  • 索引保持干净                                             │
│  • 系统保持一致                                             │
│  • 可以安全重试                                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘

关键洞察：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

索引是「指针」，数据是「真相」。

• 指针可以重建（从数据重新生成）
• 数据一旦丢失就彻底丢失
• 所以：必须先保护真相，再更新指针

这类似于数据库的 Write-Ahead Logging (WAL)：
先写日志，再写数据，最后更新索引。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


def demonstrate_recovery():
    """
    演示从日志重建索引（正确做法的恢复能力）
    """
    print("\n" + "=" * 60)
    print("🔄 演示：从日志重建索引（正确做法的恢复能力）")
    print("=" * 60)
    
    import shutil
    base_dir = ".recovery-demo"
    if os.path.exists(base_dir):
        shutil.rmtree(base_dir)
    
    os.makedirs(os.path.join(base_dir, "observations"))
    
    # 模拟：只有日志文件，没有索引
    print("\n📁 模拟场景：索引损坏，但日志文件完好")
    
    observations = [
        {"id": "abc123", "content": "修改了 main.py"},
        {"id": "def456", "content": "运行了 tests"},
        {"id": "ghi789", "content": "发现了 bug"},
    ]
    
    # 写入日志（不使用索引）
    for obs in observations:
        filepath = os.path.join(base_dir, "observations", f"{obs['id']}.json")
        with open(filepath, 'w') as f:
            json.dump(obs, f)
        print(f"   写入日志: {obs['id']}.json")
    
    print("\n🔧 重建索引过程:")
    print("   Step 1: 扫描日志目录...")
    
    rebuilt_index = {"observations": [], "rebuilt_at": time.time()}
    
    for filename in os.listdir(os.path.join(base_dir, "observations")):
        if filename.endswith('.json'):
            filepath = os.path.join(base_dir, "observations", filename)
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            rebuilt_index["observations"].append({
                "id": data["id"],
                "file": filename,
                "content_preview": data["content"][:20]
            })
            print(f"   Step 2: 添加 {data['id']} 到索引")
    
    # 保存重建的索引
    index_path = os.path.join(base_dir, "index-rebuilt.json")
    with open(index_path, 'w') as f:
        json.dump(rebuilt_index, f, indent=2)
    
    print(f"\n✅ 索引重建完成！")
    print(f"   重建的索引: {index_path}")
    print(f"   包含 {len(rebuilt_index['observations'])} 条记录")
    
    print("""
结论：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
只要日志文件存在，索引可以随时重建。
这证明了为什么「数据是真相，索引只是指针」。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
    
    # 清理
    shutil.rmtree(base_dir, ignore_errors=True)


def main():
    """运行所有失败案例分析"""
    simulate_crash_scenario()
    compare_correct_vs_broken()
    demonstrate_recovery()
    
    print("\n" + "=" * 60)
    print("📚 教学要点总结")
    print("=" * 60)
    print("""
1. 严格写入纪律的核心：先写数据，后更新索引

2. 违反纪律的后果：
   • 数据不一致（索引指向不存在的数据）
   • 查询失败
   • 难以诊断和修复

3. 正确做法的优势：
   • 原子性操作
   • 可恢复性（从日志重建索引）
   • 故障安全

4. 现实世界的例子：
   • 数据库的 WAL (Write-Ahead Logging)
   • 文件系统的日志 (journaling)
   • KAIROS 的 observation log + index 分离

5. 检查你的代码：
   □ 是否有"先更新索引再写入"的操作？
   □ 是否处理了写入失败的情况？
   □ 能否从原始数据重建索引？
""")


if __name__ == "__main__":
    main()
