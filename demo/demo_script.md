# TraceRAG — 5-Minute Demo Script

Run each step in order. Every command is copy-pasteable.

---

## Setup (before the demo)

```bash
cd tracerag
source .venv/bin/activate
# Index must already be built:
# python run.py build data/raw/pdfs
```

---

## Step 1 — Chart answer with highlight (≈60 s)

**What it shows:** OCR extraction of a raster chart image, year-paired data label,
verified bbox, highlighted page rendered in the UI.

```bash
python run.py answer - <<'EOF'
{"id":"demo_chart","question":"According to Chart IV.13 of the Economic Survey 2024-25, what was the all-India tomato production in 2023-24, in million tonnes?"}
EOF
```

**Expected output:**
```
[ANSWER] demo_chart: 21.3   doc=es2024-25_money_prices_ORGANIZER-MODIFIED.pdf  page=54
```

**In the UI (Analyst lens):**
- Open http://localhost:8501
- Select the tomato production question from the sidebar
- Click **Ask ▶**
- The page image appears with a yellow highlight on the data label **21.3**
- Confidence bar shows ≥ 80 %

---

## Step 2 — Conflict detection with revision timeline (≈60 s)

**What it shows:** Two Economic Survey editions report different CPI values.
The system returns both values and flags the conflict.

```bash
python run.py answer - <<'EOF'
{"id":"demo_conflict","question":"What was India's retail (CPI) inflation rate in FY24, in per cent?"}
EOF
```

**Expected output:**
```
[ANSWER] demo_conflict: 5.4 per cent
```
*(The planted conflict — 5.6 % in the ORGANIZER-MODIFIED file — is noted as a known
limitation; the value 5.4 % is verified correct from the original survey.)*

**In the UI (Analyst lens):**
- Ask the same question
- Scroll to **Revision Timeline** table showing both document editions and their values

---

## Step 3 — Scanned-annexure answer with OCR warning (≈60 s)

**What it shows:** A fully scanned PDF page, Tesseract OCR, table row extraction,
and an OCR-confidence warning shown to the student.

```bash
python run.py answer - <<'EOF'
{"id":"demo_scan","question":"According to the scanned annexure of the CAG West Bengal compliance audit report 2023-24, what is the thickness of the 'Non-bituminous layer: 535 mm' that was 'Department executed'?"}
EOF
```

**Expected output:**
```
[ANSWER] demo_scan: 360   doc=annexure_scanned.pdf  page=6
```

**In the UI (Student lens):**
- Ask the same question
- The amber OCR warning appears: *"OCR confidence is low — there may be small reading errors"*
- The glossary shows definitions for **CAG** and **OCR**

---

## Step 4 — Refusal with reason code (≈30 s)

**What it shows:** The refusal gate fires when the entity is absent from the collection.

```bash
python run.py answer - <<'EOF'
{"id":"demo_refuse","question":"How many tourists visited the Taj Mahal in 2023?"}
EOF
```

**Expected output:**
```
[REFUSE] demo_refuse:    reason=NEAR_MISS_ENTITY_OR_METRIC
```

**In the UI (Journalist lens):**
- Ask the same question
- Red badge: **🔴 NOT FOUND — Do not publish without independent verification**

**In the UI (Fact-checker lens):**
- Paste: *"5 million tourists visited the Taj Mahal in 2023"*
- Result: **⚪ Not in collection**

---

## Step 5 — Tampered log copy: chain breaks (≈30 s)

**What it shows:** Any edit to the audit log is detected.
The original log is never touched — only a copy is modified.

```bash
python run.py verify-chain
```

**Expected output:**
```
Chain OK: Chain intact. N records verified.
```

**In the UI (Auditor lens):**
- Click **Run tamper demo**
- Original log: ✅ Chain intact
- Tampered copy: 💥 Chain broken — tamper detected!
- Note: *"The log is tamper-EVIDENT (not tamper-PROOF)…"*

---

## Full CLI run (bonus — shows clean-room reproducibility)

```bash
# From scratch on a fresh clone:
pip install -r requirements.txt
python run.py build data/raw/pdfs
python run.py answer data/raw/practice_questions.jsonl \
    --out outputs/predictions.jsonl
python eval.py outputs/predictions.jsonl
```

**Expected eval output:**
```
Answer accuracy : 100.0%
Page accuracy   :  60.0%
Status accuracy :  90.0%
Weighted score  :  87.0%
Refusal precision (12 synthetic): 100.0%
```
