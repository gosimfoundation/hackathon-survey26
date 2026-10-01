<script setup lang="ts">
import { computed } from 'vue'
import { linkSegments } from '../../lib/linkify'

// Announcement text with clickable links and image URLs shown as images (no v-html).
// `poster` sizes images to fit the viewport whole (the popup); otherwise they stay a modest preview.
const props = defineProps<{ text: string | null | undefined; poster?: boolean }>()
const segments = computed(() => linkSegments(props.text))
</script>

<template>
  <div class="whitespace-pre-line leading-relaxed"><template v-for="(seg, i) in segments" :key="i"><template v-if="seg.kind === 'text'">{{ seg.text }}</template><a v-else-if="seg.kind === 'link'" class="accent-l break-all underline underline-offset-2" :href="seg.href" target="_blank" rel="noopener noreferrer">{{ seg.href }}</a><a v-else :href="seg.href" target="_blank" rel="noopener noreferrer" class="mt-4 block" :class="poster ? 'poster' : 'max-w-md'"><img :src="seg.href" alt="" :loading="poster ? 'eager' : 'lazy'" class="w-full rounded border border-border"></a></template></div>
</template>

<style scoped>
.poster { max-width: 100%; }
.poster img { width: auto; max-width: 100%; max-height: 72vh; margin: 0 auto; object-fit: contain; }
</style>
