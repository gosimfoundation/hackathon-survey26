<script setup lang="ts">
// My UID, friends, friend requests and blocked people. A captain can invite a friend without a team in one click.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { describeError } from '../../lib/errors'
import { useAuth } from '../../stores/auth'
import { useFlash } from '../../stores/flash'
import { emptyFriends, parseUid, type FriendsData } from '../../lib/friends'
import { blockUser, cancelFriendRequest, inviteToTeamByUid, loadFriends, removeFriend, respondFriendRequest,
  sendFriendRequest, unblockUser } from '../../lib/friendsApi'
import UserAvatar from '../UserAvatar.vue'

const { t, tf } = useI18n()
const i18n = useI18n()
const flash = useFlash()
const { me, team } = useAuth()
const data = ref<FriendsData>(emptyFriends())
const loaded = ref(false)
const busy = ref(false)
const uidInput = ref('')
const copied = ref(false)
const isLeader = computed(() => Boolean(team.value && me.value && team.value.leader_id === me.value.id))
const myUid = computed(() => data.value.uid ?? me.value?.uid ?? null)
const errorText = (e: unknown) => describeError(e, i18n, ['friends.errors', 'team.errors'])

async function reload() {
  try { data.value = await loadFriends() } catch (e) { flash.error(errorText(e)) }
  finally { loaded.value = true }
}
async function run(action: () => Promise<unknown>, success?: string | ((r: unknown) => string)) {
  busy.value = true
  try {
    const result = await action()
    if (success) flash.success(typeof success === 'function' ? success(result) : success)
    await reload()
  } catch (e) { flash.error(errorText(e)) }
  finally { busy.value = false }
}

function add() {
  const uid = parseUid(uidInput.value)
  if (!uid) { flash.error(t('friends.invalid_uid')); return }
  void run(async () => { const status = await sendFriendRequest(uid); uidInput.value = ''; return status },
    status => t(`friends.result.${status}`))
}
const accept = (id: string) => run(() => respondFriendRequest(id, true), t('friends.result.accepted'))
const decline = (id: string) => run(() => respondFriendRequest(id, false))
const cancel = (id: string) => run(() => cancelFriendRequest(id))
const remove = (userId: string) => { if (window.confirm(t('friends.remove_confirm'))) void run(() => removeFriend(userId)) }
const block = (userId: string) => { if (window.confirm(t('friends.block_confirm'))) void run(() => blockUser(userId)) }
const unblock = (userId: string) => run(() => unblockUser(userId))
const invite = (uid: number) => run(() => inviteToTeamByUid(uid), t('friends.invited'))

async function copyUid() {
  if (!myUid.value) return
  try { await navigator.clipboard.writeText(String(myUid.value)); copied.value = true; window.setTimeout(() => { copied.value = false }, 2000) }
  catch { flash.error(t('team.copy_fallback')) }
}

onMounted(reload)
</script>

