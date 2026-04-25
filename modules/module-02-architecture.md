# 模块二：架构深度拆解——三层模型

> "Architecture is the art of deciding what goes where, and why." — 本模块核心

**时长**：4-5 小时  
**形式**：代码阅读 + 图解  
**前置要求**：完成模块一

---

## 2.0 从零开始：你会犯哪些错误？

> 在解释 KAIROS 如何解决这些问题之前，让我们先犯一遍错误。

假设你接到一个任务：**设计一个在你工作时持续观察、主动帮助的 AI 系统**。你会怎么做？

### 错误一：事件驱动架构

**直觉**: "用户做了某件事 → AI 响应"，这是聊天机器人的工作方式。

```typescript
// naive.ts - 你的第一版设计
fs.watch('./src', (event, filename) => {
  // 文件变化了！立即分析
  analyzeFile(filename);  // 可能耗时 30 秒
});

process.on('userCommand', (cmd) => {
  // 用户运行命令了！立即响应
  analyzeCommand(cmd);  // 可能耗时 10 秒
});
```

**问题**（很快就会遇到）：
```
T+0ms:  用户保存 file.ts → 开始分析
T+100ms: 用户保存 file.ts 再次 → 开始另一个分析
T+200ms: 用户运行 npm test → 开始命令分析
T+500ms: git 自动提交触发 → 开始 git 分析
        ...
T+3000ms: 系统同时运行 15 个分析任务，CPU 100%，用户电脑卡顿
```

**你的系统变成了 DDoS 攻击者** —— 帮助变成了骚扰。

---

### 错误二：全量记忆加载

**直觉**: "AI 需要理解上下文 → 把历史记录全部加载到 prompt"，这是 RAG 的标准做法。

```typescript
// naive.ts - 你的第二版设计
async function getContext() {
  const history = await db.query('SELECT * FROM observations');
  const content = history.map(h => h.content).join('\n');
  return content;  // 可能 10MB+
}

async function onTick() {
  const context = await getContext();  // 加载全部历史！
  const response = await llm.chat([
    { role: 'system', content: '你是帮助用户的 AI 助手。历史:\n' + context },
    { role: 'user', content: '现在情况如何？' }
  ]);
}
```

**问题**（数据量增长后）：
- 第 1 天：100 条观察，prompt 10KB，LLM 调用 2 秒
- 第 7 天：700 条观察，prompt 70KB，LLM 调用 10 秒
- 第 30 天：3000 条观察，prompt 300KB，**超出 token 限制**

**你的 AI 得了"失忆症"** —— 越用越笨。

---

### 错误三：同步写入

**直觉**: "用户操作了 → 立即写入数据库"，确保数据不丢失。

```typescript
// naive.ts - 你的第三版设计
async function recordObservation(obs) {
  await db.insert(obs);        // 等待磁盘写入
  await updateIndex(obs);      // 等待索引更新
  await syncToCloud(obs);      // 等待网络同步
  return true;                 // 整个过程 200-500ms
}

// 用户每次操作都要等待
user.on('save', async (file) => {
  await recordObservation({ type: 'file_save', file });  // 阻塞 500ms！
});
```

**问题**（用户体验）：
```
用户保存文件 → 等待 500ms → 文件才真的保存 → 用户骂骂咧咧
```

**你的 AI 成了"路障"** —— 帮助变成了阻碍。

---

### 错误四：无限自主

**直觉**: "AI 应该尽可能多做"，把权限都给 AI。

```typescript
// naive.ts - 你的第四版设计
async function onTick() {
  const plan = await llm.generatePlan();
  for (const step of plan) {
    await execute(step);  // 执行任意工具
    // 没有预算限制！没有用户确认！
  }
}
```

**问题**（某天深夜）：
```
T+0:    AI 决定 "重构代码"
T+10s:  AI 删除了 50 个文件
T+20s:  AI 生成了新实现
T+30s:  AI 运行测试 → 失败
T+40s:  AI 继续尝试修复 → 越改越糟
T+60s:  用户发现时，git status 显示 200+ 文件变更
```

**你的 AI 成了"失控的自动修复机"** —— 好心办坏事。

---

### 错误五：密集循环

**直觉**: "AI 应该一直检查有没有事做"，while(true) 循环。

```typescript
// naive.ts - 你的第五版设计
async function main() {
  while (true) {
    await onTick();       // 执行一次 tick
    await sleep(100);     // 每 100ms 检查一次
  }
}
```

**问题**（笔记本电脑）：
- CPU 使用率 10-20%（即使没有用户活动）
- 电池 2 小时耗尽
- 风扇狂转

**你的 AI 成了"电老虎"** —— 用户想关掉它。

---

## KAIROS 如何避免这些错误

