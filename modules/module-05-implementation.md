# 模块五：实现实验

> "You don't truly understand a system until you've built it." — 动手哲学

**时长**：6-8 小时  
**形式**：动手编程  
**前置要求**：完成模块四

---

## 5.1 项目：micro-kairos（渐进式实现）

### 目标

通过三个渐进式版本构建 KAIROS 克隆，理解：
- **v1**: Tick 调度机制（~50 行）
- **v2**: 只写日志存储（~150 行）  
- **v3**: 四重门记忆整合（~400 行）

每个版本都可独立运行，展示架构的逐层叠加。

### 项目结构

```
code/
├── micro_kairos_v1.py      # 第一步：让 tick 跑起来
├── micro_kairos_v2.py      # 第二步：添加观察存储
├── micro_kairos_v3.py      # 第三步：完整整合循环
└── micro_kairos.py         # 完整参考实现（原文件）
```

---

## 5.2 三步实现

### Step 1: v1 - 最简 Tick 调度器

**文件**: `code/micro_kairos_v1.py` (~60 行)

**学习目标**: 理解 tick 驱动架构的核心循环。

```python
class TickScheduler:
    def __init__(self, interval_ms=3000, budget_ms=5000):
        # interval: 心跳间隔
        # budget: 单次行动预算（硬性约束）
    
    def register_evaluator(self, evaluator):
        # 评估器：给定 Tick -> 返回 Decision(ACT|SLEEP)
    
    async def run(self):
        # 循环：创建 Tick -> 评估 -> 执行 -> 睡眠等待
```

**核心设计决策**:
1. 固定间隔而非事件驱动 —— 提供可预测的节奏
2. 预算约束 —— 硬性超时保护，防止卡住
3. 外部评估器 —— 决策逻辑与调度分离

**运行验证**:
```bash
python code/micro_kairos_v1.py
# 输出：每 3 秒一个 tick，交替显示 "执行行动" 和 "睡眠"
```

**5 分钟实验**:
- 修改 `interval_ms` 为 500，观察系统行为变化
- 在 `quick_action` 中添加 `time.sleep(3)`，触发预算警告
- 问题：预算超时时应该如何处理？（v3 会有答案）

---

### Step 2: v2 - 添加观察存储

**文件**: `code/micro_kairos_v2.py` (~180 行)

**新增组件**: `ObservationStore` —— 只写日志存储

**学习目标**: 理解严格写入纪律和轻量索引。

```python
class ObservationStore:
    def append(self, obs: Observation) -> bool:
        # 严格写入纪律：
        # 1. 序列化观察 -> JSONL
        # 2. 原子追加到日志文件
        # 3. 成功后返回 True（调用者再更新索引）
    
    def query(self, since, pattern, limit) -> List[Observation]:
        # grep 风格：逐行读取，不加载整个文件
```

**严格写入纪律示例**:
```python
# ✅ 正确：先写数据，成功后更新索引
success = store.append(obs)
if success:
    update_index(obs.id)  # 确保索引永远指向有效数据

# ❌ 错误：先更新索引再写数据
update_index(obs.id)     # 如果写入失败，索引指向不存在的数据
store.append(obs)
```

**运行验证**:
```bash
python code/micro_kairos_v2.py
# 输出：tick 运行，观察被记录，最后显示索引统计
```

**5 分钟实验**:
1. 查看生成的 `.micro-kairos/observations/` 目录
2. 手动添加一行损坏的 JSON，验证容错能力
3. 修改 `query` 的 `limit` 参数，观察性能差异

---

### Step 3: v3 - 完整记忆整合

**文件**: `code/micro_kairos_v3.py` (~370 行)

**新增组件**: 
- `ConsolidationLock` —— mtime-based 文件锁
- `Consolidator` —— 四重门 + 4阶段整合

**学习目标**: 理解 AutoDream 的触发机制和整合流程。

**四重门检查**（源自 `autoDream.ts`）:
```python
def should_run(self) -> Tuple[bool, str]:
    # Gate 1: 时间门（距上次 >= min_hours）
    # Gate 2: 扫描节流门（距上次扫描 >= 10分钟）
    # Gate 3: 会话门（观察数 >= min_sessions）  
    # Gate 4: 文件锁门（无其他进程持有锁）
```

**4阶段整合流程**（源自 `consolidationPrompt.ts`）:
```python
def consolidate(self):
    # Phase 1: Orient —— 了解现有结构
    # Phase 2: Gather —— 收集新信息
    # Phase 3: Consolidate —— 分析模式
    # Phase 4: Prune and Index —— 更新索引
```

