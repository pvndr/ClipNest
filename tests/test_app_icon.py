"""Tests for the application icon asset lookup.

ClipNest ships supplied artwork: ``clipnest.ico`` (multi-size Windows icon)
and ``clipnest_icon_transparent.png`` (transparent source). These tests pin the
paths, prove missing/corrupt/valid files are told apart, and check the shipped
assets really decode.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap

from clipnest.core.clipboard import ClipboardService
from clipnest.core.storage import ClipboardRepository
from clipnest.ui.app_icon import (
    APP_ICON_PATH,
    FALLBACK_ICON_PATHS,
    icon_candidates,
    load_app_icon,
)
from clipnest.ui.main_window import MainWindow
from tests.fakes import FakeClipboard

SHIPPED_PNG = Path(FALLBACK_ICON_PATHS[0])


def test_expected_asset_path_is_documented_and_inside_the_package() -> None:
    assert APP_ICON_PATH.name == "clipnest.ico"
    assert APP_ICON_PATH.parent.name == "assets"
    assert APP_ICON_PATH.parent.parent.name == "clipnest"
    assert icon_candidates()[0] == APP_ICON_PATH


def test_fallback_matches_the_supplied_png_source() -> None:
    assert icon_candidates()[-1].name == "clipnest_icon_transparent.png"


def test_missing_asset_yields_no_icon(qapp, tmp_path) -> None:
    assert load_app_icon([tmp_path / "clipnest.ico"]) is None


def test_corrupt_asset_is_rejected(qapp, tmp_path) -> None:
    path = tmp_path / "clipnest.ico"
    path.write_bytes(b"this is not an icon")

    assert load_app_icon([path]) is None


def test_valid_asset_is_loaded(qapp, tmp_path) -> None:
    path = tmp_path / "clipnest.png"
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.magenta)
    assert pixmap.save(str(path))

    icon = load_app_icon([tmp_path / "missing.ico", path])

    assert icon is not None
    assert icon.isNull() is False


def test_window_uses_the_supplied_icon(
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    tmp_path: Path,
) -> None:
    path = tmp_path / "clipnest.png"
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.magenta)
    assert pixmap.save(str(path))
    icon = load_app_icon([path])
    assert icon is not None

    window = MainWindow(
        repository=repository,
        clipboard_service=ClipboardService(fake_clipboard, repository),
        window_icon=icon,
    )

    assert window.windowIcon().isNull() is False
    window.deleteLater()


# ------------------------------------------------- the shipped icon files


def test_shipped_ico_is_a_valid_multi_size_windows_icon(qapp) -> None:
    assert APP_ICON_PATH.is_file(), f"missing asset: {APP_ICON_PATH}"

    reader = QImageReader(str(APP_ICON_PATH))
    assert reader.canRead()
    assert bytes(reader.format()).decode() == "ico"
    assert reader.imageCount() >= 5

    sizes = set()
    frame = QImage()
    for index in range(reader.imageCount()):
        assert reader.jumpToImage(index)
        frame = reader.read()
        assert frame.isNull() is False
        sizes.add((frame.width(), frame.height()))

    for expected in (16, 32, 48, 256):
        assert (expected, expected) in sizes
    assert frame.hasAlphaChannel()


def test_shipped_ico_loads_through_the_lookup(qapp) -> None:
    icon = load_app_icon()

    assert icon is not None, "the shipped .ico should be picked up"
    for size in (16, 32, 48):
        pixmap = icon.pixmap(QSize(size, size))
        assert pixmap.isNull() is False
        assert pixmap.width() > 0


def test_shipped_png_source_has_a_transparent_background(qapp) -> None:
    assert SHIPPED_PNG.is_file(), f"missing asset: {SHIPPED_PNG}"

    image = QImage(str(SHIPPED_PNG))
    assert image.isNull() is False
    assert image.hasAlphaChannel()

    # Transparent margin all round, artwork in the middle.
    for x, y in ((0, 0), (image.width() - 1, 0), (0, image.height() - 1)):
        assert image.pixelColor(x, y).alpha() == 0
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(0, image.width(), 16)
        for y in range(0, image.height(), 16)
    )