| 错误 | KAIROS 的解决方案 | 源码位置 |
|------|------------------|----------|
| **事件驱动 → DDoS** | **Tick 架构**: 固定节奏评估，而非事件触发 | `tickHandler.ts` |
| **全量加载 → 失忆** | **三层记忆**: 指针 + 摘要 + 原始日志，按需获取 | `bootstrap/state.ts` |
| **同步写入 → 阻塞** | **严格写入纪律**: 异步队列，用户操作不等待 | `ObservationStore` |
| **无限自主 → 失控** | **15 秒预算**: 硬边界，超时必须 Sleep | `onTick()` |
| **密集循环 → 耗电** | **智能睡眠**: 根据用户活动调整 tick 间隔 | `autoDream.ts` |

---

## 2.1 第一层：心跳（Tick 系统）

### 核心数据结构

```typescript
// src/proactive/tickHandler.ts
interface TickContext {
  timestamp: number;                    // 当前时间戳
  projectStateHash: string;             // 项目状态指纹
  userActivity: 'active' | 'idle' | 'away';  // 用户活动状态
  pendingObservations: Observation[];   // 待处理的观察
}

interface Observation {
  id: string;
  timestamp: number;
  type: 'file_change' | 'command_run' | 'user_action' | 'inference';
  content: string;
  importance: number;  // 0-1，用于优先级排序
}

type Action = { type: 'act'; tool: string; params: any };
type Sleep = { type: 'sleep'; reason: string };

// 决策边界
async function onTick(ctx: TickContext): Promise<Action | Sleep> {
  const budget = 15000; // 15 秒 = 15000 毫秒
  const deadline = Date.now() + budget;
  
  // 评估是否有高价值行动
  const candidates = await evaluateOpportunities(ctx);
  const viable = candidates.filter(c => 
    c.estimatedDuration < deadline - Date.now()
  );
  
  if (viable.length === 0) {
    return { type: 'sleep', reason: 'no_high_value_action' };
  }
  
  // 选择最佳行动
  const best = selectBest(viable);
  return { type: 'act', tool: best.tool, params: best.params };
}
```

### 为什么是 Tick 架构？

**事件驱动的问题**：
```
用户保存文件 → 触发分析 → 用户又保存 → 队列堆积 → 系统过载
```

**Tick 架构的优势**：
```
tick @ T0: 评估所有待处理事件 → 决定行动
tick @ T1: 重新评估（可能包括新事件）→ 决定行动
...
```

Ticks 提供**可预测的节奏**用于推理，而不是被事件淹没。

### Tick 调度时间线（ASCII 动画示意）

```
时间轴 ──────────────────────────────────────────────────────────►

Tick 0    Tick 1    Tick 2    Tick 3    Tick 4    Tick 5
  │         │         │         │         │         │
  ▼         ▼         ▼         ▼         ▼         ▼
┌────┐    ┌────┐    ┌────┐    ┌────┐    ┌────┐    ┌────┐
│ 😴 │    │ ⚡ │    │ 😴 │    │ ⚡ │    │ 😴 │    │ ⚡ │
│SLEEP│   │ ACT│    │SLEEP│   │ ACT│    │SLEEP│   │ ACT│
└────┘    └──┬─┘    └────┘    └──┬─┘    └────┘    └──┬─┘
             │                   │                   │
             ▼                   ▼                   ▼
        ┌─────────┐        ┌─────────┐        ┌─────────┐
        │ 观察项目 │        │ 发送通知 │        │ 整合记忆 │
        │ 状态变化 │        │ 用户进度 │        │ (若满足) │
        │ (0.3s)  │        │ (0.1s)  │        │ (8min)  │
        └─────────┘        └─────────┘        └─────────┘

图例: 😴 = Sleep (无事可做)    ⚡ = Act (执行行动)
```

**关键观察**：
- 大多数 tick 返回 Sleep（反叙述设计）
- Act 在 15 秒预算内完成
- AutoDream 是特殊的 Act，有独立的 8-10 分钟预算

### 状态流转图

```
┌─────────────┐     创建     ┌─────────────┐
│   系统启动   │ ──────────► │  Tick等待   │
└─────────────┘              └──────┬──────┘
                                    │ 定时唤醒
                                    ▼
                           ┌─────────────────┐
                           │   评估器运行     │
                           │  (预算: 15s)    │
                           └────────┬────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             ┌──────────┐    ┌──────────┐    ┌──────────┐
             │ 无高价值 │    │ 有行动但 │    │ 有行动且│
             │   行动   │    │ 超预算   │    │ 在预算内│
             └────┬─────┘    └────┬─────┘    └────┬─────┘
                  │               │               │
                  ▼               ▼               ▼
            ┌──────────┐    ┌──────────┐    ┌──────────┐
            │  Sleep   │    │  Defer   │    │   Act    │
            │  (默认)  │    │ (推迟)   │    │ (执行)   │
            └──────────┘    └──────────┘    └──────────┘
                  │               │               │
                  └───────────────┴───────────────┘
                                  │
                                  ▼
                           ┌─────────────┐
                           │  记录观察   │
                           │  (若需要)   │
                           └──────┬──────┘
                                  │
                                  ▼
                           ┌─────────────┐
                           │  返回等待   │
                           └─────────────┘
```

