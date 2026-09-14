"""The export health check's log parser and finding rules, without ffmpeg."""

from __future__ import annotations

from app.domain.editor import analysis

SAMPLE_LOG = """
[blackdetect @ 0x1] black_start:0 black_end:2.04 black_duration:2.04
[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 0.5
[freezedetect @ 0x2] lavfi.freezedetect.freeze_duration: 1.6
[freezedetect @ 0x2] lavfi.freezedetect.freeze_end: 2.1
[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 6
[silencedetect @ 0x3] silence_start: 3.0
[silencedetect @ 0x3] silence_end: 5.5 | silence_duration: 2.5
[Parsed_ebur128_1 @ 0x4] Summary:

  Integrated loudness:
    I:         -21.3 LUFS
    Threshold: -31.6 LUFS

  True peak:
    Peak:       -0.4 dBFS
"""


def test_the_parser_reads_every_detector_and_the_loudness_summary() -> None:
    parsed = analysis.parse_qa_output(SAMPLE_LOG, duration_seconds=9.0)
    assert parsed["black"] == [(0.0, 2.04)]
    # The second freeze never ends before end of stream — it runs to 9s.
    assert parsed["freeze"] == [(0.5, 1.6), (6.0, 3.0)]
    assert parsed["silence"] == [(3.0, 2.5)]
    assert parsed["integrated_lufs"] == -21.3
    assert parsed["true_peak_dbfs"] == -0.4


def test_findings_cover_what_a_viewer_would_notice() -> None:
    parsed = analysis.parse_qa_output(SAMPLE_LOG, duration_seconds=9.0)
    findings = analysis.qa_findings(parsed, has_audio=True)
    assert [(f["code"], f["severity"], f["at_seconds"]) for f in findings] == [
        ("black_frames", "warning", 0.0),
        # The 1.6s freeze is too short; the 3s one at 6s is reported.
        ("frozen_frames", "info", 6.0),
        ("long_silence", "info", 3.0),
        ("loudness_off_target", "info", None),
        ("true_peak_clipping", "warning", None),
    ]
    assert findings[3]["value"] == -21.3


def test_a_black_stretch_is_not_also_reported_as_frozen() -> None:
    parsed = {
        "black": [(0.0, 4.0)],
        "freeze": [(1.0, 3.0)],
        "silence": [],
        "integrated_lufs": -14.2,
        "true_peak_dbfs": -2.0,
    }
    assert [f["code"] for f in analysis.qa_findings(parsed, has_audio=True)] == ["black_frames"]


def test_a_silent_export_reports_no_audio_instead_of_loudness() -> None:
    parsed = analysis.parse_qa_output("", duration_seconds=5.0)
    assert [f["code"] for f in analysis.qa_findings(parsed, has_audio=False)] == ["no_audio"]


def test_an_on_target_mix_is_clean() -> None:
    parsed = analysis.parse_qa_output(
        "  I:         -14.8 LUFS\n  Peak:       -1.6 dBFS\n", duration_seconds=5.0
    )
    assert analysis.qa_findings(parsed, has_audio=True) == []
