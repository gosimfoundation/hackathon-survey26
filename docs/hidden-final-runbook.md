# 隐藏卡决赛评测操作手册（E–H，阶段 `final-hidden`）

比赛（`online`）截止后，主办方用每队的**最终版本**在隐藏任务卡 E、F、G、H 上各跑一次，最终成绩为四张卡得分的算术平均（规则第 5 节第 13 条、第 6 节）。本手册是这一步的完整操作流程。所有命令都在仓库根目录执行，需要环境变量 `SUPABASE_PROJECT_REF`、`SUPABASE_ACCESS_TOKEN`（与其他主办方脚本相同），**不要把输出贴到公开渠道**。

工具：`scripts/run-hidden-final.py`（默认只预览，`--apply` 才写入）。数据库逻辑在 `private.observer_run_hidden_final`（迁移 `20260927000800`、`20261001000200`、`20261001000900`）。

## 1 · 规则在系统里如何落地

| 规则 | 实现 |
|---|---|
| 每队「最终版本」 | 队伍在 `online` 期间选定的版本；未选则用该队 `online` 最高分评测（四卡全部完成的那次，均分最高，同分取较早）的版本。`online.ends_at` 后锁定。管理后台「队伍 → 最终版本」可逐队查看。 |
| 每队在 E–H 各跑一次 | 每队一个 formal 批次，批次里每张挂在 `final-hidden` 上的卡一个 run（共 4 个），不占每日额度。 |
| 只评测一次；平台原因失败不计 | 已有当前卡组批次的队伍不会重复创建。某张卡因**选手自身原因**失败（项目构建失败、崩溃、协议错误或轨迹核验被 rejected，`private.observer_participant_failure`）时该卡记 0 分，批次不会因此失败，其余卡照常调度（迁移 `20261001000900`，只对 sealed 且计入决赛的阶段生效）。只要有一张卡因**平台原因**（调度、runner、引擎、过期等）失败，批次即失败，`--retry-failed` 重跑整批 4 张卡。`--retry-participant-failures` 只用于此规则之前就因选手原因失败的旧批次，属主办方决定。 |
| 最终成绩 = E–H 均分 | 4 个 run 都计分或因选手原因失败后批次状态为 `scored`，`score` 即四卡均分（选手原因失败的卡按 0 计）。`--results` 中这类卡显示 `0.00*`，CSV 的 `unfinished_cards` 列出它们；公布后的卡榜上显示 0 并标「未完成」。`--results` 按均分降序排名（同分同名次，规则规定同分处理由主办方决定）。不完整或失败的队伍、隐藏队伍列出但不排名。 |
| 公布前保密 | `final-hidden` 是 sealed 阶段：`leaderboard_mode` 不为 `published` 时，选手看不到该阶段、卡名、批次、run、日志和结果下载，也不能自己在该阶段发起评测。隐藏卡文件在公布后也不公开。 |
| 旧卡组的批次 | 只有恰好跑了当前 4 张卡的批次才算数。切换到 v4 之前的测试批次（v3 `eval-final`）既不挡住队伍、也不进入结果和卡榜。 |

v4 卡（含观测请求）只能在 colocated 模式下运行：`final-hidden` 已设 `colocated=true`、`runtime_seconds=900`、`board_layout=cards_overall`，4 张卡都有评测包（与 A–D 同一批构建，含观测请求文件）。预览输出里的 `target phase:` 一行会再核对一次。

## 2 · 赛前检查（10-07 白天完成）

1. 迁移已部署：`python3 scripts/deploy-observer-backend.py` 输出的 `pending` 为空。
2. 阶段配置：`python3 scripts/configure-v4-phases.py --status`，确认 `final-hidden` 为 sealed、colocated、900 s、4 张隐藏卡、`leaderboard_mode=hidden`。
3. 单队演练（可在比赛截止前做，用隐藏测试队）：
   `python3 scripts/run-hidden-final.py --team <测试队 slug> --before-freeze`（预览）→ 加 `--apply` 实跑 → `--status` 看进度 → `--results` 看结果。测试队是隐藏队伍，不参与排名，公布后普通选手在榜上也看不到它。
4. 模型密钥：预览输出会标出仍为「不保存（relay）」或「加密保存但没有密钥」的队伍。规则要求调用模型的队伍在截止前改为加密保存；截止前可再发一次提醒。
5. runner 分钟：预览输出的 `runner capacity:` 一行显示本月所有启用 runner 组织剩余分钟，`! AGENTIC-OBSERVER26-runner-N: needs …` 列出分钟不够其已分配队伍的组织。处理方法见第 4 节。

## 3 · 截止后执行（10-07 15:59 UTC 之后）

```bash
# 1. 预览：每队的最终版本、来源（chosen/best）、模型方式、估算
python3 scripts/run-hidden-final.py

# 2. 金丝雀：先只创建 5 队，确认能正常调度、计分
python3 scripts/run-hidden-final.py --apply --limit 5
python3 scripts/run-hidden-final.py --status      # 约 20 分钟后应有 scored

# 3. 其余所有队伍（已创建的自动跳过）
python3 scripts/run-hidden-final.py --apply

# 4. 监控（每 10–15 分钟一次即可）
python3 scripts/run-hidden-final.py --status

# 5. 全部结束后，重跑平台失败（只重跑平台原因失败的批次）
python3 scripts/run-hidden-final.py --retry-failed           # 预览：这些队伍显示为 would_create（retry after platform failure）
python3 scripts/run-hidden-final.py --apply --retry-failed

# 6. 结果（只在本地输出；CSV 不要提交或外传）
python3 scripts/run-hidden-final.py --results --csv ~/hidden-final-results.csv
```