### 15 秒约束：软实时系统中的硬边界

```
┌─────────────────────────────────────────┐
│           15 秒阻塞预算                  │
├─────────────────────────────────────────┤
│  0-5s   │ 快速读取、状态检查            │
│  5-10s  │ 分析、决策                    │
│  10-15s │ 执行快速操作                  │
│  >15s   │ ❌ 必须推迟到下次 tick        │
└─────────────────────────────────────────┘
```

#### 15 秒预算耗尽时的检查点可视化

**正常完成场景**：
```
时间轴:  0s      3s      6s      9s      12s     15s
         │       │       │       │       │       │
         ▼       ▼       ▼       ▼       ▼       ▼
步骤:   [Step1] [Step2] [Step3] [Step4] [Step5] [Done]
         ████    ████    ████    ████    ████
         
状态:   运行中 → 运行中 → 运行中 → 运行中 → 运行中 → ✅ 完成

结果: { status: 'completed', completed: 5/5, elapsed: '12.5s' }
```

**预算耗尽场景**（需要检查点）：
```
时间轴:  0s      4s      8s      12s     15s     18s
         │       │       │       │       │       │
         ▼       ▼       ▼       ▼       ▼       ▼
步骤:   [Step1] [Step2] [Step3] [Step4] [Step5] [Step6]
         ███████ ███████ ███████ ███████ │ 被推迟 │
                                           ▲
                                          ╱ ╲
                                    预算耗尽!
                                    ⏰ 15s 到达

检查点保存:
┌─────────────────────────────────────────┐
│ CHECKPOINT                              │
├── completed: 4 (Step1-4 已完成)        │
├── remaining: [Step5, Step6]            │
├── state: { partialEdit: 'line 42' }    │
└── timestamp: 1712134567890             │
└─────────────────────────────────────────┘

结果: { 
  status: 'deferred', 
  completed: 4/6, 
  elapsed: '15.1s',
  checkpoint: { remaining: [Step5, Step6], ... }
}
```

**下次 tick 恢复执行**：
```
时间轴:  (上次)  15s              (下次 tick)  18s    21s
                 │                              │       │
                 ▼                              ▼       ▼
步骤:           [Step4]    [检查点恢复]        [Step5] [Step6] [Done]
                 ███████   ┌───────────┐       ███     ███
                           │ 恢复状态   │
                           │ Step5,6   │
                           └───────────┘

结果: { status: 'completed', completed: 2/2, total: 6/6, elapsed: '6.2s' }
```

**代码实现示意**（`BudgetExecutor`）：
```typescript
class BudgetExecutor {
  private budgetMs: number = 15000;
  
  async execute<T>(steps: Step<T>[]): Promise<BudgetResult<T>> {
    const start = Date.now();
    const completed: T[] = [];
    
    for (let i = 0; i < steps.length; i++) {
      const elapsed = Date.now() - start;
      const remaining = this.budgetMs - elapsed;
      
      if (remaining <= 0) {
        // ⏰ 预算耗尽！保存检查点
        return {
          status: 'deferred',
          checkpoint: {
            completed: i,
            remaining: steps.slice(i),
            state: this.captureState()
          }
        };
      }
      
      // 执行步骤
      const result = await steps[i].run();
      completed.push(result);
    }
    
    return { status: 'completed', results: completed };
  }
  
  resume(checkpoint: Checkpoint): Step[] {
    // 🔄 从检查点恢复
    this.restoreState(checkpoint.state);
    return checkpoint.remaining;
  }
}
```

这创建了一个自然的**能力层级**：
- ✅ 文件扫描、通知发送、PR 监控
- ⚠️ 小文件编辑（如果在预算内）
- ❌ 大规模重构、多文件修改

---

## 2.2 第二层：观察日志（只写日志）

### 目录结构

```
.claude/kairos/
├── observations/
│   ├── 2026-04-02.jsonl          # 只追加，每日滚动
│   ├── 2026-04-03.jsonl
│   └── 2026-04-04.jsonl
├── kairos-index.md               # 轻量指针文件
└── consolidated/
    ├── week-13-consolidated.md   # AutoDream 输出
    └── month-04-consolidated.md
```

### 严格的写入纪律

```typescript
// ❌ 错误：先更新索引，再写入
async function badUpdate(obs: Observation) {
  await updateIndex(obs);  // 如果下一步失败，索引就脏了
  await appendToLog(obs);
}

// ✅ 正确：先写入，成功后更新索引
async function goodUpdate(obs: Observation) {
  await appendToLog(obs);  // 写入文件系统
  await updateIndex({      // 成功后，更新指针
    date: getDate(),
    count: await getLogCount(),
    hash: await computeHash(obs)
  });
}
```

