-- Owner, 10-10: every team may read its OWN hidden-final evaluations (batches, and through them their runs,
-- agent logs and result downloads) while the final phase stays sealed. Other teams' final evaluations and every
-- other sealed phase stay closed. Writes keep their own checks: participants still cannot create or cancel
-- evaluations in a sealed phase (observer_restrict_phase_writes, observer_cancel_batch).
alter policy observer_batch_sealed on public.observer_batches
  using ((not public.observer_phase_sealed(phase_id)) or public.is_admin()
         or (public.observer_team(team_id) and phase_id = '6fe1e45f-927c-4b52-aada-bcc14fb00fdc'::uuid));   -- final-hidden (by id: phases itself is sealed-filtered)

notify pgrst, 'reload schema';
