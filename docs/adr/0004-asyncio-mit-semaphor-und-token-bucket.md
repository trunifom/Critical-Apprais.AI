# ADR 0004: asyncio mit Semaphor und Token-Bucket

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
Parallele Aufrufe, RPM/TPM-Limiter, adaptive Parallelität (Kap. 9.3).

## Alternativen
Threads, Multiprocessing, sequentiell wie im Bestand (L3)

## Folgen
Deutlich schneller; Limiter und Abbruch sauber testen.
