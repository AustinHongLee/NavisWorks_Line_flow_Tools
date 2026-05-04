# -*- coding: utf-8 -*-
import unittest

from utils.trace_builder import SEP, TraceBuilder, parse_trace


class TraceBuilderTests(unittest.TestCase):
    def test_build_basic(self):
        tb = TraceBuilder()
        tb.add("raw", "/foo")
        tb.add("source", "pipeline_id")
        tb.add_event("size_norm", "[2]:1.1_2→1-1/2")
        s = tb.build()
        self.assertTrue(s.startswith(SEP))
        self.assertIn("raw=/foo", s)
        self.assertIn("size_norm:[2]:1.1_2→1-1/2", s)

    def test_escape_section_separator(self):
        tb = TraceBuilder()
        tb.add("note", "value contains §should escape")
        s = tb.build()
        self.assertIn("§§should", s)
        parts = parse_trace(s)
        self.assertTrue(
            any(v == "value contains §should escape" for _, _, v in parts)
        )

    def test_parse_kv_and_event(self):
        s = "§raw=foo§source=pipeline_id§size_norm:[2]:1.1_2→1-1/2"
        parts = parse_trace(s)
        self.assertIn(("kv", "raw", "foo"), parts)
        self.assertIn(("kv", "source", "pipeline_id"), parts)
        self.assertIn(("event", "size_norm", "[2]:1.1_2→1-1/2"), parts)

    def test_truncate_when_too_long(self):
        tb = TraceBuilder()
        for i in range(2000):
            tb.add(f"k{i}", "v" * 50)
        s = tb.build()
        self.assertLessEqual(len(s), 4096)
        self.assertIn("truncated=1", s)


if __name__ == "__main__":
    unittest.main()