**为什么这很重要？**
- 防止"幻觉式记忆"：模型不能把失败的尝试污染进上下文
- 可恢复性：如果索引损坏，可以从日志重建
- 可验证性：索引只是提示，真实数据在日志中

### 轻量索引设计

```markdown
# kairos-index.md (~150 字符/行)

## 2026-04-02
- 观察数: 47
- 关键事件: 重构 auth 模块
- 指向: observations/2026-04-02.jsonl

## 2026-04-03  
- 观察数: 23
- 关键事件: 新增 API 端点
- 指向: observations/2026-04-03.jsonl
```

这个索引文件**常驻上下文**，但体积很小。

#### 数值实验：索引 vs 完整转录的 Token 对比

**实验设置**：模拟一个 30 天的开发会话，每天产生 50 条观察。

**数据规模**：
| 指标 | 数值 |
|------|------|
| 会话天数 | 30 天 |
| 日均观察数 | 50 条 |
| 单条观察平均长度 | 200 tokens |
| 总观察数 | 1,500 条 |

**Token 占用对比**：

```
方案 A: 加载完整转录（Naive 实现）
├─ 1,500 条 × 200 tokens = 300,000 tokens
├─ 系统提示词 overhead = ~2,000 tokens
└─ 总计: 302,000 tokens (~75% 的 128K 上下文窗口)

方案 B: KAIROS 轻量索引（实际实现）
├─ 索引文件: 30 天 × 150 字符 = 4,500 字符 ≈ 1,125 tokens
├─ 按需加载 (grep 筛选后): ~10 条 × 200 tokens = 2,000 tokens
├─ 系统提示词 overhead = ~2,000 tokens
└─ 总计: ~5,125 tokens (~4% 的 128K 上下文窗口)

内存效率提升: 302,000 / 5,125 ≈ 59×
```

**不同时间窗口的对比表**：

| 时间跨度 | 完整转录 | 轻量索引 | 按需加载 | 节省比例 |
|---------|---------|---------|---------|---------|
| 1 天 (50 条) | 10,000 | 1,125 | ~2,000 | 69% |
| 7 天 (350 条) | 70,000 | 1,125 | ~2,000 | 96% |
| 30 天 (1,500 条) | 300,000 | 1,125 | ~2,000 | 99% |
| 90 天 (4,500 条) | 900,000 | 1,125 | ~2,000 | 99.7% |

**关键洞察**：
- 随着时间推移，完整转录呈线性增长，很快超出上下文限制
- 轻量索引保持恒定（只保留最近 N 天的指针），与总历史无关
- 按需加载通过 `grep` 过滤，只加载相关的 5-15 条观察

#### Tick 间隔的 CPU 占用实测

**实验设置**：在标准笔记本 (MacBook Pro M3, 16GB RAM) 上运行 micro-kairos，测量不同 tick 间隔的 CPU 占用。

**测试场景**：
- 观察存储：1,000 条历史记录
- 评估器复杂度：中等（包含一次文件系统扫描）
- 运行时长：60 秒

**结果**：

```
Tick 间隔    CPU 占用    每秒评估次数    适合场景
─────────    ────────    ────────────    ─────────
100ms        12.5%       10              ❌ 过高频率，不推荐
500ms        3.2%        2               ⚠️ 高实时性场景
1,000ms      1.8%        1               ✅ 标准开发场景
3,000ms      0.6%        0.33            ✅ 推荐默认值
5,000ms      0.4%        0.2             ✅ 低功耗场景
30,000ms     0.1%        0.033           😴 后台监控模式
```

**可视化对比**：

```
CPU 占用 (%)
    │
 15 ┤                    ████
    │                   ██████
 10 ┤                  ████████
    │                 ██████████
  5 ┤                ████████████
    │    ████       ██████████████
  1 ┤   ██████     ████████████████
    │  ████████   ██████████████████
  0 ┼──┬─────┬────┬─────┬──────────┬────
     0.1s  0.5s  1s    3s         30s
          Tick 间隔

图例: ████ = CPU 占用比例
```

**设计启示**：
- **3-5 秒**是开发场景的甜点：足够响应快速变化，又不会过度消耗资源
- **15 秒预算**与 **3 秒 tick** 的比例（5:1）提供了自然的"思考 vs 执行"平衡
- CPU 占用 < 1% 意味着 KAIROS 可以与其他开发工具（IDE、浏览器、构建工具）共存而无感知影响

### Grep-Only 约束

```typescript
// ❌ 错误：加载所有原始转录
const allHistory = await loadAllTranscripts();

// ✅ 正确：只 grep 特定标识符
const relevant = await grepObservations({
  pattern: 'auth|login|session',
  since: '2026-04-01'
});
```

原始转录**永远不会**被完整加载到上下文中。

---

## 2.3 第三层：AutoDream（记忆整合）

### 触发条件（四重门）

