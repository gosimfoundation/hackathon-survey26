import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { cliInstallCommand, siteBase, SITE_BASE, SKILL_PATH, skillInstallCommand } from '../src/lib/cliInstall.ts'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('the one-line installs point at the published tool and skill', () => {
  assert.equal(cliInstallCommand(), 'curl -fsSLO https://create.gosim.org/survey26/platform/survey26.py && python3 survey26.py --help')
  assert.equal(skillInstallCommand(), 'mkdir -p ~/.claude/skills/survey26 && curl -fsSL https://create.gosim.org/survey26/platform/skills/survey26/SKILL.md -o ~/.claude/skills/survey26/SKILL.md')
  assert.equal(siteBase('http://localhost:5173', '/'), 'http://localhost:5173/')
  assert.equal(siteBase(undefined, '/'), SITE_BASE)
})

test('the guide (both languages) and the FAQ give the same skill install, and the build publishes the skill there', () => {
  for (const lang of ['en', 'zh']) {
    assert.ok(read(`../src/content/cli.${lang}.md`).includes(skillInstallCommand()), lang)
    assert.ok(JSON.stringify(JSON.parse(read(`../src/i18n/${lang}.json`)).faq.items).includes(skillInstallCommand()), lang)
  }
  assert.ok(read('../scripts/build-cli.mjs').includes(`'skills/survey26/SKILL.md'`) && SKILL_PATH === 'skills/survey26/SKILL.md')
  const skill = read('../../cli/skill/SKILL.md')
  assert.match(skill, /^---\nname: survey26\ndescription: .+\n---\n/)
  assert.ok(skill.includes('SURVEY26_TOKEN') && skill.includes('SOPHON_RUN_TOKEN') && !/johnny|contact-johnny/i.test(skill))
})