不需要手动分批：所有批次一次创建后，调度器每分钟最多安排 5 个 run，按创建顺序（同一次 `--apply` 内按队名顺序，一队的 4 张卡相邻）逐个跑完。`--limit` 只用于金丝雀。

预览/执行输出中 `skip` 的原因：

| 原因 | 含义 | 处理 |
|---|---|---|
| `already_evaluated` | 已有当前卡组的批次（排队、运行中或已计分） | 无需处理 |
| `failed_settling` | 批次已判失败，但还有 run 在运行 | 等这些 run 结束后再判断、再重跑 |
| `failed_platform` | 上次因平台原因失败 | `--retry-failed`（同时取消旧批次里不会再被调度的排队 run） |
| `failed_participant` | 旧批次（迁移 `20261001000900` 之前）只因选手原因失败，其余卡没跑 | 如主办方决定重跑，用 `--retry-participant-failures` |
| `version_not_materialized` | 最终版本没有可运行的物化包 | 人工检查该版本 |
| `no_active_member` | 队伍没有未封禁的成员 | 人工处理 |
| 未列出的队伍 | 没有最终版本（既没选，也没有完整计分的 `online` 评测） | 不参加决赛评测 |

## 4 · 用时与 runner 分钟估算（约 150 队）

- run 数：150 队 × 4 卡 = **600 个 run**（每个 run 是一个 GitHub Actions engine 作业，colocated，选手程序在同一作业内运行）。
- 每个 run 的上限：900 s 卡时限 + 约 3 分钟启动/镜像/计分/上传 ≈ **18 分钟**；提前结束的程序更短（演练中的探针程序不到 1 分钟）。
- runner 分钟：最多约 600 × 18 ≈ **10,800 分钟**；实际通常明显更少。脚本预览按同样口径给出估算。
- 墙钟：调度速度约 5 run/分钟，600 个 run 约 120 分钟排完，加最后一批的运行时间，**约 2.5 小时**全部结束；平台失败重跑另需约 20–30 分钟。
- 并发：稳定时约 5 × 18 ≈ 90 个作业同时运行（GitHub Free 每组织 20 个并发作业，13 个组织共 260，不是瓶颈）。
- 作业落在哪个组织：每个批次以该队一名成员的身份运行，作业固定发往该成员已记录的 runner 组织（`private.observer_placements`，线上赛期间已确定）；只有派发报错时才会改投其他组织。也就是说**超过分钟上限的组织仍会继续接收其已分配队伍的作业**。
- 容量风险：每个 runner 组织的计数上限 `monthly_minute_limit` 默认 1800 分钟/月（GitHub Free 私有仓库额度 2000），13 个组织约 23,400 分钟/月，**且与 10-05–10-07 的线上赛同属 10 月**。某个组织的 GitHub 额度用完后，发往它的作业不会启动、最终过期失败（平台失败，可重跑，但会拖延公布）。预览输出会给出总剩余分钟，并逐个列出「已分配队伍所需分钟超过剩余分钟」的组织（`! AGENTIC-OBSERVER26-runner-N: needs …`）。出现时先用 `scripts/rebalance-observer-placements.py` 把空闲成员挪到有余量的组织、启用更多组织或调整 `monthly_minute_limit`，再执行。10-07 截止前后务必各看一次预览。

## 5 · 核验与公布

1. `--results` 确认所有应参赛队伍都有 `scored` 结果（选手原因失败的卡已按 0 计入，标 `*`）；仍为 `failed (platform)` 的先 `--retry-failed`。
2. 前列复现：对前列队伍的 run 用 `scripts/verify-v4-run.py --bundle <卡包> --result <结果包>` 回放核对（只输出总分、计数和摘要，不输出卡内容）；规则第 6 节第 4 条的复现核验另按约定进行。
3. 公布：在管理后台「阶段」把 `final-hidden` 的榜单模式改为 `published`（或 `update public.phases set leaderboard_mode='published' where slug='final-hidden'`）。公布后选手可看到该阶段卡榜（每卡 + 总榜）和自己的结果；隐藏卡文件仍不公开。加密保存的模型密钥在公布且保留期满后自动删除（迁移 `20260927001200`）。

## 6 · 保密要求

- 公布前不要在任何公开渠道（群聊、issue、PR、网站文案）提及 E–H 的内容、分数或排名；脚本输出和 CSV 只留在主办方本地。
- 脚本不会打印卡的内容（只有卡 slug、分数和状态）；不要把卡包或结果包解压后外传。
- 不要对隐藏卡使用「轮换种子」等会在日志中写出种子的操作。

## 7 · 线上演练记录

- 2026-10-01：迁移 `20261001000200` 已部署。用隐藏测试队 `acceptance-w02-platform-test`（最终版本设为其 v4 探针版本）执行 `--team … --before-freeze` 预览 → `--apply`：4 个 run 全部由正常调度在 colocated 模式下跑完并计分，批次 `scored`，`--status`、`--results --csv` 输出正常（该队为隐藏队伍，不排名）。匿名访问 `final-hidden` 的阶段、卡榜和批次均为空或被拒。探针程序很快结束（平均每 run 不到 1 分钟），不能代表 900 s 跑满时的耗时。
