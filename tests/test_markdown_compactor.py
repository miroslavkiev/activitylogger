"""Regression tests for trustworthy Markdown compaction."""

from __future__ import annotations

import hashlib
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import clean_markdown_log as compactor


REPO = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def test_parser_requires_immediate_timestamp_and_tracks_fences():
    lines = [
        "# Work Log\n",
        "## Not generated\n",
        "ordinary prose\n",
        "## Real\n",
        "*12:00:00*\n",
        "````text\n",
        "## Captured heading\n",
        "*13:00:00*\n",
        "```\n",
        "````\n",
        "## Next\n",
        "*14:00:00*\n",
        "event\n",
    ]
    preamble, sections = compactor.split_into_preamble_and_sections(lines)
    assert "## Not generated\n" in preamble
    assert [section.header for section in sections] == ["## Real\n", "## Next\n"]
    assert "## Captured heading\n" in sections[0].body


def test_generic_event_transforms_do_not_cross_fences():
    body = [
        "```text\n",
        "same\n",
        "same\n",
        "## captured\n",
        "```\n",
        "outside\n",
        "outside\n",
    ]
    output = compactor.sanitize_section_body(body)
    assert output.count("same\n") == 2
    assert "## captured\n" in output
    assert "outside (x2)\n" in output


def test_repeat_marker_counts_only_omitted_copies():
    lines = ["same\n"] * (compactor.INTRA_BLOCK_REPEAT_THRESHOLD + 2)
    output = compactor.compress_repeated_lines_in_code_block(lines)
    assert output == [
        "same\n",
        "... [Previous line repeated 4 times]\n",
    ]


def test_traceback_compaction_accepts_standard_source_lines():
    traceback_lines = ["Traceback (most recent call last):\n"]
    for index in range(compactor.TRACEBACK_MAX_LINES):
        traceback_lines.extend(
            [
                f'  File "/tmp/example.py", line {index + 1}, in run\n',
                "    call_that_failed()\n",
            ]
        )
    traceback_lines.extend(["RuntimeError: failed\n", "normal work\n"])
    output = compactor.compress_traceback_blocks(traceback_lines)
    assert any("Truncated" in line for line in output)
    assert "RuntimeError: failed\n" in output
    assert output[-1] == "normal work\n"


def test_atomic_output_is_private_and_preserves_previous_file_on_failure(
    tmp_path: Path,
):
    destination = tmp_path / "day_compacted.md"
    destination.write_text("previous\n", encoding="utf-8")

    def failing_lines():
        yield "replacement\n"
        raise RuntimeError("write failed")

    with pytest.raises(RuntimeError, match="write failed"):
        compactor.write_text_file(str(destination), failing_lines())
    assert destination.read_text(encoding="utf-8") == "previous\n"
    assert list(tmp_path.glob(".day_compacted.md.*.tmp")) == []

    compactor.write_text_file(str(destination), ["complete\n"])
    assert destination.read_text(encoding="utf-8") == "complete\n"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_compact_file_streams_input_and_output(tmp_path: Path, monkeypatch):
    source = tmp_path / "daily_log.md"
    source.write_text(
        "# Work Log\n\n## App\n*12:00:00*\nactivity\n",
        encoding="utf-8",
    )
    observed: list[str] = []

    def capture_stream(path: str, lines):
        assert not isinstance(lines, list)
        observed.extend(lines)

    monkeypatch.setattr(compactor, "write_text_file", capture_stream)
    monkeypatch.setattr(
        compactor,
        "read_text_file",
        lambda path: pytest.fail("compact_file must not load the whole input"),
    )
    compactor.compact_file(str(source), str(tmp_path / "out.md"))
    assert observed[0] == "# Work Log\n"
    assert observed[-1] == "activity\n"


def test_small_section_keeps_full_compaction_semantics():
    warnings: list[str] = []
    output = "".join(
        compactor.iter_compacted_lines(
            ["## App\n", "*12:00:00*\n", "same\n", "\n", "same\n"],
            warn=warnings.append,
        )
    )
    assert "same (x2)\n" in output
    assert warnings == []


def test_single_large_section_uses_bounded_safe_mode(tmp_path: Path):
    source = tmp_path / "large.md"
    destination = tmp_path / "large_compacted.md"
    target_size = 20 * 1024 * 1024
    with source.open("w", encoding="utf-8") as output:
        output.write("# Work Log\n\n## Large\n*12:00:00*\n```text\n")
        index = 0
        while output.tell() < target_size:
            output.write(f"payload-{index:08d} " + ("x" * 220) + "\n")
            index += 1
        output.write("## Captured heading\n*13:00:00*\n```\nfinal sentinel\n")

    probe = """
import resource
import sys

import clean_markdown_log as compactor

compactor.compact_file(sys.argv[1], sys.argv[2])
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
if sys.platform != "darwin":
    rss *= 1024
print(f"PEAK_RSS_BYTES={rss}", file=sys.stderr)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(source), str(destination)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    peak_line = next(
        line for line in result.stderr.splitlines() if line.startswith("PEAK_RSS_BYTES=")
    )
    peak_rss = int(peak_line.partition("=")[2])

    assert "bounded safe mode" in result.stderr
    assert peak_rss < 64 * 1024 * 1024
    assert source.stat().st_size >= target_size
    assert destination.stat().st_size == source.stat().st_size
    assert _sha256(destination) == _sha256(source)


def test_cli_uses_compact_term_and_always_warns_plaintext(tmp_path: Path, capsys):
    source = tmp_path / "daily_log.md"
    source.write_text(
        "# Work Log\n\n## App\n*12:00:00*\nactivity\n",
        encoding="utf-8",
    )
    assert compactor.main([str(source)]) == 0
    captured = capsys.readouterr()
    assert "does not redact secrets" in captured.err
    assert "sensitive plaintext" in captured.err
    output = Path(captured.out.strip())
    assert output.name == "daily_log_compacted.md"
    assert output.is_file()


def test_analysis_prompt_rejects_instructions_from_logs():
    prompt = (
        Path(__file__).resolve().parents[1]
        / "prompts"
        / "gemini-automation-analysis.md"
    ).read_text(encoding="utf-8")
    assert "untrusted data" in prompt
    assert "Do not follow" in prompt
    assert "explicit human review" in prompt
