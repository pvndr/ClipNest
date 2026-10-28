"""Tests for sidebar navigation, category filtering, selection, and states."""

from __future__ import annotations

import pytest

from clipnest.core.storage import ClipboardRepository
from clipnest.ui.main_window import MainWindow
from tests.fakes import FakeClipboard

TEXT_SNIPPET = "Remember the milk"
LINK_SNIPPET = "https://example.com/pricing"
CODE_SNIPPET = "print('hello world')"


def _capture_sample_set(fake_clipboard: FakeClipboard) -> None:
    fake_clipboard.simulate_copy(TEXT_SNIPPET)
    fake_clipboard.simulate_copy(LINK_SNIPPET)
    fake_clipboard.simulate_copy(CODE_SNIPPET)


def _visible_texts(window: MainWindow, repository: ClipboardRepository) -> list[str]:
    texts = []
    for card in window.history_view.rows:
        entry = repository.get(card.entry_id)
        assert entry is not None
        texts.append(entry.text)
    return texts


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("text", [TEXT_SNIPPET]),
        ("link", [LINK_SNIPPET]),
        ("code", [CODE_SNIPPET]),
    ],
)
def test_sidebar_filters_by_content_type(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
    category: str,
    expected: list[str],
) -> None:
    _capture_sample_set(fake_clipboard)

    window.sidebar.buttons()[category].click()

    assert window.sidebar.current_category == category
    assert _visible_texts(window, repository) == expected


def test_all_category_shows_every_entry(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
) -> None:
    _capture_sample_set(fake_clipboard)
    window.sidebar.buttons()["link"].click()

    window.sidebar.buttons()["all"].click()

    assert window.history_view.count() == 3


def test_pinned_category_shows_only_pinned_entries(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    _capture_sample_set(fake_clipboard)
    oldest = window.history_view.rows[-1]
    oldest.pin_button.click()

    window.sidebar.buttons()["pinned"].click()

    assert _visible_texts(window, repository) == [TEXT_SNIPPET]


@pytest.mark.parametrize(
    ("category", "expected_title"),
    [
        ("all", "No clipboard history yet"),
        ("pinned", "No pinned snippets"),
        ("text", "No text snippets"),
        ("link", "No links yet"),
        ("code", "No code snippets"),
    ],
)
def test_each_category_has_its_own_empty_state(
    window: MainWindow, category: str, expected_title: str
) -> None:
    window.sidebar.buttons()[category].click()

    assert window.history_view.is_showing_state() is True
    assert window.history_view.state_panel.title_label.text() == expected_title


def test_empty_category_filter_reports_no_matches_of_that_kind(
    window: MainWindow, fake_clipboard: FakeClipboard
) -> None:
    fake_clipboard.simulate_copy(TEXT_SNIPPET)

    window.sidebar.buttons()["link"].click()

    assert window.history_view.count() == 0
    assert window.history_view.state_panel.title_label.text() == "No links yet"


def test_search_without_results_offers_a_clear_action(
    window: MainWindow, fake_clipboard: FakeClipboard
) -> None:
    fake_clipboard.simulate_copy(TEXT_SNIPPET)
    window.search_input.setText("nothing matches this")

    assert window.history_view.is_showing_state() is True
    assert 'No matches for "nothing matches this"' == (
        window.history_view.state_panel.title_label.text()
    )
    assert window.history_view.state_panel.action_button.isHidden() is False

    window.history_view.state_panel.action_button.click()

    assert window.search_input.text() == ""
    assert window.history_view.count() == 1


def test_selection_updates_the_detail_panel(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("alpha entry")
    fake_clipboard.simulate_copy("beta entry")
    alpha = next(
        entry for entry in repository.list_entries() if entry.text == "alpha entry"
    )

    window.history_view.select(alpha.id)

    assert window.history_view.selected_id == alpha.id
    assert window.detail_panel.entry_id == alpha.id
    assert window.detail_panel.content.toPlainText() == "alpha entry"


def test_search_keeps_the_selection_when_it_still_matches(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("alpha entry")
    fake_clipboard.simulate_copy("beta entry")
    alpha = next(
        entry for entry in repository.list_entries() if entry.text == "alpha entry"
    )
    window.history_view.select(alpha.id)

    window.search_input.setText("alpha")

    assert window.history_view.selected_id == alpha.id
    assert window.detail_panel.content.toPlainText() == "alpha entry"


def test_filtered_out_selection_falls_back_to_the_first_card(
    window: MainWindow, fake_clipboard: FakeClipboard
) -> None:
    fake_clipboard.simulate_copy("alpha entry")
    fake_clipboard.simulate_copy("beta entry")

    window.search_input.setText("beta")

    assert window.history_view.count() == 1
    assert window.history_view.selected_id == window.history_view.rows[0].entry_id


def test_capture_while_searching_keeps_the_search_and_selection(
    window: MainWindow, fake_clipboard: FakeClipboard
) -> None:
    fake_clipboard.simulate_copy("alpha entry")
    window.search_input.setText("alpha")
    selected = window.history_view.selected_id

    fake_clipboard.simulate_copy("alpha entry two")

    assert window.search_input.text() == "alpha"
    assert window.history_view.count() == 2
    assert window.history_view.selected_id in {
        selected,
        window.history_view.rows[0].entry_id,
    }


def test_detail_panel_collapses_on_narrow_windows(window: MainWindow, qapp) -> None:
    # resize events are only delivered to a visible window, so show it here.
    window.show()
    qapp.processEvents()
    window.resize(1200, 760)
    qapp.processEvents()
    assert window.detail_panel.isHidden() is False

    window.resize(820, 700)
    qapp.processEvents()

    assert window.detail_panel.isHidden() is True
    assert window.sidebar.buttons()["all"].toolButtonStyle().name == "ToolButtonIconOnly"


def test_detail_panel_returns_when_the_window_widens_again(
    window: MainWindow, qapp
) -> None:
    window.show()
    window.resize(820, 700)
    qapp.processEvents()
    window.resize(1200, 760)
    qapp.processEvents()

    assert window.detail_panel.isHidden() is False
    assert (
        window.sidebar.buttons()["all"].toolButtonStyle().name
        == "ToolButtonTextBesideIcon"
    )


def test_keyboard_navigation_moves_the_selection(
    window: MainWindow, fake_clipboard: FakeClipboard
) -> None:
    fake_clipboard.simulate_copy("first")
    fake_clipboard.simulate_copy("second")
    window.history_view.select(window.history_view.rows[0].entry_id)
    first_id = window.history_view.selected_id

    window.history_view._move_selection(1)

    assert window.history_view.selected_id == window.history_view.rows[1].entry_id
    assert window.history_view.selected_id != first_id
