"""Pinned announcements pop up, one per page load, with clickable links and its poster shown whole (also on a phone).
Each one pops up on every page load (except /announcements) until the person has closed it 3 times (any way); an
organizer's "remind everyone" (notify_version) brings it back with a fresh count; edits never re-show it; keys of the
older snooze / switch-off scheme do not count. Several pinned announcements take turns across page loads
(web/src/lib/popupRules.ts)."""
import os
import secrets

import pytest
from playwright.sync_api import sync_playwright, expect

from test_project_http import edge_stack  # noqa: F401
from test_project_portal_browser import portal_site  # noqa: F401
from test_project_database import query

pytestmark = pytest.mark.skipif(not all(os.environ.get(k) for k in ('OBSERVER_DENO_BIN', 'SAC_POSTGREST_BIN', 'SAC_NODE_BIN')),
                                reason='Local browser toolchain required')


def announce(uri, title, body, *, pinned=True, published=True, age='0 minutes'):
    return query(uri, """insert into public.announcements(title_en,title_zh,body_en,body_zh,is_pinned,is_published,created_at)
                         values(%s,%s,%s,%s,%s,%s,now()-%s::interval) returning id""",
                 (title + ' (en)', title + '（中文）', 'EN ' + body, '中文 ' + body, pinned, published, age))[0][0]


def popup_box(page):
    return page.get_by_test_id('pinned-announcement')


