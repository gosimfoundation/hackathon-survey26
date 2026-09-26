> 本页按参赛的实际顺序组织：第 1–4 节从零跑通到完成提交，第 5–6 节讲分数从哪来、怎么提高，第 7–8 节是本地运行与协议合约，第 9 节是提交前自检，第 10 节是数据文件字典（备查）。

## 1. 概览

你要构建的，是一个替天文台值夜班的程序。夜晚被切成 900 秒一格的时隙；每一格，你的智能体看一眼当前天况和一串候选天区，决定观测哪一块天，或者等一等。跑完一整场，它会留下一张按时隙排列的决策清单（`decisions.csv`）；一个冻结不变的评分器读这张清单，产出成绩单（`score_report.json`）。

一个场景就是一道题，形式是一个文件夹：`config/` 下六个配置文件写明这一局的全部规则；`outputs/reference/` 下是参考数据——按真实太阳历生成的时隙日历，分 REQUIRED / FLEXIBLE 两类、各有可用时间窗的天区与目标目录，逐时隙的天气与影响特定天区的方向性干扰事件，每日修订、带不确定性的预报，以及中途插进来的临时观测请求。练习场景的天气全部公开；比赛场景通过官方会话逐步提供当前天气、已发布预报与真实观测结果，并启用异常机制——隐藏的仪器故障与逐天区异常标签，`decisions.csv` 里的 `report_*` 行就是对它们的上报（开关写在各场景 `score_config.json` 的异常小节；入门包的 `finals-preview` 场景也启用，便于本地演练）。全部练习场景保持赛初合约逐字节不变（快照 `decision-snapshot-v2`，不接受上报）。这套合约的正式名字是 **challenge v3**（`challenge-score-v3`、`participant-agent-protocol-v2`）。

练习赛继续接收本地练习生成的 `decisions.csv`。正式赛支持完整项目（公开仓库链接或私有 ZIP）以及官方本地会话导出的 CSV。两种正式赛方式逐步接收相同信息，未来天气保留在服务器。项目语言不限，不强制调用模型；已有提交、成绩与回放全部保留。

平台和入门包使用同一份 `scoring_core.py`。入门包包含 workflow、评分器、最小智能体与公开的场景文件。

赞助商 API 额度以兑换码形式发放：队伍注册后在控制台领取，每个服务商一个，用于在本地运行时调用模型 API。

## 2. Playground与线上比赛

两个赛场：**Playground** 随时练手——随便交、马上出分、名次只供参考；**线上比赛**决定名次。下表是全部差别。

| | Playground | 线上比赛 |
|---|---|---|
| 场景 | `demo-week`（7 晚演示）、`dev-fortnight`（14 晚）与 `dev-reference`（180 晚，公开示例）；天气、预报、事件全部公开 | 开赛时公布；通过会话逐步提供当前信息，未来天气不公开 |
| 提交 | 结果文件（`decisions.csv`），每队每天 50 次；或完整项目，每队每天 5 次，单独榜单 | 完整项目或官方本地会话 CSV，每队每天 10 个完整批次 |
| 得分 | 按场景分开排名，仅供参考 | 同一批全部场景的平均值，每队取最高分的完整批次 |

公开练习数据可用 `score_decisions.py` 在本地复现评分。正式赛由服务器计算官方成绩，隐藏天气与异常答案不会放入选手项目或下载文件。

两个阶段用同一个评分器和同一份 `score_config.json`，报告格式相同，因此 Playground 调出来的策略可以直接用于比赛。

**赛前演练。** Playground 的「完整项目」赛道和正式赛走同一套流程：提交仓库或 ZIP，平台在云端逐轮运行。题目由练习赛数据生成，没有异常机制；每队每天 5 次（因平台原因失败的不计次数），只能用本队自己的模型密钥，成绩进单独榜单。10 月 1–4 日培训期间建议用它把正式赛流程完整走一遍；异常机制用入门包的 `finals-preview` 在本地练习。

