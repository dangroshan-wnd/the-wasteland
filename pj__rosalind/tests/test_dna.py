"""Tests for the Counting DNA Nucleotides solution."""

from pathlib import Path
import subprocess
import sys
import unittest


ROSALIND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROSALIND_DIR))

from dna import count_nucleotides  # noqa: E402


class CountNucleotidesTests(unittest.TestCase):
    def test_rosalind_sample(self) -> None:
        sequence = (
            "AGCTTTTCATTCTGACTGCAACGGGCAATATGTCTCTGTGTGGATT"
            "AAAAAAAGAGTGTCTGATAGCAGC"
        )

        self.assertEqual(count_nucleotides(sequence), (20, 12, 17, 21))

    def test_returns_zero_for_missing_nucleotides(self) -> None:
        self.assertEqual(count_nucleotides("AAAA"), (4, 0, 0, 0))

    def test_rejects_an_empty_sequence(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            count_nucleotides("")

    def test_rejects_invalid_symbols(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid symbols: 'N'"):
            count_nucleotides("ACNT")

    def test_rejects_a_sequence_over_the_problem_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "at most 1000"):
            count_nucleotides("A" * 1_001)


class CommandLineTests(unittest.TestCase):
    def run_solution(self, sequence: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROSALIND_DIR / "dna.py")],
            input=sequence,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_prints_counts_in_rosalind_order(self) -> None:
        result = self.run_solution("GATTACA\n")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "3 1 1 2\n")
        self.assertEqual(result.stderr, "")

    def test_reports_invalid_input(self) -> None:
        result = self.run_solution("ACGTN\n")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("invalid symbols: 'N'", result.stderr)


if __name__ == "__main__":
    unittest.main()
