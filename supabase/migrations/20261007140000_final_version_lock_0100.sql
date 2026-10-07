-- Owner decision 2026-10-07: the post-deadline window (15 new versions, final-version choice) ends and the
-- final version locks at 2026-10-08 01:00:00 UTC (09:00 UTC+8). The announced deadline stays 10-07 15:59:59 UTC.
update public.phases set ends_at = timestamptz '2026-10-08 01:00:00+00'
  where id = '049d6029-343d-4d16-80d5-94b56b350301' and ends_at = timestamptz '2026-10-07 21:59:59+00';
