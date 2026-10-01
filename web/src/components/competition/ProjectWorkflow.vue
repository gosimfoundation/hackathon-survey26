<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { useAuth } from '../../stores/auth'
import { supabase } from '../../lib/supabase'
import { portal, uploadProjectFile, type PortalData, type ProjectRevision } from '../../lib/observerPortal'
import { usePersonalModel } from '../../composables/usePersonalModel'
import { DEFAULT_MODEL_KEY_MODE, relayMissesHiddenFinal, teamModelMode, type ModelKeyMode } from '../../lib/modelKeyMode'
import { competition } from '../../stores/competition'
import { canChooseFinal, canClearFinal, canWithdraw, countedEvaluations, finalRole, finalVersionFor, recentDuplicate, visibleProjects, withdrawnCount } from '../../lib/projectEvaluation'
import { canPrepareAgain, formatDailyReset, formatDateTime, revisionErrorText } from '../../lib/projectText'
const { pick, t, tf, locale } = useI18n()
const { team, refreshMe } = useAuth()
const personal=usePersonalModel()
const data = ref<PortalData | null>(null)
// Suggestions only: any public https:// address works (the server refuses IPs and internal names).
const personalBases=computed(()=>data.value?.model_bases.filter(base=>base.startsWith('https://'))??[])
const loading = ref(true), busy = ref(false), error = ref(''), notice = ref('')
// A completed request keeps its button disabled until the list shows its result,
// so a second click (or a failed refresh) cannot create a duplicate.
const locked = ref(new Set<string>()), showWithdrawn = ref(false), targetBatch = ref('')
// The action a click started, until its request and the refreshed list are back: its button reads "Working…".
const pending = ref('')
const form = ref({ title: '', kind: 'repository', url: '' })
const selectedFile = ref<File | null>(null), review = ref<ProjectRevision | null>(null)
/** 0–100 while a ZIP is uploading; null the rest of the time. */
const uploadPercent = ref<number | null>(null)
const reviewPanel = ref<HTMLElement | null>(null)
const phaseId = ref(''), confirmed = ref(false), notes = ref(''), codeUrl = ref('')
const diagnostics = ref<{ kind: string; status: string; code: string; log: string }[] | null>(null)
// Formal model calls use the team's choice: the relay to this open page (default;
// nothing is stored) or, as an explicit opt-in, a key saved encrypted on the
// server that is deleted automatically after the results are verified.
const modelMode = computed(() => teamModelMode(data.value?.team_model))
const savedModel = computed(() => data.value?.team_model?.saved ?? null)
const modeChoice = ref<ModelKeyMode>(DEFAULT_MODEL_KEY_MODE), replacingKey = ref(false)
// Collapsed by default; teams that use a model (saved key or a key connected in this tab) always see it open.
const modelOpen = ref(false)
const modelForm = ref({ base_url: '', model: '', key: '' })
const relayRunning = computed(() => modelMode.value === 'relay' && (data.value?.batches ?? []).some(b => ['queued', 'running'].includes(b.status)))
watch(modelMode, mode => { if (mode === 'stored') personal.clear() })
const when = (value: string | null | undefined) => formatDateTime(value, locale.value)
const sentences = (...parts: string[]) => parts.join(['zh', 'ja'].includes(locale.value) ? '' : ' ')
let timer: ReturnType<typeof setInterval> | undefined
const words = computed(() => pick({
  title: 'Agent projects', intro: 'Submit a complete project, test its interface, then confirm the exact version for evaluation.',
  diagnostics: 'Private run logs', diagnosticsHelp: 'Build and program output is visible only to your team and the organizers.', noLogs: 'No task logs yet.',
  localInfo: 'Local run instructions', runner: 'Download local runner', credential: 'Temporary run credential', copy: 'Copy credential',
  localCommand: 'Extract the runner, replace the project path, and run this command. Paste the credential at its hidden prompt.',
  expires: 'Credential expires', localSecret: 'This credential is only for this run. Do not commit it to a repository.',
  closed: 'Project evaluation is not open for the current competition.',
  step1: 'Step 1 · Upload a project', step1Note: 'Up to 10 uploads per day. Uploading does not use evaluations.',
  step2: 'Step 2 · Review and confirm a version', step2Note: 'Does not use evaluations. When preparation finishes, open the review, check the execution settings and adapter code, and confirm the version.',
  step3: 'Step 3 · Start an evaluation', step3Note: 'Each click uses one of today’s evaluations. One evaluation runs every scenario of this phase once; its score is the average of those scenarios. The leaderboard keeps your team’s best evaluation. Evaluations that fail because of the platform are not counted.',
  left: 'Evaluations left today', perDay: 'per day', dailyLimit: 'Daily evaluation limit', active: 'An evaluation is running. Start the next one when it finishes.',
  noneLeft: 'No evaluations left today.', noApproved: 'Confirm a version in step 2 first.', evaluated: 'Evaluated', times: '×', confirmedAt: 'Confirmed',
  evaluateAgain: 'Evaluate again', repeat: 'This version has already been evaluated. Evaluating it again uses one more of today’s evaluations', repeatLeft: 'left today', proceed: 'Continue?',
  withdraw: 'Withdraw', withdrawConfirm: 'Withdraw this version? It will be hidden and can no longer be confirmed or evaluated. The upload still counts toward today’s 10 uploads.',
  withdrawn: 'Version withdrawn.', withdrawnPill: 'Withdrawn', showWithdrawn: 'Show withdrawn versions', hideWithdrawn: 'Hide withdrawn versions',
  duplicate: 'You submitted the same project a few minutes ago. Submit it again? This uses one of today’s 10 uploads.',
  logs: 'Logs', refunded: 'Not counted toward the daily limit', noBatches: 'No evaluations yet.',
  prepareAgain: 'Prepare again', prepareAgainConfirm: 'Prepare this repository again from its current default branch? This uses one of today’s 10 uploads.',
  reuploadZip: 'Fix the project and upload the ZIP again (the uploaded ZIP is not kept for another attempt).',
  csv: 'Existing CSV submission', newProject: 'Submit a project', name: 'Project name', repository: 'Public GitHub repository',
  zip: 'Private ZIP upload', privacy: 'Public repositories remain public after forking. ZIP projects and detailed results are private to your team and the organizers.',
  file: 'Complete project ZIP · up to 50 MB', submit: 'Upload and prepare', projects: 'Your projects', empty: 'No projects yet.',
  refresh: 'Refresh', review: 'Review interface', explain: 'Adapter explanation', original: 'Original source fingerprint',
  manifest: 'Execution settings', changes: 'Added adapter files', unchanged: 'This project supplies its own interface; no adapter files were added.',
  check: 'I reviewed the execution settings and adapter code, and confirm this exact version.', approve: 'Confirm version',
  approveHint: 'Tick the self-check box above to enable the confirmation button.', fileSelected: 'Selected file',
  uploading: 'Uploading {n}%',
  testPassed: 'Public scenario test passed', testResult: 'Download public test result', projectDownload: 'Download this project version', phase: 'Evaluation phase', evaluate: 'Evaluate this version',
  batches: 'Evaluations', local: 'Start local CSV session', localHelp: 'Run locally with the same step-by-step information. Upload the resulting decisions.csv after the session.',
  download: 'Download private result', uploadCsv: 'Upload matching CSV', average: 'Combined score',
  api: 'Model APIs', apiHelp: 'The platform does not require model calls; awards require LLM-driven agent techniques in at least two stages. Team keys stay on the server. Set the model parameter to the call name below; OPENAI_BASE_URL and OPENAI_API_KEY are provided for each run. Each run and provider has separate limits.', callName: 'Model call name',
  shared: 'Organizer API', own: 'Team API', modelNames: 'Model names, separated by commas', endpoint: 'API endpoint', key: 'API key',
  apiName: 'API name', edit: 'Edit', limit: 'Daily token limit', saveKey: 'Save encrypted key', disable: 'Disable', enabled: 'Enabled', disabled: 'Disabled',
  evidence: 'Design award evidence', evidenceHelp: 'Describe the architecture and reproducible steps. This does not change performance scores.',
  codeUrl: 'Code or documentation URL (optional)', saveEvidence: 'Save evidence', notes: 'Architecture and reproduction notes',
  close: 'Close review', done: 'Saved.', prepared: 'Project queued for preparation. When it is ready, open the review in step 2 below.', confirmed: 'Version confirmed. Start it in step 3 below.',
  queued: 'Evaluation queued.', failed: 'This request could not be completed. Refresh and try again.', working: 'Working…',
  team: 'Join or create a team first.', phaseUnavailable: 'No evaluation phase is open.',
  final: 'Final version', finalIntro: 'After the online phase ends, the organizers evaluate your team’s final version once on a hidden scenario. Only that hidden score decides the final ranking; the online board does not.',
  finalDefault: 'If you do not choose, the version of your team’s best evaluation is used.', finalDeadline: 'You can change the choice until',
  finalLocked: 'The choice is locked. This version will be evaluated on the hidden scenario.', finalChosen: 'Chosen by your team', finalBest: 'Default: best evaluation',
  finalNone: 'No final version yet. Confirm a version and evaluate it, or choose one below.', finalSet: 'Set as final version', finalClear: 'Clear choice',
  finalClearConfirm: 'Clear your choice? The version of your best evaluation will be used instead.', finalSaved: 'Final version saved.', finalCleared: 'Choice cleared; the default applies.',
  finalBadge: 'Final version', finalScore: 'score',
  finalRelay: 'If your program calls a large model, switch the model API to “Save encrypted on the server” before the competition ends; otherwise model calls will fail in the hidden final evaluation.',
  apiFinalNote: 'Nobody keeps a page open during the hidden final evaluation: teams whose program calls a model must switch to “Save encrypted on the server” before the online phase ends.',
}, {
  title: '智能体项目', intro: '提交完整项目，测试接口后，确认用于评测的具体版本。',
  diagnostics: '运行日志', diagnosticsHelp: '编译和程序输出只供本队与主办方查看。', noLogs: '暂时没有任务日志。',
  localInfo: '本地运行信息', runner: '下载本地运行器', credential: '本次临时凭证', copy: '复制凭证',
  localCommand: '解压运行器后，替换项目路径并运行下面的命令，按提示粘贴凭证；凭证输入不会显示。',
  expires: '凭证到期时间', localSecret: '凭证只用于这次运行，请勿提交到仓库。',
  step1: '第1步 · 上传项目', step1Note: '每天最多 10 次，不占评测次数。',
  step2: '第2步 · 检查并确认版本', step2Note: '不占评测次数。准备完成后点“检查接口”，核对运行设置和适配代码，再确认版本。',
  step3: '第3步 · 开始评测', step3Note: '每点一次占当天 1 次；一次评测会把本赛程全部场景各跑一遍，分数是这些场景的平均分；排行榜取本队最高的一次；因平台原因失败的不计次数。',
  left: '今天还剩', perDay: '每天', dailyLimit: '每日评测上限', active: '本队有评测正在进行，结束后才能开始下一次。',
  noneLeft: '今天的评测次数已用完。', noApproved: '请先在第2步确认一个版本。', evaluated: '已评测', times: '次', confirmedAt: '确认于',
  evaluateAgain: '再评测一次', repeat: '这个版本已经评测过。再评测一次会再占用今天 1 次评测', repeatLeft: '今天还剩', proceed: '确定继续吗？',
  withdraw: '撤回', withdrawConfirm: '撤回这个版本？撤回后它会被隐藏，不能再确认或评测；已用的上传次数不退回。',
  withdrawn: '已撤回。', withdrawnPill: '已撤回', showWithdrawn: '显示已撤回的版本', hideWithdrawn: '隐藏已撤回的版本',
  duplicate: '几分钟前刚提交过相同的项目。确定再提交一次吗？这会占用今天 10 次上传中的 1 次。',
  logs: '日志', refunded: '未计入次数', noBatches: '还没有评测记录。',
  prepareAgain: '重新准备', prepareAgainConfirm: '用这个仓库当前的默认分支重新准备？这会占用今天 10 次上传中的 1 次。',
  reuploadZip: '请修正后重新上传 ZIP（已上传的 ZIP 不会保留用于重试）。',
  closed: '当前比赛尚未开放项目评测。', csv: '原有 CSV 提交', newProject: '提交项目',
  name: '项目名称', repository: '公开 GitHub 仓库', zip: '私有 ZIP 上传',
  privacy: '公开仓库 Fork 后仍然公开；ZIP 项目和详细结果只供本队与主办方查看。', file: '完整项目 ZIP · 最大 50 MB',
  submit: '上传并准备', projects: '我的项目', empty: '还没有项目。', refresh: '刷新', review: '检查接口', explain: '适配说明',
  original: '原始代码指纹', manifest: '运行设置', changes: '新增的适配文件', unchanged: '项目自带接口，没有新增适配文件。',
  check: '我已检查运行设置和适配代码，确认使用这个版本。', approve: '确认版本',
  approveHint: '先勾选上面的自查框，才能点确认版本。', fileSelected: '已选文件',
  uploading: '正在上传 {n}%', testPassed: '公开场景测试通过', testResult: '下载公开测试结果', projectDownload: '下载此版本项目',
  phase: '评测赛程', evaluate: '评测此版本', batches: '评测记录', local: '启动本地 CSV 会话',
  localHelp: '在本机运行，按步骤获得相同信息；运行结束后上传生成的 decisions.csv。', download: '下载私有结果',
  uploadCsv: '上传匹配的 CSV', average: '综合成绩', api: '模型 API', apiHelp: '平台不强制调用模型，但评奖要求至少两个环节采用大模型驱动的智能体技术。队伍密钥保存在服务器。model 参数使用下方调用名；每次运行会提供 OPENAI_BASE_URL 和 OPENAI_API_KEY。运行与接口均有独立额度。', callName: '模型调用名',
  shared: '主办方接口', own: '队伍接口', modelNames: '模型名称，用逗号分隔', endpoint: 'API 地址', key: 'API 密钥',
  apiName: '接口名称', edit: '修改', limit: '每天最多使用的 token 数', saveKey: '加密保存密钥', disable: '停用', enabled: '已启用', disabled: '已停用',
  evidence: '设计奖材料', evidenceHelp: '说明项目架构和复现步骤；这里不影响实际成绩。', codeUrl: '代码或文档链接（选填）',
  saveEvidence: '保存材料', notes: '架构和复现说明', close: '关闭检查', done: '已保存。', prepared: '项目已排队，等待准备。准备好后请到下方第2步点“检查接口”。',
  confirmed: '已确认版本。请到下方第3步开始评测。', queued: '已加入评测队列。', failed: '操作未完成，请刷新后重试。', working: '处理中…',
  team: '请先加入或创建队伍。', phaseUnavailable: '当前没有开放的评测赛程。',
  final: '最终版本', finalIntro: '线上赛结束后，主办方会在一个隐藏场景上对每队的最终版本评测一次。最终排名只看这个隐藏场景的成绩，线上榜不决定最终排名。',
  finalDefault: '如果不选择，默认使用本队最高分那次评测的版本。', finalDeadline: '可修改至',
  finalLocked: '选择已锁定，将用这个版本参加隐藏场景评测。', finalChosen: '本队已选择', finalBest: '默认：最高分评测',
  finalNone: '还没有最终版本。请先确认并评测一个版本，或在下方选择。', finalSet: '设为最终版本', finalClear: '取消选择',
  finalClearConfirm: '取消选择？将改用本队最高分评测的版本。', finalSaved: '已保存最终版本。', finalCleared: '已取消选择，恢复默认。',
  finalBadge: '最终版本', finalScore: '分数',
  finalRelay: '如果你的程序会调用大模型，请在比赛结束前把模型 API 改为『加密保存』，否则最终隐藏场景评测时模型调用会失败。',
  apiFinalNote: '最终隐藏场景评测时不会有人打开本页面：程序会调用大模型的队伍，请在线上赛结束前改为『加密保存』。',
}))
const activePhases = computed(() => (data.value?.phases ?? []).filter(p => (p.phase_id===competition.phaseId||p.phase_id===competition.betaPhaseId||p.phase_id===competition.projectPhaseId) && p.phases.is_active &&
  (!p.phases.ends_at || Date.parse(p.phases.ends_at) > Date.now())))
