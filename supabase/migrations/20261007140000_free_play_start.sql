-- Free Play (after-party) opens when the online phase now locks: 2026-10-08 01:00:00 UTC.
update public.phases set starts_at='2026-10-08 01:00:00+00'
  where id='a0f7e9a2-5d3c-4b1e-9f60-2b7c1d8e4a01' and slug='after-party';
