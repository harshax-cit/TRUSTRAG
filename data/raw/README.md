---
license: other
pretty_name: "PS03 Multimodal RAG with Explainability (student data)"
tags: [hackathon, rag]
---
# PS03: Multimodal RAG with Explainability

**Theme:** Pipeline Building | 24-hour hackathon, teams of two, AI coding tools allowed.

## What you build
Answer questions over long government reports, including facts only in charts, tables and a scanned annexure, cite document and page, and refuse when the answer is not there.

## What is in this repository
9 report PDFs (Economic Survey chapters of two editions, CAG audit reports, Kerala budget documents), a 20-page image-only scanned annexure, and 10 practice questions with answers and pages. `es2024-25_money_prices_ORGANIZER-MODIFIED.pdf` has a few numbers changed on purpose.

## Output format
JSONL: `{"id","answer","doc","page","bbox"(optional),"status":"answer|conflict|refuse"}`.

## Source and licence
Government of India publications (Economic Survey, CAG, Kerala Government). Licences are not confirmed per file. Use this data only for the event and for non-commercial work, with attribution. Hidden test data and answer keys are not included.
Read the student problem statement document for the full task, scoring and rules.
