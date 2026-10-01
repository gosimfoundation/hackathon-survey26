"""Pinned announcements pop up: the newest unseen pinned one opens on any page, with clickable links and
its poster shown whole (also on a phone); once dismissed it stays closed, a newer pinned one pops up again;
it never covers the sky-map walkthrough (one after the other)."""
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
        page.get_by_test_id('pinned-announcement-close').click()
        expect(box).to_have_count(0)
        # Dismissed: no popup on the next page or after a reload; the older pinned one does not follow.
        page.goto(portal_site + '/leaderboard?lang=zh', wait_until='domcontentloaded')
        page.wait_for_timeout(1500)
        expect(popup_box(page)).to_have_count(0)
        assert sorted(page.evaluate("JSON.parse(localStorage.getItem('sac.pinned-announcements.seen'))")) == sorted([str(older), str(talk)])

        # A newer pinned announcement pops up again (English); Esc closes it too.
        announce(uri, 'Newer ' + tag, 'fresh news')
        page.goto(portal_site + '/faq?lang=en', wait_until='domcontentloaded')
        expect(popup_box(page)).to_contain_text('Newer ' + tag + ' (en)', timeout=15000)
        expect(popup_box(page)).to_contain_text('2 more pinned')
        page.keyboard.press('Escape')
        expect(popup_box(page)).to_have_count(0)
        context.close()

        # First visit to the home page: the sky-map walkthrough and the popup take turns, never both at once.
        home = browser.new_context(viewport={'width': 1365, 'height': 900}).new_page()
        home.on('pageerror', lambda e: errors.append(str(e)))
        home.goto(portal_site + '/?lang=zh', wait_until='domcontentloaded')
        tour, popup = home.locator('.sky-tour-shade'), popup_box(home)
        expect(popup).to_have_count(1, timeout=15000)  # the announcements have arrived
        home.wait_for_timeout(500)
        assert tour.is_visible() != popup.is_visible(), 'exactly one of the two is open'
        if tour.is_visible():
            home.get_by_test_id('sky-tour-close').click()
            expect(popup).to_be_visible()
            home.get_by_role('button', name='知道了').click()
        else:
            home.get_by_role('button', name='知道了').click()
            expect(tour).to_be_visible()
            home.get_by_test_id('sky-tour-close').click()
        expect(popup).to_have_count(0)
        expect(tour).to_have_count(0)
        # "See all announcements" leads to the list, which is never covered.
        home.evaluate("localStorage.removeItem('sac.pinned-announcements.seen')")
        home.goto(portal_site + '/start?lang=en', wait_until='domcontentloaded')
        home.get_by_test_id('pinned-announcement-all').click()
        expect(home).to_have_url(portal_site + '/announcements')
        expect(popup_box(home)).to_have_count(0)
        expect(home.locator('main')).to_contain_text('Talk ' + tag + ' (en)')

        # On a phone the poster fits the screen and the dialog scrolls; nothing overflows sideways.
        phone = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True).new_page()
        phone.on('pageerror', lambda e: errors.append(str(e)))
        query(uri, "update public.announcements set is_pinned=false where title_en like %s", ('Newer ' + tag + '%',))
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
