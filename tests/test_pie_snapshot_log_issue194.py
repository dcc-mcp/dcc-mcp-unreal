"""Focused behavioral tests for issue #194 pie log snapshots."""

from __future__ import annotations

from pathlib import Path

from test_pie_skill import _import_script, _patch_unreal


def _write_log(tmp_path: Path, text: str) -> None:
    log_dir = tmp_path / "Saved" / "Logs"
    log_dir.mkdir(parents=True)
    (log_dir / "Game.log").write_text(text, encoding="utf-8")


def test_filter_matches_category_not_message_body(tmp_path, monkeypatch):
    """A category filter must not match asset names in the message body."""
    _write_log(
        tmp_path,
        "[2026.08.29-10.00.00:000]LogScript: Warning: BP_ShooterEnemyAI asset path\n"
        "[2026.08.29-10.00.01:000]LogCombat: Display: Shoot event\n",
    )
    with _patch_unreal() as _:
        import unreal

        unreal.Paths.project_dir.return_value = str(tmp_path)
        mod = _import_script("pie_snapshot_log")
        result = mod.pie_snapshot_log(filter="Shoot", include_verbosity=False)

    assert result["success"] is True
    assert result["context"]["entries"] == []


def test_time_window_cursor_and_dedupe_report_occurrences(tmp_path):
    """Time/cursor bounds and dedupe keep output bounded while counting repeats."""
    _write_log(
        tmp_path,
        "[2026.08.29-10.00.00:000]LogScript: Warning: noisy warning\n"
        "[2026.08.29-10.00.01:000]LogScript: Warning: noisy warning\n"
        "[2026.08.29-10.00.02:000]LogCombat: Display: Damage dealt\n"
        "[2026.08.29-10.00.03:000]LogCombat: Display: Damage dealt\n",
    )
    with _patch_unreal():
        import unreal

        unreal.Paths.project_dir.return_value = str(tmp_path)
        mod = _import_script("pie_snapshot_log")
        result = mod.pie_snapshot_log(
            since_timestamp="2026-08-29T10:00:01Z",
            until_timestamp="2026-08-29T10:00:03Z",
            dedupe=True,
            max_lines=1,
            include_verbosity=False,
        )

    context = result["context"]
    assert context["entries"] == ["[2026.08.29-10.00.03:000]LogCombat: Display: Damage dealt"]
    assert context["occurrence_counts"] == [2]
    assert context["next_cursor"] == "4"


def test_cursor_rejects_malformed_and_limits_max_lines(tmp_path):
    """Malformed cursors fail closed and max_lines is clamped to a safe bound."""
    _write_log(tmp_path, "LogTest: Display: one\n")
    with _patch_unreal():
        import unreal

        unreal.Paths.project_dir.return_value = str(tmp_path)
        mod = _import_script("pie_snapshot_log")
        bad = mod.pie_snapshot_log(cursor="not-a-cursor")
        bounded = mod.pie_snapshot_log(max_lines=999999, include_verbosity=False)

    assert bad["success"] is False
    assert bounded["context"]["max_lines"] == 2000


def test_unreal_log_path_uses_same_category_and_message_semantics(tmp_path):
    """The unreal.log fallback applies the same parser/filter contract."""
    with _patch_unreal():
        import unreal

        unreal.Paths.project_dir.return_value = str(tmp_path)
        unreal.log.get_log.return_value = (
            "[2026.08.29-10.00.00:000]LogScript: Warning: BP_ShooterEnemyAI\n"
            "[2026.08.29-10.00.01:000]LogCombat: Display: Shoot event\n"
        )
        mod = _import_script("pie_snapshot_log")
        result = mod.pie_snapshot_log(filter="Shoot", include_verbosity=False)

    assert result["success"] is True
    assert result["context"]["entries"] == []
