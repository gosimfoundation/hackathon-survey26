-- Cards A1–D1 joined the online competition; their card pages and public inputs were announced as
-- public ("加入正式赛时公开：卡片页面和公开输入；天气、预报与事件不公开"). Release their public/ folder
-- the same way as A–D (release 'competition': readable while the card is in the started, public
-- 'online' phase and the site is in competition mode). Only public/ — never config/ or truth/.
insert into private.observer_scenario_public_files(scenario_id, path, release)
select s.id, f.path, 'competition'
from public.scenarios s
cross join (values ('public/footprint.csv'), ('public/targets.csv'), ('public/v4_night_calendar.csv'),
                   ('public/taskcard.zh.md'), ('public/taskcard.en.md')) f(path)
where s.slug in ('v4-a1-v5', 'v4-b1-v5', 'v4-c1-v5', 'v4-d1-v5')
on conflict (scenario_id, path) do nothing;