### 正式赛项目与本地会话

1. 打开[智能体项目](/projects)，提交公开仓库链接或私有 ZIP（不超过 50 MB）。[最小完整项目示例](https://github.com/BH3GEI/observer-project-example)展示 JSONL 接口；Python 是运行器的语言，不限制项目语言。
2. 公开试跑通过后，审阅固定的源码、容器镜像、启动设置与适配文件，确认版本后才能正式评测。上传和确认版本都不占评测次数（上传每队每天最多 10 次）。还没评测过的版本可以撤回，撤回后不再显示，也不能确认或评测；正在准备的版本要等准备结束后才能撤回。
3. 选择本地运行时，启动本地 CSV 会话，从运行说明下载运行器，执行自己的完整项目，再把导出的 CSV（不超过 20 MB）上传到对应记录。修改过的文件会被拒绝；旧入门包的 CSV 用于练习，不能替代正式会话。
4. 每点一次「评测此版本」占当天 1 次评测：一次评测把本赛程全部场景各跑一遍，分数是这些场景的平均分，排行榜取本队最高的一次完整评测。因平台原因（评测引擎、调度、网络或超时等）失败的评测不计次数，记录中标为「未计入次数」；你的程序构建失败、崩溃或输出不符合协议导致的失败照常计次。再次评测已经评测过的版本需要确认。每日次数按 UTC 0 点（北京时间 8 点）重置，页面显示今天还剩几次。队伍可以下载私有结果、查看运行日志。模型调用可选，可使用主办方 API 或在项目页保存受支持的个人 API；临时凭证有额度与有效期。
5. 可随已确认项目保存架构与复现说明，用于独立设计评价，不计入成绩榜分数。

## 3. 入门包（练习赛）

### 最短路径（不需要任何工具）

1. 在「资源」页下载[入门包 agent-observer-starter-kit.zip](/resources)并解压，双击 `run_baseline.command`（macOS）、`run_baseline.bat`（Windows，先从 python.org 安装 Python 3.12）或运行 `./run_baseline.sh`（Linux）。基线在自带场景上约 12287 分，回放会在浏览器里打开。想先快速看一遍，把文件名换成 `run_demo_week`：7 晚的演示场景，约 2 秒跑完，同一套流程和评分器，结果写在 `demo_week_output/`。
2. 修改 `agent/my_strategy.py`：`choose_action(candidates, snapshot, memory)` 收到按估计收益排好序的合法候选，返回要观测的那个，或返回 `None` 等待。再双击一次比较分数。
3. 在「提交」页选择场景，把生成的 `run_output/decisions.csv` 拖进去即可。

入门包里的 `QUICKSTART_ZH.md` / `QUICKSTART.md` 就是这三步。下面是给工程师看的完整版。

### 内容与命令


在「资源」页下载 `agent-observer-starter-kit.zip`。目录结构：`agent/`（要提交的智能体：`minimal_agent.py`、`decision_graph.py`、`model_factory.py`、`protocol.py`、`state.py`、`scoring_preview.py`、`requirements.txt`、`.env.example`）、`challenge/`（公开环境：契约、历法、瓦片几何、天气、请求、workflow、评分器、回放渲染器）、`scenarios/dev-reference/`（公开的 180 晚场景）、`scenarios/demo-week/`（公开的 7 晚演示场景）、`local_runner.py`、`score_decisions.py`、`make_scenario.py`、`fetch_scenario.py`、`pack_agent.py`、`sac_submit.py`、`SKILL.md` 与 `README.md`。Python 3.9 及以上加标准库即可运行（macOS 自带的 `python3` 直接可用；Windows 请从 python.org 安装 Python 3.12）。

```
python3 local_runner.py --scenario scenarios/dev-reference --agent agent/minimal_agent.py --wallclock 600 --out run_output
python3 score_decisions.py --scenario scenarios/dev-reference --decisions run_output/decisions.csv
python3 make_scenario.py --out scenarios/mine --seed 7 --days 30 --start-date 2026-10-05
python3 pack_agent.py --agent agent --out my-agent.zip
python3 fetch_scenario.py --list && python3 fetch_scenario.py dev-fortnight   # 其它公开场景 -> scenarios/<slug>/
```

`run_output/decisions.csv` 就是可上传的结果文件；`run_output/score_report.json` 与平台生成的报告一致（场景天气与事件公开时逐字节相同）；`run_output/decision_replay.html` 就是提交页内嵌的那份回放。`fetch_scenario.py` 可把任一已发布场景（如 `dev-fortnight`）完整下载到 `scenarios/<slug>/` 并校验哈希；「资源」页也提供逐个文件的链接。最小智能体不需要任何依赖或密钥（`MODEL_PROVIDER=deterministic`），几秒钟即可跑完 180 晚的场景。

## 4. 提交

做出东西之后怎么交卷：网页上拖文件就行；喜欢命令行的用脚本。

### 网站

控制台 → 提交。选择阶段、场景与文件，页面显示队伍今日剩余次数。每次提交都有独立页面：得分分解、完成情况、请求、等待秒数、终止原因、交互式决策回放、已观测天图、动作时间线，以及可下载的 `score_report.json` / `decisions.csv`。

### 命令行

```
python3 sac_submit.py --phase practice --kind results --scenario dev-reference --file run_output/decisions.csv --wait
python3 sac_submit.py --phase online --kind results --scenario <正式场景> --file run_output/decisions.csv --wait
```

`sac_submit.py` 读取 `SAC_URL`、`SAC_KEY`、`SAC_EMAIL`、`SAC_PASSWORD`（见「资源」页），`--wait` 轮询直到评测结束。

## 5. 评分（challenge-score-v3）

概括：**天区越有价值、拍它时天况越好，得分越高**；REQUIRED 天区没拍完、临时请求超期，扣分。公式供程序核对，表格已列出全部数值。

对每次完成的曝光，各分段（按时隙边界切分，取中点）贡献：

```
A_atm      = min(instrument_efficiency · transparency · sky_quality / (seeing_arcsec · airmass), 3.0)
combined   = A_atm · lunar_quality_factor                      # 计分用（含效率）
combined₀  = min(transparency · sky_quality / (seeing_arcsec · airmass), 3.0) · lunar_quality_factor   # 档位用（不含效率）
band       = combined₀ ≥ 0.65 → DARK；≥ 0.40 → BRIGHT；否则 BACKUP
base       = V_tile · (segment_seconds / nominal_exptime_seconds) · combined
bonus      = program == band 时 base · {DARK: 0.25, BRIGHT: 0.15, BACKUP: 0.08}[program]，否则 0
```

`total = base_science + program_bonus + request_reward + report_reward + coverage_bonus − unsafe_observation − invalid_action − avoidable_wait − required_miss − flexible_shortfall − request_miss − fault_misreport − wrong_tag_report`，常数来自 `config/score_config.json`：

| 项 | 规则 | 数值 |
|---|---|---|
| `unsafe_observation` | 开始时 `is_observable=false` 仍 `observe`；消耗当前时隙剩余时间 | 每次 2000 |
| `invalid_action` | 未知天区/项目/时隙、窗口之外、错误请求标注、在天区落下或夜晚结束前无法完成的曝光、过期决策 | 每次 100 |
| `avoidable_wait` | 有可合法完成或可提分的重复观测时的等待秒数 | 每秒 0.001（每个空时隙约 0.9） |
| `required_miss` | 运行结束时未完成的 REQUIRED 天区 | 每个 1000 |
| `flexible_shortfall` | 某分区完成的 FLEXIBLE 天区少于 4 个 | 每缺一个 100 |
| `request_miss` | 请求到期时访问数不足，除非根本不存在可行机会（`excused_unobservable`） | 每个所需天区 `miss_penalty`（190） |
| `request_reward` | 请求在截止前完成 | 每个所需天区 `reward`（140） |
| `report_reward` / `wrong_tag_report` | 标签上报每个 (tile, 标签) 首次正确 +100、错误 −150 | +100 / −150 |
| `fault_misreport` | 两次正确故障上报之间的误报超过一次免费额度后 | 每次 100 |
| `coverage_bonus` | 已完成天区在各分区间的均匀度（Jain 指数）× 基础科学分 × 权重 | 权重见场景的 `score_config.json`：练习 0，正式比赛 0.35 |

只有完成的曝光计分。后续分段遇到关闭天气的曝光为 `weather_interrupted`（无科学分，无惩罚）；跑到天区落到 30° 以下或夜晚结束的为 `geometry_or_night_interrupted`（无科学分，记无效动作惩罚）。重复观测合法：每个天区按历次观测的最高分入账（更差的重复不会拉低它），完成状态、REQUIRED 豁免与分区配额仍以首次合法观测为准。隐藏标签静默乘分：nova ×1.5、reddening ×0.8（同一 tile 可叠加）；公布的 `tile_science_value` 保持未乘基线。月亮升起时月光因子持续降低 `combined`，并可能改变匹配的项目。终局惩罚（`required_miss`、`flexible_shortfall`、`request_miss`）对被时钟或智能体错误截断的运行同样适用。

`scoring_preview.py` 只用当前快照估算各候选的边际价值（不含未来天气，也不含仪器效率——基线是不乘效率的公开公式）；这是最小智能体使用的同一份代码，永远不能替代正式回放。

## 6. 策略提示

1. REQUIRED 天区每个缺失扣 1000，其中一半只有 14 天可用：优先安排。
2. 每个分区完成 4 个 FLEXIBLE 天区可避免每个 100 的缺额；分散到各分区比压榨单个分区更重要。
3. 项目加成为基础分的 25 % / 15 % / 8 %；用 preview 的 `combined_quality` 选择区间，注意长曝光可能随月亮升起或 airmass 增大而滑入另一区间。
4. 等待很便宜（每时隙 0.9），而一次不安全曝光扣 2000：绝不在 `is_observable=false` 时观测；方向性事件活动时优先选 `effective_weather` 开放的天区。
5. 请求每个所需天区奖励 140、缺失扣 190：每个快照都检查 `active_requests`，并在观测时标注 `request_id`。
6. 时钟是全局的。几百次决策各调用一次模型可以承受，180 晚约 8,000 次决策则不行；把显而易见的等待交给确定性代码。
7. 异常检测：把 `tile_last_finished.score` 和该曝光的公开公式估值对比——基线不含仪器效率，正常读数因抖动落在 ≈0.90–1.00；≈1.35–1.5 是 nova、≈0.72–0.80 是红化、持续低于 0.70 是仪器故障。这些区间只是发现异常的启发式参考，不是评分器执行的判据。预报中的 cold_wave 也会压效率，那段读数别算进异常证据。标签永久、天气抖动暂时，让同一 tile 的多次读数说话再上报；错报标签 −150（对了才 +100），故障误报超额每次 −100。故障确认后避开其作用区直到 `repair_complete_utc`。重复观测是合法的提分手段：完成后继续拍最高质量的天区，每场只按最高分入账。

## 7. 本地运行

智能体在你自己的电脑上运行，语言、依赖与环境不限，可以联网调用模型 API。入门包的 `local_runner.py` 扮演平台的角色：在每个场景上启动一次你的入口脚本，按下一节的协议逐条发送快照，把动作写进 `run_output/decisions.csv`，再用公开评分器算出分数。上传的 `decisions.csv` 不超过 20 MB。

## 8. 参赛协议（participant-agent-protocol-v2；练习场景仍为 v1）

本地运行时，下文的「平台」就是 `local_runner.py`。它和你的程序之间是一问一答的 JSON 对话：每个时隙，平台发来「现在的天况和候选天区」，你的程序回一句「拍这个」或「等待」。下面是每条消息的精确格式。（本页底部有可交互的协议消息演示。）

平台在每个场景上启动一次你的入口脚本（用 `--agent` 指定），并在整个运行期间保持进程存活。消息通过标准输入输出传递，每行一个 JSON 对象；标准输出不要打印其他内容。标准错误记录在输出目录的 `agent.log` 里；云端评测时，队伍的私有结果 ZIP 同样包含 `agent.log`（构建输出与标准错误的最后 2 MB，平台凭据和网址已移除）。每条消息都带 `protocol_version`、`message_type`，除 `initialize` 外还带 `decision_sequence`。

### `initialize`（平台 → 智能体，一次，不需回复）

payload 为 `initial-publication-v2`：`calendar`（首末夜、夜数与时隙数、时隙时长）、`site`、`tile_catalog`（每个天区的公开列加 `tile_science_value`、`required_tile_ids`、`region_ids`）、`target_catalog`（全部目标）、`scoring_contract`（完整 `score_config.json`、天气评分接口与月光模型）以及 `global_wallclock_seconds`。参考目录约 2 MB，大规模比赛目录可能超过 60 MB。Runner 会自动解压平台传输的数据，向 Agent 提供完整的原始 JSON。启动并读取它有 30 秒预算；全局时钟在其发送完成后开始。

### `decision_request`（平台 → 智能体，每次决策一条）

payload 为 `decision-snapshot-v3`：

- `cursor`：`slot_id`、`night_id`、`timestamp_utc`、`slot_offset_seconds`。
- `current_site_weather`：当前时隙的基线条件（`is_observable`、`seeing_arcsec`、`transparency`、`sky_quality`、`active_event_ids`）。快照天气永远不含 `instrument_efficiency`：preview 基线因此不乘效率，实现分与基线的偏差恰好隔离出隐藏的仪器侧（效率抖动 × 故障乘数 × 标签乘数）。
- `tile_last_finished`：最近一次完成观测的实现官方分 `{tile_id, score}`（中断曝光为 0；首次完成前为 `null`；等待与非法动作不更新）。与公开公式估值对比即可发现隐藏异常。
- `candidate_tiles`：处于可用窗口内、此刻高于 30° 且当夜窗口包含游标的天区（`already_completed` 标记是否已完成——重复观测合法且按最高分入账）。每个带 `scheduling_class`、`nominal_exptime_seconds`、`tile_science_value`（未乘隐藏标签的基线值）、`window_start_utc` / `window_end_utc`、`geometry`（高度、方位、时角、airmass、月距、`lunar_quality_factor`）与 `effective_weather`（对该天区应用方向性事件后的天气）。候选仍可能无法在窗口结束前完成；`scoring_preview.py` 会过滤这些。
- `active_requests`：已发布且未到期的请求，含天区要求与已完成访问。
- `night_start`：每晚第一个时隙给出当夜行与当夜天区窗口；其余为 `null`。
- `weekly`：每第七晚的第一个时隙给出到目前为止发布的预报、未来七天的天区窗口与请求；其余为 `null`。
- `fault_status`：只在夜初出现，且只在你的故障上报正确之后——上报一天（模拟日）后首次发布 `{"status":"fault","spatial_scope_type":...,"spatial_scope_payload":{...},"instrument_efficiency_multiplier":...,"repair_complete_utc":...}`，维修期（两天）每晚重发，修复完成后消失；误报（无活跃故障）按同一时刻表收到一次性的 `{"status":"normal","reference_report_id":...}` 应答。
- `progress`：`completed_tile_ids`、`flexible_completed_by_region`。

任何消息中都没有未来天气。读取快照不推进时间；只有提交的动作才推进。

### `decision_response`（智能体 → 平台）

```
{"protocol_version": "participant-agent-protocol-v2", "message_type": "decision_response", "decision_sequence": 12,
 "action": "observe", "tile_id": "T00037", "program": "DARK", "request_id": "", "reason": "highest preview estimate", "decision_source": "deterministic",
 "reports": [{"kind": "NOVA", "tile_id": "T00037"}, {"kind": "Instrument_Failure"}]}
{"protocol_version": "participant-agent-protocol-v2", "message_type": "decision_response", "decision_sequence": 13,
 "action": "wait", "tile_id": "", "program": "", "request_id": "", "reason": "no completable candidate", "decision_source": "deterministic"}
```

`decision_sequence` 必须与请求相同。`action` 必须是 `observe` 或 `wait`；其他值、畸形行或进程退出都会以 `termination_reason = agent_error` 结束运行，已提交的动作照常评分。未知天区、错误项目或错误请求标注不会被拒绝：评分器把它们作为受罚的无效动作提交，时间继续推进。

`reports` 为可选数组，每项 `{"kind":"Instrument_Failure"}` 或 `{"kind":"NOVA"|"Reddening","tile_id":"..."}`：上报不占时隙、不推进时间；畸形条目被丢弃（动作照常），重复条目容忍（结算去重）。标签在终局结算：每个 (tile, 标签) 只计首次，正确 +100、错误 −150（同一 tile 两种标签独立结算）。故障上报是局内仪表：有未确认活跃故障时为正确上报——触发 `fault_status` 发布与修复时钟；无活跃故障时为误报——两次正确上报之间有一次免费额度，之后每次 −100，正确上报清零计数器；对已确认未修复故障的重复上报中立。每条被接受的上报在运行产物的 `decisions.csv` 里落为一行 `report_*` 动作（紧随其承载决策，共享 `decision_id` 递增序列），随该文件进 SHA-256 审计链。

### 时间核算

每个场景一个全局时钟（`global_wallclock_seconds`，在「资源」与「提交」页显示：参考场景 7200 秒，短场景更少）。它从初始发布结束起计时，直到巡天完成或时钟到期，并包含快照序列化、你的思考时间与解析时间。没有单次决策限制。在截止时刻或之后到达的响应被丢弃（`ignored_in_flight_response`），进程被终止，已提交动作连同终局惩罚一起评分；报告写明 `global_wallclock_expired`。未处理的未来时间不会被算作可避免等待。

## 9. 本地自检清单

1. `local_runner.py` 在 `scenarios/dev-reference`（以及 `make_scenario.py` 新生成的种子）上以 `termination_reason = survey_complete` 结束。
2. `score_decisions.py` 对生成的 `decisions.csv` 输出与运行相同的 `score.total`。
3. 上传的是 `run_output/decisions.csv`，场景与本地运行的场景一致。
4. 智能体的标准输出只打印协议行。
## 10. 数据格式

以下是全部数据文件的逐列参考——用到哪个查哪个，不必通读。

约定：UTF-8（允许 BOM），逗号分隔，表头必须严格按顺序包含列出的列。时间戳为 `YYYY-MM-DDTHH:MM:SSZ`（UTC）。区间为左闭右开 `[start, end)`。布尔值为小写 `true` / `false`。标识符：夜 `N20260907`，时隙 `N20260907-S001`，天区 `T00001`，分区 `R00`–`R07`，请求 `RQ0001`，目标 `TG00000001`。

### 场景目录

| 路径 | 内容 | 可见性 |
|---|---|---|
| `config/scenario_config.json` | 场景 id、seed、`competition.global_wallclock_seconds` | 公开 |
| `config/calendar_config.json` | 台址（纬度 31.9634°，经度 −111.599°，UTC−7，太阳高度阈值 −12°）、起始日、天数、`slot_seconds` 900 | 公开 |
| `config/tile_config.json` | 目录布局（8 个分区 × 8 个天区，每区 2 个 REQUIRED，其中 1 个只有 14 天可用）、高度下限 30°、月光模型、目标类别、隐藏异常标签数量 | 公开 |
| `config/weather_config.json` | 质量过程（仪器效率逐时隙在 [0.90, 1.00] 内抖动并冻结）、关闭模型、预报范围与误差模型、事件目录（含 `instrument_fault`）、`score_interface` | 公开 |
| `config/request_config.json` | 请求节奏、截止档期、每个所需天区奖励 140 / 缺失惩罚 190 | 公开 |
| `config/workflow_config.json` | `global_wallclock_seconds`、每周信息 7 天、无单次决策超时 | 公开 |
| `config/score_config.json` | 阈值、项目加成、惩罚、FLEXIBLE 配额 | 公开 |
| `outputs/reference/night_calendar.csv`、`slots.csv` | 共享时间轴（每晚 37–47 个时隙） | 公开 |
| `outputs/reference/tiles.csv`、`targets.csv`、`tile_windows.csv` | 目录、逐目标科学权重、可见窗口示例 | 公开 |
| `outputs/reference/observation_requests.csv`、`observation_request_tiles.csv` | 预生成的请求及其天区 | 公开 |
| `outputs/reference/weather.csv` | 逐时隙站点基线天气 | 练习场景公开；正式赛仅通过会话提供当前已发布信息 |
| `outputs/reference/weather_forecasts.csv` | 不确定、每日修订的预报 | 练习场景公开；正式赛仅通过会话提供当前已发布信息 |
| `outputs/reference/weather_events.csv` | 方向性干扰事件（`active_event_ids` 背后的真值；`instrument_fault` 故障事件永不进预报、不进快照） | 练习场景公开；正式赛仅通过会话提供当前已发布信息 |
| `outputs/reference/tile_anomalies.csv` | 隐藏 per-tile 真值标签（nova ×1.5 / reddening ×0.8，只作用于评分器） | 比赛场景隐藏，练习场景可审计 |
| `outputs/reference/scenario_manifest.json`、`*_metadata.json` | 每个文件的行数与 SHA-256 | 公开 |

### tiles.csv

```
tile_id,ra_deg,dec_deg,nominal_exptime_seconds,region_id,scheduling_class,available_from_utc,available_until_utc,n_lrg,n_elg,n_qso,n_bgs
```

`scheduling_class` 为 `REQUIRED` 或 `FLEXIBLE`。天区只能在 `[available_from_utc, available_until_utc)` 内观测。天区没有固定项目：智能体在决策时选择 `DARK`、`BRIGHT` 或 `BACKUP`，与曝光的质量区间匹配时获得加成。曝光时长为 450、600、900、1200 或 1350 秒。

### targets.csv

```
target_id,tile_id,target_class,feature_flux,redshift,science_weight
```

天区价值 `V_tile = Σ science_weight`（默认 LRG 1.0、ELG 1.0、QSO 1.7、BGS 0.45）。平台在初始消息中以 `tile_science_value` 发布。

### weather.csv

```
slot_id,night_id,timestamp_utc,duration_seconds,is_observable,seeing_arcsec,transparency,sky_quality,instrument_efficiency
```

`is_observable=false` 时四个质量字段为空：圆顶关闭，时隙仍存在并消耗时间。`sky_quality` 为线性质量量（越大越好）。该文件只是站点基线；天区实际感受到的条件还取决于方向性事件（`weather_events.csv`），平台会替你应用，并在每个候选天区的 `effective_weather` 中给出。

### weather_forecasts.csv 与 weather_events.csv

预报含发布时间、预测事件窗口、概率与空间范围；每日修订，可能漏报或误报（默认 12 % 漏报率、每场景 6 个误报）。平台只显示当前游标之前已发布的修订。事件含范围（`ALL`、`REGION_SET`、`SKY_CAP_ICRS`、`HORIZON_SECTOR`、`TILE_SET`）、条件（`rainy`、`cloudy`、`smoggy`、`rocket_launch`、`cold_wave`、`tornado`、`instrument_fault`）与乘子；部分事件会对其覆盖的天区强制关闭。`instrument_fault` 是区域级仪器故障：效率乘数最低压到 0.10、每场至多一次、不自行结束（只有正确上报后两天才修复）、绝不出现在预报里，只能靠实现分偏差发现。

### observation_requests.csv 与 observation_request_tiles.csv

```
request_id,issued_at_utc,available_from_utc,deadline_utc,deadline_class,completion_mode,required_tile_count,reward,miss_penalty,reason
request_id,tile_id,required_visits
```

请求发布后出现在快照中，到期后消失。观测时标注 `request_id` 才计入请求；访问计数与天区得分完全解耦：对已完成天区的请求标注复访既计访问也正常计分（天区按历次观测最高分入账）；请求指向此前已观测的天区时，需要一次发布后的新观测才计访问。`ALL` 请求需要列出的全部天区，`AT_LEAST_N` 请求需要其中 `required_tile_count` 个。

### decisions.csv

```
decision_id,slot_id,action,tile_id,program,request_id,reason
```

1. `decision_id` 为任意非空且唯一的字符串（平台生成 `D000001`、`D000002`…，决策行与上报行共享同一递增序列）。
2. `action` 为 `observe`、`wait` 或上报行 `report_instrument_failure` / `report_nova` / `report_reddening`。`wait` 行的 `tile_id`、`program`、`request_id` 留空，消耗当前时隙剩余时间。`observe` 行需要 `tile_id` 与 `DARK` / `BRIGHT` / `BACKUP` 之一的 `program`；`request_id` 可选。上报行紧随其承载决策之后，不占时隙、不动游标：`report_nova` / `report_reddening` 必须带 `tile_id`，`report_instrument_failure` 不得带；`program`、`request_id` 留空。
3. `slot_id` 是动作开始的时隙。曝光从游标起持续天区的 `nominal_exptime_seconds`，可跨时隙并按分段评分。短曝光结束后可在同一 `slot_id` 内再提交动作。
4. 晚于游标的时隙会插入隐式等待；早于游标的是 `stale_decision`（受罚，不消耗时间）；未知时隙为 `unknown_slot`。
5. 表格畸形（表头错误、未知动作、带天区的 `wait`、缺天区或项目的 `observe`、重复 `decision_id`、字段不合法的上报行）作为无效提交被拒绝。其余情况一律评分，不拒绝。

### score_report.json（`score-report-v3`）

`score{total, base_science, program_bonus, request_reward, report_reward, coverage_bonus, coverage_evenness, penalties{unsafe_observation, invalid_action, avoidable_wait, required_miss, flexible_shortfall, request_miss, fault_misreport, wrong_tag_report}}`、`completion{completed_tiles[], required_missing[], flexible_by_region{}, flexible_shortfall{}}`、`requests[{request_id, status, satisfied_tile_count, required_tile_count, feasible_tile_count, reward, penalty}]`、`reports`（逐 (tile, tag) 结算与故障上报计数）、`wait_seconds{explicit, implicit, invalid, avoidable, unavailable}`、每个决策一条的 `actions[]`（`outcome`、`start_utc`、`elapsed_seconds`、`base_science_score`、`program_bonus_score`、`penalty`，以及带 airmass、活动事件、大气与月光质量、质量区间和项目匹配的 `segments[]`）、`termination_reason`、`final_cursor`、`parameters` 与 `input_sha256`（含 `reports` 的 SHA-256）。

动作结果：`completed`、`wait`、`weather_interrupted`、`geometry_or_night_interrupted`、`unsafe_observation`、`invalid_observe`、`invalid_request_tag`、`outside_tile_window`、`unknown_slot`、`stale_decision`（重复观测已完成天区是合法动作，不再是 `duplicate_tile`），上报行为 `report_recorded` / `report_duplicate_ignored` / `report_correct` / `report_neutral` / `report_misreport` / `report_dropped`。

