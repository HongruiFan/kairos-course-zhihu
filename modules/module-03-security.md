# 模块三：权限架构

> "Trust is not a binary. It's a gradient with multiple checkpoints." — 安全设计哲学

**时长**：3 小时  
**形式**：安全分析 + 威胁建模  
**前置要求**：完成模块二

---

## 3.1 信任边界问题

### 核心矛盾

KAIROS 在你不看的时候也有 WRITE 权限。这听起来很可怕。Anthropic 如何让它变得安全？

```
用户关闭终端
        ↓
Claude 仍在运行 ← 这安全吗？
        ↓
它可以修改你的代码 ← 在什么条件下？
```

### 五层激活门

```
┌─────────────────────────────────────────────────────────────┐
│                    KAIROS 激活流程                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: 编译时开关                                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  feature('KAIROS') === true                         │   │
│  │  公开 npm 包: ❌ dead-code eliminated               │   │
│  │  内部构建: ✅ 包含 KAIROS 代码                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓ 通过                             │
│  Layer 2: 本地设置                                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  .claude/settings.json                              │   │
│  │  { "assistant": true }                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓ 通过                             │
│  Layer 3: 目录信任                                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  检查: 当前目录是否被用户显式信任？                  │   │
│  │  目的: 防止恶意仓库劫持 KAIROS                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓ 通过                             │
│  Layer 4: 远程开关                                           │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  GrowthBook: tengu_kairos === true                  │   │
│  │  目的: Anthropic 可以全局关闭 KAIROS                │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓ 通过                             │
│  Layer 5: 运行时激活                                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  setKairosActive(true)                              │   │
│  │  存储在: src/bootstrap/state.ts                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ✅ KAIROS 激活！                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 每层的作用（基于实际代码）

| 层级 | 控制者 | 代码位置 | 目的 |
|------|--------|----------|------|
| 1. 编译时 | Anthropic (构建系统) | `feature('KAIROS')` | Bun DCE 完全移除代码 |
| 2. CLI 参数 | 用户 | `main.tsx:1050` `--assistant` | Agent SDK daemon 模式，跳过远程检查 |
| 3. 本地设置 | 用户 | `.claude/settings.json` `assistant: true` | 显式启用意图 |
| 4. 目录信任 | 用户 + Claude | `checkHasTrustDialogAccepted()` | 防止恶意仓库劫持 |
| 5. 远程开关 | Anthropic | GrowthBook `tengu_kairos` | 全局紧急关闭 |
| 6. 运行时 | Claude | `setKairosActive(true)` | 全局状态激活 |

**关键代码路径** (`main.tsx:1050-1100`):
```typescript
// 条件加载模块
const assistantModule = feature('KAIROS') 
  ? require('./assistant/index.js') 
  : null;
const kairosGate = feature('KAIROS') 
  ? require('./assistant/gate.js') 
  : null;

// 激活流程
if (feature('KAIROS') && assistantModule?.isAssistantMode()) {
  // 检查目录信任（关键！）
  if (!checkHasTrustDialogAccepted()) {
    console.warn('Assistant mode disabled: directory is not trusted');
  } else {
    // CLI --assistant 跳过远程检查
    kairosEnabled = assistantModule.isAssistantForced() 
      || await kairosGate.isKairosEnabled();
    
    if (kairosEnabled) {
      opts.brief = true;           // 强制启用 Brief 模式
      setKairosActive(true);       // 设置全局状态
      assistantTeamContext = await assistantModule.initializeAssistantTeam();
    }
  }
}
```

**为什么目录信任是关键防线**：
- `.claude/settings.json` 是攻击者可控制的（恶意仓库可能包含 `assistant: true`）
- 但信任对话框是用户显式确认的
- 即使前 2 层通过（编译时 + CLI），第 4 层仍然可以阻断

**远程开关的绕过**：
- `--assistant` CLI 参数会设置 `isAssistantForced() = true`
- 这会跳过 `tengu_kairos` GrowthBook 检查
- 但仍然需要目录信任（第 4 层）

---

### 🔬 GrowthBook 远程开关实战演练

**文件**: `code/mock_growthbook_server.py` + `code/mock_growthbook_client.py`

这是安全关键设计的实战体验。你将亲手控制远程开关，观察 KAIROS 如何优雅降级。

#### 什么是 GrowthBook？

GrowthBook 是 Anthropic 使用的**远程特性开关系统**（Feature Flag）。它允许在不发布新版本的情况下：
- 动态开启/关闭功能
- 渐进发布（先给 1% 用户）
- 紧急情况一键关闭

#### 实战演练步骤

**Step 1: 启动 Mock GrowthBook 服务器**

```bash
# 终端 1
python code/mock_growthbook_server.py
```

你会看到：
```
╔══════════════════════════════════════════════════════════════════╗
║           Mock GrowthBook Server                                 ║
╚══════════════════════════════════════════════════════════════════╝

