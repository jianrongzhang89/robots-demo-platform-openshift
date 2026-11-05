import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from manifest_validation import require_reviewed_rows


class ReviewedManifestTests(unittest.TestCase):
    def test_accepts_independently_accepted_and_legacy_reviewed_rows(self):
        require_reviewed_rows([
            {"capture_id": "accepted", "review_status": "independently_reviewed_accepted_JZ_2026-10-15"},
            {"capture_id": "legacy", "review_status": "visually-reviewed"},
        ])

    def test_pending_rows_are_rejected_before_scoring(self):
        with self.assertRaisesRegex(ValueError, "pending-1"):
            require_reviewed_rows([
                {"capture_id": "accepted", "review_status": "independently_reviewed_accepted_JZ_2026-10-15"},
                {"capture_id": "pending-1", "review_status": "pending_independent_review"},
            ])

    def test_missing_or_provisional_review_status_is_rejected(self):
        for row in ({"capture_id": "missing"}, {"capture_id": "provisional", "review_status": "review_required"}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                require_reviewed_rows([row])


if __name__ == "__main__":
    unittest.main()