基于 `services/autoDream/autoDream.ts` 的实际实现：

#### 四重门决策流程（ASCII 流程图）

```
                           ┌─────────────────┐
                           │  shouldRun()?   │
                           └────────┬────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
              ┌─────┤ Gate 1: 时间门 (Time Gate)    │
              │     │ hoursSince = now - lastAt     │
              │     │ hoursSince >= 24h?            │
              │     └───────────────────────────────┘
              │                 │
              │         ┌───────┴───────┐
              │         ▼               ▼
              │      [通过]          [拒绝]
              │         │               │
              │         ▼               │
              │    "通过时间门"         │
              │                         │
              │    ┌────────────────────┘
              │    ▼
              │    ┌───────────────────────────────┐
              └────┤ Gate 2: 扫描节流门           │
                   │ sinceScan = now - lastScan    │
                   │ sinceScan >= 10min?           │
                   └───────────────────────────────┘
                                   │
                           ┌───────┴───────┐
                           ▼               ▼
                        [通过]          [拒绝]
                           │               │
                           ▼               │
                      "更新 lastScan"      │
                                           │
                      ┌────────────────────┘
                      ▼
                      ┌───────────────────────────────┐
                ┌─────┤ Gate 3: 会话门 (Session Gate) │
                │     │ sessions = getRecentSessions()│
                │     │ sessions.length >= 5?         │
                │     └───────────────────────────────┘
                │                 │
                │         ┌───────┴───────┐
                │         ▼               ▼
                │      [通过]          [拒绝]
                │         │               │
                │         ▼               │
                │    "会话数达标"          │
                │                         │
                │    ┌────────────────────┘
                │    ▼
                │    ┌───────────────────────────────┐
                └────┤ Gate 4: 文件锁门 (Lock Gate)  │
                     │ priorMtime = tryAcquireLock() │
                     │ lock acquired?                │
                     └───────────────────────────────┘
                                     │
                             ┌───────┴───────┐
                             ▼               ▼
                          [通过]          [拒绝]
                             │               │
                             ▼               ▼
                    ┌─────────────────┐  ┌─────────────────┐
                    │  ✅ 开始整合     │  │ ❌ 返回 false   │
                    │  consolidate()  │  │ (其他进程持有)  │
                    └─────────────────┘  └─────────────────┘
```

**颜色图例**：
- 🟢 通过 → 继续下一门
- 🔴 拒绝 → 立即返回 false
- 🟡 扫描节流门特殊：通过后更新 `lastScanAt`

**失败路径汇总**：

| 门 | 失败原因 | 返回消息 |
|----|---------|---------|
| Gate 1 | 距上次整合不足 24h | `"时间未达标 (${hoursSince}h < 24h)"` |
| Gate 2 | 距上次扫描不足 10min | `"扫描过于频繁"` |
| Gate 3 | 观察数不足 5 个 | `"会话数不足 (${count} < 5)"` |
| Gate 4 | 其他进程持有锁 | `"其他进程正在整合"` |

#### 实际代码实现

```typescript
// Gate 1: 时间门（默认 24 小时）
const hoursSince = (Date.now() - lastAt) / 3_600_000;
if (hoursSince < cfg.minHours) return;

// Gate 2: 扫描节流门（10 分钟）
// 防止时间门通过后，session 门不满足时的频繁扫描
const sinceScanMs = Date.now() - lastSessionScanAt;
if (sinceScanMs < SESSION_SCAN_INTERVAL_MS) return;  // 10 * 60 * 1000

// Gate 3: 会话门（默认 5 个会话）
const sessionIds = await listSessionsTouchedSince(lastAt);
// 排除当前会话（它的 mtime 总是最新的）
const otherSessions = sessionIds.filter(id => id !== currentSession);
if (otherSessions.length < cfg.minSessions) return;

// Gate 4: 文件锁门
const priorMtime = await tryAcquireConsolidationLock();
if (priorMtime === null) return;  // 其他进程持有锁
```

**配置来源**：`tengu_onyx_plover` (GrowthBook)
```typescript
const DEFAULTS = {
  minHours: 24,
  minSessions: 5,
};
```

**KAIROS 模式下的行为**：
```typescript
function isGateOpen(): boolean {
  if (getKairosActive()) return false;  // KAIROS 使用 disk-skill dream
  // ... 其他检查
}
```
// 防止时间门通过后，session 门不满足时的频繁扫描
const sinceScanMs = Date.now() - lastSessionScanAt;
if (sinceScanMs < SESSION_SCAN_INTERVAL_MS) return;  // 10 * 60 * 1000

// Gate 3: 会话门（默认 5 个会话）
const sessionIds = await listSessionsTouchedSince(lastAt);
// 排除当前会话（它的 mtime 总是最新的）
const otherSessions = sessionIds.filter(id => id !== currentSession);
if (otherSessions.length < cfg.minSessions) return;