🚀 服务器启动于 http://localhost:8765

📋 可用开关:
   • tengu_kairos       - KAIROS 主开关
   • tengu_kairos_brief - Brief 工具权限
   • tengu_onyx_plover  - AutoDream 配置
   • tengu_scratch      - Scratchpad 功能

⌨️  交互命令:
   toggle <feature>     - 切换指定开关
   kill                 - 紧急关闭所有功能
   status               - 查看当前状态
```

**Step 2: 启动 KAIROS 客户端**

```bash
# 终端 2
python code/mock_growthbook_client.py
```

**Step 3: 实验场景**

在服务器终端尝试以下操作，观察客户端行为：

**场景 A: 正常全功能运行**
```
[gb] > status
```
客户端应显示：
```
🚀 [FULL OPERATIONAL]
   • ✅ 所有功能正常运行
   • ✅ Brief 工具: 可用
   • ✅ AutoDream: 可用
```

**场景 B: 关闭 Brief 工具**
```
[gb] > toggle tengu_kairos_brief
🟢 ON → 🔴 OFF
```

客户端降级：
```
⚡ [DEGRADED MODE]
   • ❌ Brief 工具: 禁用
   • ✅ AutoDream: 可用
   • ✅ Scratchpad: 可用
```

**场景 C: 关闭 KAIROS 主开关（紧急停止）**
```
[gb] > toggle tengu_kairos
```

客户端紧急停止：
```
🛑 [EMERGENCY STOP]
   • ❌ 禁用所有主动行为
   • ❌ 禁用 Brief 工具
   • ❌ 禁用 AutoDream
   • 观察继续记录（本地）
   • 等待 tengu_kairos 重新开启...
```

**场景 D: 紧急关闭所有功能**
```
[gb] > kill
🚨 紧急关闭所有功能!
```

**关键观察点**

| 场景 | 客户端状态 | 为什么这样设计 |
|------|-----------|---------------|
| 主开关关闭 | Emergency Stop | 安全第一，立即停止所有主动行为 |
| 部分开关关闭 | Degraded | 核心功能保留，非关键功能关闭 |
| 无法连接服务器 | Offline | 使用安全默认（全部关闭） |
| 恢复连接 | 重新评估 | 自动恢复功能，无需重启 |

**优雅降级的关键机制**

```python
# 1. 缓存 + 定期刷新
CACHE_TTL = 60  # 60秒刷新一次

# 2. 失败回退（Fail-safe）
if cannot_connect_to_growthbook:
    use_fallback_defaults()  # 全部关闭

# 3. 运行时检查
on_every_tick():
    if not is_enabled("tengu_kairos"):
        disable_all_active_behavior()
    else:
        continue_normal_operation()
```

**为什么这是安全关键设计？**

```
情景: 发现 KAIROS 有严重安全漏洞

传统方式:
  1. 修复代码
  2. 构建新版本
  3. 发布到 npm
  4. 用户升级
  （耗时数小时到数天）

GrowthBook 方式:
  1. 登录 GrowthBook 控制台
  2. 点击: tengu_kairos → OFF
  3. 所有在线实例 60 秒内停止
  （耗时 30 秒）