def test_pinned_announcement_popup(portal_site, edge_stack):
    uri = edge_stack['harness'].db_uri
    tag = secrets.token_hex(3)
    query(uri, "update public.announcements set is_pinned=false")
    poster = portal_site + '/apple-touch-icon.png'
    older = announce(uri, 'Older ' + tag, 'old', age='2 days')
    talk = announce(uri, 'Talk ' + tag, f'Join us: https://example.org/talk-{tag}\nPoster: {poster}', age='1 hour')
    announce(uri, 'Plain ' + tag, 'not pinned', pinned=False)
    announce(uri, 'Draft ' + tag, 'not published', published=False)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.environ.get('OBSERVER_BROWSER_CHANNEL'))
        context = browser.new_context(viewport={'width': 1365, 'height': 900})
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))

        # Any page: the newest pinned, published announcement opens, in the visitor's language.
        page.goto(portal_site + '/rules?lang=zh', wait_until='domcontentloaded')
        box = popup_box(page)
        expect(box).to_be_visible(timeout=15000)
        expect(box).to_contain_text('Talk ' + tag + '（中文）')
        expect(box.locator(f'a[href="https://example.org/talk-{tag}"]')).to_have_attribute('target', '_blank')
        image = box.locator(f'img[src="{poster}"]')
        expect(image).to_be_visible()
        page.wait_for_function('img => img.complete && img.naturalWidth > 0', arg=image.element_handle())
        expect(box).to_contain_text('另有 1 条置顶公告')
        expect(box.get_by_test_id('pinned-announcement-all')).to_have_text('查看全部公告 →')
        expect(box.get_by_test_id('pinned-announcement-closes-left')).to_have_text('再关闭 3 次后不再显示')
        expect(box.get_by_test_id('pinned-announcement-off')).to_have_count(0)
        page.get_by_test_id('pinned-announcement-close').click()
        expect(box).to_have_count(0)
        # The pinned ones take turns (least closed first, newest on a tie); every way of closing counts.
        closes = [('Older', 3, 'close'), ('Talk', 2, 'escape'), ('Older', 2, 'ok'), ('Talk', 1, 'close'), ('Older', 1, 'escape')]
        for i, (title, left, how) in enumerate(closes):
            page.goto(portal_site + ('/leaderboard' if i % 2 == 0 else '/rules') + '?lang=zh', wait_until='domcontentloaded')
            box = popup_box(page)
            expect(box).to_be_visible(timeout=15000)
            expect(box).to_contain_text(title + ' ' + tag)
            expect(box.get_by_test_id('pinned-announcement-closes-left')).to_have_text(f'再关闭 {left} 次后不再显示')
            if how == 'escape':
                page.keyboard.press('Escape')
            elif how == 'ok':
                box.get_by_role('button', name='知道了').click()
            else:
                page.get_by_test_id('pinned-announcement-close').click()
            expect(box).to_have_count(0)
        # Closed 3 times each: they stop for good.
        page.goto(portal_site + '/faq?lang=zh', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        expect(popup_box(page)).to_have_count(0)
        seen = page.evaluate("JSON.parse(localStorage.getItem('sac.popups.seen'))")
        for ann in (talk, older):
            assert all(f'ann-off:{ann}:v1#close{n}' in seen for n in (1, 2, 3)), seen
        assert not any(k.startswith('ann-snooze:') for k in seen)
        # Editing the text never re-shows it.
        query(uri, "update public.announcements set body_zh=body_zh||' (更新)' where id=%s", (talk,))
        page.goto(portal_site + '/leaderboard?lang=zh', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        expect(popup_box(page)).to_have_count(0)
        # "Remind everyone" brings it back, with a fresh count.
        query(uri, "update public.announcements set notify_version=notify_version+1 where id=%s", (talk,))
        page.goto(portal_site + '/faq?lang=zh', wait_until='domcontentloaded')
        expect(popup_box(page)).to_contain_text('Talk ' + tag, timeout=15000)
        expect(popup_box(page).get_by_test_id('pinned-announcement-closes-left')).to_have_text('再关闭 3 次后不再显示')
        context.close()

        # A newer pinned announcement pops up (English). Keys of the older snooze / switch-off scheme do not
        # suppress it, and staying on screen without closing does not count: a reload shows it again.
        newer = announce(uri, 'Newer ' + tag, 'fresh news')
        home = browser.new_context(viewport={'width': 1365, 'height': 900}).new_page()
        home.on('pageerror', lambda e: errors.append(str(e)))
        home.goto(portal_site + '/?lang=en', wait_until='domcontentloaded')
        home.evaluate("keys => localStorage.setItem('sac.popups.seen', JSON.stringify(keys))",
                      [f'ann:{newer}:v1', f'ann-off:{newer}:v1', f'ann-snooze:{newer}:v1:2026-10-06'])
        home.reload(wait_until='domcontentloaded')
        expect(popup_box(home)).to_contain_text('Newer ' + tag + ' (en)', timeout=15000)
        expect(popup_box(home).get_by_test_id('pinned-announcement-closes-left')).to_have_text('Closes left before it stops: 3')
        home.wait_for_timeout(3500)
        home.reload(wait_until='domcontentloaded')
        expect(popup_box(home)).to_contain_text('Newer ' + tag, timeout=15000)
        query(uri, "update public.announcements set is_pinned=false where id=%s", (newer,))
        # "See all announcements" leads to the list, which is never covered.
        home.evaluate("localStorage.removeItem('sac.popups.seen')")
        home.goto(portal_site + '/start?lang=en', wait_until='domcontentloaded')
        home.get_by_test_id('pinned-announcement-all').click()
        expect(home).to_have_url(portal_site + '/announcements')
        expect(popup_box(home)).to_have_count(0)
        expect(home.locator('main')).to_contain_text('Talk ' + tag + ' (en)')

        # On a phone the poster fits the screen and the dialog scrolls; nothing overflows sideways.
        phone = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True).new_page()
        phone.on('pageerror', lambda e: errors.append(str(e)))
        phone.goto(portal_site + '/rules?lang=zh', wait_until='domcontentloaded')
        box = popup_box(phone)
        expect(box).to_be_visible(timeout=15000)
        dialog = box.bounding_box()
        assert dialog['x'] >= 0 and dialog['x'] + dialog['width'] <= 390 and dialog['height'] <= 844
        img = box.locator(f'img[src="{poster}"]')
        img.scroll_into_view_if_needed()
        shown = img.bounding_box()
        assert shown['width'] <= dialog['width'] and shown['height'] <= 844 * 0.72 + 1
        browser.close()
    assert not errors, errors