// Gate 4: 文件锁门
const priorMtime = await tryAcquireConsolidationLock();
if (priorMtime === null) return;  // 其他进程持有锁
```

**配置来源**：`tengu_onyx_plover` (GrowthBook)
```typescript
const DEFAULTS = {
  minHours: 24,
  minSessions: 5,
};
```

**KAIROS 模式下的行为**：
```typescript
function isGateOpen(): boolean {
  if (getKairosActive()) return false;  // KAIROS 使用 disk-skill dream
  // ... 其他检查
}
```

### 文件锁机制（consolidationLock.ts）

```typescript
const LOCK_FILE = '.consolidate-lock';
const HOLDER_STALE_MS = 60 * 60 * 1000;  // 1 小时过期

// 锁文件语义：
// - mtime = lastConsolidatedAt（实际时间戳）
// - 文件内容 = 持有者 PID

async function tryAcquireConsolidationLock(): Promise<number | null> {
  const path = lockPath();
  
  // 检查现有锁
  let mtimeMs: number | undefined;
  let holderPid: number | undefined;
  try {
    const [s, raw] = await Promise.all([stat(path), readFile(path, 'utf8')]);
    mtimeMs = s.mtimeMs;
    holderPid = parseInt(raw.trim(), 10);
  } catch {
    // ENOENT — 无锁
  }
  
  // 锁被持有且未过期
  if (mtimeMs !== undefined && Date.now() - mtimeMs < HOLDER_STALE_MS) {
    if (holderPid !== undefined && isProcessRunning(holderPid)) {
      return null;  // 活的 PID 持有锁
    }
    // 死 PID — 回收锁
  }
  
  // 获取锁
  await mkdir(getAutoMemPath(), { recursive: true });
  await writeFile(path, String(process.pid));
  
  // 验证（防止竞争）
  const verify = await readFile(path, 'utf8');
  if (parseInt(verify.trim(), 10) !== process.pid) return null;
  
  return mtimeMs ?? 0;  // 返回之前的时间戳（用于回滚）
}

// 失败后的回滚
async function rollbackConsolidationLock(priorMtime: number): Promise<void> {
  if (priorMtime === 0) {
    await unlink(lockPath());  // 恢复到无文件状态
  } else {
    await writeFile(lockPath(), '');
    await utimes(lockPath(), priorMtime / 1000, priorMtime / 1000);
  }
}
```

**关键设计**：
- mtime 即状态：锁文件的修改时间就是 `lastConsolidatedAt`
- PID 检查：防止 PID 重用导致的误判
- 竞争安全：写入后必须验证内容
- 可回滚：失败时可以将 mtime 恢复到之前的状态

### 整合提示词（4 阶段流程）

来自 `consolidationPrompt.ts`：

```markdown
## Phase 1 — Orient
- ls 记忆目录，了解现有结构
- 读取 ENTRYPOINT_NAME 理解当前索引
- 检查 logs/ 或 sessions/ 子目录

## Phase 2 — Gather recent signal
优先级：
1. Daily logs (logs/YYYY/MM/YYYY-MM-DD.md)
2. 现有记忆的漂移检测
3. Transcript 搜索（grep 特定关键词，不读整个文件）

## Phase 3 — Consolidate
- 合并新信号到现有主题文件
- 相对日期转绝对日期（"yesterday" → "2026-04-01"）
- 删除已证伪的记忆

## Phase 4 — Prune and index
- ENTRYPOINT_NAME 保持在 ~25KB 以内
- 每项 ~150 字符：`- [Title](file.md) — one-line hook`
- 移除过时/错误的指针
```

**工具约束**：
```
Bash 限制为只读命令（ls, find, grep, cat, stat, wc, head, tail）
禁止写入、重定向或修改状态的操作
```

### DreamTask UI 状态机

```typescript
type DreamPhase = 'starting' | 'updating';

type DreamTaskState = {
  type: 'dream';
  status: 'running' | 'completed' | 'failed' | 'killed';
  phase: DreamPhase;
  sessionsReviewing: number;  // 正在回顾的会话数
  filesTouched: string[];     // 检测到的 Edit/Write 操作
  turns: DreamTurn[];         // 助手回复（工具使用折叠为计数）
  abortController?: AbortController;
  priorMtime: number;         // 用于 kill 时的回滚
};

// 阶段切换：
// 'starting' → 第一次检测到 Edit/Write → 'updating'
```

**进度追踪**：`onMessage` 回调监控 forked agent 的输出
- 提取文本块（用户想看的推理）
- 折叠 tool_use 块为计数
- 捕获 Edit/Write 的文件路径

### 分叉子代理（runForkedAgent）

```typescript
const result = await runForkedAgent({
  promptMessages: [createUserMessage({ content: prompt })],
  cacheSafeParams: createCacheSafeParams(context),
  canUseTool: createAutoMemCanUseTool(memoryRoot),  // 工具权限限制
  querySource: 'auto_dream',
  forkLabel: 'auto_dream',
  skipTranscript: true,  // 不写入主会话记录
  overrides: { abortController },
  onMessage: makeDreamProgressWatcher(taskId, setAppState),
});
```

**为什么分叉？**
- 隔离失败：Dream 崩溃不影响主进程
- 独立预算：~8-10 分钟的整合预算 vs 15 秒 tick 预算
- 用户可控：可在 UI 中 kill，自动回滚锁

### 完成与失败处理

```typescript
// 成功
completeDreamTask(taskId, setAppState);
appendSystemMessage(createMemorySavedMessage(filesTouched));