**文件锁设计**（可回滚）:
```python
# 锁文件语义：
# - mtime = lastConsolidatedAt
# - 内容 = 持有者 PID

prior_mtime = lock.try_acquire()  # 获取锁，保存原 mtime
if prior_mtime is None:
    return {"status": "locked"}   # 其他进程持有

try:
    run_consolidation()
except Exception:
    lock.rollback(prior_mtime)    # 失败时恢复，允许重试
```

**运行验证**:
```bash
python code/micro_kairos_v3.py
# 输出：完整的 tick -> 观察 -> 整合循环
```

**5 分钟实验**:
1. 修改 `min_hours` 为 `0.001`，加快整合触发
2. 同时运行两个 v3 实例，观察锁竞争
3. 删除锁文件，观察系统如何恢复

---

## 5.3 数值实验验证

**文件**: `code/micro_kairos_benchmark.py`

基于 Andrej Karpathy 的建议，我们设计了三个数值实验来验证 KAIROS 的设计决策。

### 实验 1: Token 占用对比（索引 vs 完整转录）

**问题**: "150 字符指针是轻量的"——具体轻多少？

**方法**: 
- 生成 30 天 × 50 条 = 1,500 条观察（每条 ~200 tokens）
- 对比三种加载策略的 token 占用

**运行**:
```bash
python code/micro_kairos_benchmark.py
# 自动运行所有实验
```

**预期结果**:
```
┌─────────────────┬─────────────┬─────────────┬──────────┐
│ 加载策略        │ Token 数    │ 占比        │ 节省     │
├─────────────────┼─────────────┼─────────────┼──────────┤
│ 完整转录        │ 302,000     │ 100%        │ -        │
│ 轻量索引        │ 1,125       │ 0.4%        │ 99.6%    │
│ 索引+按需加载   │ 5,125       │ 1.7%        │ 98.3%    │
└─────────────────┴─────────────┴─────────────┴──────────┘

内存效率提升: 59×
```

**关键发现**:
- 随着时间推移，完整转录呈线性增长，很快超出上下文限制
- 轻量索引保持恒定（~1,125 tokens），与总历史无关
- 按需加载通过 `grep` 过滤，只加载相关的 5-15 条观察

### 实验 2: Tick 间隔的 CPU 占用

**问题**: 不同 tick 频率对系统性能的影响？

**方法**:
- 在标准笔记本上测试 0.1s 到 5s 的 tick 间隔
- 每个配置运行 10 秒，测量 CPU 占用

**预期结果**:
```
┌────────────┬──────────┬─────────────┐
│ Tick 间隔  │ CPU 占用 │ 适用场景    │
├────────────┼──────────┼─────────────┤
│ 100ms      │ 12.5%    │ ❌ 过高     │
│ 500ms      │ 3.2%     │ ⚠️ 高实时   │
│ 1,000ms    │ 1.8%     │ ✅ 标准     │
│ 3,000ms    │ 0.6%     │ ✅ 推荐     │
│ 5,000ms    │ 0.4%     │ ✅ 低功耗   │
└────────────┴──────────┴─────────────┘
```

**设计启示**:
- **3-5 秒**是开发场景的甜点
- **15 秒预算**与 **3 秒 tick** 的比例（5:1）提供了"思考 vs 执行"平衡
- CPU 占用 < 1% 意味着 KAIROS 可以与其他工具共存

### 实验 3: 查询性能对比（Grep 风格 vs 全量加载）

**问题**: `grep` 风格的查询真的比全量加载快吗？

**方法**:
- 对比两种查询策略的性能
- 测试 100 次查询的平均耗时

**预期结果**:
```
┌──────────────────┬─────────────┬─────────────┐
│ 查询策略         │ 平均耗时    │ 内存占用    │
├──────────────────┼─────────────┼─────────────┤
│ 全量加载+过滤    │ 45 ms       │ 1,500 条    │
│ Grep 风格        │ 3 ms        │ 10 条       │
├──────────────────┼─────────────┼─────────────┤
│ 性能提升         │ 15×         │ 150×        │
└──────────────────┴─────────────┴─────────────┘
```

**关键机制**:
- 逐行读取 + 提前终止（达到 limit 立即停止）
- 不解析无关的 JSON，减少 CPU 和内存开销

---

## 5.3 进阶挑战

### 挑战 1: 预算检查点（15秒约束的真正实现）

v3 中的预算只是打印警告。实现真正的检查点机制：

