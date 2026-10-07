// A short, actionable hint for a failed evaluation, public test or version, chosen from the
// failure code, the platform diagnostics and the tail of the team's own agent.log. Only fixed
// wording is returned; nothing from the logs is echoed back.

export type HintLink = { href: { en: string; zh: string }; en: string; zh: string }
export type FailureHint = { id: string; en: string; zh: string; link?: HintLink }

const KEYS: HintLink = { href: { en: '/compete#model-api', zh: '/compete#model-api' }, en: 'Keys and network', zh: '密钥与网络' }
const DEPS: HintLink = { href: { en: '/faq#q16', zh: '/faq#q16' }, en: 'FAQ: installing dependencies', zh: '常见问题：如何安装依赖' }
const PROTOCOL: HintLink = {
  href: { en: '/docs#8-what-the-agent-sees-and-must-decide', zh: '/docs#8-智能体看到什么-需要决定什么' },
  en: 'Docs §8: the agent protocol', zh: '文档第 8 节：智能体协议',
}
const EXAMPLES: HintLink = { href: { en: '/start', zh: '/start' }, en: 'Getting started and examples', zh: '入门与官方示例' }

type Rule = [RegExp, Omit<FailureHint, 'id'> & { id: string }]

// Ordered: the first match wins, so more specific causes come first.
const RULES: Rule[] = [
  [/missing api key|set OPENAI_API_KEY|AGENT_LLM_ENABLED=0|no complete set of variables|No model API is set up|add the variable \w+ under Keys|save OPENAI_API_KEY/i, {
    id: 'model_key',
    en: 'Your program could not find a model key. Save OPENAI_API_KEY (and its _BASE_URL / _MODEL) under Participate → Keys and network, then try again.',
    zh: '程序没找到模型密钥：请在「参赛 → 密钥与网络」保存 OPENAI_API_KEY 等变量（以及对应的 _BASE_URL、_MODEL）后再试。',
    link: KEYS }],
  [/platform settings must not be placed|schema_version must be|Project paths cannot be absolute|environment must be an object|build must be|run contains an invalid|run must be|Add observer\.project\.json|AssertionError: observer\.project\.json/i, {
    id: 'manifest',
    en: 'observer.project.json is not valid. Start from the one in an official example (schema_version observer-project-v1, relative paths).',
    zh: 'observer.project.json 格式不对：建议从官方示例复制一份再改（schema_version 为 observer-project-v1，路径用相对路径）。',
    link: EXAMPLES }],
  [/No space left on device|Errno 28|ENOSPC/i, {
    id: 'deps_too_large',
    en: 'Dependency install ran out of space. Trim requirements to what the agent really uses (e.g. drop torch / large ML stacks, or use CPU-only builds).',
    zh: '依赖安装空间不足：请精简依赖，只保留智能体真正用到的包（例如去掉 torch 等大型机器学习库，或改用仅 CPU 版本）。',
    link: DEPS }],
  [/Read-only file system|os error 30|EROFS|\/\.npm\/_logs|not owned or is not writable/i, {
    id: 'deps_read_only',
    en: 'A write to a read-only system folder failed. Install dependencies in the "build" steps of observer.project.json (HOME and the pip, npm and cargo caches are writable there), and while running write files only under /workspace or /tmp.',
    zh: '写入只读的系统目录失败：请在 observer.project.json 的 build 步骤中安装依赖（构建时 HOME 以及 pip、npm、cargo 缓存都可写），运行时只往 /workspace 或 /tmp 写文件。',
    link: DEPS }],
  [/ModuleNotFoundError|No module named|Cannot find module|tsc: not found|command not found|: not found\b|Could not open requirements file|could not compile|error\[E\d+\]|npm (?:ERR|error)|ResolutionImpossible|No matching distribution/i, {
    id: 'build_failed',
    en: 'The build or a dependency failed. Make sure every tool and package is installed by the "build" steps in observer.project.json (e.g. npm ci --include=dev for tsc), then check the log for the first error.',
    zh: '构建或依赖出错：请确认所有工具和依赖都由 observer.project.json 的 build 步骤安装（例如 tsc 需要 npm ci --include=dev），再看日志里的第一条报错。',
    link: DEPS }],
  [/rejected the request \(HTTP (?:401|403)\)|HTTP 401|invalid api key|Incorrect API key/i, {
    id: 'provider_auth',
    en: 'The model provider rejected your key. Check the key, endpoint and model name under Keys and network.',
    zh: '模型服务商拒绝了密钥：请在「密钥与网络」检查密钥、接口地址和模型名。',
    link: KEYS }],
  [/rejected the request \(HTTP 429\)|HTTP 429|rate limit|insufficient_quota/i, {
    id: 'provider_rate',
    en: 'The model provider is rate-limiting or out of balance. Check your balance, and in your code wait and retry on 429 instead of exiting.',
    zh: '模型服务商限流或余额不足：请检查余额，并在代码中遇到 429 时等待后重试，不要直接退出。',
    link: KEYS }],
  [/rejected the request \(HTTP \d{3}\)|Model call failed \(HTTP|Model service is unavailable/i, {
    id: 'provider_http',
    en: 'The model API returned an error. Check the endpoint and model name under Keys and network; if it is a 5xx, the provider is busy, so try again later.',
    zh: '模型接口返回了错误：请在「密钥与网络」检查接口地址和模型名；若是 5xx，多半是服务商繁忙，稍后再试即可。',
    link: KEYS }],
  [/did not return a valid interface proposal|Automatic adaptation|did not answer within \d+ seconds|took longer than the two-minute/i, {
    id: 'adaptation',
    en: 'Automatic adaptation did not succeed. The easiest fix: add observer.project.json (copy it from an official example) so no adaptation is needed.',
    zh: '自动适配没有成功：最省事的办法是在项目里加入 observer.project.json（从官方示例复制），这样就不需要自动适配。',
    link: EXAMPLES }],
  [/duration_seconds or until_utc|wait requires|wait needs|wait must not carry both/i, {
    id: 'wait_params',
    en: 'A wait needs exactly one of duration_seconds (an integer) or until_utc.',
    zh: 'wait 需要 duration_seconds（整数）或 until_utc 二选一。',
    link: PROTOCOL }],
  [/protocol[_ ]version|participant-agent-protocol|decision_sequence/i, {
    id: 'protocol',
    en: 'Protocol mismatch: the platform sends participant-agent-protocol-v4. Update to the current starter kit and echo the request\'s decision_sequence in each reply.',
    zh: '协议版本不匹配：平台发送的是 participant-agent-protocol-v4，请更新入门包，并在每次回复中带上请求里的 decision_sequence。',
    link: PROTOCOL }],
  [/TimeoutError|timed out|ReadTimeout/i, {
    id: 'timeout',
    en: 'Something timed out. Give model calls a short timeout and fall back to a simple action (e.g. a wait) instead of stopping.',
    zh: '程序里有操作超时：请给模型调用设置较短的超时，超时后改用简单动作（例如 wait）继续，而不是退出。',
    link: PROTOCOL }],
  [/Traceback \(most recent call last\)|panicked at|Segmentation fault|Unhandled|uncaught|Exception|exit code|exited with/i, {
    id: 'crash',
    en: 'Your program crashed. The log above shows the last error; reproduce it with the local runner from the starter kit before resubmitting.',
    zh: '程序崩溃了：上面的日志里有最后的报错；建议先用入门包里的本地运行器复现并修好，再重新提交。',
    link: EXAMPLES }],
]

const PLATFORM: FailureHint = {
  id: 'platform',
  en: 'This looks like a temporary platform problem, not your code. Please run the evaluation again in a little while; if it shows "not counted", it did not use your quota.',
  zh: '这看起来是平台的临时问题，不是你的代码出错。请稍后重新评测；显示「不计次数」的评测不占用你的次数。',
}
const GENERIC: FailureHint = {
  id: 'generic',
  en: 'This did not run through. The last lines of your program\'s output under "Logs" (or in the result ZIP) usually say why; the local runner in the starter kit reproduces most problems.',
  zh: '这次没有跑通。「日志」里程序输出的最后几行（或结果 ZIP 中的 agent.log）通常就是原因；用入门包里的本地运行器一般能复现。',
  link: EXAMPLES,
}

const PLATFORM_CODES = /^(job_http_5\d\d|job_http_40[13]|snapshot_repository_unavailable|job_expired|evaluation_expired|session_expired_rerun)$/

export type FailureInput = {
  /** Failure codes such as engine_job_failed, project_operation_failed, job_http_503. */
  codes?: Array<string | null | undefined>
  /** Free text: revision errors, diagnostic logs, the agent.log tail. */
  texts?: Array<string | null | undefined>
}

/** The hint for a failure, or the generic friendly line when the cause is not recognised. */
export function failureHint({ codes = [], texts = [] }: FailureInput): FailureHint {
  const text = texts.filter(Boolean).join('\n')
  for (const [pattern, hint] of RULES) if (pattern.test(text)) return hint
  if (codes.some(code => code && PLATFORM_CODES.test(code))) return PLATFORM
  return GENERIC
}
