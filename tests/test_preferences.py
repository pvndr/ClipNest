"""Tests for QSettings-backed preferences.

Every test writes to a throwaway INI file (the ``preferences`` fixture), never
to the per-user registry the real application uses.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from clipnest.core.storage import DEFAULT_HISTORY_LIMIT, MAX_RETENTION_DAYS
from clipnest.preferences import (
    DEFAULT_PAUSED,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SENSITIVE_DETECTION,
    DEFAULT_THEME,
    HISTORY_LIMIT_KEY,
    MAX_HISTORY_LIMIT,
    MIN_HISTORY_LIMIT,
    PAUSED_KEY,
    RETENTION_DAYS_KEY,
    SENSITIVE_DETECTION_KEY,
    THEME_KEY,
    Preferences,
    validate_history_limit,
)


def _store(tmp_path, name: str = "raw.ini") -> QSettings:
    return QSettings(str(tmp_path / name), QSettings.Format.IniFormat)


def test_defaults_are_dark_and_five_hundred(preferences: Preferences) -> None:
    assert preferences.theme() == DEFAULT_THEME == "dark"
    assert preferences.history_limit() == DEFAULT_HISTORY_LIMIT == 500


def test_theme_survives_a_new_preferences_instance(tmp_path) -> None:
    store = _store(tmp_path)

    Preferences(store).set_theme("light")

    assert Preferences(_store(tmp_path)).theme() == "light"


def test_history_limit_survives_a_new_preferences_instance(tmp_path) -> None:
    store = _store(tmp_path)

    Preferences(store).set_history_limit(120)

    assert Preferences(_store(tmp_path)).history_limit() == 120


def test_unknown_stored_theme_falls_back_to_dark(tmp_path) -> None:
    store = _store(tmp_path)
    store.setValue(THEME_KEY, "midnight")
    store.sync()

    assert Preferences(store).theme() == DEFAULT_THEME


def test_unusable_stored_limit_falls_back_to_the_default(tmp_path) -> None:
    store = _store(tmp_path)
    store.setValue(HISTORY_LIMIT_KEY, "not-a-number")
    store.sync()

    assert Preferences(store).history_limit() == DEFAULT_HISTORY_LIMIT


def test_out_of_range_stored_limit_falls_back_to_the_default(tmp_path) -> None:
    store = _store(tmp_path)
    store.setValue(HISTORY_LIMIT_KEY, 10_000_000)
    store.sync()

    assert Preferences(store).history_limit() == DEFAULT_HISTORY_LIMIT


def test_set_theme_rejects_an_unknown_name(preferences: Preferences) -> None:
    with pytest.raises(ValueError):
        preferences.set_theme("sepia")

    assert preferences.theme() == DEFAULT_THEME


def test_set_history_limit_rejects_out_of_range_values(
    preferences: Preferences,
) -> None:
    for value in (MIN_HISTORY_LIMIT - 1, 0, -5, MAX_HISTORY_LIMIT + 1):
        with pytest.raises(ValueError):
            preferences.set_history_limit(value)

    assert preferences.history_limit() == DEFAULT_HISTORY_LIMIT


def test_validate_history_limit_accepts_the_boundaries() -> None:
    assert validate_history_limit(MIN_HISTORY_LIMIT) == MIN_HISTORY_LIMIT
    assert validate_history_limit(MAX_HISTORY_LIMIT) == MAX_HISTORY_LIMIT


def test_validate_history_limit_rejects_non_integers() -> None:
    for value in ("250", 250.5, None, True):
        with pytest.raises(ValueError):
            validate_history_limit(value)


# ------------------------------------------------------------------ privacy

def test_sensitive_detection_is_on_by_default(preferences: Preferences) -> None:
    assert preferences.sensitive_detection_enabled() is True
    assert DEFAULT_SENSITIVE_DETECTION is True


def test_sensitive_detection_survives_a_new_preferences_instance(tmp_path) -> None:
    store = _store(tmp_path)

    Preferences(store).set_sensitive_detection(False)

    assert Preferences(_store(tmp_path)).sensitive_detection_enabled() is False


def test_reenabling_sensitive_detection_survives_a_new_instance(tmp_path) -> None:
    Preferences(_store(tmp_path)).set_sensitive_detection(False)

    Preferences(_store(tmp_path)).set_sensitive_detection(True)

    assert Preferences(_store(tmp_path)).sensitive_detection_enabled() is True


@pytest.mark.parametrize("stored", ["perhaps", "", 7, None])
def test_unusable_sensitive_setting_falls_back_to_the_default(
    tmp_path, stored
) -> None:
    store = _store(tmp_path)
    if stored is not None:  # ``None`` leaves the key absent
        store.setValue(SENSITIVE_DETECTION_KEY, stored)

    assert Preferences(store).sensitive_detection_enabled() is True


@pytest.mark.parametrize("stored", ["false", "0", "no", "off"])
def test_false_like_stored_values_disable_detection(tmp_path, stored) -> None:
    store = _store(tmp_path)
    store.setValue(SENSITIVE_DETECTION_KEY, stored)

    assert Preferences(store).sensitive_detection_enabled() is False


# ---------------------------------------------------------------- retention


def test_age_expiry_is_disabled_by_default(preferences: Preferences) -> None:
    assert preferences.retention_days() is None
    assert DEFAULT_RETENTION_DAYS is None


def test_age_limit_survives_a_new_preferences_instance(tmp_path) -> None:
    Preferences(_store(tmp_path)).set_retention_days(30)

    assert Preferences(_store(tmp_path)).retention_days() == 30


def test_disabling_age_expiry_is_remembered(tmp_path) -> None:
    Preferences(_store(tmp_path)).set_retention_days(30)

    Preferences(_store(tmp_path)).set_retention_days(None)

    assert Preferences(_store(tmp_path)).retention_days() is None


@pytest.mark.parametrize("stored", ["", "0", "none", "off", "disabled"])
def test_disabled_markers_read_as_none(tmp_path, stored) -> None:
    store = _store(tmp_path)
    store.setValue(RETENTION_DAYS_KEY, stored)

    assert Preferences(store).retention_days() is None


@pytest.mark.parametrize("stored", ["soon", -5, MAX_RETENTION_DAYS + 10, 0.5])
def test_unusable_stored_age_limit_falls_back_to_disabled(tmp_path, stored) -> None:
    store = _store(tmp_path)
    store.setValue(RETENTION_DAYS_KEY, stored)

    assert Preferences(store).retention_days() is None


def test_set_retention_days_rejects_out_of_range_values(
    preferences: Preferences,
) -> None:
    with pytest.raises(ValueError):
        preferences.set_retention_days(0)
    with pytest.raises(ValueError):
        preferences.set_retention_days(MAX_RETENTION_DAYS + 1)


# ---------------------------------------------------------------- monitoring


def test_monitoring_starts_unpaused_by_default(preferences: Preferences) -> None:
    assert preferences.monitoring_paused() is DEFAULT_PAUSED is False


def test_pause_state_survives_a_new_preferences_instance(tmp_path) -> None:
    Preferences(_store(tmp_path)).set_monitoring_paused(True)

    assert Preferences(_store(tmp_path)).monitoring_paused() is True


def test_resuming_is_remembered(tmp_path) -> None:
    Preferences(_store(tmp_path)).set_monitoring_paused(True)

    Preferences(_store(tmp_path)).set_monitoring_paused(False)

    assert Preferences(_store(tmp_path)).monitoring_paused() is False


@pytest.mark.parametrize("stored", ["sometimes", "2", "unknown"])
def test_unreadable_pause_state_reports_none(tmp_path, stored) -> None:
    # ``None`` is not a default: it tells the caller the value exists but is
    # unusable, so startup can stay paused instead of resuming capture.
    store = _store(tmp_path)
    store.setValue(PAUSED_KEY, stored)

    assert Preferences(store).monitoring_paused() is None


def test_monitoring_notice_flag_starts_unset(preferences: Preferences) -> None:
    assert preferences.monitoring_notice_shown() is False


def test_monitoring_notice_flag_survives_a_new_preferences_instance(tmp_path) -> None:
    Preferences(_store(tmp_path)).set_monitoring_notice_shown(True)

    assert Preferences(_store(tmp_path)).monitoring_notice_shown() is True
