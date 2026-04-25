#!/usr/bin/env python3
"""
micro-kairos 调试工具

使用方法:
    python debug_micro_kairos.py [base_dir]

功能:
    1. 检查目录结构
    2. 验证数据一致性
    3. 检查锁状态
    4. 重建损坏的索引
"""

import os
import json
import sys
import subprocess
from pathlib import Path


class KairosDebugger:
    """micro-kairos 调试器"""
    
    def __init__(self, base_dir: str = ".micro-kairos"):
        self.base_dir = base_dir
        self.obs_dir = os.path.join(base_dir, "observations")
        self.index_file = os.path.join(base_dir, "index.json")
        self.lock_file = os.path.join(base_dir, "consolidation.lock")
    
    def check_directory_structure(self) -> bool:
        """检查目录结构"""
        print("=" * 60)
        print("📁 目录结构检查")
        print("=" * 60)
        
        all_ok = True
        
        # 检查主目录
        if not os.path.exists(self.base_dir):
            print(f"❌ 主目录不存在: {self.base_dir}")
            print(f"   修复: mkdir -p {self.base_dir}")
            return False
        
        print(f"✅ 主目录存在: {self.base_dir}")
        
        # 检查观察目录
        if os.path.exists(self.obs_dir):
            files = [f for f in os.listdir(self.obs_dir) 
                    if f.endswith('.json') or f.endswith('.jsonl')]
            print(f"✅ 观察目录: {len(files)} 个文件")
            
            # 显示文件大小分布
            if files:
                sizes = []
                for f in files[:5]:  # 只显示前5个
                    filepath = os.path.join(self.obs_dir, f)
                    size = os.path.getsize(filepath)
                    sizes.append((f, size))
                
                print(f"   示例文件:")
                for f, size in sizes:
                    print(f"     - {f}: {size:,} bytes")
        else:
            print(f"❌ 观察目录不存在: {self.obs_dir}")
            print(f"   修复: mkdir -p {self.obs_dir}")
            all_ok = False
        
        # 检查索引
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file) as f:
                    index = json.load(f)
                count = len(index.get('observations', []))
                print(f"✅ 索引文件: {count} 条记录")
            except json.JSONDecodeError as e:
                print(f"❌ 索引文件损坏: {e}")
                print(f"   修复: 删除 {self.index_file} 并重建")
                all_ok = False
        else:
            print(f"⚠️  索引不存在: {self.index_file}")
            print(f"   这将是新创建的")
        
        return all_ok
    
    def check_consistency(self) -> bool:
        """检查数据一致性"""
        print("\n" + "=" * 60)
        print("🔍 数据一致性检查")
        print("=" * 60)
        
        if not os.path.exists(self.index_file):
            print("⚠️  索引不存在，跳过一致性检查")
            return True
        
        # 加载索引
        try:
            with open(self.index_file) as f:
                index = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ 索引文件损坏: {e}")
            return False
        
        index_entries = index.get("observations", [])
        index_ids = {obs.get("id") for obs in index_entries if "id" in obs}
        
        print(f"索引记录数: {len(index_ids)}")
        
        # 扫描文件
        file_ids = set()
        corrupted_files = []
        
        if os.path.exists(self.obs_dir):
            for filename in os.listdir(self.obs_dir):
                if filename.endswith('.json') or filename.endswith('.jsonl'):
                    filepath = os.path.join(self.obs_dir, filename)
                    try:
                        with open(filepath) as f:
                            data = json.load(f)
                            if isinstance(data, dict) and "id" in data:
                                file_ids.add(data["id"])
                            elif isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict) and "id" in item:
                                        file_ids.add(item["id"])
                    except json.JSONDecodeError as e:
                        corrupted_files.append((filename, str(e)))
        
        print(f"文件记录数: {len(file_ids)}")
        
        if corrupted_files:
            print(f"\n⚠️  损坏的文件 ({len(corrupted_files)} 个):")
            for fname, err in corrupted_files[:5]:
                print(f"   - {fname}: {err}")
        
        # 对比
        missing_files = index_ids - file_ids
        missing_index = file_ids - index_ids
        
        if missing_files:
            print(f"\n❌ 幽灵记录: 索引中有但文件不存在 ({len(missing_files)} 个)")
            for obs_id in list(missing_files)[:5]:
                print(f"   - {obs_id}")
            if len(missing_files) > 5:
                print(f"   ... 还有 {len(missing_files) - 5} 个")
        
        if missing_index:
            print(f"\n⚠️  孤儿文件: 文件存在但索引中缺失 ({len(missing_index)} 个)")
            for obs_id in list(missing_index)[:5]:
                print(f"   - {obs_id}")
            if len(missing_index) > 5:
                print(f"   ... 还有 {len(missing_index) - 5} 个")
        
        if not missing_files and not missing_index and not corrupted_files:
            print("\n✅ 数据一致性检查通过")
            return True
        
        return False
    
    def check_lock(self) -> tuple[bool, str]:
        """检查锁状态"""
        print("\n" + "=" * 60)
        print("🔒 锁状态检查")
        print("=" * 60)
        
        if not os.path.exists(self.lock_file):
            print("✅ 无锁文件（系统可用）")
            return True, "available"
        
        # 读取锁内容
        try:
            with open(self.lock_file) as f:
                content = f.read().strip()
        except Exception as e:
            print(f"❌ 无法读取锁文件: {e}")
            return False, "error"
        
        # 尝试解析 PID
        try:
            pid = int(content)
        except ValueError:
            print(f"⚠️  锁文件内容无效: '{content}'")
            print(f"   可能是死锁，建议删除: rm {self.lock_file}")
            return False, "invalid"
        
        print(f"锁持有者 PID: {pid}")
        
        # 检查 PID 是否存在
        try:
            result = subprocess.run(
                ['ps', '-p', str(pid)], 
                capture_output=True, 
                text=True
            )
            
            if result.returncode == 0:
                print(f"❌ 锁被 PID {pid} 持有（进程正在运行）")
                print(f"   系统当前不可用")
                return False, "held"
            else:
                print(f"⚠️  死锁 detected!")
                print(f"   PID {pid} 不存在，但锁文件残留")
                print(f"   修复: rm {self.lock_file}")
                return False, "stale"
        except Exception as e:
            print(f"⚠️  无法检查 PID: {e}")
            return False, "unknown"
    
    def rebuild_index(self) -> bool:
        """从日志文件重建索引"""
        print("\n" + "=" * 60)
        print("🔧 重建索引")
        print("=" * 60)
        
        if not os.path.exists(self.obs_dir):
            print(f"❌ 观察目录不存在: {self.obs_dir}")
            return False
        
        new_index = {
            "observations": [],
            "total": 0,
            "rebuilt_at": __import__('time').time()
        }
        
        count = 0
        errors = 0
        
        for filename in os.listdir(self.obs_dir):
            if not (filename.endswith('.json') or filename.endswith('.jsonl')):
                continue
            
            filepath = os.path.join(self.obs_dir, filename)
            
            try:
                with open(filepath, 'r') as f:
                    content = f.read().strip()
                
                if filename.endswith('.jsonl'):
                    # JSONL 格式：每行一个 JSON
                    for line in content.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if isinstance(data, dict) and "id" in data:
                                new_index["observations"].append({
                                    "id": data["id"],
                                    "file": filename,
                                    "timestamp": data.get("timestamp", 0)
                                })
                                count += 1
                        except json.JSONDecodeError:
                            errors += 1
                else:
                    # JSON 格式
                    data = json.loads(content)
                    if isinstance(data, dict) and "id" in data:
                        new_index["observations"].append({
                            "id": data["id"],
                            "file": filename,
                            "timestamp": data.get("timestamp", 0)
                        })
                        count += 1
                        
            except Exception as e:
                print(f"   ⚠️  跳过 {filename}: {e}")
                errors += 1
        
        new_index["total"] = count
        
        # 保存新索引
        os.makedirs(self.base_dir, exist_ok=True)
        with open(self.index_file, 'w') as f:
            json.dump(new_index, f, indent=2)
        
        print(f"✅ 索引重建完成")
        print(f"   记录数: {count}")
        print(f"   错误/跳过: {errors}")
        print(f"   保存到: {self.index_file}")
        
        return True
    
    def full_diagnostic(self) -> bool:
        """运行完整诊断"""
        print("\n" + "🚀 " * 30)
        print("micro-kairos 完整诊断")
        print("🚀 " * 30 + "\n")
        
        # 1. 目录结构
        structure_ok = self.check_directory_structure()
        
        # 2. 一致性
        consistency_ok = True
        if structure_ok:
            consistency_ok = self.check_consistency()
        
        # 3. 锁状态
        lock_ok, lock_status = self.check_lock()
        
        # 总结
        print("\n" + "=" * 60)
        print("📊 诊断总结")
        print("=" * 60)
        
        issues = []
        
        if not structure_ok:
            issues.append("目录结构问题")
        if not consistency_ok:
            issues.append("数据不一致")
        if not lock_ok:
            if lock_status == "stale":
                issues.append("死锁 (可清理)")
            elif lock_status == "held":
                issues.append("锁被占用")
            else:
                issues.append("锁状态异常")
        
        if issues:
            print("❌ 发现问题:")
            for issue in issues:
                print(f"   - {issue}")
            print("\n建议操作:")
            
            if not consistency_ok:
                print("   1. 重建索引: python debug_micro_kairos.py --rebuild")
            if lock_status == "stale":
                print(f"   2. 清理死锁: rm {self.lock_file}")
            
            return False
        else:
            print("✅ 所有检查通过，系统健康")
            return True


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='micro-kairos 调试工具')
    parser.add_argument('base_dir', nargs='?', default='.micro-kairos',
                       help='micro-kairos 数据目录 (默认: .micro-kairos)')
    parser.add_argument('--rebuild', action='store_true',
                       help='重建索引')
    parser.add_argument('--check-lock', action='store_true',
                       help='只检查锁状态')
    
    args = parser.parse_args()
    
    debugger = KairosDebugger(args.base_dir)
    
    if args.rebuild:
        debugger.rebuild_index()
    elif args.check_lock:
        debugger.check_lock()
    else:
        debugger.full_diagnostic()


if __name__ == "__main__":
    main()
