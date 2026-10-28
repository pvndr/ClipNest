"""Icon set for ClipNest, rendered from inline SVG.

Keeping the paths in code avoids shipping binary assets and lets every icon be
re-coloured for hover/selected/theme states. QtSvg ships with PySide6, so this
adds no dependency.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_ICON_BODIES: dict[str, str] = {
    "all": (
        '<path d="M12 3 3 7.5 12 12l9-4.5L12 3Z"/>'
        '<path d="M3 12l9 4.5L21 12"/>'
        '<path d="M3 16.5 12 21l9-4.5"/>'
    ),
    "pinned": '<path d="M6 4h12v17l-6-4-6 4V4Z"/>',
    "text": '<path d="M4 6h16"/><path d="M4 12h11"/><path d="M4 18h14"/>',
    "link": (
        '<path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.3-2.3a4 4 0 0 0-5.7-5.7l-1.2 1.2"/>'
        '<path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.3 2.3a4 4 0 0 0 5.7 5.7l1.2-1.2"/>'
    ),
    "code": '<path d="M9 8l-4 4 4 4"/><path d="M15 8l4 4-4 4"/>',
    "settings": (
        '<path d="M4 7h4"/><path d="M12 7h8"/>'
        '<path d="M4 17h10"/><path d="M18 17h2"/>'
        '<circle cx="10" cy="7" r="2"/><circle cx="16" cy="17" r="2"/>'
    ),
    "about": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 11v5"/><path d="M12 8h.01"/>'
    ),
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
    "close": '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    "copy": (
        '<rect x="9" y="9" width="11" height="11" rx="2"/>'
        '<path d="M15 6.5V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h1.5"/>'
    ),
    "trash": (
        '<path d="M4 7h16"/><path d="M9 7V4.5h6V7"/>'
        '<path d="M6.5 7l.8 12.5h9.4L17.5 7"/>'
        '<path d="M10.5 11v5"/><path d="M13.5 11v5"/>'
    ),
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": (
        '<path d="M10.3 4.3 2.7 17.4A1.8 1.8 0 0 0 4.3 20h15.4a1.8 1.8 0 0 0 '
        '1.6-2.6L13.7 4.3a1.9 1.9 0 0 0-3.4 0Z"/>'
        '<path d="M12 9v4.5"/><path d="M12 17h.01"/>'
    ),
    "pause": '<path d="M9 5v14"/><path d="M15 5v14"/>',
    "play": '<path d="M7 4.5 19 12 7 19.5V4.5Z"/>',
    "inbox": (
        '<path d="M3 12.5h5l1.5 3h5l1.5-3h5"/>'
        '<path d="M5.5 4.5h13l2.5 8v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5l2.5-8Z"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "database": (
        '<ellipse cx="12" cy="6" rx="7.5" ry="3"/>'
        '<path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"/>'
        '<path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3"/>'
    ),
    "shield": (
        '<path d="M12 3.5 5 6v6c0 4.2 3 7.4 7 8.5 4-1.1 7-4.3 7-8.5V6l-7-2.5Z"/>'
        '<path d="M9 12l2 2 4-4"/>'
    ),
    "trim": (
        '<path d="M4 7h9"/><path d="M17 7h3"/>'
        '<path d="M4 12h5"/><path d="M13 12h7"/>'
        '<path d="M4 17h16"/>'
    ),
}

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="{fill}" stroke="{color}" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)


def pixmap(name: str, color: str, size: int = 18, filled: bool = False) -> QPixmap:
    """Render ``name`` as a device-independent pixmap, cached per colour."""
    return _render(name, color, size, filled)


def icon(name: str, color: str, size: int = 18, filled: bool = False) -> QIcon:
    """Return ``name`` as a QIcon tinted with ``color``."""
    return QIcon(pixmap(name, color, size, filled))


@lru_cache(maxsize=256)
def _render(name: str, color: str, size: int, filled: bool) -> QPixmap:
    body = _ICON_BODIES.get(name)
    if body is None:
        raise KeyError(f"Unknown icon: {name!r}")

    svg = _SVG_TEMPLATE.format(
        fill=color if filled else "none", color=color, body=body
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    # Paint at 2x while the pixmap is still 1:1, then declare the pixel ratio.
    # Setting it first would apply a scale transform and clip the 24x24 view box.
    scale = 2
    canvas = QPixmap(size * scale, size * scale)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    try:
        renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
    finally:
        painter.end()

    canvas.setDevicePixelRatio(scale)
    return canvas


def icon_names() -> tuple[str, ...]:
    """Names available to callers (useful for tests)."""
    return tuple(_ICON_BODIES)
