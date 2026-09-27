## 1. 当前比赛

当前是练习赛 / Playground。你只需要运行算法、上传结果、查看成绩；平台自动选择比赛，不需要自行辨别阶段。

## 2. 报名与组队

注册后在「找队友」创建队伍，或点击队伍发送加入申请。队长接受后加入；也可向选手发送邀请。双方通过右上角通知查看进度，接收方可以接受或拒绝。每队最多 3 人。

## 3. 运行入门包

从[资源页](/resources)下载并解压入门包。双击 `run_baseline`，或在目录中运行：

```sh
python3 local_runner.py --scenario scenarios/dev-reference --agent agent/minimal_agent.py --wallclock 600 --out run_output
python3 score_decisions.py --scenario scenarios/dev-reference --decisions run_output/decisions.csv
```

更短的演示可用 `scenarios/demo-week`。修改 `agent/my_strategy.py` 中的 `choose_action(candidates, snapshot, memory)`，重新运行并比较成绩。算法语言不限；使用自定义程序时，按入门包的标准输入输出协议交换 JSON 消息，普通日志写入标准错误。

模型调用可选。确定性基线无需密钥；使用自己的模型服务时，不要把密钥写入结果文件或公开代码。

## 4. 提交与结果

打开[提交](/compete)，选择本地运行的场景，上传 `run_output/decisions.csv`。文件最大 20 MB，每队每天最多 50 次，以网页额度为准。

CSV 列固定为 `decision_id, slot_id, action, tile_id, program, request_id, reason`。提交成功后进入详情页，查看评测状态、得分构成、完成情况和回放。每个场景分别排名，保留本队最高分。

想提前熟悉评测流程，在「参赛」页选「提交完整项目」，提交 GitHub 仓库或 ZIP。平台在云端逐轮运行你的程序（和比赛相同的评测流程），使用公开场景 dev-fortnight 和 dev-reference，每个场景运行时限 5 小时。每队每天 5 次（UTC 0 点即北京时间 8 点重置，因平台原因失败的不计次数），调用模型只能用本队自己的模型 API 密钥，成绩进单独的完整项目榜。建议在 10 月 2–3 日培训前后用这种方式把流程走一遍。

### 完整项目的启动配置（任何语言）

项目根目录必须有 `observer.project.json`，告诉平台用哪个镜像、怎么构建、怎么启动。入门包 `pack_agent.py` 打出的 ZIP 已经自带。**没有这个文件时**，平台会尝试用你在「模型 API」里设置的模型自动生成适配器；没有设置模型或模型调用失败，准备就会失败。

```json
{"schema_version": "observer-project-v1", "image": "python:3.12-slim", "run": ["python3", "-u", "agent.py"]}
```

Node.js：`"image": "node:22-slim", "run": ["node", "agent.js"]`。Rust：`"image": "rust:1-bookworm", "build": [["cargo", "build", "--release"]], "run": ["./target/release/agent"]`（`build` 是命令数组的数组）。程序从 stdin 逐行读 JSON 消息、向 stdout 逐行写回答，协议见入门包 `SKILL.md`；日志请写到 stderr，评测后会出现在结果包的 `agent.log` 里。

## 5. 数据与评分

`config/` 包含规则配置；`outputs/reference/` 包含天区、目标、日历、时隙、天气、预报、事件和观测请求。公开文件可从资源页下载。当前练习场景使用原有 `participant-agent-protocol-v1` 合约，已有成绩与回放保持不变。

当前快照提供可用候选、天气与进度。`observe` 观测，`wait` 等待；平台和入门包使用同一评分器。科学分、项目加成、请求奖励与各项扣分见[规则](/rules)，精确公式和常数以场景配置与公开评分器为准。

## 6. 排查问题

程序报错时查看输出目录的 `agent.log`；核对场景名称、CSV 列名、文件大小和当天额度。可以用上面的 `score_decisions.py` 命令独立复算。完整命令与字段说明保存在入门包的 `SKILL.md`、`QUICKSTART_ZH.md` 和 `README.md`。
