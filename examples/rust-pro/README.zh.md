# rust-pro —— 易读的规则型 python-pro 的 Rust 移植版

[English README see README.md](README.md)

GOSIM survey26 望远镜巡天赛题（`participant-agent-protocol-v4`）示例智能体 [`../python-pro`](../python-pro/README.zh.md)
的 Rust 移植版。策略、常数、运算顺序和平局处理都相同：先完成 `required` 目标、基础天球计算、保守的仪器故障报告规则，
以及一个可选的、读值班笔记的大模型环节，用几百行带注释的 Rust 写成。和 python-pro 一样，它是用来读懂和改进的起点，
不是有竞争力的参赛作品。运行时只用协议给智能体的信息（星表、公开评分配置、公报、预报、限时观测请求、自己的观测结果），
从不读取卡片文件。

移植改变的是速度：每次决策的 CPU 时间只是 Python 版的一小部分，平台的 CPU 预算留出了大量余量，扩展搜索时可以用上。

## 成绩（本地引擎，只用规则，`OBSERVER_MODEL_DISABLED=1`）

| 卡 | A | B | C | D | A1 | B1 | C1 | D1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| python-pro | 17,962 | 30,734 | 17,884 | 26,695 | 11,689 | 16,037 | 11,058 | 26,809 |
| **rust-pro** | 17,962 | 30,734 | 17,884 | 26,695 | 11,689 | 16,037 | 11,058 | 26,659 |

移植版和 python-pro 做出相同的决策：在本地 L1 卡上两者发出完全相同的 671 个决策，上表八张卡中七张的分数完全相同。
D1 上科学分也相同，故障报告和另一次本地 python-pro 运行（26,659）完全一致；表中 26,809 来自另一次报告时机不同的
python-pro 运行。平台公平时钟计入的 CPU 时间从每张卡 18-93 秒（python-pro）降到 1-4 秒。

## 目录结构（每个文件对应一个 python-pro 模块）

```
src/main.rs        agent.py        入口：协议主循环、等待、仪器故障规则（FaultWatch）、节奏控制
src/planner.rs     planner.py      贪心、required 优先的调度器；从命中结果学习完成因子和天空质量
src/skymath.rs     skymath.py      公开天球几何：恒星时、地平坐标、切平面投影、光纤网格、月亮
src/log_reader.rs  log_reader.py   可选的大模型环节：读限时观测请求里附带的值班自由文本
src/llm_client.rs  llm_client.py   OpenAI 兼容客户端（ureq）
observer.project.json   平台清单（cargo build --release --locked；./target/release/rust-pro）
pack_agent.py      打包上传用的 ZIP（不会打包 target/ 和 .env）
.env.example       复制成 .env，本地用大模型时填 API key
```

## 怎么做决策（src/planner.rs）

1. **候选目标。** 现在和十分钟后都在高度限制之上、还有价值的目标：
   `价值 = 50（未完成的 required 目标，即它能避免的罚分）+ 权重 ×（1 − 已有完成因子）+ 请求奖励`。
   优先级 = 价值 ×（现在的天空质量 / 它能得到的最好质量）× 紧迫度。中间一项用公开的大气质量和月光公式，
   所以接近中天、远离月亮的目标优先；剩下夜晚少的目标更紧迫。
2. **曝光时长。** 对优先级最高的几个目标（锚点）算出达到目标所需的曝光：required 目标是完成因子 0.5 × 1.3，
   其他目标是完成因子 0.9（最多 30 分钟）。今晚一次曝光达不到门槛的 required 目标等更好的天空。
3. **视场。** 让锚点落在中央光纤上；其余每根光纤分给同一次曝光中收益最大的邻近目标（太靠近光纤边缘的跳过）。
   哪个锚点的视场每秒收益最高就选哪个。搜索就这么多：没有细化，也没有前瞻。
4. **项目。** 根据分配目标的预测天空质量选 DARK / BRIGHT / BACKUP。

学习：命中得分 = 权重 × 完成因子 × 项目倍率。规划器为每个目标保留一个保守的完成因子（假设项目匹配），
并用未饱和命中的"观测 / 预测完成因子"估计天空质量；最近八次曝光的中位数用来缩放所有预测。

公报：全天下雨或风暴时站点关闭（等待）；地形遮挡或火箭发射挡住对应方向的低空；方向性天气降低该方向的权重。

## 仪器故障（src/main.rs 的 `FaultWatch`）

仪器故障会一直降低仪器效率，直到有人报告；天气和地震也会降低质量，但报告修不好它们。规则把每次曝光的质量
和上次修复以来的常见水平（无全天天气的曝光的 90 分位）比较，只在以下情况报告：

- 连续两次曝光低于常见水平的 10%（天气很少能解释的崩塌）；
- 最近两个观测夜（每夜至少四次无全天天气的曝光）的质量中位数都低于常见水平的 55%（天气每夜不同，故障会一直在）。

只有上次报告之后的曝光才算证据，同一次故障不会报两次。免费误报额度用完后，两次报告至少间隔 120 小时。

## 可选的大模型：值班笔记（src/log_reader.rs）

有些卡会在限时观测请求里附上较长的值班自由文本。有 API key 时，每条新笔记只发给模型一次，JSON 答案变成三条规则：
宣布的关闭 → 等待，坏方向 → 降权，宣布的仪器问题 → 报告。调用在后台线程里跑，不会卡住巡天；没有 key，
或平台以"本次不提供模型"（`OBSERVER_MODEL_DISABLED=1`）评测时，智能体只用规则运行。

```
OPENAI_API_KEY=sk-...                            # 可选（也接受 KIMI_API_KEY）
OPENAI_BASE_URL=https://api.kimi.com/coding/v1   # 默认；中国大陆以外用 https://api.kimi.ai/coding/v1
OPENAI_MODEL=k3                                  # 默认
```

平台上会自动注入 `OPENAI_BASE_URL` / `OPENAI_API_KEY`。

## 本地构建和运行

```bash
cargo build --release --locked
python3 ../_local/runner/run_local.py --inherit-env --card ../_local/cards/L1 --agent "./target/release/rust-pro" --agent-cwd .
python3 pack_agent.py --out ../rust-pro-agent.zip
```

平台在只读容器里构建，所以 `observer.project.json` 把 `CARGO_HOME` 指到 `/tmp`。

## 可以改进的方向

- **多搜索。** 每次决策多试一些指向（锚点放在不同光纤、剩余科学价值密集的区域、小幅平移）和曝光时长，
  给望远镜时间定价，而不是只看每秒收益。Rust 版为此留出了大量 CPU 预算。
- **规划整个观测季。** 暗弱的 required 目标需要最好的夜晚；决定哪些夜晚观测哪片天区，而不是只做贪心。
- **从命中结果读出项目档位。** 饱和命中会准确显示项目倍率，因此能判断申报的项目是否匹配。
- **更好的故障检测。** 单次曝光里天气和仪器故障很像；把质量和天空档位、不同方向、不同夜晚对比，并用好免费报告额度。
- **更多地使用大模型**，比如读预报，或判断疑似故障。

## 许可

任务卡、模拟数据、评测代码和示例项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 许可；
请引用 GOSIM 2026 Agentic Observer Hackathon（https://create.gosim.org/survey26/）。见 `../LICENSE.md`。