const projectsOpen = computed(() => activePhases.value.some(p => p.projects_enabled))
const openPhases = computed(() => activePhases.value.filter(p => !p.phases.starts_at || Date.parse(p.phases.starts_at) <= Date.now()))
const selectedPhase = computed(() => openPhases.value.find(p => p.phase_id === phaseId.value))
const quota = computed(() => data.value?.quota?.find(q => q.phase_id === phaseId.value) ?? null)
// Shown even before the quota RPC answers: the phase setting is the same number the database enforces.
const dailyLimit = computed(() => quota.value?.daily_batches ?? selectedPhase.value?.daily_batches ?? null)
const activeBatch = computed(() => (data.value?.batches ?? []).some(b => ['queued', 'running'].includes(b.status)))
const shownProjects = computed(() => visibleProjects(data.value?.projects, showWithdrawn.value))
const hiddenCount = computed(() => withdrawnCount(data.value?.projects))
const approvedVersions = computed(() => (data.value?.projects ?? []).flatMap(p => p.observer_revisions
  .filter(r => r.status === 'approved' && !r.archived_at)
  .map(r => ({ title: p.title, revision: r, evaluated: countedEvaluations(data.value?.batches, r.id, phaseId.value) }))))
// After the phase closes no phase is selected; the competition's own phase still owns the choice.
const finalVersion = computed(() => finalVersionFor(data.value?.final_versions, phaseId.value || (competition.betaPhaseId ?? competition.phaseId ?? '')))
// Every confirmed version can be chosen, also after the phase stopped taking evaluations.
const finalCandidates = computed(() => (data.value?.projects ?? []).flatMap(p => p.observer_revisions
  .filter(r => r.status === 'approved' && !r.archived_at).map(r => ({ title: p.title, revision: r }))))
