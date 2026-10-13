/**
 * AOH benchmark task registry for the benchmark view (2026-10-12 trial). Numbers are organizer measurements:
 * v1 from the published final results (src/content/final/results.json), the new tasks from the multi-model
 * local validation of 2026-10-12 (mean over hidden seeds; agents written by coding agents on Kimi, Kimi K3, GLM-5).
 */
export interface BenchTask {
  id: string
  version: string
  set: 'v1' | 'new'
  en: string
  zh: string
  enDesc: string
  zhDesc: string
  cadenceEn: string
  cadenceZh: string
  /** official reference points (no rank) */
  baselines: { en: string; zh: string; score: number }[]
  /** organizer validation agents (not submissions) */
  validation?: { en: string; zh: string; score: number }[]
  kit?: string
}

export const KITS_BASE = 'https://s26-agents-8ebd56.vercel.app/newproblems/'

export const benchTasks: BenchTask[] = [
  {
    id: 'survey26', version: 'v1', set: 'v1',
    en: 'Wide-field spectroscopic survey operations', zh: '大视场光谱巡天运行',
    enDesc: 'Run a fibre-fed survey telescope for weeks: every 15 minutes choose where to point, which targets get the 16 fibres, how long to expose, when to wait, and when to report an instrument fault. Weather, faults and urgent requests arrive with uncertainty.',
    zhDesc: '连续几周运行一台光纤光谱巡天望远镜：每 15 分钟决定指向哪里、16 根光纤分给哪些目标、曝光多久、什么时候等待、什么时候上报设备故障。天气、故障和临时观测请求都带着不确定性到来。',
    cadenceEn: 'every 15 min, thousands of decisions', cadenceZh: '每 15 分钟一步，共几千步',
    baselines: [
      { en: 'Official planning example (Python)', zh: '官方规划示例（Python）', score: 27100.9 },
      { en: 'Official single-step example', zh: '官方单步示例', score: 24133.5 },
    ],
  },
  {
    id: 'nu_followup', version: 'v5', set: 'new',
    en: 'Neutrino multi-messenger follow-up', zh: '中微子多信使跟进',
    enDesc: 'One 1-m telescope, three nights, a decision every 10 minutes: find the fading optical counterparts of neutrino alerts and report them quickly and without false claims. Revised positions, retractions and debunked candidates arrive only as prose circulars in four languages.',
    zhDesc: '一台 1 米级望远镜、三个晚上、每 10 分钟一步：在中微子告警的误差圈里找出正在变暗的光学对应体，快而准地上报。修正位置、撤回和辟谣只出现在四种语言的文字通报里。',
    cadenceEn: 'every 10 min, 144 decisions', cadenceZh: '每 10 分钟一步，共 144 步',
    baselines: [{ en: 'Trivial', zh: '平凡基线', score: -191 }, { en: 'Reference', zh: '参考基线', score: 45 }],
    validation: [{ en: 'Kimi', zh: 'Kimi', score: 1352 }, { en: 'Kimi K3', zh: 'Kimi K3', score: 1653 }, { en: 'GLM-5', zh: 'GLM-5', score: 1733 }],
    kit: 'nu_followup_v5.zip',
  },
  {
    id: 'cr_array', version: 'v5', set: 'new',
    en: 'Cosmic-ray air-shower array operations', zh: '宇宙线簇射阵列运行',
    enDesc: 'A 36-station surface array for 7 days, a decision every hour: drop broken stations, veto thunderstorms, send the single repair crew, and switch to fast trigger for genuine target-of-opportunity requests hidden in a noisy multilingual channel.',
    zhDesc: '36 个探测站、7 天、每小时一步：剔除坏站、雷暴时暂停、派唯一的维修队，并在嘈杂的多语种频道里认出真正的目标机遇请求、及时切换快速触发。',
    cadenceEn: 'hourly, 168 decisions', cadenceZh: '每小时一步，共 168 步',
    baselines: [{ en: 'Trivial', zh: '平凡基线', score: 1212 }, { en: 'Reference', zh: '参考基线', score: 2927 }],
    validation: [{ en: 'Kimi', zh: 'Kimi', score: 4439 }, { en: 'Kimi K3', zh: 'Kimi K3', score: 4076 }, { en: 'GLM-5', zh: 'GLM-5', score: 4616 }],
    kit: 'cr_array_v5.zip',
  },
  {
    id: 'sn_burst', version: 'v4', set: 'new',
    en: 'Supernova neutrino burst early warning', zh: '超新星中微子爆发预警',
    enDesc: 'Duty officer of a four-detector alert network for 4 days, a decision every 15 minutes: catch the injected supernova bursts, alert fast with a direction, and never cry wolf at calibrations, noise storms, clock faults or pipeline tests.',
    zhDesc: '四台探测器组成的预警网络值班 4 天、每 15 分钟一步：发现注入的超新星爆发，快速报警并给出方向，同时不被刻度、噪声暴、时钟故障和管线测试骗到。',
    cadenceEn: 'every 15 min, 384 decisions', cadenceZh: '每 15 分钟一步，共 384 步',
    baselines: [{ en: 'Trivial', zh: '平凡基线', score: -2075 }, { en: 'Reference', zh: '参考基线', score: 1835 }],
    validation: [{ en: 'Kimi', zh: 'Kimi', score: 4381 }, { en: 'Kimi K3', zh: 'Kimi K3', score: 5155 }, { en: 'GLM-5', zh: 'GLM-5', score: 4952 }],
    kit: 'sn_burst_v4.zip',
  },
  {
    id: 'osc_run', version: 'v3', set: 'new',
    en: 'Reactor-neutrino oscillation experiment operations', zh: '振荡实验运行',
    enDesc: 'Run coordinator of a JUNO-like detector for 30 days, a decision every 6 hours: keep the energy scale calibrated, flag bad data, and catch reactor-off periods. The key clues are scattered through power-plant, slow-control, seismology and chat messages.',
    zhDesc: '类 JUNO 探测器运行 30 天、每 6 小时一步：保持能标刻度、标记坏数据、抓住反应堆停堆期。关键线索散落在电厂、慢控、地震台和闲聊消息里。',
    cadenceEn: 'every 6 h, 120 decisions', cadenceZh: '每 6 小时一步，共 120 步',
    baselines: [{ en: 'Trivial', zh: '平凡基线', score: -303 }, { en: 'Reference', zh: '参考基线', score: 686 }],
    validation: [{ en: 'Kimi', zh: 'Kimi', score: 960 }, { en: 'Kimi K3', zh: 'Kimi K3', score: 889 }, { en: 'GLM-5', zh: 'GLM-5', score: 915 }],
    kit: 'osc_run_v3.zip',
  },
]