```python
class BudgetExecutor:
    def execute(self, steps: List[Callable]) -> BudgetResult:
        for i, step in enumerate(steps):
            if elapsed > budget:
                # 保存检查点
                return BudgetResult(
                    status='deferred',
                    checkpoint={
                        'completed': i,
                        'remaining': steps[i:]
                    }
                )
        
    def resume(self, checkpoint):
        # 从检查点恢复
```

### 挑战 2: 真实文件监控

使用 `watchdog` 库监控真实文件变化：

```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class KairosEventHandler(FileSystemEventHandler):
    def on_modified(self, event):
        obs = Observation(
            type='file_change',
            content=f'File modified: {event.src_path}'
        )
        store.append(obs)
```

### 挑战 3: LLM 驱动的洞察提取

替换 `_extract_insights` 的启发式规则，使用真实 LLM：

```python
import anthropic

async def extract_insights_with_llm(observations):
    client = anthropic.Anthropic()
    
    content = '\n'.join([obs.content for obs in observations])
    
    response = await client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=500,
        system="Summarize key patterns from these observations.",
        messages=[{"role": "user", "content": content}]
    )
    
    return response.content
```

### 挑战 4: 可视化仪表板

用 Flask 添加 Web 界面：

```python
from flask import Flask, jsonify
import asyncio

app = Flask(__name__)

@app.route('/api/ticks')
def get_ticks():
    return jsonify({
        'counter': scheduler.counter,
        'observations': store.get_index()
    })

@app.route('/api/consolidate', methods=['POST'])
def trigger_consolidate():
    result = consolidator.consolidate()
    return jsonify(result)
```

---

## 5.4 "现在你自己试试" —— 5分钟动手任务

每个任务都有明确的**预期输出**和**验证方法**。

### ✅ 任务 1: 观察锁竞争（难度 ⭐）

**目标**: 理解 mtime-based 文件锁的行为

**操作**:
```bash
# 终端 1
python code/micro_kairos_v3.py

# 在 v3 运行期间，打开终端 2 再次运行
python code/micro_kairos_v3.py
```

**预期输出**:
```
终端 2: "🔒 整合检查: 时间门 ✅ 扫描门 ✅ 会话门 ✅ 文件锁门 ❌"
终端 2: "   原因: 其他进程正在整合"
```

**问题**: 为什么第二个实例不能获取锁？锁的过期时间是多久？

---

### ✅ 任务 2: 修改 min_hours 观察快速触发（难度 ⭐⭐）

**目标**: 观察 AutoDream 在同一秒内多次触发时的锁回滚

**操作**:
```python
# 在 micro_kairos_v3.py 中修改
self.config = {
    'min_hours': 0.001,        # 原来是 24，改为 0.001
    'min_sessions': 3,
    'scan_interval_ms': 100    # 原来是 5000，改为 100
}
```

**运行**:
```bash
python code/micro_kairos_v3.py
```

**预期输出**:
```
🌙 ========== 开始记忆整合 ==========
  [Phase 1] Orient...
  [Phase 2] Gather...
  ...
🌙 ========== 开始记忆整合 ==========  # 再次触发！
  [Phase 1] Orient...
```

**观察**: 锁文件的时间戳如何变化？为什么第二次整合不会立即执行？

---

### ✅ 任务 3: 制造严格写入纪律失败（难度 ⭐⭐）

**目标**: 理解为什么必须先写数据再更新索引

**操作**:
```python
# 在 micro_kairos_v2.py 中，修改 append 方法为"错误版本":
def append(self, obs: Observation) -> bool:
    # ❌ 错误：先更新索引
    self._update_index(obs.id)  # 先执行
    
    # 然后写入（模拟失败）
    raise IOError("磁盘已满")    # 写入失败！
    
    return True
```

**运行并观察**:
```bash
python code/micro_kairos_v2.py
# 程序崩溃后检查索引文件
ls -la .micro-kairos/index/
```

**问题**: 索引中有一条记录指向不存在的数据，这会导致什么问题？

**修复**: 改回正确顺序（先写数据，成功后再更新索引）

---

### ✅ 任务 4: 基准测试真实数据（难度 ⭐⭐⭐）

**目标**: 在自己的项目上运行性能测试

**操作**:
```bash
# 1. 复制 benchmark 文件到临时目录
cp code/micro_kairos_benchmark.py /tmp/
cd /tmp

# 2. 修改数据生成参数
# 将 days=30 改为 days=7，减少测试时间

# 3. 运行
python micro_kairos_benchmark.py
```

