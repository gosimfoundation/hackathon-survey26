<script setup lang="ts">
// Pinned announcements open as a dialog on any page (the slim banner alone went unnoticed), one per page load.
// It pops up on every page load (except /announcements) until the person has closed it twice (lib/popupRules: key
// id + notify_version, so an organizer's "remind everyone" brings it back with a fresh count, edits do not).
// Remembered on this device and, when signed in, on the server. Several pinned ones take turns across page loads.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '../../composables/useI18n'
import { isSupabaseConfigured } from '../../lib/supabase'
import { loadAnnouncements, type Announcement } from '../../lib/data'
import { fmtUtc } from '../../lib/format'
import { announcementText as annText } from '../../lib/announcementText'
import { pinnedRows } from '../../lib/pinnedPopup'
import { ANNOUNCEMENT_CLOSES, announcementCloseKey, announcementCloses, pickAnnouncement } from '../../lib/popupRules'
import { markSeen, seenKeys } from '../../stores/popupSeen'
import { overlayActive, releaseOverlay, requestOverlay } from '../../stores/overlay'
import AnnouncementBody from '../content/AnnouncementBody.vue'

const OVERLAY = 'pinned-announcement'
const { t, tf, locale } = useI18n()
const route = useRoute()
const dialog = ref<HTMLDialogElement | null>(null)
const item = ref<Announcement | null>(null)
const pinnedCount = ref(0)
/** Closes recorded before this one (0..ANNOUNCEMENT_CLOSES-1). */
const closes = ref(0)
const open = computed(() => !!item.value && overlayActive(OVERLAY))

onMounted(async () => {
  if (!isSupabaseConfigured) return
  let rows: Announcement[] = []
  try { rows = await loadAnnouncements(20) } catch { return }
  const pinned = pinnedRows(rows)
  if (!pinned.length) return
  const seen = await seenKeys()
  const next = pickAnnouncement(pinned, seen)
  if (!next) return
  pinnedCount.value = pinned.filter(row => row !== next && pickAnnouncement([row], seen)).length
  closes.value = announcementCloses(next, seen)
  item.value = next
  requestOverlay(OVERLAY, { modal: true })
})

// The announcements page already shows everything: do not cover it, and keep the popup for later.
watch([open, () => route.path], async ([isOpen, path]) => {
  await nextTick()
  const el = dialog.value
  if (!el) return
  if (isOpen && path !== '/announcements' && !el.open) el.showModal()
  else if ((!isOpen || path === '/announcements') && el.open) el.close()
}, { immediate: true })

function dismiss() {
  if (!item.value) return
  // Every close counts (button, ×, Esc, outside click, "all announcements"); the 2nd one stops it for good.
  markSeen([announcementCloseKey(item.value, closes.value + 1)])
  item.value = null
  if (dialog.value?.open) dialog.value.close()
  releaseOverlay(OVERLAY)
}
const others = computed(() => pinnedCount.value)
const closesLeft = computed(() => ANNOUNCEMENT_CLOSES - closes.value)
</script>

<template>
  <dialog v-if="item" ref="dialog" class="pinned-dialog" :aria-labelledby="`pinned-title-${item.id}`" data-testid="pinned-announcement"
    @cancel.prevent="dismiss" @click.self="dismiss">
    <div class="pinned-panel">
      <button type="button" class="pinned-close" :aria-label="t('ann.popup_close')" data-testid="pinned-announcement-close" @click="dismiss">×</button>
      <span class="label accent">{{ t('ann.pinned') }} · {{ t('ann.kicker') }} · {{ fmtUtc(item.created_at) }} UTC</span>
      <h2 :id="`pinned-title-${item.id}`" class="pinned-title">{{ annText(item, 'title', locale) }}</h2>
      <AnnouncementBody class="text2 mt-3" :text="annText(item, 'body', locale)" poster />
      <div class="pinned-actions">
        <router-link class="btn sm" to="/announcements" data-testid="pinned-announcement-all" @click="dismiss">{{ t('ann.popup_all') }} →</router-link>
        <span class="text3 text-xs" data-testid="pinned-announcement-closes-left">{{ tf('ann.popup_closes_left', { n: closesLeft }) }}</span>
        <span v-if="others" class="text3 text-xs">{{ tf('ann.popup_more', { n: others }) }}</span>
        <button type="button" class="btn sm primary" @click="dismiss">{{ t('ann.popup_ok') }}</button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.pinned-dialog { width: min(64rem, calc(100vw - 1.5rem)); max-height: calc(100dvh - 1.5rem); padding: 0; margin: auto;
  border: 1px solid rgba(158,173,255,.35); background: #0b1022; color: #e8ecf8; box-shadow: 0 24px 80px rgba(0,0,0,.6); }
.pinned-dialog::backdrop { background: rgba(2,5,14,.72); backdrop-filter: blur(2px); }
.pinned-panel { position: relative; padding: 1.5rem 1.4rem 1.25rem; overflow-wrap: anywhere; }
@media (min-width: 640px) { .pinned-panel { padding: 2rem 2rem 1.5rem; } }
.pinned-title { margin-top: .75rem; padding-right: 2rem; font-size: 1.45rem; font-weight: 600; line-height: 1.3; letter-spacing: -.02em; color: #f5f7ff; }
.pinned-close { position: absolute; top: .6rem; right: .7rem; width: 2.4rem; height: 2.4rem; font-size: 1.6rem; line-height: 1; color: #aeb6c8; background: none; border: 0; cursor: pointer; }
.pinned-close:hover { color: #fff; }
.pinned-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .75rem; margin-top: 1.5rem; }
</style>
