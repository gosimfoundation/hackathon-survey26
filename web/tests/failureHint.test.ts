import assert from 'node:assert/strict'
import test from 'node:test'
import { failureHint } from '../src/lib/failureHint.ts'

const id = (texts: string[], codes: string[] = []) => failureHint({ texts, codes }).id

test('common failures map to a specific hint', () => {
  assert.equal(id(['Compiling...\n\nagent: missing API key: set OPENAI_API_KEY\n']), 'model_key')
  assert.equal(id(['Project preparation failed: Platform settings must not be placed in the project manifest.']), 'manifest')
  assert.equal(id(["ERROR: Could not install packages due to an OSError: [Errno 30] Read-only file system: '/.local'"]), 'deps_read_only')
  assert.equal(id(['Defaulting to user installation\nERROR: Could not install packages due to an OSError: [Errno 28] No space left on device']), 'deps_too_large')
  assert.equal(id(['> tsc -p tsconfig.json\n\nsh: 1: tsc: not found\n']), 'build_failed')
  assert.equal(id(['The model provider rejected the request (HTTP 404). Check the API endpoint, model name, key and balance under Keys and network.']), 'provider_http')
  assert.equal(id(['Automatic adaptation used OPENAI_API_KEY (openai protocol): The model provider rejected the request (HTTP 429). Check']), 'provider_rate')
  assert.equal(id(['Automatic adaptation used OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL (openai protocol): The adaptation model did not return a valid interface proposal.']), 'adaptation')
  assert.equal(id(['Automatic adaptation uses your team\'s model: add the variable OPENAI_MODEL under Keys and network']), 'model_key')
  assert.equal(id(['wait requires duration_seconds or until_utc']), 'wait_params')
  assert.equal(id(['unexpected protocol_version']), 'protocol')
  assert.equal(id(['Traceback (most recent call last):\n  File "agent.py"\nKeyError: x']), 'crash')
})

test('platform codes and unknown causes get friendly fallbacks', () => {
  assert.equal(id([], ['engine_job_failed', 'job_http_503']), 'platform')
  assert.equal(id(['Public test failed. Check the project interface and submit again.']), 'generic')
  assert.equal(id([]), 'generic')
})