**记录你的结果**:
```
我的环境: _______ (CPU 型号)
实验 1 结果: _____ tokens (完整) vs _____ tokens (索引)
节省比例: _____%

实验 2 结果:
0.1s tick: _____% CPU
1.0s tick: _____% CPU  
5.0s tick: _____% CPU
```

---

### ✅ 任务 5: 添加自定义观察类型（难度 ⭐⭐⭐）

**目标**: 扩展 Observation 类型系统

**操作**:
```python
# 1. 在 v3 中添加新类型
class ObservationType(Enum):
    FILE_CHANGE = "file_change"
    COMMAND = "command"
    INFERENCE = "inference"
    GIT_COMMIT = "git_commit"  # 新增
    TEST_RESULT = "test_result"  # 新增

# 2. 修改 tick 处理器，在特定条件下生成 GIT_COMMIT 观察
if tick.counter % 7 == 0:
    obs = Observation(
        type='git_commit',
        content=f'模拟提交: {tick.project_hash}',
        importance=0.8
    )
```

**验证**:
```bash
python code/micro_kairos_v3.py
grep "git_commit" .micro-kairos/observations/*.jsonl | head -5
```

---

## 5.5 失败案例分析：违反严格写入纪律的后果

**文件**: `code/micro_kairos_failure_cases.py`

成功路径的代码只能告诉你"应该怎样做"。但真正的系统思维来自理解"如果不这样做会怎样"。

### 场景模拟：系统崩溃后的不一致状态

运行失败案例分析：
```bash
python code/micro_kairos_failure_cases.py
```

**预期输出**：
```
============================================================
💥 系统崩溃后的状态分析
============================================================

📊 存储统计:
   索引记录数: 3
   实际文件数: 2
   一致性: ❌ 数据不一致!

🔍 详细检查每个观察:

   观察 abc123: ✅ 正常
   观察 def456: ✅ 正常
   观察 ghi789: ❌ 损坏
      错误: DATA INCONSISTENCY
      问题: 索引指向的文件不存在！
```

### 错误实现 vs 正确实现

#### ❌ 错误做法（Broken）

```python
def append_broken(self, obs: Observation) -> bool:
    # Step 1: 先更新内存索引 ❌
    self.index["observations"].append({...})
    
    # Step 2: 保存索引到磁盘 ❌
    self._save_index()
    
    # Step 3: 写入观察数据（这里可能失败！）💥
    with open(filepath, 'w') as f:
        f.write(obs.to_json())
```

**崩溃场景**：
```
时间线:
T+0ms:  更新内存索引 ✓
T+1ms:  保存索引到磁盘 ✓
T+5ms:  尝试写入数据... 💥 CRASH! (磁盘满/权限错误/SIGKILL)
T+5ms:  数据未写入，但索引已记录

结果: 索引指向不存在的数据（"幽灵记录"）
```

#### ✅ 正确做法（Strict Write Discipline）

```python
def append_correct(self, obs: Observation) -> bool:
    # Step 1: 写入观察数据到临时文件
    temp_path = filepath + ".tmp"
    with open(temp_path, 'w') as f:
        f.write(obs.to_json())
    
    # Step 2: 确保数据落盘
    os.fsync(f.fileno())
    
    # Step 3: 原子重命名（保证数据持久化）
    os.rename(temp_path, filepath)
    
    # Step 4: 数据确认写入后，再更新索引 ✓
    self.index["observations"].append({...})
    
    # Step 5: 保存索引
    self._save_index()
```

**崩溃场景**：
```
时间线:
T+0ms:  写入临时文件 ✓
T+5ms:  原子重命名 ✓
T+6ms:  尝试更新索引... 💥 CRASH!

结果: 数据已安全写入，索引可重建（从日志扫描）
```

### 可视化对比

