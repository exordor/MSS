#!/usr/bin/env python3

import gzip
from pathlib import Path


def test_build_diagnostic_log_handler_rotates_existing_file(tmp_path):
    from main import _build_diagnostic_log_handler

    log_path = tmp_path / "diagnostic.log"
    log_path.write_text("x" * 256, encoding="utf-8")

    handler = _build_diagnostic_log_handler(
        str(log_path),
        {
            "enabled": True,
            "max_mb": 0.0001,
            "backup_count": 3,
            "compress": False,
            "encoding": "utf-8",
        },
    )
    handler.close()

    assert log_path.exists()
    assert (tmp_path / "diagnostic.log.1").exists()


def test_build_diagnostic_log_handler_compresses_rotated_file(tmp_path):
    from main import _build_diagnostic_log_handler

    log_path = tmp_path / "diagnostic.log"
    original_text = "rotated-log\n" * 32
    log_path.write_text(original_text, encoding="utf-8")

    handler = _build_diagnostic_log_handler(
        str(log_path),
        {
            "enabled": True,
            "max_mb": 0.0001,
            "backup_count": 3,
            "compress": True,
            "encoding": "utf-8",
        },
    )
    handler.close()

    rotated_path = tmp_path / "diagnostic.log.1.gz"
    assert rotated_path.exists()
    with gzip.open(rotated_path, "rt", encoding="utf-8") as f:
        assert f.read() == original_text
