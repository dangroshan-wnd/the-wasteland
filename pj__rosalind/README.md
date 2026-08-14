# Rosalind

Small, tested solutions to problems from [Rosalind](https://rosalind.info/), a
platform for learning bioinformatics through programming exercises.

## DNA: Counting DNA Nucleotides

[`dna.py`](dna.py) solves
[Counting DNA Nucleotides](https://rosalind.info/problems/dna/). It reads one
DNA sequence from standard input and prints the counts of `A`, `C`, `G`, and
`T`, in that order.

Run the solution:

```powershell
Get-Content input.txt | python pj__rosalind/dna.py
```

Run its tests from the repository root:

```powershell
python -m unittest discover -s pj__rosalind/tests -v
```

The solution uses only the Python standard library.
