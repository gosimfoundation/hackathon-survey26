<script setup lang="ts">
// 参赛 page: the command-line tool and the agent skill, with a one-line install each (copy buttons).
import { computed, ref } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { cliInstallCommand, siteBase, skillInstallCommand, SKILL_PATH } from '../../lib/cliInstall'

const { pick } = useI18n()
const base = computed(() => siteBase(typeof window === 'undefined' ? undefined : window.location.origin, import.meta.env.BASE_URL))
const rows = computed(() => [
  { id: 'cli', label: pick('Command line', '命令行'), command: cliInstallCommand(base.value) },
  { id: 'skill', label: 'Claude Code Skill', command: skillInstallCommand(base.value) },
])
// Collapsed by default; the choice is remembered per browser.
const STORE = 'survey26.cliCard.open'
function readOpen() { try { return window.localStorage.getItem(STORE) === '1' } catch { return false } }
const open = ref(readOpen())
function toggle() {
  open.value = !open.value
  try { window.localStorage.setItem(STORE, open.value ? '1' : '0') } catch { /* private mode: not remembered */ }
}
const copied = ref('')
async function copy(id: string, text: string) {
  try { await navigator.clipboard.writeText(text); copied.value = id; window.setTimeout(() => { if (copied.value === id) copied.value = '' }, 1600) }
  catch { /* the command stays selectable */ }
}
</script>

<template>
  <section class="cli-card" data-testid="cli-skill-card" :aria-label="pick('Command-line tool & agent skill', '命令行工具 & 智能体 Skill')">
    <button type="button" class="cli-toggle" :aria-expanded="open" aria-controls="cli-card-body" data-testid="cli-card-toggle" @click="toggle">
      <span class="cli-title">{{ pick('Command-line tool & agent skill', '命令行工具 & 智能体 Skill') }}</span>
      <span class="cli-hint">{{ pick('One-line install; let Claude Code or another agent upload and evaluate', '一行安装，让 Claude Code 等智能体替你上传和评测') }}</span>
      <span class="cli-chevron" :class="{ open }" aria-hidden="true">▾</span>
    </button>
    <div v-show="open" id="cli-card-body" class="cli-body" data-testid="cli-card-body">
    <div class="cli-card-hd">
      <p>{{ pick('Upload, evaluate and read logs and results from a terminal or a coding agent (Claude Code, Codex, Cursor…), with the same permissions, limits and quotas as the website.',
        '在终端或编程智能体（Claude Code、Codex、Cursor 等）里上传、评测、看日志和结果，权限、次数和配额与网站相同。') }}</p>
    </div>
    <div v-for="row in rows" :key="row.id" class="cli-row">
      <span class="cli-label">{{ row.label }}</span>
      <code class="cli-cmd" :data-testid="`cli-install-${row.id}`">{{ row.command }}</code>
      <button type="button" class="cli-copy" :data-testid="`cli-copy-${row.id}`" @click="copy(row.id, row.command)">{{ copied === row.id ? pick('Copied', '已复制') : pick('Copy', '复制') }}</button>
    </div>
    <p class="cli-links">
      <router-link to="/cli" data-testid="cli-card-guide">{{ pick('Full guide', '完整说明') }} →</router-link>
      <a :href="`${base}${SKILL_PATH}`" target="_blank" rel="noopener" data-testid="cli-card-skill">{{ pick('Skill file', 'Skill 文件') }} →</a>
      <a :href="`${base}survey26-AGENTS.md`" target="_blank" rel="noopener">{{ pick('Other agents: AGENTS.md', '其他智能体：AGENTS.md') }} →</a>
      <router-link to="/profile#api-tokens">{{ pick('Create an API token', '创建 API 令牌') }} →</router-link>
    </p>
    </div>
  </section>
</template>

<style scoped>
.cli-card { margin-bottom: 1rem; border: 1px solid rgba(158,173,255,.26); background: rgba(49,94,251,.06); min-width: 0; }
.cli-toggle { display: flex; align-items: center; gap: .4rem .9rem; width: 100%; padding: .5rem .9rem; text-align: left; min-height: 40px; }
.cli-toggle:hover { background: rgba(49,94,251,.12); }
.cli-title { flex: 0 0 auto; font-size: .88rem; font-weight: 600; color: #f5f5f5; }
.cli-hint { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .78rem; color: rgba(255,255,255,.55); }
.cli-chevron { flex: 0 0 auto; color: #78a6ff; font-size: .75rem; transition: transform .15s ease; }
.cli-chevron.open { transform: rotate(180deg); }
.cli-body { padding: .1rem .9rem .85rem; }
.cli-card-hd { margin-bottom: .5rem; }
.cli-card-hd p { font-size: .8rem; line-height: 1.5; color: rgba(255,255,255,.6); }
.cli-row { display: flex; align-items: center; gap: .6rem; margin-top: .4rem; min-width: 0; }
.cli-label { flex: 0 0 8.5rem; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .68rem; letter-spacing: .06em; text-transform: uppercase; color: #9aa5bd; }
.cli-cmd { flex: 1; min-width: 0; overflow-x: auto; white-space: nowrap; padding: .35rem .55rem; border: 1px solid rgba(255,255,255,.1); background: rgba(2,8,20,.55);
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .74rem; color: #d9e5ff; user-select: all; }
.cli-copy { flex: 0 0 auto; min-height: 30px; padding: .25rem .65rem; border: 1px solid rgba(120,166,255,.5); font-size: .72rem; color: #cfe0ff; }
.cli-copy:hover { border-color: #78a6ff; background: rgba(49,94,251,.2); color: #fff; }
.cli-links { display: flex; flex-wrap: wrap; gap: .3rem 1.1rem; margin-top: .65rem; font-size: .8rem; }
.cli-links a { color: #78a6ff; }
.cli-links a:hover { text-decoration: underline; }
@media (max-width: 640px) { .cli-row { flex-wrap: wrap; } .cli-label { flex-basis: 100%; } .cli-cmd { flex: 1 1 0; } .cli-hint { display: none; } }
@media (prefers-reduced-motion: reduce) { .cli-chevron { transition: none; } }
</style>
