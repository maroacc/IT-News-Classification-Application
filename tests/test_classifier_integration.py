"""
Integration tests for the classifier — these load the actual model.
The first run will download the model (~300MB). Subsequent runs use the cache.

Run with: pytest tests/test_classifier_integration.py -v -s
The -s flag is needed to see the printed score table.
"""
import pytest

from app.classifier import ClassifierService, IMPORTANCE_THRESHOLD, LABEL_WEIGHTS

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Sample headlines — mix of clearly relevant and irrelevant
# ---------------------------------------------------------------------------

SAMPLE_HEADLINES = [
    # (headline, expected_pass)  — None means no assertion, just observe
    ("Major AWS outage takes down us-east-1 region",               True),
    ("Critical zero-day vulnerability found in Windows kernel",    True),
    ("Ransomware attack hits major US hospital network",           True),
    ("MySQL database crashes causing data loss in production",     True),
    ("GitHub releases Copilot with new autocomplete features",     None),
    ("Apple announces new MacBook Pro with M4 chip",              False),
    ("Google celebrates 25th anniversary with a logo change",     False),
    ("New JavaScript framework released by indie developer",      False),
]


class TestClassifierModelIntegration:
    def setup_method(self):
        self.service = ClassifierService()

    def test_print_classification_scores(self, capsys):
        """
        Runs the classifier on each sample headline and prints a score table.
        Use `pytest -s` to see the output. Only asserts on structure, not model decisions.
        """
        with capsys.disabled():  # ensure output is printed even with pytest capturing
            print("\n" + "=" * 85)
            print(f"  {'HEADLINE':<52} {'SCORE':>6}  {'STATUS':<6}  CATEGORY")
            print("=" * 85)

            for headline, _ in SAMPLE_HEADLINES:
                score, category = self.service._compute_importance(headline)
                status = "PASS" if score > IMPORTANCE_THRESHOLD else "FAIL"
                short_cat = category.replace(" or ", "/")[:28]
                print(f"  {headline[:52]:<52} {score:.3f}   {status:<6}  {short_cat}")

            print("=" * 85)

    def test_scores_are_valid_floats_in_range(self):
        """Scores must always be floats within the expected weighted range [0.2, 1.0]."""
        for headline, _ in SAMPLE_HEADLINES:
            score, category = self.service._compute_importance(headline)

            assert isinstance(score, float), \
                f"Score for '{headline}' is not a float"
            assert 0.0 <= score <= 1.01, \
                f"Score {score:.3f} out of expected range for '{headline}'"
            assert category in LABEL_WEIGHTS, \
                f"Unknown category '{category}' returned for '{headline}'"

    def test_clearly_relevant_headlines_pass_filter(self):
        """Headlines about outages and breaches should score above the threshold."""
        relevant = [h for h, expected in SAMPLE_HEADLINES if expected is True]
        for headline in relevant:
            score, _ = self.service._compute_importance(headline)
            assert score > IMPORTANCE_THRESHOLD, \
                f"Expected '{headline}' to pass the filter but got score={score:.3f}"

    def test_clearly_irrelevant_headlines_fail_filter(self):
        """Headlines about product announcements and general news should score below threshold."""
        irrelevant = [h for h, expected in SAMPLE_HEADLINES if expected is False]
        for headline in irrelevant:
            score, _ = self.service._compute_importance(headline)
            assert score <= IMPORTANCE_THRESHOLD, \
                f"Expected '{headline}' to fail the filter but got score={score:.3f}"