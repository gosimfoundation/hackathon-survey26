/** Current competition copy, without asking participants to choose a stage. */
export function competitionMessages(base: Record<string, any>, chinese: boolean) {
  const result=structuredClone(base)
  const pick=(en:unknown,zh:unknown)=>chinese?zh:en
  const patches:Record<string,unknown>={
    'hero.pipeline':[{label:pick('Competition','正式比赛'),date:pick('See current schedule','以当前赛程为准'),note:pick('Submit · evaluate · review','提交 · 评测 · 查看成绩')}],
    'hero.location.0':pick('Online competition · join from anywhere','线上比赛 · 全球参与'),
    'hero.console.replay_note':pick('Example replay · {nights} nights · {actions} decisions','示例回放 · {nights} 晚 · {actions} 次决策'),
    'home.mission.closing':pick('No astronomy background is required. Start with the task description and example project.','无需天文背景，从任务说明和示例项目开始即可。'),
    'home.participate.steps.2.desc':pick('Open Participate to upload a complete project, confirm its version and start evaluation.','进入「参赛」，上传完整项目、确认版本并启动评测。'),
    'home.participate.timeline':[{label:pick('Competition','正式比赛'),desc:pick('The current competition','当前比赛')}],
    'home.leaderboard.lede':pick('The live online board shows each team’s best complete batch (the mean over the three formal scenarios). It is feedback only: the final ranking uses the hidden final scenario.','线上榜实时显示每队最高分的完整批次（三个正式场景的平均分），只作反馈；最终排名只看隐藏决赛场景的成绩。'),
    'home.submission.items.0.desc':pick('Upload a public repository or private ZIP. Evaluations run your confirmed project one round at a time.','上传公开仓库链接或私有 ZIP，平台运行确认后的项目，逐轮评测。'),
    'home.submission.items.1.desc':pick('Any language is allowed. ZIP projects may be up to 50 MB. 10 batches per team per day, 3600 s per scenario. Bring your own model API and quota; awards require LLM-driven agent techniques in at least two stages.','语言不限，ZIP 项目最大 50 MB。每队每天 10 批，每个场景 3600 秒。模型请自备 API 和额度；评奖要求至少两个环节采用大模型驱动的智能体技术。'),
    'home.quest.levels.2.desc':pick('Prepare your complete project in any language. Check its launch settings and confirm the tested revision.','使用任意语言准备完整项目，检查启动设置并确认通过测试的版本。'),
    'home.quest.levels.3.to':'/compete',
    'vision.sections.2.paragraphs.0':pick('The mission defines the science goal, tiles, observing constraints, requests and scoring. Public files are on Resources; the server releases observations during each run.','任务定义科学目标、天区、观测约束、请求和评分。资源页提供公开文件，服务器在评测中逐轮发放观测数据。'),
    'vision.sections.2.paragraphs.1':pick('The online competition uses three fixed formal scenarios A, B and C, the same for every team and every evaluation. Their files, weather, forecasts and events are not published. Only after a decision is recorded does the server return the next observation. After the online phase, each team’s final version is evaluated once on one hidden scenario.','线上比赛使用三个固定的正式场景 A、B、C，所有队伍、每次评测都相同；场景文件、天气、预报和事件不公开。服务器先记录本轮决策，再返回下一轮观测。线上赛结束后，每队的最终版本在一个隐藏场景上评测一次。'),
    'vision.sections.4.paragraphs.0':pick('Build a complete project in any language and submit its repository or ZIP. Awards require agent (LLM-driven) techniques in at least two stages; see Rules.','使用任意语言编写完整项目，提交仓库或 ZIP。评奖要求至少两个环节采用智能体（大模型驱动）技术，见规则页。'),
    'vision.sections.4.paragraphs.2':pick('Use Participate to prepare your project, review its launch settings and confirm a version for evaluation.','从「参赛」准备项目，检查启动设置和适配文件，再确认用于评测的版本。'),
    'vision.sections.5.paragraphs.1':pick('The scorer is fixed and every team plays the same formal scenarios. Immutable run records support organizer reproduction and audits.','评分器保持固定，所有队伍使用相同的正式场景。不可替换的运行记录支持主办方复现和复核。'),
    'vision.sections.6.paragraphs.3':pick('Use realized observation results to test your anomaly hypotheses. The scoring configuration defines report rewards and penalties.','根据实际观测结果检验异常判断，上报奖励与惩罚以评分配置为准。'),
    'vision.sections.6.highlight':pick('Future weather and anomaly answers stay private. Your decisions determine which observations you receive.','未来天气和异常答案保持私有，你的决策决定实际获得的观测结果。'),
    'vision.sections.8.title':pick('Competition schedule','比赛安排'),
    'vision.sections.8.paragraphs':[pick('See Rules for the current competition dates and Announcements for updates.','当前比赛日期见规则页，更新见公告。'),pick('Use the Submit button to open Participate. All scenarios in one batch contribute to its mean score on the online board; the final ranking uses only the hidden final scenario.','点击「提交」按钮进入「参赛」，同一批次的全部场景共同决定线上榜平均分；最终排名只看隐藏决赛场景。')],
    'vision.sections.8.rounds':[],
    'schedule.intro':pick('Current dates are shown in Rules; updates appear in Announcements.','当前日期见规则页，更新见公告。'),
    'schedule.rounds':[],
    'rules_page.phases_title':pick('Current competition','当前比赛'),
    'dash.phases':pick('Current competition','当前比赛'),
    'dash.quick.kit':pick('Example project and interface','示例项目与接口'),
    'start_page.cta_kit':pick('Project resources','项目资源'),
    'resources.kit':pick('Complete example project','完整项目示例'),
    'resources.kit_desc':pick('Use this complete example to implement the language-neutral project interface. The platform runs your confirmed version.','参考完整示例实现语言无关的项目接口，平台运行你确认的版本。'),
    'resources.reference':pick('Example source','示例源码'),
    'resources.reference_desc':pick('A complete project implementing the round-by-round JSONL interface.','实现逐轮 JSONL 接口的完整项目。'),
    'resources.skill':pick('Project submission guide','项目提交指南'),
    'resources.skill_desc':pick('Project preparation, confirmation, evaluation and personal API requirements.','项目准备、版本确认、评测和个人 API 使用要求。'),
    'resources.flow1_hint':pick('Download the example project, then read the interface instructions.','下载示例项目，并阅读接口说明。'),
    'resources.scenarios_note':pick('Only public scenario configuration is downloadable. Future weather and anomaly answers stay on the server.','仅提供场景公开配置，未来天气和异常答案保留在服务器。'),
    'resources.file_group_desc.weather':pick('Current weather arrives through the session. Future weather cannot be downloaded.','当前天气通过会话提供，未来天气不提供下载。'),
    'resources.cli':pick('Prepare your project','准备你的项目'),
    'faq.items.4.a':pick('Yes, and awards require agent (LLM-driven) techniques in at least two stages. Bring your own API and quota. In Participate, either save the key encrypted on the server (used only for evaluation and verification, deleted after the hidden final results are verified) or do not save it and keep that page open during evaluations. The hidden final runs with no page open: if your program calls a model, switch to saving the key before the online phase ends.','可以，评奖还要求至少两个环节采用智能体（大模型驱动）技术。请自备 API 和额度。可在「参赛」页选择将密钥加密保存在服务器上（只用于评测和核验，隐藏决赛成绩核实后删除），或不保存密钥、评测期间保持该页面打开。隐藏决赛评测时无人打开页面：程序会调用大模型的队伍，须在线上赛结束前改为「加密保存」。'),
    'faq.items.14.q':pick('Does the platform provide model credits?','平台提供模型额度吗？'),
    'faq.items.14.a':pick('No. Use your own model API and quota, set on the Participate page. Captains of teams that completed the practice round (at least one successful practice score) can claim a sponsor code, such as Kimi Coding Plan, on the dashboard.','不提供，请在「参赛」页设置自己的模型 API。跑通练习赛（至少获得一次成功评分）的队伍，由队长在控制台领取赞助兑换码（如 Kimi Coding Plan）。'),
    'faq.items.3.a':pick('Any language can use the JSONL interface. Submit a complete repository or ZIP; CSV uploads are not accepted.','任意语言都可使用 JSONL 接口，提交完整仓库或 ZIP，不接受 CSV。'),
    'faq.items.6.a':pick('Future weather, unreleased forecasts, hidden tags and future events stay private. Each round includes current observations and forecasts released so far.','未来天气、未发布的预报、隐藏标签与未来事件保密，每轮只提供当前观测和已发布预报。'),
    'faq.items.7.a':pick('10 batches per team per day, reset at 00:00 UTC; batches that fail because of the platform are not counted. Each batch covers all three formal scenarios; the online board shows your best complete batch.','每队每天 10 批，UTC 0 点重置，因平台原因失败的不计次数。每批覆盖全部三个正式场景，线上榜显示最高分的完整批次。'),
    'faq.items.16.a':pick('Use the project preview to check your interface. Review realized scores and reports to test anomaly detection.','使用项目预检检查接口，结合实际观测得分和上报记录检验异常识别。'),
  }
  for(const [path,value] of Object.entries(patches)) {
    const parts=path.split('.');let parent=result
    for(let i=0;i<parts.length-1;i++){const key=parts[i]!;parent=parent[key]??=(/^\d+$/.test(parts[i+1]??'')?[]:{})}
    parent[parts.at(-1)!]=value
  }
  return result
}
