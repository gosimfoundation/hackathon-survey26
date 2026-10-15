# typescript-pro —— participant-agent-protocol-v4 的规则型示例智能体

[English README see README.md](README.md)

[`../python-pro`](../python-pro) 的 TypeScript（Node.js 22+）移植版：GOSIM survey26 望远镜巡天赛题的同一个简短易读的示例智能体——先完成 `required` 目标、基础天球计算、保守的仪器故障报告规则，以及一个可选的、读值班笔记的大模型环节。策略和常数都与 python-pro 相同，每个模块对应一个 python-pro 模块。只依赖 `typescript` 和 `@types/node`，而且只在构建时用到。它是用来读懂和改进的起点，不是有竞争力的参赛作品。运行时只用协议给智能体的信息（星表、公开评分配置、公报、预报、限时观测请求、自己的观测结果），从不读取卡片文件。

## 成绩（本地引擎，只用规则，`OBSERVER_MODEL_DISABLED=1`）

| 卡 | A | B | C | D | A1 | B1 | C1 | D1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| typescript-pro | 17,962 | 30,734 | 17,884 | 26,695 | 11,689 | 16,037 | 11,058 | 26,659 |
| python-pro | 17,962 | 30,734 | 17,884 | 26,695 | 11,689 | 16,037 | 11,058 | 26,809 |

A–D 和 A1–C1 与 python-pro 得分相同（A 卡上 2,423 个动作完全一致）。D1 最长，是在负载很高的机器上跑的，节奏控制减少了锚点数。不同运行之间会有几个百分点的波动（机器速度影响 CPU 预算，从而影响尝试的锚点数，故障报告时机也会变）。

## 目录结构

```
src/agent.ts       agent.py        入口：协议主循环、等待、仪器故障规则（FaultWatch）、节奏控制
src/planner.ts     planner.py      贪心、required 优先的调度器；从命中结果学习完成因子和天空质量
src/skymath.ts     skymath.py      公开天球几何：恒星时、地平坐标、切平面投影、光纤网格、月亮
src/logReader.ts   log_reader.py   可选的大模型环节：读限时观测请求里附带的值班自由文本
src/llmClient.ts   llm_client.py   OpenAI 兼容客户端（内置 fetch，调用在后台进行）
src/packAgent.ts   pack_agent.py   打包上传用的 ZIP（不会打包 .env、node_modules 和 dist）
observer.project.json   平台清单：镜像 node:22-slim，构建 `npm ci --include=dev` + `npm run build`，运行 `node dist/agent.js`
.env.example      复制成 .env，本地用大模型时填 API key
```

## 怎么做决策（src/planner.ts）

1. **候选目标。** 现在和十分钟后都在高度限制之上、还有价值的目标：
   `价值 = 50（未完成的 required 目标，即它能避免的罚分）+ 权重 ×（1 − 已有完成因子）+ 请求奖励`。
   优先级 = 价值 ×（现在的天空质量 / 它能得到的最好质量）× 紧迫度。中间一项用公开的大气质量和月光公式，
   所以接近中天、远离月亮的目标优先；剩下夜晚少的目标更紧迫。
2. **曝光时长。** 对优先级最高的几个目标（锚点）算出达到目标所需的曝光：required 目标是完成因子 0.5 × 1.3，
   其他目标是完成因子 0.9（最多 30 分钟）。今晚一小时内达不到门槛的 required 目标等更好的天空。
3. **视场。** 让锚点落在中央光纤上；其余每根光纤分给同一次曝光中收益最大的邻近目标（太靠近光纤边缘的跳过）。
   哪个锚点的视场每秒收益最高就选哪个。搜索就这么多：没有细化，也没有前瞻。
4. **项目。** 根据分配目标的预测天空质量选 DARK / BRIGHT / BACKUP。

学习：命中得分 = 权重 × 完成因子 × 项目倍率。规划器为每个目标保留一个保守的完成因子（假设项目匹配），
并用未饱和命中的"观测 / 预测完成因子"估计天空质量；最近八次曝光的中位数用来缩放所有预测。