```

---

## 3.2 KAIROS 下的工具门控

### 完整工具矩阵

| 工具 | 标准模式 | KAIROS 模式 | 原理 |
|------|----------|-------------|------|
| **ReadFile** | ✅ | ✅ | 只读，安全 |
| **Grep** | ✅ | ✅ | 只读，安全 |
| **ListDir** | ✅ | ✅ | 只读，安全 |
| **Bash (读)** | ✅ | ✅ | cat, grep, ls, head, tail |
| **Bash (写)** | ✅ | ❌ | rm, mv, cp, echo, > 风险太高 |
| **EditFile** | ✅ | ⚠️ | 受 15s 预算限制，受信任目录 |
| **WriteFile** | ✅ | ⚠️ | 受 15s 预算限制，受信任目录 |
| **SleepTool** | N/A | ✅ | KAIROS 专用：主动睡眠 |
| **SendUserFile** | N/A | ✅ | KAIROS 专用：异步通知 |
| **PushNotification** | N/A | ✅ | KAIROS 专用：推送 |
| **SubscribePR** | N/A | ✅ | KAIROS 专用：订阅 |

### 15 秒预算的安全含义

```typescript
// 即使允许 EditFile，也有硬性约束
async function boundedEdit(file: string, changes: Change[]) {
  const start = Date.now();
  const budget = 15000; // 15 秒
  
  for (const change of changes) {
    if (Date.now() - start > budget) {
      // 时间到！保存检查点，推迟剩余操作
      await saveCheckpoint({
        remainingChanges: changes.slice(changes.indexOf(change)),
        reason: 'budget_exhausted'
      });
      return { status: 'deferred', completed: changes.indexOf(change) };
    }
    
    await applyChange(change);
  }
  
  return { status: 'completed' };
}
```

**为什么这很重要**：
- 即使用户不在，KAIROS 也不能"卡住"在长时间操作上
- 用户回来后会看到检查点，可以选择继续或取消

---

### BriefTool（SendUserMessage）授权检查

**文件**: `tools/BriefTool/BriefTool.ts`

**两级授权模型**：

```typescript
// Level 1: 资格检查（Entitlement）
// 决定用户是否"被允许"使用 Brief
export function isBriefEntitled(): boolean {
  return feature('KAIROS') || feature('KAIROS_BRIEF')
    ? getKairosActive()  // KAIROS 模式自动获得资格
      || isEnvTruthy(process.env.CLAUDE_CODE_BRIEF)  // 环境变量覆盖
      || getFeatureValue_CACHED_WITH_REFRESH(
           'tengu_kairos_brief', 
           false, 
           5 * 60 * 1000  // 5分钟缓存刷新
         )
    : false;
}

