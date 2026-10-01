import { reactive } from 'vue'

// First-visit overlays (the pinned-announcement popup, the sky-map walkthrough) take turns: one at a
// time, in the order they asked; the next one opens once the current one is released.
const queue = reactive<string[]>([])

export function requestOverlay(name: string) { if (!queue.includes(name)) queue.push(name) }
export function releaseOverlay(name: string) { const i = queue.indexOf(name); if (i >= 0) queue.splice(i, 1) }
/** True while `name` holds the screen; reactive, so a watcher can open the overlay when its turn comes. */
export function overlayActive(name: string) { return queue[0] === name }