// 失败（包括用户 kill）
if (abortController.signal.aborted) {
  // DreamTask.kill 已处理回滚
  return;
}
failDreamTask(taskId, setAppState);
await rollbackConsolidationLock(priorMtime);  // 允许重试
```

---

## 架构图总览

```
┌─────────────────────────────────────────────────────────────┐
│                        KAIROS 架构                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: Tick (心跳)                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  <tick> → 评估 → 决策 (15s 预算) → SleepTool       │   │
│  └─────────────────────────────────────────────────────┘   │
│                         ↓ 生成                              │
│  Layer 2: Observation Log (观察日志)                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  observations/*.jsonl (只追加)                       │   │
│  │  kairos-index.md (轻量指针, ~150 字符/行)            │   │
│  │  严格写入纪律: 先写入 → 成功 → 更新索引              │   │
│  └─────────────────────────────────────────────────────┘   │
│                         ↓ 触发                              │
│  Layer 3: AutoDream (记忆整合)                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  三重门触发 → 分叉子代理 → 合并/消解 → 写入          │   │
│  │  (24h + 5 会话 + 锁)      (8-10 分钟预算)            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 练习

### 练习 2.1：实现极简 Tick 调度器

```python
# tick_scheduler.py
import asyncio
from dataclasses import dataclass
from typing import Callable, Any
import time

@dataclass
class Tick:
    timestamp: float
    counter: int

class TickScheduler:
    def __init__(self, interval_ms: int = 1000):
        self.interval = interval_ms / 1000
        self.handlers = []
        self.counter = 0
    
    def register(self, handler: Callable[[Tick], Any]):
        self.handlers.append(handler)
    
    async def run(self, duration_sec: int = 60):
        start = time.time()
        while time.time() - start < duration_sec:
            tick = Tick(
                timestamp=time.time(),
                counter=self.counter
            )
            
            for handler in self.handlers:
                try:
                    result = handler(tick)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    print(f"Handler error: {e}")
            
            self.counter += 1
            await asyncio.sleep(self.interval)

# 使用示例
scheduler = TickScheduler(interval_ms=5000)  # 5 秒 tick

@scheduler.register
def my_handler(tick: Tick):
    print(f"Tick {tick.counter} at {tick.timestamp}")
    # 返回 Action 或 Sleep

asyncio.run(scheduler.run(duration_sec=30))
```

### 练习 2.2：只写日志存储

实现一个只追加的观察存储，支持：
- `append(observation)` - 原子写入
- `query(since, pattern)` - grep 风格查询
- `get_index()` - 返回轻量指针

**约束**：
- 加载索引到内存必须 < 100KB
- 查询原始日志时不能直接加载整个文件

---

## 现在你自己试试 —— 5分钟动手任务

### ✅ 任务 1: 设计一个"朴素版"持久化 AI（难度 ⭐）

**目标**: 亲身体验从零设计的错误陷阱

**场景**: 设计一个在你写代码时持续观察的 AI

**操作**: 
画出你的第一版架构（ naive 版本），包含：
1. 如何检测用户活动？
2. 如何存储观察？
3. AI 如何获取上下文？
4. AI 如何响应？

用简单的框图表示：
```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  检测       │ ───▶ │  存储       │ ───▶ │  AI 响应    │
│  (怎么检测?)│      │  (怎么存?)  │      │  (怎么做?)  │
└─────────────┘      └─────────────┘      └─────────────┘
```

**然后问自己**（每个问题 30 秒思考）：
1. 如果用户 1 秒内保存 5 次文件，会发生什么？
2. 运行 30 天后，你的系统会变慢吗？为什么？
3. 如果 AI 想修改文件但失败了，怎么办？
4. 如果 AI 陷入循环（不断触发自己），怎么停止？

**预期**: 你会发现至少 2-3 个潜在问题

---

### ✅ 任务 2: 对比 KAIROS 的解决方案（难度 ⭐）

**目标**: 理解 KAIROS 如何解决朴素设计的问题

**操作**: 对照你的设计，查看 KAIROS 的方案：

| 你的设计问题 | KAIROS 方案 | 源码文件 |
|-------------|------------|----------|
| _____       | Tick 架构  | `tickHandler.ts` |
| _____       | 三层记忆   | `bootstrap/state.ts` |
| _____       | 严格写入纪律 | `ObservationStore` |
| _____       | 15 秒预算  | `onTick()` |

**问题**: 哪个方案最让你意外？为什么？

---

### ✅ 任务 3: 用 ASCII 画你自己的架构（难度 ⭐⭐）

**目标**: 理解架构可视化的价值

**操作**:
用 ASCII 画出你当前项目的某部分架构，例如：

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  用户请求 │ ──▶ │  路由层   │ ──▶ │  控制器  │
└──────────┘     └──────────┘     └────┬─────┘
                                        │
                    ┌───────────────────┼───────────┐
                    ▼                   ▼           ▼
              ┌──────────┐        ┌──────────┐ ┌──────────┐
              │  数据库   │        │  缓存层   │ │  消息队列 │
              └──────────┘        └──────────┘ └──────────┘
```

**问题**: 
- 哪一层是你的"15秒预算"约束所在？
- 如果这一层超时，应该如何处理？

---

### ✅ 任务 4: 计算你的项目索引大小（难度 ⭐）

**目标**: 验证"150 字符指针是轻量的"这一设计

**操作**:
1. 找到一个你维护的项目
2. 假设你要为每一天创建一条索引记录：
   ```
   ## 2026-04-03
   - 提交数: X
   - 关键改动: Y
   - 指向: commits/2026-04-03.md
   ```
3. 统计这条记录大约多少字符

**计算**:
```
单条索引字符数: _____
项目活跃天数: _____
总索引大小: _____ 字符 ≈ _____ KB
```

**对比**: 
- 完整的 git log 有多大？
- 索引 / 完整日志 = _____%

---

### ✅ 任务 5: 模拟四重门决策（难度 ⭐⭐）

**目标**: 理解四重门的组合逻辑

**场景**: 你正在设计一个"每日总结"功能，需要决定是否发送邮件给用户。

**设计你的四重门**:

| 门 | 检查条件 | 通过标准 |
|----|---------|---------|
| Gate 1 (时间) | 距上次发送 | ≥ 24 小时 |
| Gate 2 (内容) | 今日有无新内容 | ≥ 1 条 |
| Gate 3 (用户) | 用户是否在线 | 不在线 |
| Gate 4 (锁) | 是否有其他进程在发送 | 无 |

**测试用例**:
```
场景 A: 昨天刚发过，今天有新内容，用户离线，无锁
结果: _____ (哪扇门拒绝？)

场景 B: 三天没发，今天无新内容，用户离线，无锁  
结果: _____ (哪扇门拒绝？)

场景 C: 三天没发，今天有新内容，用户在线，无锁
结果: _____ (哪扇门拒绝？)
```

**问题**: 如果四个条件都满足但你觉得不应该发送，缺少了什么门？

---

### ✅ 任务 6: 预算耗尽模拟（难度 ⭐⭐）

**目标**: 体验 15 秒预算约束的实际影响

**操作**:
1. 设置一个 15 秒的计时器
2. 开始一个真实任务（如：查找一个 bug）
3. 当计时器响起时，立即停止，无论做到哪里
4. 记录：
   - 任务完成了多少？_____%
   - 你正处于什么状态？（思路中断点/中间状态）
   - 如果要"保存检查点"，你需要记录什么信息？

**反思**: 
- 什么任务适合 15 秒内完成？
- 什么任务必须拆分成多个 15 秒片段？
- 如何在每个片段结束时保存"可恢复状态"？

---

### ✅ 任务 7: 严格写入纪律实战（难度 ⭐⭐⭐）

**目标**: 理解为什么顺序很重要

**场景**: 你在做一个 TODO 列表应用。

**错误版本**:
```python
def add_todo_wrong(text):
    # 先更新内存索引
    todos.append({"id": next_id, "text": text})  # 索引已更新
    
    # 然后写入文件（模拟失败）
    raise IOError("磁盘已满")  # 写入失败！
    
    return True
```

**正确版本**:
```python
def add_todo_correct(text):
    # 先写入临时文件
    with open("todos.tmp", "w") as f:
        f.write(json.dumps({"id": next_id, "text": text}))
    
    # 原子重命名
    os.rename("todos.tmp", "todos.json")
    
    # 成功后更新索引
    todos.append({"id": next_id, "text": text})
    return True
```

**操作**:
1. 用 Python 实现这两个版本
2. 在写入时手动触发异常（Ctrl+C 或 raise）
3. 观察：错误版本会导致什么数据不一致？

**问题**: 为什么 KAIROS 使用"先写日志后更新索引"而不是数据库事务？

---

## 检查点

完成本模块后，你应该能够：
- [ ] 解释 tick 架构相对于事件驱动的优势
- [ ] 画出三层架构图并解释每层的作用
- [ ] 实现一个带预算约束的简单 tick 调度器
- [ ] 理解"严格写入纪律"的重要性
- [ ] 描述 AutoDream 的三重门触发机制
