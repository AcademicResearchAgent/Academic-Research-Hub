"""Boundary tests for the research-frontier plugin. No network, no model keys."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "extensions/plugins/research-frontier"
SAMPLE = PLUGIN / "samples/corpus.example.json"

spec = importlib.util.spec_from_file_location(
    "research_frontier_test", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeContext:
    def __init__(self):
        self.tools, self.skills = {}, []

    def register_tool(self, **definition):
        self.tools[definition["name"]] = definition

    def register_skill(self, name, path):
        self.skills.append((name, path))


RECORDS = [
    {"title": "CRISPR screening in cancer models", "year": 2019, "keywords": ["crispr", "cancer", "screening"]},
    {"title": "Machine learning for CRISPR off-target prediction", "year": 2019, "keywords": ["machine learning", "crispr", "off-target"]},
    {"title": "Deep learning methods in oncology imaging", "year": 2020, "keywords": ["deep learning", "oncology", "imaging"]},
    {"title": "CRISPR gene editing in human cells", "year": 2020, "keywords": ["crispr", "gene editing"]},
    {"title": "Machine learning biomarkers in oncology", "year": 2021, "keywords": ["machine learning", "oncology", "biomarker"]},
    {"title": "CRISPR delivery systems for therapeutics", "year": 2021, "keywords": ["crispr", "delivery"]},
    {"title": "Deep learning for protein folding prediction", "year": 2022, "keywords": ["deep learning", "protein folding"]},
    {"title": "CRISPR clinical trials and safety", "year": 2022, "keywords": ["crispr", "clinical trial", "safety"]},
    {"title": "Machine learning approaches to protein folding", "year": 2023, "keywords": ["machine learning", "protein folding"]},
    {"title": "Machine learning guided CRISPR design", "year": 2024, "keywords": ["machine learning", "crispr", "design"]},
]

HOTSPOT_ARGS = {"records": RECORDS, "text_fields": ["keywords"], "ngram_max": 2}
GAP_ARGS = {"records": RECORDS, "text_fields": ["keywords"],
            "domain_terms": ["crispr", "oncology"], "method_terms": ["machine learning", "clinical trial"]}


class RegistrationTests(unittest.TestCase):
    def test_registers_four_tools_and_the_bundled_skill(self):
        context = FakeContext()
        module.register(context)
        self.assertEqual(set(context.tools), {
            "frontier_corpus_profile", "frontier_hotspot_analysis",
            "frontier_gap_analysis", "frontier_report_build",
        })
        for definition in context.tools.values():
            self.assertEqual(definition["toolset"], "research_frontier")
            self.assertIn("description", definition["schema"])
        self.assertEqual(context.skills[0][0], "research-frontier")
        self.assertTrue(Path(context.skills[0][1]).is_file())


class CorpusTests(unittest.TestCase):
    def test_profile_counts_drops_and_years(self):
        result = json.loads(module.tools.corpus_profile(
            {"records": RECORDS + [{"abstract": "no title here"}, "not an object"], "text_fields": ["keywords"]}))
        self.assertTrue(result["success"])
        self.assertEqual(result["record_count"], 10)
        self.assertEqual(result["dropped_count"], 2)
        self.assertEqual((result["year_min"], result["year_max"]), (2019, 2024))

    def test_profiles_bundled_sample_and_json_object_file(self):
        from_file = json.loads(module.tools.corpus_profile({"records_path": str(SAMPLE)}))
        self.assertTrue(from_file["success"])
        self.assertEqual(from_file["record_count"], 10)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.json"
            path.write_text(json.dumps({"records": RECORDS}), encoding="utf-8")
            nested = json.loads(module.tools.corpus_profile({"records_path": str(path)}))
        self.assertTrue(nested["success"])
        self.assertEqual(nested["record_count"], 10)

    def test_duplicate_doi_reported_and_prefix_normalised(self):
        duplicated = [{"title": "A", "doi": "10.1000/dup"},
                      {"title": "B", "doi": "https://doi.org/10.1000/dup"}]
        result = json.loads(module.tools.corpus_profile({"records": duplicated}))
        self.assertTrue(result["success"])
        self.assertEqual(result["duplicate_dois"], ["10.1000/dup"])


class HotspotTests(unittest.TestCase):
    def test_document_frequencies_and_burst_are_deterministic(self):
        with tempfile.TemporaryDirectory() as workspace, patch.dict("os.environ", {"RESEARCH_FRONTIER_WORKSPACE": workspace}):
            first = json.loads(module.tools.hotspot_analysis({**HOTSPOT_ARGS, "case": "t"}))
            second = json.loads(module.tools.hotspot_analysis({**HOTSPOT_ARGS, "case": "t"}))
            self.assertTrue(first["success"])
            self.assertEqual(first["terms"], second["terms"])
            self.assertTrue(Path(first["artifacts"]["json"]).is_file())
            self.assertTrue(Path(first["artifacts"]["markdown"]).is_file())

        terms = {row["term"]: row for row in first["terms"]}
        self.assertEqual(terms["crispr"]["documents"], 6)
        self.assertEqual(terms["machine learning"]["documents"], 4)
        self.assertEqual(terms["crispr"]["burst_ratio"], 0.75)
        self.assertAlmostEqual(terms["machine learning"]["burst_ratio"], 1.5, places=3)

    def test_keywords_do_not_create_cross_keyword_ngrams(self):
        with tempfile.TemporaryDirectory() as workspace, patch.dict("os.environ", {"RESEARCH_FRONTIER_WORKSPACE": workspace}):
            result = json.loads(module.tools.hotspot_analysis({**HOTSPOT_ARGS, "case": "t"}))
        names = {row["term"] for row in result["terms"]}
        self.assertIn("machine learning", names)
        self.assertNotIn("learning crispr", names)
        self.assertNotIn("crispr cancer", names)


class GapTests(unittest.TestCase):
    def test_under_observed_pair_is_reported_as_candidate_gap(self):
        with tempfile.TemporaryDirectory() as workspace, patch.dict("os.environ", {"RESEARCH_FRONTIER_WORKSPACE": workspace}):
            result = json.loads(module.tools.gap_analysis({**GAP_ARGS, "case": "g"}))
        self.assertTrue(result["success"])
        self.assertEqual(len(result["candidate_gaps"]), 1)
        gap = result["candidate_gaps"][0]
        self.assertEqual((gap["domain"], gap["method"], gap["observed"]), ("crispr", "machine learning", 2))
        self.assertLess(gap["residual"], 0)
        self.assertEqual(result["sparse_domains"][0]["domain"], "oncology")

    def test_overlapping_domain_and_method_terms_rejected(self):
        result = json.loads(module.tools.gap_analysis(
            {**GAP_ARGS, "domain_terms": ["crispr"], "method_terms": ["CRISPR"]}))
        self.assertFalse(result["success"])


class ReportTests(unittest.TestCase):
    def test_report_assembles_artifacts_with_limitations(self):
        with tempfile.TemporaryDirectory() as workspace, patch.dict("os.environ", {"RESEARCH_FRONTIER_WORKSPACE": workspace}):
            hotspot = json.loads(module.tools.hotspot_analysis({**HOTSPOT_ARGS, "case": "r"}))
            gap = json.loads(module.tools.gap_analysis({**GAP_ARGS, "case": "r"}))
            report = json.loads(module.tools.report_build({
                "analysis_paths": [hotspot["artifacts"]["json"], gap["artifacts"]["json"]],
                "title": "Demo frontier report", "case": "r"}))
            self.assertTrue(report["success"])
            content = Path(report["report_path"]).read_text(encoding="utf-8")
            self.assertEqual(report["report"], content)
            self.assertIn("Demo frontier report", report["report"])
        self.assertIn("局限", content)
        self.assertIn("crispr", content)


class InputBoundaryTests(unittest.TestCase):
    def test_missing_source_and_bad_types_are_refused(self):
        cases = [
            (module.tools.corpus_profile, {}),
            (module.tools.corpus_profile, {"records": "not-a-list"}),
            (module.tools.corpus_profile, {"records": RECORDS, "text_fields": ["unknown-field"]}),
            (module.tools.corpus_profile, {"records_path": "does/not/exist.jsonl"}),
            (module.tools.hotspot_analysis, {"records": RECORDS, "ngram_max": "two"}),
            (module.tools.hotspot_analysis, {"records": [{"no": "title"}], "text_fields": ["keywords"]}),
            (module.tools.report_build, {"analysis_paths": ["does/not/exist.json"]}),
            (module.tools.report_build, {}),
        ]
        for handler, params in cases:
            with self.subTest(handler=handler.__name__, params=params):
                result = json.loads(handler(params))
                self.assertFalse(result["success"])
                self.assertTrue(result["error"])

    def test_artifacts_stay_inside_the_workspace(self):
        with tempfile.TemporaryDirectory() as workspace, patch.dict("os.environ", {"RESEARCH_FRONTIER_WORKSPACE": workspace}):
            result = json.loads(module.tools.hotspot_analysis(
                {**HOTSPOT_ARGS, "case": "../../escape"}))
        self.assertTrue(result["success"])
        self.assertTrue(Path(result["artifacts"]["json"]).is_relative_to(Path(workspace).resolve()))


if __name__ == "__main__":
    unittest.main()
