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
const copied = ref('')
async function copy(id: string, text: string) {
  try { await navigator.clipboard.writeText(text); copied.value = id; window.setTimeout(() => { if (copied.value === id) copied.value = '' }, 1600) }
  catch { /* the command stays selectable */ }
}
</script>

<template>
  <section class="cli-card" data-testid="cli-skill-card" :aria-label="pick('Command-line tool & agent skill', '命令行工具 & 智能体 Skill')">
    <div class="cli-card-hd">
      <h2>{{ pick('Command-line tool & agent skill', '命令行工具 & 智能体 Skill') }}</h2>
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
  </section>
</template>

<style scoped>
.cli-card { margin-bottom: 1.25rem; padding: .9rem 1.1rem; border: 1px solid rgba(158,173,255,.26); background: rgba(49,94,251,.06); }
.cli-card-hd { display: flex; flex-wrap: wrap; align-items: baseline; gap: .25rem 1rem; margin-bottom: .6rem; }
.cli-card-hd h2 { font-size: .95rem; font-weight: 600; color: #f5f5f5; }
.cli-card-hd p { flex: 1 1 22rem; font-size: .8rem; line-height: 1.5; color: rgba(255,255,255,.6); }
.cli-row { display: flex; align-items: center; gap: .6rem; margin-top: .4rem; min-width: 0; }
.cli-label { flex: 0 0 8.5rem; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .68rem; letter-spacing: .06em; text-transform: uppercase; color: #9aa5bd; }
.cli-cmd { flex: 1; min-width: 0; overflow-x: auto; white-space: nowrap; padding: .35rem .55rem; border: 1px solid rgba(255,255,255,.1); background: rgba(2,8,20,.55);
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .74rem; color: #d9e5ff; user-select: all; }
.cli-copy { flex: 0 0 auto; min-height: 30px; padding: .25rem .65rem; border: 1px solid rgba(120,166,255,.5); font-size: .72rem; color: #cfe0ff; }
.cli-copy:hover { border-color: #78a6ff; background: rgba(49,94,251,.2); color: #fff; }
.cli-links { display: flex; flex-wrap: wrap; gap: .3rem 1.1rem; margin-top: .65rem; font-size: .8rem; }
.cli-links a { color: #78a6ff; }
.cli-links a:hover { text-decoration: underline; }
@media (max-width: 640px) { .cli-row { flex-wrap: wrap; } .cli-label { flex-basis: 100%; } }
</style>
