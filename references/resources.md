# KAIROS 参考资源

> 基于 `/workspace/repos/claude-code-source/` 实际源码分析

**分析时间**: 2026-04-02

---

## 源码文件定位

### 核心入口与状态

| 功能 | 文件路径 | 行号范围 | 说明 |
|------|----------|----------|------|
| KAIROS 激活流程 | `main.tsx` | 80-81, 1050-1100 | 条件模块加载、五层门控 |
| 全局状态 | `bootstrap/state.ts` | 72, 301, 1085-1090 | kairosActive 状态管理 |
| Brief 工具授权 | `tools/BriefTool/BriefTool.ts` | 120-180 | isBriefEnabled/isBriefEntitled |

### AutoDream（记忆整合）

| 功能 | 文件路径 | 关键内容 |
|------|----------|----------|
| 主逻辑 | `services/autoDream/autoDream.ts` | 四重门触发、forked agent |
| 文件锁 | `services/autoDream/consolidationLock.ts` | mtime-based 锁、回滚机制 |
| 提示词 | `services/autoDream/consolidationPrompt.ts` | 4阶段整合流程 |
| 配置 | `services/autoDream/config.ts` | isAutoDreamEnabled 开关 |

### Assistant 模块

| 功能 | 文件路径 | 关键内容 |
|------|----------|----------|
| 历史记录 | `assistant/sessionHistory.ts` | 游标分页 (anchor_to_latest, before_id) |
| 初始化 | `assistant/index.js` | initializeAssistantTeam |
| GrowthBook 门 | `assistant/gate.js` | isKairosEnabled 检查 |

### Coordinator Mode

| 功能 | 文件路径 | 关键内容 |
|------|----------|----------|
| 协调器模式 | `coordinator/coordinatorMode.ts` | isCoordinatorMode, 工人工具集 |
| 系统提示词 | 同上 | 协调器角色定义 |

### Dream Task（UI）

| 功能 | 文件路径 | 关键内容 |
|------|----------|----------|
| 任务状态 | `tasks/DreamTask/DreamTask.ts` | DreamTaskState, 状态机 |
| 进度追踪 | 同上 | onMessage 回调、工具折叠 |

---

## Feature Flags

### 编译时标志（Bun feature()）

```typescript
feature('KAIROS')           // 主功能开关 - main.tsx 中 ~30 处引用
feature('KAIROS_BRIEF')     // Brief 工具独立开关
feature('KAIROS_CHANNELS')  // 多通道支持
feature('COORDINATOR_MODE') // 协调器模式
feature('PROACTIVE')        // 主动模式（与 KAIROS 共享部分代码）
```

### GrowthBook 远程开关

| 开关名称 | 功能 | 文件位置 |
|----------|------|----------|
| `tengu_kairos` | KAIROS 主开关 | `assistant/gate.js` |
| `tengu_kairos_brief` | Brief 工具开关 | `BriefTool.ts` |
| `tengu_onyx_plover` | AutoDream 配置（minHours, minSessions） | `autoDream.ts` |
| `tengu_scratch` | Scratchpad 功能 | `coordinatorMode.ts` |

---

## 关键设计参数

### AutoDream 触发条件

```typescript
const DEFAULTS = {
  minHours: 24,           // 时间门：距上次 24 小时
  minSessions: 5,         // 会话门：至少 5 个新会话
};

const SESSION_SCAN_INTERVAL_MS = 10 * 60 * 1000;  // 扫描节流：10 分钟
const HOLDER_STALE_MS = 60 * 60 * 1000;          // 锁过期：1 小时
```

### 分页参数

```typescript
const HISTORY_PAGE_SIZE = 100;  // 历史记录每页条数
```

### 缓存刷新

```typescript
const KAIROS_BRIEF_REFRESH_MS = 5 * 60 * 1000;  // 5 分钟
```

---

## 环境变量

| 变量 | 用途 | 位置 |
|------|------|------|
| `CLAUDE_CODE_BRIEF` | 强制启用 Brief（开发测试） | `BriefTool.ts` |
| `CLAUDE_CODE_COORDINATOR_MODE` | 启用协调器模式 | `coordinatorMode.ts` |
| `CLAUDE_CODE_ASSISTANT` | 助手模式 | `main.tsx` |

---

## 未发布功能

### 已知功能标志（未完全实现或已禁用）

| 功能 | 代号 | 状态 |
|------|------|------|
| BUDDY | - | 代码中提及，未找到完整实现 |
| ULTRAPLAN | - | 推测：30 分钟自主推理 |
| Undercover Mode | `isUndercover()` | 存在但功能有限 |

### 预留接口

```typescript
// main.tsx ~2518 行
assistantActivationPath: feature('KAIROS') && kairosEnabled 
  ? assistantModule?.getAssistantActivationPath() 
  : undefined
```

---

## 学术参考

1. **Mark Weiser** - "The Computer for the 21st Century" (1991)
   - URL: https://www.ics.uci.edu/~corps/phaseii/Weiser-Computer21stCentury-SciAm.pdf

2. **Daniel Kahneman** - "Thinking, Fast and Slow" (2011)

3. **Herbert Simon** - "The Sciences of the Artificial" (1969)

---

## 技术参考

1. **Bun** - https://bun.sh/
2. **Ink** - https://github.com/vadimdemedes/ink
3. **systemd** - https://systemd.io/

---

## 相关新闻

1. **VentureBeat** - "Claude Code's source code appears to have leaked" (2026-04-01)
   - URL: https://venturebeat.com/technology/claude-codes-source-code-appears-to-have-leaked

2. **Claude Mythos** - "KAIROS: The Hidden Daemon Mode Inside Claude Code"
   - URL: https://claudemythosai.io/blog/claude-code-kairos-daemon-mode/

---

*最后更新：2026-04-02*
*基于实际源码路径：/workspace/repos/claude-code-source/*
