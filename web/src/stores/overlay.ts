import { reactive } from 'vue'

// First-visit overlays (the pinned-announcement popup, the Kimi plan popup, the quota-reset notice, the sky-map walkthrough)
// take turns: one at a time, in the order they asked; the next one opens once the current one is
// released. The sky-map walkthrough is a non-modal page overlay (can be ignored by scrolling past it
// without ever closing it, holding its slot for the rest of the visit); a real modal popup always
// cuts ahead of it, so it is never stuck invisibly behind a walkthrough nobody dismissed.
const queue = reactive<string[]>([])
const modalNames = new Set<string>()

export function requestOverlay(name: string, opts?: { modal?: boolean }) {
  if (queue.includes(name)) return
  if (opts?.modal) {
    modalNames.add(name)
    const i = queue.findIndex(n => !modalNames.has(n))
    if (i === -1) queue.push(name)
    else queue.splice(i, 0, name)
  } else {
    queue.push(name)
  }
}
export function releaseOverlay(name: string) { const i = queue.indexOf(name); if (i >= 0) queue.splice(i, 1); modalNames.delete(name) }
/** True while `name` holds the screen; reactive, so a watcher can open the overlay when its turn comes. */
export function overlayActive(name: string) { return queue[0] === name }