// Level 2: 激活检查（Activation）
// 决定工具在当前会话是否"实际启用"
export function isBriefEnabled(): boolean {
  return feature('KAIROS') || feature('KAIROS_BRIEF')
    ? (getKairosActive() || getUserMsgOptIn()) && isBriefEntitled()
    : false;
}
```

**激活方式**（设置 `userMsgOptIn`）：
1. `--brief` CLI 标志
2. `defaultView: 'chat'` in settings
3. `/brief` slash 命令
4. `/config` defaultView 选择器
5. `--tools` / SDK `tools` 选项中的 SendUserMessage
6. `CLAUDE_CODE_BRIEF` 环境变量（开发测试）

**KAIROS 模式的特殊处理**：
```typescript
// KAIROS 模式下，Brief 自动激活（无需用户显式 opt-in）
// 因为系统提示词硬编码了 "you MUST use SendUserMessage"
if (kairosEnabled) {
  opts.brief = true;  // 强制启用
}
```

---

## 3.3 "Undercover Mode" 的讽刺

### 什么是 Undercover Mode？

泄露源码揭示了一个名为 `Undercover Mode` 的功能：

```typescript
// 当 Anthropic 员工在公开仓库工作时自动激活
const UNDERCOVER_PROMPT = `
You are in Undercover Mode. Do not mention:
- Internal model names ("Capybara", "Fennec")
- Internal project codenames
- Internal Slack channels
- Anything that identifies this as AI-generated content from Anthropic
`;
```

### 功能目的

防止 Claude Code 在公开 commit 中泄露内部信息：
- 不要在 commit message 中提及 "Capybara"（Claude 变体内部代号）
- 不要引用内部 Slack 讨论
- 不要暴露内部系统架构

### 讽刺之处

```
一个为防止信息泄露而设计的系统...
...因为构建者忘记从 npm 包中移除 .map 文件而被泄露
```

### 更大的问题

**California AI 水印法案**（2026 年 3 月 30 日签署）：
- 要求所有 AI 生成内容必须可追踪标记
- Undercover Mode 的设计目的是**移除**这些标记
- Anthropic（总部位于旧金山）需要向监管机构解释这一点

---

## 威胁建模练习

### 场景 1：恶意仓库攻击

**攻击者**：创建一个看似无害的开源项目，实际包含 `.claude/settings.json` 启用 KAIROS。

**防御**：
- Layer 3（目录信任）：用户必须显式信任该目录
- 即使信任，Layer 4（远程开关）仍可全局关闭

### 场景 2：权限提升

**攻击者**：利用 KAIROS 的 WRITE 权限修改系统文件。

**防御**：
- 工具门控：Bash 写入被禁用
- 目录限制：只能修改受信任的项目文件
- 15 秒预算：无法执行大规模修改而不被发现

### 场景 3：数据泄露

**攻击者**：KAIROS 将观察日志发送到外部服务器。

**防御**：
- 网络工具在 KAIROS 中被限制
- SendUserFile 只能向用户发送（不是任意服务器）
- 观察日志存储在本地

---

## 安全设计原则总结

```
┌─────────────────────────────────────────────────────────────┐
│              KAIROS 安全设计的核心原则                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 纵深防御 (Defense in Depth)                             │
│     → 五层激活门，没有单点故障                              │
│                                                             │
│  2. 最小权限 (Least Privilege)                              │
│     → KAIROS 只能做标准模式的一小部分                       │
│                                                             │
│  3. 显式同意 (Explicit Consent)                             │
│     → 用户必须在多个层面选择启用                            │
│                                                             │
│  4. 可逆性 (Reversibility)                                  │
│     → 任何操作都可以被检查、回滚                            │
│                                                             │
│  5. 透明性 (Transparency)                                   │
│     → 用户能看到 KAIROS 做了什么（观察日志）                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 讨论问题

1. 五层激活门中，你认为哪一层最重要？为什么？

2. 如果 KAIROS 是你的产品，你会添加什么安全措施？

3. Undercover Mode 的存在是合理的安全措施，还是逃避责任的工具？

4. 如何平衡"自主 AI 的有用性"与"用户控制和隐私"？

---

## 现在你自己试试 —— 5分钟动手任务

### ✅ 任务 1: 画出你的信任边界（难度 ⭐）

**目标**: 理解"目录信任"的安全模型

**操作**:
列出你电脑上的项目目录，按信任程度分类：

```
┌─────────────────────────────────────────────────────────┐
│ 高信任（我的代码）                                        │
│ ~/projects/my-company/    ~/personal/                   │
├─────────────────────────────────────────────────────────┤
│ 中信任（开源项目我贡献过）                                │
│ ~/opensource/react/       ~/opensource/rust/           │
├─────────────────────────────────────────────────────────┤
│ 低信任（刚 clone 的陌生项目）                             │
│ ~/tmp/some-random-repo/                                 │
├─────────────────────────────────────────────────────────┤
│ 不信任（下载的压缩包）                                    │
│ ~/Downloads/unknown-source.zip                          │
└─────────────────────────────────────────────────────────┘
```

**问题**:
- 你会在哪个层级启用 KAIROS？
- 如果一个低信任项目试图修改你的 `.bashrc`，应该被哪层门阻止？

---

### ✅ 任务 2: 设计你的五层门（难度 ⭐⭐）