公报：全天下雨或风暴时站点关闭（等待）；地形遮挡或火箭发射挡住对应方向的低空；方向性天气降低该方向的权重。

节奏：平台按智能体回合内消耗的 CPU 时间计费。`agent.ts` 测量每次决策的 CPU 时间，预算紧张时减少锚点数（最多 6 个）。

## 仪器故障（src/agent.ts 的 `FaultWatch`）

仪器故障会一直降低仪器效率，直到有人报告；天气和地震也会降低质量，但报告修不好它们。规则把每次曝光的质量
和上次修复以来的常见水平（没有全天天气的曝光的 90 分位）比较，只在以下情况报告：

- 连续两次曝光低于常见水平的 10%（天气很少能解释的崩塌）；
- 最近两个观测夜（每夜至少四次无全天天气的曝光）的质量中位数都低于常见水平的 55%（天气每夜不同，故障会一直在）。

只有上次报告之后的曝光才算证据，所以同一次异常不会报告两次。免费误报额度用完后，最多每五天报告一次。

## 可选的大模型：值班笔记（src/logReader.ts）

有些卡会在限时观测请求里附上较长的值班自由文本。有 API key 时，每条新笔记只发给模型一次，JSON 答案变成三条规则：
宣布的关闭 → 等待，坏方向 → 降权，宣布的仪器问题 → 报告。调用在后台进行（事件循环上的 promise），不会卡住巡天；
没有 key，或平台以"本次不提供模型"（`OBSERVER_MODEL_DISABLED=1`）评测时，智能体只用规则运行。

```
OPENAI_API_KEY=sk-...                            # 可选（也接受 KIMI_API_KEY）
OPENAI_BASE_URL=https://api.kimi.com/coding/v1   # 默认；中国大陆以外用 https://api.kimi.ai/coding/v1
OPENAI_MODEL=k3                                  # 默认
```

平台上会自动注入 `OPENAI_BASE_URL` / `OPENAI_API_KEY`。

## 本地运行

```bash
npm ci && npm run build                          # tsc -> dist/
python3 ../_local/runner/run_local.py --inherit-env --card ../_local/cards/L1 --agent "node dist/agent.js" --agent-cwd .
npm run pack                                     # -> ../typescript-pro-agent.zip
```

## TypeScript 说明

- **与 Python 数值一致。** `src/skymath.ts` 复现了 Python 的浮点 `%`、`round()` 和 `sum()`（Python 3.12 起的补偿求和），
  排序的并列规则与 Python 的元组排序相同，迭代顺序有影响的容器用 `Map`（普通对象会把整数样的键排序）。所以两个智能体的决策相同。
- **用异步代替线程。** python-pro 在后台线程里读值班笔记；这里的调用是 promise，在智能体等待 stdin 下一行时推进。
- **平台构建。** 平台用清单里的环境变量、在只读的 home 目录下构建，所以清单设置了 `NPM_CONFIG_CACHE=/workspace/.npm-cache`，
  并用 `npm ci --include=dev` 安装（TypeScript 编译器是开发依赖）。

## 可以改进的方向

- **多搜索。** 每次决策多试一些指向（锚点放在不同光纤、剩余科学价值密集的区域、小幅平移）和曝光时长，
  给望远镜时间定价，而不是只看每秒收益。
- **规划整个观测季。** 暗弱的 required 目标需要最好的夜晚；决定哪些夜晚观测哪片天区，而不是只做贪心。
- **从命中结果读出项目档位。** 饱和命中会准确显示项目倍率，因此能判断申报的项目是否匹配。
- **更好的故障检测。** 单次曝光里天气和仪器故障很像；把质量和天空档位、不同方向、不同夜晚对比，并用好免费报告额度。
- **更多地使用大模型**，比如读预报，或判断疑似故障。

## 许可

任务卡、模拟数据、评测代码和示例项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 许可；
请引用 GOSIM 2026 Agentic Observer Hackathon（https://create.gosim.org/survey26/）。见 `../LICENSE.md`。
