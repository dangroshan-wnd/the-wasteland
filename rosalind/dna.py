"""Solve Rosalind problem DNA: Counting DNA Nucleotides."""

from collections import Counter
import sys


NUCLEOTIDES = ("A", "C", "G", "T")
MAX_SEQUENCE_LENGTH = 1_000


def count_nucleotides(sequence: str) -> tuple[int, int, int, int]:
    """Return the A, C, G, and T counts for a valid DNA sequence."""
    if not sequence:
        raise ValueError("DNA sequence must not be empty")
    if len(sequence) > MAX_SEQUENCE_LENGTH:
        raise ValueError(
            f"DNA sequence must be at most {MAX_SEQUENCE_LENGTH} nucleotides"
        )

    invalid_symbols = sorted(set(sequence).difference(NUCLEOTIDES))
    if invalid_symbols:
        symbols = ", ".join(repr(symbol) for symbol in invalid_symbols)
        raise ValueError(f"DNA sequence contains invalid symbols: {symbols}")

    counts = Counter(sequence)
    return tuple(counts[nucleotide] for nucleotide in NUCLEOTIDES)


def main() -> int:
    """Read a sequence from stdin and print its nucleotide counts."""
    sequence = sys.stdin.read().strip()
    try:
        counts = count_nucleotides(sequence)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(*counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
