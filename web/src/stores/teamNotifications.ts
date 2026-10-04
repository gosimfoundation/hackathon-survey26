import { ref } from 'vue'
import { supabase } from '../lib/supabase'

/** Unread team notifications (any change since the person last opened the list). */
export const unreadTeamNotifications = ref(0)
/** Requests/invitations waiting for this person's answer; stays until answered, read or not. */
export const pendingTeamActions = ref(0)
export async function refreshTeamNotifications() {
  const { data, error } = await supabase.rpc('team_notification_counts')
  if (!error && data) {
    pendingTeamActions.value = Number(data.pending ?? 0)
    unreadTeamNotifications.value = Number(data.unread ?? 0)
    return
  }
  // Older backend: unread only.
  const old = await supabase.rpc('team_invitation_unread')
  if (!old.error) unreadTeamNotifications.value = Number(old.data ?? 0)
}
export function clearTeamNotifications() { unreadTeamNotifications.value = 0; pendingTeamActions.value = 0 }
export async function teamAction(name: string, args?: Record<string, unknown>) {
  const { data, error } = await supabase.rpc(name, args)
  if (error) throw error
  await refreshTeamNotifications()
  return data
}
