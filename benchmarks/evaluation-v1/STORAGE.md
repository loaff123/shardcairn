# Lossless evidence storage

The published row file is `cases.jsonl.gz`, a lossless gzip representation of the
original frozen `cases.jsonl`. All 930 rows, all misses, no-improvement cases, and
held-out rows are preserved byte for byte. No model values or results changed.

Original uncompressed size: 1857958 bytes.
Original uncompressed SHA-256: `18ab43daa943c7fdb37fa7b2b31a06303220ba9bc385f1b347a17ec4d6cffb55`.

`SHA256SUMS` now indexes the distributed compressed bytes and this note. The
original synthetic manifests and their hash index are unchanged. `run.json`
continues to identify the actual evaluator and product sources used for that run.
The only edits to the generated report are this file link and its storage note.

Read the data without creating a file, using Python's standard library:

```console
python -c "import gzip,sys; sys.stdout.buffer.write(gzip.decompress(open('benchmarks/evaluation-v1/cases.jsonl.gz','rb').read()))"
```

To reproduce, follow `benchmarks/README.md`. The unchanged evaluator writes raw
`cases.jsonl` in the new output directory. Compare its SHA-256 with the original
uncompressed digest above or compare its bytes with `gzip.decompress` of this
file. The compressed container's digest is an integrity check on this published
representation, not a claim about identical compression across zlib versions.
Other machine records and all plan files remain directly inspectable.