const titles = computed(() => new Map((data.value?.projects ?? []).flatMap(p => p.observer_revisions.map(r => [r.id, p.title] as const))))
const phaseName = (id: string) => { const p = data.value?.phases.find(x => x.phase_id === id)?.phases; return p ? pick(p.name_en, p.name_zh) : '' }
// Team-key runs have no practical token cap (1,000,000,000 or more is shown as uncapped).
const TOKENS_UNCAPPED = 1_000_000_000
const relayFinalRisk = computed(() => relayMissesHiddenFinal(modelMode.value, !!finalVersion.value || competition.mode === 'competition'))
const modelLimits = computed(() => {
  const p = activePhases.value[0]
  if (!p || !(p.model_call_limit > 0)) return null
  const params = { calls: p.model_call_limit.toLocaleString(), tokens: p.model_token_limit.toLocaleString(), concurrency: p.model_concurrency ?? 1 }
  return { key: p.model_token_limit >= TOKENS_UNCAPPED ? 'submit.model_api.limits' : 'submit.model_api.limits_tokens', params }
})
const statuses = computed(() => pick<Record<string, string>>({ queued:'Queued', preparing:'Preparing', reviewable:'Ready for review', approved:'Confirmed',
  failed:'Failed', starting:'Starting', ready:'Ready', running:'Running', awaiting_csv:'Waiting for CSV', scored:'Scored', cancelled:'Cancelled' },
  { queued:'排队中', preparing:'准备中', reviewable:'等待确认', approved:'已确认', failed:'失败', starting:'启动中', ready:'已就绪',
    running:'运行中', awaiting_csv:'等待 CSV', scored:'已评分', cancelled:'已取消' }))
