# kairos-course-zhihu
知乎专栏《KAIROS：AI 助手的心跳与记忆》(https://www.zhihu.com/column/c_2023460451049063586) 的配套代码

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

> 知乎专栏《KAIROS：AI 助手的心跳与记忆》配套代码仓库
> 
> 基于 Anthropic Claude Code 泄露源码的架构分析

---

## 📚 专栏目录

| 篇数 | 标题 | 代码 | 状态 |
|------|------|------|------|
| 1 | 为什么 AI 助手总是"失忆"？ | - | 📝 已发布 |
| 2 | 从泄露源码看 KAIROS 架构 | - | ⏳ 待发布 |
| 3 | Chronos vs Kairos - 两种时间哲学 | - | ⏳ 待发布 |
| 4 | 上下文熵增 - 如何量化 AI 的"记忆力" | `context_entropy_analyzer.py` | ⏳ 待发布 |
| ... | ... | ... | ... |

👉 [知乎专栏主页](https://www.zhihu.com/column/xxx)（关注获取更新）

---

## 🚀 快速开始

### 环境要求
- Python 3.8+
- 无其他依赖（纯标准库实现）

### 运行示例

```bash
# 1. 克隆仓库
git clone https://github.com/HongruiFan/kairos-course-zhihu.git
cd kairos-course-zhihu

# 2. 运行熵分析工具（第4篇配套）
python code/context_entropy_analyzer.py

# 3. 运行渐进式 micro-kairos（第13-14篇配套）
python code/micro_kairos_v1.py  # 基础版
python code/micro_kairos_v2.py  # 存储版
python code/micro_kairos_v3.py  # 完整版

# 4. 体验远程开关演练（第10篇配套）
# 终端1
python code/mock_growthbook_server.py

# 终端2
python code/mock_growthbook_client.py
```

---

## 📁 代码结构

```
code/
├── micro_kairos.py                   # 完整参考实现 (~400行)
├── micro_kairos_v1.py                # 渐进式 v1：Tick 调度器
├── micro_kairos_v2.py                # 渐进式 v2：观察存储
├── micro_kairos_v3.py                # 渐进式 v3：记忆整合
├── micro_kairos_benchmark.py         # 性能基准测试
├── micro_kairos_failure_cases.py     # 失败案例分析
├── storage_comparison_benchmark.py   # 存储方案对比
├── debug_micro_kairos.py             # 故障排查工具
├── mock_growthbook_server.py         # GrowthBook 模拟服务器
├── mock_growthbook_client.py         # KAIROS 客户端模拟
└── context_entropy_analyzer.py       # 上下文熵分析工具
```

---

## 🎯 核心概念速查

### 1. Tick 架构
```python
# 不是事件驱动，而是心跳驱动
while True:
    context = gather_context()
    action = decide_action(context)  # 15秒预算内
    if action:
        execute(action)
    sleep_until_next_tick()
```

### 2. 严格写入纪律
```python
# 正确顺序：先写数据，再更新索引
def append_observation(obs):
    # 1. 写入日志（持久化）
    log_file.write(json.dumps(obs) + '\n')
    log_file.flush()  # 强制刷盘
    
    # 2. 更新索引（内存）
    index.append(obs.id)
    
    # 3. 保存索引（持久化）
    save_index()

# 错误顺序会导致：系统崩溃后索引指向不存在的数据
```

### 3. 四重门触发
```python
def should_run_autodream():
    # Gate 1: 时间门（距上次 ≥24小时）
    if now - last_run < 24*3600: return False
    
    # Gate 2: 扫描节流门（距上次扫描 ≥10分钟）
    if now - last_scan < 10*60: return False
    
    # Gate 3: 会话门（≥5个新会话）
    if new_sessions < 5: return False
    
    # Gate 4: 文件锁门（无其他进程运行）
    if not acquire_lock(): return False
    
    return True
```

---

## 📊 运行结果示例

### 熵分析工具输出
```
📊 分析结果汇总
--------------------------------------------------
最终相关性 (越高越好)
  滑动窗口        │███████                       │ 0.235 ± 0.123
  全历史          │████████                      │ 0.297 ± 0.091
  KAIROS          │██████████████████████████    │ 0.687 ± 0.043 ⭐

📈 KAIROS vs 基线改进
  相关性保留: +63.2% (vs 滑动窗口)
  熵减少: -45.1% (vs 全历史)
```

### 存储性能对比
```
📦 存储方案性能对比
--------------------------------------------------
方案 A: 全量加载（1500条观察全部加载）
   平均查询: 8.71 ms
   内存占用: ~1500 条观察

方案 B: Grep 风格（只加载匹配项）
   平均查询: 0.08 ms
   内存占用: 仅 10 条匹配结果

性能提升: 110.9×
内存效率: 减少 99.3%
```

---

## 🛠️ 故障排查

遇到 micro-kairos 问题？运行诊断工具：

```bash
python code/debug_micro_kairos.py
```

常见问题：
| 问题 | 诊断 | 解决 |
|------|------|------|
| 观察没写入 | 检查目录权限 | `chmod 755 .micro-kairos/` |
| 整合不触发 | 检查四重门状态 | 修改测试阈值 |
| 锁竞争 | 检查 PID 存在性 | 删除过期锁文件 |
| 数据不一致 | 索引 vs 文件对比 | 重建索引 |

---

## 🤝 参与贡献

1. **Fork** 本仓库
2. 创建你的功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

欢迎提交：
- 代码优化
- Bug 修复
- 文档改进
- 翻译（英文版）

---

## 📖 扩展阅读

### 官方资源
- [Claude Code 官方文档](https://docs.anthropic.com/claude-code)
- [Anthropic 研究博客](https://www.anthropic.com/research)

### 论文
- Mark Weiser - "The Computer for the 21st Century" (普适计算)
- Claude Shannon - "A Mathematical Theory of Communication" (信息论)

### 系统架构
- systemd 服务管理
- Erlang/OTP 容错设计
- Unix 守护进程编程

---

## ⚠️ 免责声明

本课程基于 2026 年 4 月泄露的 Claude Code 源码进行教育分析，仅供学习研究使用：

1. 所有代码实现均为独立编写的教学示例，非原始源码
2. 不涉及任何商业机密或敏感信息
3. 不代表 Anthropic 官方立场
4. 请勿将分析内容用于商业目的

---

## 📬 联系作者

- 知乎：[@Zen](https://www.zhihu.com/people/xxx)
- GitHub Issues：欢迎提问和讨论
- 邮箱：xxx@example.com

---

## License

[MIT](LICENSE) © 2026 Zen

---

如果这个项目对你有帮助，请 ⭐ Star 支持！

也欢迎关注知乎专栏，第一时间获取更新：
👉 [《KAIROS：AI 助手的心跳与记忆》](https://www.zhihu.com/column/xxx)