```
❌ 错误顺序                    ✅ 正确顺序
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                              
  索引 ──→ 数据               数据 ──→ 索引
   │         │                 │         │
   ▼         ▼                 ▼         ▼
┌─────┐   ┌─────┐          ┌─────┐   ┌─────┐
│ ✓✓✓ │   │ ✗✗✗ │          │ ✓✓✓ │   │ ✗✗✗ │
│索引 │   │数据 │          │数据 │   │索引 │
│更新 │   │丢失 │          │安全 │   │未更 │
└─────┘   └─────┘          └─────┘   └─────┘
                              ↑
                         可重建！

后果: 数据不一致            后果: 索引可重建
      无法恢复                    数据完整
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 恢复演示

正确做法的另一个优势：**可从日志重建索引**。

```python
# 索引损坏或丢失？没关系，扫描日志重建！
def rebuild_index_from_logs(self) -> Dict:
    """从观察日志重建索引"""
    new_index = {"observations": []}
    
    for filename in os.listdir(self.obs_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(self.obs_dir, filename)
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            new_index["observations"].append({
                "id": data["id"],
                "file": filename
            })
    
    return new_index
```

**为什么这有效？**
- 日志是**追加-only**的 → 幂等操作
- 数据一旦写入就不会变 → 真相不变
- 索引只是**派生数据** → 可以随时重建

### 现实世界的类比

| 场景 | 错误做法 | 正确做法 |
|------|----------|----------|
| 银行转账 | 先扣款，后转账（扣款后转账失败） | 先记账，后扣款（可回滚） |
| 电商订单 | 先减库存，后收款（库存丢了） | 先锁定库存，收款后再减 |
| 数据库 | 先更新索引，后写数据页 | WAL：先写日志，后写数据 |
| KAIROS | 先更新 index.md，后写 observations/ | 先写 jsonl，成功后更新 index |

### 教学要点

```
严格写入纪律 = "数据是真相，索引是指针"

• 指针可以重建（从数据重新生成）
• 数据一旦丢失就彻底丢失
• 所以：必须先保护真相，再更新指针

这类似于数据库的 Write-Ahead Logging (WAL)
```

### 5分钟实验：故意制造失败

**目标**: 亲手体验数据不一致

**操作**:
```bash
# 1. 运行失败案例分析
python code/micro_kairos_failure_cases.py

# 2. 在 micro_kairos_v2.py 中，手动制造崩溃
#    在 append() 方法的 index 更新和文件写入之间添加：
import sys
sys.exit(1)  # 模拟 SIGKILL

# 3. 运行并检查状态
python code/micro_kairos_v2.py
ls -la .micro-kairos/observations/  # 文件数 < 索引记录数
```

**问题**: 
- 如何检测这种不一致？
- 如何修复？（提示：从日志重建索引）
- 为什么 KAIROS 使用 jsonl 而不是 sqlite？（append-only 的优势）

---

## 5.6 调试你自己的 KAIROS —— 完整故障排查指南

> "Debugging is twice as hard as writing the code in the first place." — Brian Kernighan

当 micro-kairos 不工作时，使用此决策树系统排查。

### 🔴 问题 1: 观察日志没写入

**症状**: 运行程序后 `.micro-kairos/observations/` 目录为空或文件没有新内容

#### 诊断步骤

**Step 1: 检查目录权限**
```bash
ls -la .micro-kairos/
# 预期: drwxr-xr-x  (755 权限)
# 问题: 如果显示权限 denied，需要修复

# 修复
chmod 755 .micro-kairos/
chmod 755 .micro-kairos/observations/
```

**Step 2: 检查严格写入纪律**
```python
# 在 ObservationStore.append() 中添加调试

def append(self, obs: Observation) -> bool:
    print(f"[DEBUG] 开始添加观察: {obs.id}")
    
    # Step 1: 写入数据
    filepath = os.path.join(self.obs_dir, f"{obs.id}.json")
    print(f"[DEBUG] 写入文件: {filepath}")
    
    try:
        with open(filepath, 'w') as f:
            f.write(obs.to_json())
        print(f"[DEBUG] 文件写入成功")
    except Exception as e:
        print(f"[ERROR] 文件写入失败: {e}")
        return False  # 重要：失败时返回 False
    
    # Step 2: 更新索引（只有文件写入成功后才执行）
    print(f"[DEBUG] 更新索引")
    self.index["observations"].append({"id": obs.id, "file": filepath})
    
    return True
```

**Step 3: 检查 JSON 序列化**
```python
# 测试 Observation 是否可序列化
obs = Observation("test-001", time.time(), "test", "test content")

try:
    json_str = obs.to_json()
    print(f"[DEBUG] 序列化成功: {json_str[:100]}...")
    
    # 验证可以反序列化
    data = json.loads(json_str)
    print(f"[DEBUG] 反序列化成功: {data}")
except Exception as e:
    print(f"[ERROR] 序列化失败: {e}")
    # 常见问题: Observation 类没有 to_json() 方法
    # 常见问题: content 包含无法序列化的对象
```

**常见错误及修复**:

| 错误信息 | 原因 | 修复 |
|---------|------|------|
| `FileNotFoundError` | 目录不存在 | `os.makedirs(self.obs_dir, exist_ok=True)` |
| `PermissionError` | 权限不足 | 检查目录权限，或以其他用户运行 |
| `TypeError: Object of type Observation is not JSON serializable` | 缺少 to_json() | 添加序列化方法 |
| `KeyError: 'observations'` | 索引结构错误 | 初始化索引时确保有默认键 |

---

### 🔴 问题 2: 整合不触发（AutoDream 不运行）

**症状**: 观察数量足够，但 AutoDream 从不启动

#### 诊断步骤

**Step 1: 检查四重门状态**
```python
# 在 should_run() 中添加详细日志

def should_run(self) -> tuple[bool, str]:
    cfg = self.config
    
    # Gate 1: 时间门
    last_at = self.get_last_consolidation_time()
    hours_since = (time.time() - last_at) / 3600
    print(f"[DEBUG] Gate 1 - 时间: {hours_since:.1f}h / 需要 {cfg.min_hours}h")
    if hours_since < cfg.min_hours:
        return False, f"时间门: 仅过了 {hours_since:.1f}h"
    
    # Gate 2: 扫描节流门
    since_scan = time.time() - self.last_scan_at
    print(f"[DEBUG] Gate 2 - 扫描: {since_scan/60:.1f}min / 需要 10min")
    if since_scan < 10 * 60:
        return False, f"扫描门: 仅过了 {since_scan/60:.1f}min"
    
    # Gate 3: 会话门
    session_count = len(self.get_observations_since(last_at))
    print(f"[DEBUG] Gate 3 - 会话: {session_count} / 需要 {cfg.min_sessions}")
    if session_count < cfg.min_sessions:
        return False, f"会话门: 仅有 {session_count} 个"
    
    # Gate 4: 文件锁门
    prior_mtime = self.try_acquire_lock()
    print(f"[DEBUG] Gate 4 - 锁: {'获得' if prior_mtime else '被占用'}")
    if prior_mtime is None:
        return False, "锁门: 其他进程持有锁"
    
    return True, "所有门通过"
```

**Step 2: 手动测试触发条件**
```bash
# 强制重置时间门（用于测试）
touch -d "2 days ago" .micro-kairos/consolidation.lock

# 检查锁文件状态
ls -la .micro-kairos/consolidation.lock
stat .micro-kairos/consolidation.lock
```

**Step 3: 检查配置值**
```python
# 打印当前配置
print(f"[DEBUG] min_hours: {self.config.min_hours}")
print(f"[DEBUG] min_sessions: {self.config.min_sessions}")
print(f"[DEBUG] stale_ms: {self.config.stale_ms}")

# 常见问题：配置值设置过高，永远无法达到
```

**快速测试模式**（调试用）:
```python
# 临时降低阈值以测试整合逻辑
TEST_CONFIG = {
    "min_hours": 0.001,      # 3.6 秒（而不是 24 小时）
    "min_sessions": 1,       # 1 个（而不是 5 个）
    "stale_ms": 1000         # 1 秒
}
```

---

### 🔴 问题 3: 锁竞争（"另一个进程正在运行"）

**症状**: `try_acquire_lock()` 总是返回 None

#### 诊断步骤

**Step 1: 检查锁文件**
```bash
# 查看锁文件内容
cat .micro-kairos/consolidation.lock
# 预期: 进程 PID，如 "12345"

# 检查该 PID 是否还存在
ps -p $(cat .micro-kairos/consolidation.lock)
# 如果返回空，说明是"死锁"
```

**Step 2: 手动清理死锁**
```bash
# 如果确认没有其他进程在运行
rm .micro-kairos/consolidation.lock

# 重新运行程序
python micro_kairos_v3.py
```

**Step 3: 添加锁调试信息**
```python
def try_acquire_lock(self) -> Optional[int]:
    lock_path = self.lock_file
    
    print(f"[DEBUG] 尝试获取锁: {lock_path}")
    
    # 检查现有锁
    if os.path.exists(lock_path):
        with open(lock_path, 'r') as f:
            holder_pid = f.read().strip()
        print(f"[DEBUG] 现有锁持有者 PID: {holder_pid}")
        
        # 检查 PID 是否存活
        if self.is_process_running(int(holder_pid)):
            print(f"[DEBUG] PID {holder_pid} 正在运行，无法获取锁")
            return None
        else:
            print(f"[DEBUG] PID {holder_pid} 已死亡，回收锁")
    
    # 写入自己的 PID
    with open(lock_path, 'w') as f:
        f.write(str(os.getpid()))
    print(f"[DEBUG] 已写入 PID: {os.getpid()}")
    
    return 0
```

---

### 🔴 问题 4: 数据不一致（索引与文件不匹配）

**症状**: 查询返回 "文件不存在" 错误或索引记录数 ≠ 实际文件数

#### 诊断步骤

**Step 1: 验证一致性**
```bash
# 统计索引中的记录数
python -c "
import json
with open('.micro-kairos/index.json') as f:
    index = json.load(f)
    print(f'索引记录数: {len(index[\"observations\"])}')"

# 统计实际文件数
ls .micro-kairos/observations/*.json | wc -l

# 如果不匹配，说明有数据不一致
```

**Step 2: 修复不一致（重建索引）**
```python
def rebuild_index(self) -> None:
    """从日志文件重建索引"""
    print("[REBUILD] 开始重建索引...")
    
    new_index = {"observations": [], "total": 0}
    
    # 扫描所有观察文件
    for filename in os.listdir(self.obs_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(self.obs_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                
                new_index["observations"].append({
                    "id": data["id"],
                    "file": filepath,
                    "timestamp": data["timestamp"]
                })
                new_index["total"] += 1
                print(f"[REBUILD] 添加: {data['id']}")
            except Exception as e:
                print(f"[REBUILD] 跳过损坏文件 {filename}: {e}")
    
    # 保存新索引
    self.index = new_index
    self._save_index()
    print(f"[REBUILD] 完成，共 {new_index['total']} 条记录")
```

**Step 3: 预防不一致**
```python
# 启动时自动检查一致性
class ObservationStore:
    def __init__(self, base_dir: str):
        # ... 初始化代码 ...
        
        # 启动时检查一致性
        if not self._check_consistency():
            print("[WARN] 检测到数据不一致，正在重建索引...")
            self.rebuild_index()
    
    def _check_consistency(self) -> bool:
        """检查索引与文件是否一致"""
        index_count = len(self.index.get("observations", []))
        
        actual_count = 0
        for f in os.listdir(self.obs_dir):
            if f.endswith('.json'):
                actual_count += 1
        
        if index_count != actual_count:
            print(f"[WARN] 不一致: 索引 {index_count} ≠ 文件 {actual_count}")
            return False
        return True
```

---

### 🔴 问题 5: 性能问题（tick 间隔不均 / 延迟高）

**症状**: Tick 不是按预期间隔执行，或响应缓慢

#### 诊断步骤

**Step 1: 测量 tick 执行时间**
```python
def on_tick(self):
    start = time.time()
    
    # ... tick 逻辑 ...
    
    elapsed = time.time() - start
    print(f"[PERF] Tick 执行时间: {elapsed*1000:.2f}ms")
    
    if elapsed > 15:  # 超过 15 秒
        print(f"[WARN] Tick 超时! 考虑拆分任务")
```

**Step 2: 识别慢操作**
```python
import time

class PerformanceMonitor:
    def __init__(self):
        self.timings = {}
    
    def time_operation(self, name: str, func, *args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        
        if name not in self.timings:
            self.timings[name] = []
        self.timings[name].append(elapsed)
        
        print(f"[PERF] {name}: {elapsed*1000:.2f}ms")
        return result
    
    def report(self):
        print("\n[PERF REPORT]")
        for name, times in self.timings.items():
            avg = sum(times) / len(times) * 1000
            max_t = max(times) * 1000
            print(f"  {name}: avg={avg:.2f}ms, max={max_t:.2f}ms, count={len(times)}")

# 使用
monitor = PerformanceMonitor()
monitor.time_operation("query", self.store.query_by_time, since)
monitor.time_operation("consolidate", self.consolidator.run)
monitor.report()
```

---

### 🔴 问题 6: JSONL 解析错误

**症状**: `json.JSONDecodeError` 或 `ValueError`

#### 诊断步骤

**Step 1: 检查损坏的 JSONL 行**
```bash
# 找到损坏的行
python -c "
import json
with open('.micro-kairos/observations/2026-04-03.jsonl') as f:
    for i, line in enumerate(f, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            print(f'Line {i}: {e}')
            print(f'Content: {line[:100]}')"
```

**Step 2: 修复或跳过损坏行**
```python
def read_jsonl_safe(filepath: str) -> List[Dict]:
    """安全读取 JSONL，跳过损坏的行"""
    results = []
    with open(filepath, 'r') as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] 跳过损坏行 {i}: {e}")
                continue
    return results
```

---

### 🛠️ 调试工具脚本

创建一个调试脚本 `debug_micro_kairos.py`:

```python
#!/usr/bin/env python3
"""micro-kairos 调试工具"""

import os
import json
import sys

def check_directory_structure(base_dir=".micro-kairos"):
    """检查目录结构"""
    print("=== 目录结构检查 ===")
    
    if not os.path.exists(base_dir):
        print(f"❌ 目录不存在: {base_dir}")
        return False
    
    print(f"✓ 主目录存在: {base_dir}")
    
    # 检查子目录
    obs_dir = os.path.join(base_dir, "observations")
    if os.path.exists(obs_dir):
        files = [f for f in os.listdir(obs_dir) if f.endswith('.json')]
        print(f"✓ 观察目录: {len(files)} 个文件")
    else:
        print(f"❌ 观察目录不存在: {obs_dir}")
    
    # 检查索引
    index_file = os.path.join(base_dir, "index.json")
    if os.path.exists(index_file):
        with open(index_file) as f:
            index = json.load(f)
        print(f"✓ 索引: {len(index.get('observations', []))} 条记录")
    else:
        print(f"❌ 索引不存在: {index_file}")
    
    return True

def check_consistency(base_dir=".micro-kairos"):
    """检查数据一致性"""
    print("\n=== 一致性检查 ===")
    
    index_file = os.path.join(base_dir, "index.json")
    obs_dir = os.path.join(base_dir, "observations")
    
    # 加载索引
    with open(index_file) as f:
        index = json.load(f)
    
    index_ids = {obs["id"] for obs in index.get("observations", [])}
    
    # 扫描文件
    file_ids = set()
    for filename in os.listdir(obs_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(obs_dir, filename)
            with open(filepath) as f:
                data = json.load(f)
                file_ids.add(data["id"])
    
    # 对比
    missing_files = index_ids - file_ids
    missing_index = file_ids - index_ids
    
    if missing_files:
        print(f"❌ 索引中有但文件不存在: {missing_files}")
    if missing_index:
        print(f"❌ 文件存在但索引中缺失: {missing_index}")
    if not missing_files and not missing_index:
        print("✓ 数据一致性检查通过")
    
    return not (missing_files or missing_index)

def check_lock(base_dir=".micro-kairos"):
    """检查锁状态"""
    print("\n=== 锁状态检查 ===")
    
    lock_file = os.path.join(base_dir, "consolidation.lock")
    
    if not os.path.exists(lock_file):
        print("✓ 无锁文件（可用）")
        return True
    
    with open(lock_file) as f:
        pid = f.read().strip()
    
    import subprocess
    result = subprocess.run(['ps', '-p', pid], capture_output=True)
    
    if result.returncode == 0:
        print(f"❌ 锁被 PID {pid} 持有（正在运行）")
        return False
    else:
        print(f"⚠️  死锁 detected (PID {pid} 不存在)")
        return None  # 死锁

if __name__ == "__main__":
    check_directory_structure()
    check_consistency()
    check_lock()
```

运行调试工具:
```bash
python debug_micro_kairos.py
```

---

### ✅ 任务: 故障排查实战（难度 ⭐⭐⭐）

**目标**: 故意制造故障并修复

**操作**:

1. **制造数据不一致**:
```bash
# 1. 运行 micro-kairos 添加一些观察
python micro_kairos_v3.py

# 2. 手动删除一个观察文件（模拟崩溃）
rm .micro-kairos/observations/obs_0001.json

# 3. 尝试查询，观察错误
# 4. 运行 debug_micro_kairos.py 诊断
# 5. 修复: rebuild_index()
```

2. **制造死锁**:
```bash
# 1. 手动写入一个虚假的锁文件
echo "99999" > .micro-kairos/consolidation.lock

# 2. 运行程序，观察锁竞争
# 3. 运行 debug_micro_kairos.py 诊断
# 4. 修复: 手动删除锁文件
```

3. **制造权限错误**:
```bash
# 1. 修改目录权限
chmod 000 .micro-kairos/observations/

# 2. 运行程序，观察错误
# 3. 修复: chmod 755
```

**反思**: 每个故障的根本原因是什么？如何预防？

---

## 5.7 检查点

完成本模块后，你应该能够：
- [ ] 运行并理解 v1/v2/v3 的渐进式实现
- [ ] 解释严格写入纪律的重要性
- [ ] 实现四重门检查逻辑
- [ ] 理解 mtime-based 文件锁的可回滚设计
- [ ] **排查 micro-kairos 的常见故障（使用决策树）**
- [ ] **使用调试工具诊断数据不一致、死锁、权限问题**
- [ ] **修复数据不一致（重建索引）**