**目标**: 理解"纵深防御"的设计哲学

**场景**: 你正在设计一个"自动备份照片"的功能。

**任务**: 为这个功能设计五层激活门：

| 层级 | 门名称 | 检查条件 | 失败时的行为 |
|------|--------|---------|-------------|
| 1 | _____ | _____ | _____ |
| 2 | _____ | _____ | _____ |
| 3 | _____ | _____ | _____ |
| 4 | _____ | _____ | _____ |
| 5 | _____ | _____ | _____ |

**示例**（KAIROS 参考）：
```
Layer 1: 编译时开关 (feature flag)
Layer 2: CLI 参数 (--assistant)
Layer 3: 本地配置 (.claude/settings.json)
Layer 4: 目录信任 (trust dialog)
Layer 5: 远程开关 (GrowthBook)
```

**问题**: 
- 为什么需要五层而不是一层？
- 哪一层是"最后一道防线"？

---

### ✅ 任务 3: 模拟权限最小化（难度 ⭐⭐）

**目标**: 体验"最小权限原则"

**场景**: 你在咖啡馆，电脑暂时离开视线 30 秒。

**操作**: 列出你当前打开的应用，按"如果此时被恶意使用"的风险排序：

```
应用              风险等级    原因                    理想权限限制
─────────────────────────────────────────────────────────────────
浏览器            高         已登录多个网站           需要密码才能支付
VS Code           中         可修改代码               不能推送到生产分支
终端              高         可执行任意命令           不能执行 rm -rf /
邮件客户端        中         可发送邮件               不能访问通讯录导出
```

**问题**: 
- 哪些应用应该有"KAIROS 模式"（受限权限）？
- 如何在"方便"和"安全"之间取得平衡？

---

### ✅ 任务 4: 分析一个真实泄露事件（难度 ⭐⭐⭐）

**目标**: 理解供应链攻击的风险

**操作**: 阅读以下简化场景：

> 2024 年，某开源库 `colors.js` 的维护者在 npm 发布了一个无限循环版本，导致全球数千个项目 CI 挂掉。

**分析**:
```
攻击向量: 恶意代码提交 → npm 发布 → 用户安装 → CI 执行

防御层分析:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer 1 (源码审查): ❌ 维护者自己提交的恶意代码
Layer 2 (发布审查): ❌ npm 不审查代码内容
Layer 3 (安装审查): ❌ 大多数人直接 npm install
Layer 4 (运行时审查): ⚠️ CI 挂掉才发现问题
Layer 5 (影响限制): ✅ 只是 CI 挂掉，没有数据泄露
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**问题**: 
- 如果这是一个"KAIROS 级别的自主系统"，后果会更严重吗？
- 应该添加什么层来防止类似事件？

---

### ✅ 任务 5: Undercover Mode 伦理辩论（难度 ⭐⭐⭐）

**目标**: 思考 AI 透明性的伦理边界

**场景 A**: Claude Code 使用 Undercover Mode 避免在公开 commit 中提及内部代号。

**场景 B**: 某营销 AI 使用类似模式隐藏"这是 AI 生成内容"的标记。

**操作**: 完成下表对比：

| 维度 | 场景 A (Claude Code) | 场景 B (营销 AI) |
|------|---------------------|-----------------|
| 隐藏什么 | 内部开发代号 | AI 生成标记 |
| 目的是 | 防止信息泄露 | 让用户以为是真人写的 |
| 伤害谁 | 可能误导贡献者 | 欺骗消费者 |
| 可接受吗？ | _____ | _____ |

**辩论立场**:
- 正方：Undercover Mode 是合理的安全实践
- 反方：任何隐藏 AI 身份的机制都是不道德的

**你的立场**: _____

---

## 检查点

完成本模块后，你应该能够：
- [ ] 列出并解释五层激活门
- [ ] 对比标准模式和 KAIROS 模式下的工具可用性
- [ ] 分析一个威胁场景并提出防御方案
- [ ] 讨论 Undercover Mode 的伦理问题
