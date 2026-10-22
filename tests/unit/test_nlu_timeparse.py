"""
tests/unit/test_nlu_timeparse.py
---------------------------------
Unit tests for nlu.timeparse — deterministic time expression parser.

Every format in R-TIME-05 must have a test. Relative times tested separately.
"""
import pytest
from nlu.timeparse import parse_time, ParsedTime, TimeParseError, extract_time_expressions

US = 1_000_000  # 1 second in microseconds


class TestColonFormat:
    def test_mm_ss(self):
        pt = parse_time("1:20")
        assert pt.value_us == 80 * US
        assert not pt.is_relative

    def test_h_mm_ss(self):
        pt = parse_time("1:02:30")
        assert pt.value_us == (3600 + 120 + 30) * US

    def test_mm_ss_zero(self):
        pt = parse_time("0:00")
        assert pt.value_us == 0

    def test_exact_seconds(self):
        pt = parse_time("0:42")
        assert pt.value_us == 42 * US


class TestUnitFormat:
    def test_seconds(self):
        pt = parse_time("80 seconds")
        assert pt.value_us == 80 * US

    def test_seconds_abbrev(self):
        pt = parse_time("80 s")
        assert pt.value_us == 80 * US

    def test_seconds_sec(self):
        pt = parse_time("30 sec")
        assert pt.value_us == 30 * US

    def test_minutes(self):
        pt = parse_time("2 minutes")
        assert pt.value_us == 120 * US

    def test_minutes_abbrev(self):
        pt = parse_time("2 mins")
        assert pt.value_us == 120 * US

    def test_minutes_min(self):
        pt = parse_time("2 min")
        assert pt.value_us == 120 * US


class TestRelativeFormats:
    def test_last_n_seconds(self):
        pt = parse_time("the last 10 seconds")
        assert pt.is_relative
        assert pt.relative_anchor == "end"
        assert pt.value_us == 10 * US
        # Resolve against 60s video
        assert pt.resolve(60 * US) == 50 * US

    def test_last_without_the(self):
        pt = parse_time("last 10 s")
        assert pt.is_relative
        assert pt.relative_anchor == "end"

    def test_first_n_seconds(self):
        pt = parse_time("the first 30 seconds")
        assert pt.is_relative
        assert pt.relative_anchor == "start"
        assert pt.value_us == 30 * US
        assert pt.resolve(60 * US) == 30 * US

    def test_first_without_the(self):
        pt = parse_time("first 30 s")
        assert pt.is_relative
        assert pt.relative_anchor == "start"

    def test_last_minutes(self):
        pt = parse_time("the last 2 minutes")
        assert pt.is_relative
        assert pt.value_us == 120 * US
        assert pt.resolve(300 * US) == 180 * US


class TestNaturalLanguage:
    def test_a_minute_twenty(self):
        pt = parse_time("a minute twenty")
        assert pt.value_us == 80 * US

    def test_two_minutes_thirty(self):
        pt = parse_time("two minutes thirty")
        assert pt.value_us == 150 * US

    def test_one_minute(self):
        pt = parse_time("one minute")
        assert pt.value_us == 60 * US

    def test_a_minute(self):
        pt = parse_time("a minute")
        assert pt.value_us == 60 * US


class TestErrorHandling:
    def test_unparseable_raises(self):
        with pytest.raises(TimeParseError):
            parse_time("the boring part")

    def test_empty_raises(self):
        with pytest.raises(TimeParseError):
            parse_time("")


class TestExtractFromText:
    def test_extracts_colon_time(self):
        results = extract_time_expressions("Cut from 1:20 to 2:30")
        assert len(results) == 2
        assert results[0][2].value_us == 80 * US
        assert results[1][2].value_us == 150 * US

    def test_extracts_unit_time(self):
        results = extract_time_expressions("Remove the first 30 seconds")
        assert len(results) == 1
        assert results[0][2].is_relative
        assert results[0][2].relative_anchor == "start"

    def test_no_overlap_in_extraction(self):
        results = extract_time_expressions("from 1:20 to 1:40")
        spans = [(r[0], r[1]) for r in results]
        for i, (s1, e1) in enumerate(spans):
            for j, (s2, e2) in enumerate(spans):
                if i != j:
                    assert e1 <= s2 or e2 <= s1, f"Overlapping spans: {spans}"