function errorMessage(e: unknown) {
  const code = e instanceof Error ? e.message : ''
  const messages: Record<string, string> = {
    stale_approval: pick('The version changed. Reopen the review before confirming.', '版本已变化，请重新打开并检查。'),
    csv_does_not_match_session: pick('This CSV differs from the server-recorded decisions.', '这个 CSV 与服务器记录的决策不一致。'),
    batch_already_active: pick('Your team already has an active evaluation.', '本队已有正在进行的评测。'),
    preparation_limit: pick('Your team already has three projects being prepared.', '本队已有三个项目正在准备，请等待完成。'),
    preparation_daily_limit: pick('Your team has used today’s ten project preparations.', '本队今天的十次项目准备机会已用完。'),
    local_session_not_ready: pick('The local engine is not ready yet, or the run has ended. Refresh its status.', '本地会话尚未启动或已经结束，请刷新查看状态。'),
    daily_limit: pick('The daily evaluation limit has been reached.', '今天的评测次数已用完。'),
    revision_already_evaluated: pick('This version has already been evaluated.', '这个版本已经评测过。'),
    revision_withdrawn: pick('This version was withdrawn.', '这个版本已撤回。'),
    revision_not_withdrawable: pick('Only versions that are not being prepared and were never evaluated can be withdrawn.', '只能撤回未在准备中、也从未评测过的版本。'),
    wrong_file_type: pick('Choose a file with the required extension.', '请选择要求的文件类型。'),
    file_too_large: pick('The file is empty or exceeds the size limit.', '文件为空或超过大小限制。'),
    invalid_repository_url: pick('Enter a public https://github.com/owner/repository URL.', '请输入公开 GitHub 仓库的完整地址。'),
    model_destination_not_enabled: t('submit.model_api.endpoint_refused'),
    invalid_team_model: t('submit.model_api.invalid'),
    final_version_locked: pick('The online phase has ended; the final version can no longer change.', '线上赛已结束，最终版本不能再修改。'),
    revision_not_approved: pick('Only a confirmed version can be chosen.', '只能选择已确认的版本。'),
  }
  return code === 'cancelled' ? '' : messages[code] ?? words.value.failed
}
// Scenario names for the runs of each evaluation. Only listed scenarios are readable; others stay unnamed.
const scenarioNames = ref<Record<string, { slug: string; name: string }>>({})
async function loadScenarioNames() {
  const ids = [...new Set((data.value?.batches ?? []).flatMap(b => b.observer_runs.map(run => run.scenario_id)))]
    .filter(id => id && !(id in scenarioNames.value))
  if (!ids.length) return
  const { data: rows } = await supabase.from('scenarios').select('id,slug,name').in('id', ids)
  scenarioNames.value = { ...scenarioNames.value, ...Object.fromEntries((rows ?? []).map(row => [row.id, { slug: row.slug, name: row.name }])) }
}
async function reload() {
  data.value = await portal<PortalData>('list')
  void loadScenarioNames().catch(() => {})
  locked.value = new Set()
  modeChoice.value = modelMode.value
  if (!modelOpen.value && (savedModel.value || personal.everConfigured.value)) modelOpen.value = true
  await personal.refresh()
  // Bind evaluations to the entry phase (beta entry first), never to whatever
  // order the database happened to return.
  const preferred=competition.betaPhaseId??competition.projectPhaseId??competition.phaseId
  if (!openPhases.value.some(p => p.phase_id === phaseId.value)) phaseId.value = openPhases.value.find(p => p.phase_id===preferred)?.phase_id ?? openPhases.value[0]?.phase_id ?? ''
}
async function action(work: () => Promise<void>, success = words.value.done, key = '') {
  if (busy.value || (key && locked.value.has(key))) return
  busy.value = true; pending.value = key; error.value = ''; notice.value = ''
  try { await work() } catch (e) { error.value = errorMessage(e); busy.value = false; pending.value = ''; return }
  // The request succeeded even if the refresh below fails; never invite a retry.
  if (key) locked.value.add(key)
  notice.value = success
  try { await reload() } catch { /* the periodic refresh retries and unlocks */ } finally { busy.value = false; pending.value = '' }
}
function submit() {
  const url = form.value.kind === 'repository' ? form.value.url : null
  if (recentDuplicate(data.value?.projects, form.value.title, url) && !window.confirm(words.value.duplicate)) return
  void action(async () => {
    if (url !== null) await portal('submit_repository', { title: form.value.title, url })
    else {
      if (!selectedFile.value) throw new Error('wrong_file_type')
      uploadPercent.value = 0
      let upload_id: string
      try { upload_id = await uploadProjectFile(selectedFile.value, 'source', p => { uploadPercent.value = p }) }
      finally { uploadPercent.value = null }
      await portal('submit_zip', { title: form.value.title, upload_id })
    }
    form.value = { title: '', kind: form.value.kind, url: '' }; selectedFile.value = null
    const file = document.querySelector<HTMLInputElement>('[data-testid="project-zip"]'); if (file) file.value = ''
  }, words.value.prepared, 'submit').then(() => {
    // Point at step 2 after a successful upload; on failure the error banner stays in view instead.
    if (!error.value) document.querySelector('[data-testid="project-versions"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}
// Resubmits the same public repository through the ordinary upload action (a new revision).
function prepareAgain(title: string, r: ProjectRevision) {
  if (!window.confirm(words.value.prepareAgainConfirm)) return
  void action(async () => { await portal('submit_repository', { title, url: r.source_location }) }, words.value.prepared, 'again:' + r.id)
}
function openReview(r: ProjectRevision) {
  review.value = r; confirmed.value = false; notes.value = r.observer_evidence?.notes ?? ''; codeUrl.value = r.observer_evidence?.code_url ?? ''
  void nextTick(() => reviewPanel.value?.focus())
}
function approve() { if (review.value && confirmed.value) { const id = review.value.id; void action(async () => {
  await portal('approve', { revision_id: id, digest: review.value!.approval_digest }); review.value = null
}, words.value.confirmed, 'approve:' + id).then(() => {
  if (!error.value) document.querySelector('[data-testid="project-evaluate"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}) } }
const repeatQuestion = () => sentences(words.value.repeat + (quota.value ? pick(` (${quota.value.remaining} ${words.value.repeatLeft}).`, `（${words.value.repeatLeft} ${quota.value.remaining} 次）。`) : pick('.', '。')), words.value.proceed)
function evaluate(revision_id: string) {
  const phase_id = phaseId.value
  // The server also refuses an unconfirmed repeat (the list may be incomplete); ask then.
  let repeat = countedEvaluations(data.value?.batches, revision_id, phase_id) > 0
  if (repeat && !window.confirm(repeatQuestion())) return
  void action(async () => {
    try { await portal('evaluate', { phase_id, revision_id, ...(repeat ? { confirm_repeat: true } : {}) }) }
    catch (e) {
      if (repeat || !(e instanceof Error) || e.message !== 'revision_already_evaluated') throw e
      if (!window.confirm(repeatQuestion())) throw new Error('cancelled')
      repeat = true
      await portal('evaluate', { phase_id, revision_id, confirm_repeat: true })
    }
  }, words.value.queued, 'evaluate:' + revision_id)
}
function setFinal(revision_id: string | null) {
  const final = finalVersion.value
  if (!final || (revision_id === null && !window.confirm(words.value.finalClearConfirm))) return
  void action(async () => { await portal('set_final_version', { phase_id: final.phase_id, revision_id }) },
    revision_id ? words.value.finalSaved : words.value.finalCleared, 'final:' + (revision_id ?? 'clear'))
}
function withdraw(revision_id: string) {
  if (!window.confirm(words.value.withdrawConfirm)) return
  void action(async () => { await portal('withdraw', { revision_id }); if (review.value?.id === revision_id) review.value = null },
    words.value.withdrawn, 'withdraw:' + revision_id)
}
function showLogs(fields: Record<string, string>) { void action(async () => { diagnostics.value = await portal('diagnostics', fields) }) }
function chooseMode() {
  const mode = modeChoice.value, hadKey = !!savedModel.value
  if (mode === modelMode.value) return
  // Choosing the relay deletes a saved key on the server immediately.
  void action(async () => {
    try { await portal('set_team_model_mode', { mode }) } catch (e) { modeChoice.value = modelMode.value; throw e }
    replacingKey.value = false
  }, mode === 'relay' ? sentences(t('submit.model_api.relay_selected'), ...(hadKey ? [t('submit.model_api.deleted_notice')] : []))
    : t('submit.model_api.stored_selected'))
}
function saveModel() { void action(async () => {
  try { await portal('save_team_model', { ...modelForm.value }) } finally { modelForm.value.key = '' }
  replacingKey.value = false
}, t('submit.model_api.saved_notice')) }
function deleteModel() { void action(async () => { await portal('delete_team_model') }, t('submit.model_api.deleted_notice')) }
function download(run_id: string) { downloadFile('download_result', { run_id }, 'observer-result.zip') }
function downloadProject(revision_id: string) { downloadFile('download_project', { revision_id }, 'observer-project.zip') }
function downloadFile(command: string, fields: Record<string, unknown>, filename: string) { void action(async () => {
  const result = await portal<{ url: string }>(command, fields)
  const url = new URL(result.url)
  if (url.protocol !== 'https:' && url.hostname !== '127.0.0.1') throw new Error('invalid_download')
  const anchor = document.createElement('a'); anchor.href = url.href; anchor.rel = 'noreferrer'; anchor.download = filename; anchor.click()
}) }
onMounted(async () => {
  await refreshMe()
  try { if (team.value) await reload() } catch (e) { error.value = errorMessage(e) }
  finally { loading.value = false }
  // Links from the records page point at one evaluation; show it once it is loaded.
  if (location.hash.startsWith('#batch-')) {
    targetBatch.value = location.hash.slice(7)
    void nextTick(() => document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: 'center' }))
  }
  timer = setInterval(() => { if (!busy.value && team.value && !document.hidden) void reload().catch(() => {}) }, 15000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <section data-testid="project-workflow">
    <p class="text2 mb-5">{{ words.intro }}</p>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="!team" class="panel">{{ words.team }} <router-link to="/team">{{ t('nav.team') }}</router-link></p>
    <template v-else>
      <p v-if="error" class="errors" role="alert" data-testid="project-error">{{ error }}</p>
      <p v-if="notice" role="status" class="mb-4">{{ notice }}</p>
      <p v-if="!projectsOpen" class="panel">{{ words.closed }}</p>
      <details class="panel mb-6 model-api" data-testid="model-api-settings" :open="modelOpen" @toggle="modelOpen = ($event.target as HTMLDetailsElement).open">
        <summary class="model-api-summary" data-testid="model-api-toggle">
          <span id="model-api" class="model-api-title" role="heading" aria-level="2">{{ t('submit.model_api.title') }}</span>
          <span class="help model-api-hint" data-testid="model-api-hint">{{ t('submit.model_api.collapsed_hint') }}</span>
        </summary>
        <div class="model-api-body">
        <p class="help mt-3">{{ t('submit.model_api.intro') }}</p>
        <p class="help" data-testid="model-mode-tradeoff">{{ t('submit.model_api.tradeoff') }}</p>
        <p v-if="relayFinalRisk" class="errors" role="note" data-testid="model-mode-final-note">{{ words.apiFinalNote }}</p>
        <fieldset class="mt-4" :disabled="busy">
          <legend class="sr-only">{{ t('submit.model_api.choice') }}</legend>
          <label class="check"><input v-model="modeChoice" type="radio" name="model-key-mode" value="relay" aria-describedby="model-mode-relay-help" data-testid="model-mode-relay" @change="chooseMode">{{ t('submit.model_api.relay') }}</label>
          <p id="model-mode-relay-help" class="help mb-3">{{ savedModel ? sentences(t('submit.model_api.relay_help'), t('submit.model_api.relay_deletes')) : t('submit.model_api.relay_help') }}</p>
          <label class="check"><input v-model="modeChoice" type="radio" name="model-key-mode" value="stored" aria-describedby="model-mode-stored-help" data-testid="model-mode-stored" @change="chooseMode">{{ t('submit.model_api.stored') }}</label>
          <p id="model-mode-stored-help" class="help">{{ t('submit.model_api.stored_help') }}</p>
        </fieldset>
        <p class="help mt-4">{{ t('submit.model_api.usage') }}</p>
        <!-- The form follows the choice at once; a refused change resets the choice (chooseMode). -->
        <template v-if="modeChoice === 'stored'">
          <p v-if="modelLimits" class="help">{{ tf(modelLimits.key, modelLimits.params) }}</p>
          <div v-if="savedModel && !replacingKey" class="mt-4" data-testid="team-model-saved">
            <h3>{{ t('submit.model_api.saved_title') }}</h3>
            <p class="help break-all">{{ savedModel.base_url }} · {{ savedModel.model }}</p>
            <p class="help" data-testid="team-model-hint">{{ savedModel.key_hint ? tf('submit.model_api.key_ending', { hint: savedModel.key_hint }) : t('submit.model_api.key_hidden') }} · {{ tf('submit.model_api.saved_at', { time: when(savedModel.saved_at) }) }}</p>
            <div class="flex flex-wrap gap-3 mt-3">
              <button type="button" class="btn sm" :disabled="busy" @click="replacingKey = true">{{ t('submit.model_api.replace') }}</button>
              <button type="button" class="btn sm" :disabled="busy" @click="deleteModel">{{ t('submit.model_api.delete') }}</button>
            </div>
          </div>
          <form v-else class="mt-4" data-testid="team-model-form" autocomplete="off" @submit.prevent="saveModel">
            <p v-if="!savedModel" class="help">{{ t('submit.model_api.none') }}</p>
            <label class="field"><span>{{ t('submit.model_api.endpoint') }}</span><input v-model="modelForm.base_url" type="url" name="observer-model-endpoint" required pattern="https://.+" maxlength="1000" list="model-base-suggestions" placeholder="https://api.moonshot.cn/v1" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" spellcheck="false" aria-describedby="team-model-endpoint-help" data-testid="team-model-endpoint"></label>
            <p id="team-model-endpoint-help" class="help">{{ t('submit.model_api.endpoint_hint') }}</p>
            <label class="field"><span>{{ t('submit.model_api.model') }}</span><input v-model="modelForm.model" type="text" name="observer-model-name" maxlength="256" required autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" spellcheck="false" data-testid="team-model-name"></label>
            <label class="field"><span>{{ t('submit.model_api.key') }}</span><input v-model="modelForm.key" type="password" name="observer-model-secret" autocomplete="new-password" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" maxlength="8192" required data-testid="team-model-key"></label>
            <div class="flex flex-wrap gap-3">
              <button class="btn sm" :disabled="busy">{{ t('submit.model_api.save') }}</button>
              <button v-if="savedModel" type="button" class="btn sm" :disabled="busy" @click="replacingKey = false; modelForm.key = ''">{{ t('submit.model_api.cancel') }}</button>
            </div>
          </form>
        </template>
        <form v-else class="mt-4" data-testid="personal-model-settings" autocomplete="off" @submit.prevent="action(personal.connect)">
          <p v-if="relayRunning && !personal.connected.value && personal.everConfigured.value" class="errors" role="alert">{{ t('submit.model_api.relay_running') }}</p>
          <p class="help">{{ t('submit.model_api.keep_open') }}</p>
          <label class="field"><span>{{ t('submit.model_api.endpoint') }}</span><input v-model="personal.endpoint.value" type="url" name="observer-relay-endpoint" :disabled="personal.connected.value" required pattern="https://.+" maxlength="1000" list="model-base-suggestions" placeholder="https://api.moonshot.cn/v1" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" spellcheck="false" aria-describedby="personal-model-endpoint-help" data-testid="personal-model-endpoint"></label>
          <p id="personal-model-endpoint-help" class="help">{{ t('submit.model_api.endpoint_hint') }}</p>
          <label class="field"><span>{{ t('submit.model_api.model') }}</span><input v-model="personal.model.value" type="text" name="observer-relay-model" :disabled="personal.connected.value" maxlength="256" required autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" spellcheck="false" data-testid="personal-model-name"></label>
          <label class="field"><span>{{ t('submit.model_api.key') }}</span><input v-model="personal.key.value" type="password" name="observer-relay-secret" autocomplete="new-password" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" :disabled="personal.connected.value" maxlength="8192" required data-testid="personal-api-key"></label>
          <button v-if="!personal.connected.value" class="btn sm" :disabled="busy">{{ t('submit.model_api.connect') }}</button>
          <button v-else type="button" class="btn sm" @click="personal.clear">{{ t('submit.model_api.disconnect') }}</button>
          <p v-if="personal.connected.value" class="help mt-3" role="status">{{ personal.status.value==='failed'?t('submit.model_api.call_failed'):personal.status.value==='working'?t('submit.model_api.working'):t('submit.model_api.connected') }}</p>
        </form>
        <datalist id="model-base-suggestions"><option v-for="base in personalBases" :key="base" :value="base"></option></datalist>
        </div>
      </details>
      <p class="mb-5"><button type="button" class="btn sm" :disabled="busy" @click="action(reload)">{{ words.refresh }}</button></p>
      <form v-if="projectsOpen" class="panel mb-6" @submit.prevent="submit">
        <h2 id="prepare">{{ words.step1 }}</h2><p class="help mb-4">{{ words.step1Note }}</p>
        <label class="field"><span>{{ words.name }}</span><input v-model="form.title" type="text" name="project-title" required maxlength="100" :placeholder="pick('e.g. my-agent v1','例如：my-agent v1')" autocomplete="off" data-testid="project-title"></label>
        <label class="check"><input v-model="form.kind" type="radio" value="repository">{{ words.repository }}</label>
        <label class="check"><input v-model="form.kind" type="radio" value="zip">{{ words.zip }}</label>
        <label v-if="form.kind === 'repository'" class="field"><span>{{ words.repository }}</span><input v-model="form.url" type="url" required placeholder="https://github.com/owner/project" data-testid="project-url"></label>
        <label v-else class="field border border-dashed border-border-subtle p-5"><span>{{ words.file }}</span><input type="file" accept=".zip,application/zip" required data-testid="project-zip" @change="selectedFile = ($event.target as HTMLInputElement).files?.[0] ?? null"></label>
        <p v-if="form.kind === 'zip' && selectedFile" class="help mt-2" data-testid="project-zip-selected">{{ words.fileSelected }}: {{ selectedFile.name }} · {{ (selectedFile.size / 1048576).toFixed(1) }} MB</p>
        <p v-if="uploadPercent != null" class="help mt-2" role="status" data-testid="project-upload-progress">
          {{ words.uploading.replace('{n}', String(uploadPercent)) }}
          <progress class="upload-progress" :value="uploadPercent" max="100"></progress>
        </p>
        <p class="help mb-4">{{ words.privacy }}</p>
        <button class="btn primary" :disabled="busy || locked.has('submit')" data-testid="project-submit">{{ busy ? words.working : words.submit }}</button>
      </form>
      <section class="panel mb-6" data-testid="project-versions">
        <h2 id="review">{{ words.step2 }}</h2><p class="help">{{ words.step2Note }}</p>
        <p v-if="!shownProjects.length" class="text3 mt-3">{{ words.empty }}</p>
        <article v-for="p in shownProjects" :key="p.id" class="project-row">
          <h3>{{ p.title }}</h3>
          <div v-for="r in p.observer_revisions" :key="r.id" class="flex flex-wrap items-center gap-3 mt-3" :data-revision-id="r.id">
            <span class="pill">{{ r.archived_at ? words.withdrawnPill : statuses[r.status] ?? r.status }}</span>
            <span v-if="finalRole(finalVersion, r.id)" class="pill ok" data-testid="final-version-badge">{{ words.finalBadge }}</span>
            <span class="meta">{{ when(r.created_at) }}</span>
            <span v-if="r.error && !r.archived_at" class="errors" role="status" data-testid="revision-error">{{ revisionErrorText(r.error, locale) }}<template v-if="r.status === 'failed' && r.source_kind === 'zip'"> {{ words.reuploadZip }}</template></span>
            <button v-if="canPrepareAgain(r) && projectsOpen" type="button" class="btn sm" :disabled="busy || locked.has('again:'+r.id)" data-testid="project-prepare-again" @click="prepareAgain(p.title, r)">{{ words.prepareAgain }}</button>
            <button v-if="!r.archived_at && (['reviewable','approved'].includes(r.status) || (r.status === 'failed' && r.manifest))" type="button" class="btn sm" :class="{ primary: r.status === 'reviewable' }" @click="openReview(r)">{{ words.review }}</button>
            <button v-if="canWithdraw(r, data?.batches) && !(data?.final_versions ?? []).some(f => f.chosen_revision_id === r.id)" type="button" class="btn sm" :disabled="busy || locked.has('withdraw:'+r.id)" data-testid="project-withdraw" :aria-busy="pending === 'withdraw:'+r.id" @click="withdraw(r.id)">{{ pending === 'withdraw:'+r.id ? words.working : words.withdraw }}</button>
            <button type="button" class="log-link" :disabled="busy" @click="showLogs({ revision_id: r.id })">{{ words.logs }}</button>
          </div>
        </article>
        <button v-if="hiddenCount" type="button" class="log-link mt-4" @click="showWithdrawn = !showWithdrawn">{{ showWithdrawn ? words.hideWithdrawn : words.showWithdrawn + ' (' + hiddenCount + ')' }}</button>
      </section>
      <section v-if="review" ref="reviewPanel" tabindex="-1" class="panel mb-6" data-testid="project-review" aria-live="polite">
        <h2>{{ words.review }}</h2><p v-if="review.public_test.passed" class="pill ok mt-3">{{ words.testPassed }}</p>
        <p v-else-if="review.error" class="errors mt-3">{{ revisionErrorText(review.error, locale) }}</p>
        <div class="flex flex-wrap gap-3 mt-3">
          <button class="btn sm" :disabled="busy" @click="downloadProject(review.id)">{{ words.projectDownload }}</button>
          <button v-if="review.public_test.passed && review.public_test.run_id" class="btn sm" :disabled="busy" @click="download(review.public_test.run_id!)">{{ words.testResult }}</button>
        </div>
        <p class="mt-4">{{ words.explain }}: {{ review.explanation }}</p>
        <p class="help break-all">{{ words.original }}: {{ review.source_digest }}</p>
        <h3 class="mt-5">{{ words.manifest }}</h3><pre>{{ JSON.stringify(review.manifest, null, 2) }}</pre>
        <h3 class="mt-5">{{ words.changes }}</h3><p v-if="!Object.keys(review.adapter_files).length" class="help">{{ words.unchanged }}</p>
        <div v-for="(code, path) in review.adapter_files" :key="path"><h4 class="break-all">{{ path }}</h4><pre>{{ code }}</pre></div>
        <template v-if="review.status === 'reviewable' && !review.archived_at"><label class="check mt-4"><input v-model="confirmed" type="checkbox" data-testid="project-confirm">{{ words.check }}</label>
          <p v-if="!confirmed" class="help mt-2" data-testid="project-approve-hint">{{ words.approveHint }}</p>
          <button class="btn primary mt-3" :disabled="busy || !confirmed || !review.public_test.passed || locked.has('approve:'+review.id)" data-testid="project-approve" @click="approve">{{ words.approve }}</button></template>
        <form class="mt-6" @submit.prevent="action(async () => { await portal('evidence', { revision_id: review!.id, notes, code_url: codeUrl }) })">
          <h3>{{ words.evidence }}</h3><p class="help">{{ words.evidenceHelp }}</p>
          <label class="field"><span>{{ words.notes }}</span><textarea v-model="notes" maxlength="8000" rows="5"></textarea></label>
          <label class="field"><span>{{ words.codeUrl }}</span><input v-model="codeUrl" type="url" maxlength="1000"></label>
          <button class="btn sm" :disabled="busy">{{ words.saveEvidence }}</button>
        </form><button class="btn sm mt-4" @click="review = null">{{ words.close }}</button>
      </section>
      <section class="panel mb-6" data-testid="project-evaluate">
        <h2 id="evaluate">{{ words.step3 }}</h2><p class="help">{{ words.step3Note }}</p>
        <p v-if="!openPhases.length" class="help">{{ words.phaseUnavailable }}</p>
        <template v-else>
          <p class="mt-4" data-testid="evaluation-quota">{{ selectedPhase ? pick(selectedPhase.phases.name_en, selectedPhase.phases.name_zh) : '' }}<template v-if="dailyLimit != null">
            · <strong data-testid="evaluation-daily-limit">{{ pick(`${words.dailyLimit}: ${dailyLimit}`, `${words.dailyLimit} ${dailyLimit} 次`) }}</strong></template><template v-if="quota">
            · <strong>{{ pick(`${words.left}: ${quota.remaining}`, `${words.left} ${quota.remaining} 次`) }}</strong></template>
            <span v-if="dailyLimit != null" class="help" data-testid="evaluation-reset"> ({{ formatDailyReset(quota?.resets_at, locale) }})</span></p>
          <p v-if="quota && quota.remaining <= 0" class="help">{{ words.noneLeft }}</p>
          <p v-else-if="activeBatch" class="help">{{ words.active }}</p>
          <p v-if="!approvedVersions.length" class="text3 mt-3">{{ words.noApproved }}</p>
          <div v-for="v in approvedVersions" :key="v.revision.id" class="flex flex-wrap items-center gap-3 mt-3" :data-revision-id="v.revision.id">
            <span>{{ v.title }}</span>
            <span v-if="finalRole(finalVersion, v.revision.id)" class="pill ok">{{ words.finalBadge }}</span>
            <span v-if="v.revision.approved_at" class="meta">{{ words.confirmedAt }} {{ when(v.revision.approved_at) }}</span>
            <span v-if="v.evaluated" class="meta">{{ pick(`${words.evaluated} ${v.evaluated}${words.times}`, `${words.evaluated} ${v.evaluated} ${words.times}`) }}</span>
            <button type="button" class="btn primary sm" :disabled="busy || locked.has('evaluate:'+v.revision.id) || !selectedPhase?.projects_enabled || activeBatch || (quota != null && quota.remaining <= 0)" data-testid="project-evaluate-button" :aria-busy="pending === 'evaluate:'+v.revision.id" @click="evaluate(v.revision.id)">{{ pending === 'evaluate:'+v.revision.id ? words.working : v.evaluated ? words.evaluateAgain : words.evaluate }}</button>
          </div>
        </template>
      </section>
      <section v-if="finalVersion" class="panel mb-6" data-testid="final-version">
        <h2 id="final">{{ words.final }}</h2>
        <p class="help">{{ words.finalIntro }}</p>
        <p class="help">{{ words.finalDefault }}<template v-if="finalVersion.deadline && !finalVersion.locked"> {{ words.finalDeadline }} {{ when(finalVersion.deadline) }}.</template></p>
        <p v-if="relayFinalRisk" class="errors mt-3" role="note" data-testid="final-version-relay-warning">{{ words.finalRelay }} <a href="#model-api">{{ t('submit.model_api.title') }}</a></p>
        <p v-if="finalVersion.locked" class="mt-3" role="status" data-testid="final-version-locked">{{ words.finalLocked }}</p>
        <p v-if="!finalVersion.revision_id" class="text3 mt-3">{{ words.finalNone }}</p>
        <p v-else class="mt-3 flex flex-wrap items-center gap-3" data-testid="final-version-current">
          <strong>{{ titles.get(finalVersion.revision_id) ?? finalVersion.revision_id }}</strong>
          <span class="pill ok">{{ finalVersion.source === 'chosen' ? words.finalChosen : words.finalBest }}</span>
          <span v-if="finalVersion.chosen_at && finalVersion.source === 'chosen'" class="meta">{{ when(finalVersion.chosen_at) }}</span>
          <span v-else-if="finalVersion.best_score != null" class="meta">{{ words.finalScore }} {{ finalVersion.best_score.toFixed(2) }}</span>
          <button v-if="canClearFinal(finalVersion)" type="button" class="btn sm" :disabled="busy || locked.has('final:clear')" data-testid="final-version-clear" @click="setFinal(null)">{{ words.finalClear }}</button>
        </p>
        <div v-for="v in finalCandidates" :key="v.revision.id" class="flex flex-wrap items-center gap-3 mt-3" :data-final-revision-id="v.revision.id">
          <span>{{ v.title }}</span>
          <span v-if="v.revision.approved_at" class="meta">{{ words.confirmedAt }} {{ when(v.revision.approved_at) }}</span>
          <span v-if="finalRole(finalVersion, v.revision.id)" class="pill ok">{{ words.finalBadge }}</span>
          <button v-if="canChooseFinal(finalVersion, v.revision.id)" type="button" class="btn sm" :disabled="busy || locked.has('final:'+v.revision.id)" data-testid="final-version-set" @click="setFinal(v.revision.id)">{{ words.finalSet }}</button>
        </div>
      </section>
      <section class="panel mb-6"><h2 id="results">{{ words.batches }}</h2>
        <p v-if="!data?.batches.length" class="text3 mt-3">{{ words.noBatches }}</p>
        <article v-for="b in data?.batches" :key="b.id" :id="'batch-'+b.id" class="project-row" :class="{ target: b.id === targetBatch }">
          <p>{{ when(b.created_at) }}<template v-if="b.revision_id && titles.get(b.revision_id)"> · {{ titles.get(b.revision_id) }}</template><template v-if="phaseName(b.phase_id)"> · {{ phaseName(b.phase_id) }}</template> · {{ statuses[b.status] ?? b.status }}
            <span v-if="b.quota_refunded" class="pill info ml-2" data-testid="batch-refunded">{{ words.refunded }}</span></p>
          <p v-if="b.score != null">{{ words.average }}: {{ b.score.toFixed(2) }}</p>
          <div v-for="run in b.observer_runs" :key="run.id" class="flex flex-wrap gap-3 mt-3 items-center">
            <span v-if="scenarioNames[run.scenario_id]" class="m text-sm" :title="scenarioNames[run.scenario_id]!.name" data-testid="run-scenario">{{ scenarioNames[run.scenario_id]!.slug }}</span>
            <span class="pill">{{ statuses[run.status] ?? run.status }}</span>
            <span v-if="run.score != null">{{ run.score_summary?.calibration ? t('leaderboard.calibrated_score') + ': ' : '' }}{{ run.score.toFixed(2) }}</span>
            <span v-if="run.score_summary?.raw_score" class="meta">{{ t('leaderboard.raw_score') }}: {{ run.score_summary.raw_score.total.toFixed(2) }}</span>
            <button v-if="run.result_path" class="btn sm" :disabled="busy" @click="download(run.id)">{{ words.download }}</button>
            <button type="button" class="log-link" :disabled="busy" @click="showLogs({ run_id: run.id })">{{ words.logs }}</button>
          </div>
        </article>
      </section>
      <section v-if="diagnostics" class="panel mb-6" data-testid="project-diagnostics" aria-live="polite">
        <h2>{{ words.diagnostics }}</h2><p class="help">{{ words.diagnosticsHelp }}</p>
        <p v-if="!diagnostics.length">{{ words.noLogs }}</p>
        <article v-for="(entry, index) in diagnostics" :key="index" class="mt-4">
          <p>{{ entry.kind }} · {{ statuses[entry.status] ?? entry.status }} · {{ entry.code }}</p><pre v-if="entry.log">{{ entry.log }}</pre>
        </article><button class="btn sm mt-3" @click="diagnostics = null">{{ words.close }}</button>
      </section>
      <p class="help mt-6">{{ pick('Bring your own model API; organizer credits are not provided. Awards require LLM-driven agent techniques in at least two stages (see Rules). Never include a permanent key in your repository or ZIP.','请自备模型 API，平台不提供额度。评奖要求至少两个环节采用大模型驱动的智能体技术（见规则）。不要把永久密钥放进仓库或 ZIP。') }}</p>
    </template>
  </section>
</template>

<style scoped>
h2 { font-size: 1.2rem; font-weight: 600; } h3 { font-weight: 600; }
.project-row { padding: 1rem 0; border-bottom: 1px solid #333; }
.project-row.target { outline: 1px solid #315efb; outline-offset: .25rem; }
/* Logs are secondary to the step actions: a quiet text link at the end of a row. */
.log-link { margin-left: auto; background: none; border: 0; padding: .25rem 0; font-size: .75rem; color: #858585; text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
.meta { font-size: .8rem; color: #858585; }
.model-api > summary { cursor: pointer; list-style: none; display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem 1rem; }
.model-api > summary::-webkit-details-marker { display: none; }
.model-api > summary::after { content: '+'; margin-left: auto; color: #78a6ff; }
.model-api[open] > summary::after { content: '–'; }
.model-api-title { font-size: 1.2rem; font-weight: 600; }
.model-api-hint { margin: 0; }
.model-api-body { margin-top: .75rem; }
.upload-progress { display: block; width: 100%; max-width: 24rem; height: .5rem; margin-top: .35rem; accent-color: #315efb; }
.log-link:hover { color: #bdbdbd; } .log-link:disabled { opacity: .5; cursor: default; }
pre { max-height: 24rem; overflow: auto; padding: 1rem; margin-top: .5rem; background: #0b0b0b; font-size: .8rem; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