<template>
  <div id="friends" class="panel mt-8" data-testid="friends-panel">
    <div class="hd"><h2>{{ t('friends.title') }}</h2></div>
    <div class="friends-uid">
      <span class="label">{{ t('friends.my_uid') }}</span>
      <span class="token friends-uid-value" translate="no" data-testid="my-uid">{{ myUid ?? '—' }}</span>
      <button v-if="myUid" type="button" class="copy-btn" data-testid="copy-uid" @click="copyUid">{{ copied ? t('common.copied') : t('common.copy') }}</button>
    </div>
    <p class="help">{{ t('friends.uid_hint') }}</p>

    <form class="friends-add mt-5" @submit.prevent="add">
      <label class="field"><span>{{ t('friends.add_label') }}</span>
        <input v-model="uidInput" data-testid="friend-uid-input" type="text" inputmode="numeric" autocomplete="off" maxlength="20" :placeholder="t('friends.add_placeholder')" class="mono">
      </label>
      <button class="btn sm" type="submit" data-testid="friend-add" :disabled="busy || !uidInput.trim()">{{ t('friends.add') }}</button>
    </form>
    <p class="help">{{ tf('friends.daily_note', { n: data.daily_limit }) }}</p>

    <template v-if="data.incoming.length">
      <h3 class="friends-h">{{ t('friends.incoming_title') }}</h3>
      <ul class="friends-list" data-testid="friend-incoming">
        <li v-for="r in data.incoming" :key="r.id">
          <span class="friends-who"><UserAvatar :name="r.name" :avatar-url="r.avatar_url" /> {{ r.name }}</span>
          <span class="actions-inline">
            <button type="button" class="copy-btn" :disabled="busy" @click="accept(r.id)">{{ t('friends.accept') }}</button>
            <button type="button" class="copy-btn" :disabled="busy" @click="decline(r.id)">{{ t('friends.decline') }}</button>
            <button type="button" class="copy-btn" :disabled="busy" @click="block(r.user_id)">{{ t('friends.block') }}</button>
          </span>
        </li>
      </ul>
    </template>

    <h3 class="friends-h">{{ t('friends.friends_title') }}</h3>
    <p v-if="loaded && !data.friends.length" class="text3 text-sm">{{ t('friends.none') }}</p>
    <ul v-else class="friends-list" data-testid="friend-list">
      <li v-for="f in data.friends" :key="f.user_id">
        <span class="friends-who"><UserAvatar :name="f.name" :avatar-url="f.avatar_url" />
          <span><b>{{ f.name }}</b><small class="friends-sub">{{ f.team_name || (f.in_team ? '—' : t('friends.no_team')) }}<template v-if="f.uid"> · <span class="mono" translate="no">{{ f.uid }}</span></template></small></span>
        </span>
        <span class="actions-inline">
          <button v-if="isLeader && !f.in_team && f.uid" type="button" class="copy-btn" data-testid="friend-invite" :disabled="busy" @click="invite(f.uid)">{{ t('friends.invite_team') }}</button>
          <button type="button" class="copy-btn" :disabled="busy" @click="remove(f.user_id)">{{ t('friends.remove') }}</button>
          <button type="button" class="copy-btn" :disabled="busy" @click="block(f.user_id)">{{ t('friends.block') }}</button>
        </span>
      </li>
    </ul>

    <template v-if="data.outgoing.length">
      <h3 class="friends-h">{{ t('friends.outgoing_title') }}</h3>
      <ul class="friends-list" data-testid="friend-outgoing">
        <li v-for="r in data.outgoing" :key="r.id">
          <span class="mono" translate="no">UID {{ r.uid }}</span><span class="text3 text-sm">{{ t('friends.pending') }}</span>
          <button type="button" class="copy-btn" :disabled="busy" @click="cancel(r.id)">{{ t('friends.cancel') }}</button>
        </li>
      </ul>
    </template>

    <template v-if="data.blocked.length">
      <h3 class="friends-h">{{ t('friends.blocked_title') }}</h3>
      <ul class="friends-list">
        <li v-for="b in data.blocked" :key="b.user_id">
          <span>{{ b.name }}</span>
          <button type="button" class="copy-btn" :disabled="busy" @click="unblock(b.user_id)">{{ t('friends.unblock') }}</button>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.friends-uid { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem .9rem; }
.friends-uid-value { font-size: 1.15rem; letter-spacing: .12em; }
.friends-add { display: flex; flex-wrap: wrap; align-items: flex-end; gap: .75rem; }
.friends-add .field { flex: 1 1 12rem; margin-bottom: 0; }
.friends-h { margin: 1.6rem 0 .6rem; font-size: .8rem; letter-spacing: .08em; text-transform: uppercase; color: rgba(205, 214, 238, .7); }
.friends-list { display: flex; flex-direction: column; gap: .1rem; margin: 0; padding: 0; list-style: none; }
.friends-list li { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .5rem .9rem;
  padding: .55rem 0; border-bottom: 1px solid rgba(255, 255, 255, .08); }
.friends-who { display: inline-flex; align-items: center; gap: .55rem; min-width: 0; overflow-wrap: anywhere; }
.friends-who b { display: block; font-weight: 600; }
.friends-sub { display: block; font-size: .74rem; color: rgba(205, 214, 238, .6); }
</style>
