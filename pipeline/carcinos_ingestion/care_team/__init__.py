"""
Care Team section — an optional, add-on step for CarcinoS cards.

A short, collapsed reference section for nurses and APPs, built ONLY from the
trial publication and official FDA labeling. Up to four of these rows with neutral,
descriptive labels:

    Schedule in the trial      (paper)
    Sequencing in the trial    (paper)
    Label monitoring           (FDA label: Dosage and Administration, Warnings, Boxed Warning)
    Label warnings             (FDA label: Warnings, Boxed Warning) — conditions, not symptoms
    Label interactions         (FDA label: Drug Interactions)
    Toxicity in the trial      (paper) — both arms when compared
    Patient-reported outcomes  (paper)

Design rules:
  * Runs AFTER the main pipeline. It never changes Pass 1, Pass 2, tiers or the
    "So what". It only adds keys to summary_json.
  * Extraction, not advice: no general medical knowledge, no inference, no
    instructions, no doses. Each row may only quote the sources allowed for it
    (fields.py), and code checks every quote word for word against that exact
    source. Rows that fail are removed; the editor sees why.
  * Trial rows may also quote ClinicalTrials.gov (fetched by code from its API)
    and primary-source pages the model finds with web search. The model may look
    anywhere, but CarcinoS downloads each page itself, only from an allowlist of
    primary-source domains (no press releases or trade news), and keeps a quote
    only if it appears word for word on that page (sources.py, finder.py).
  * Nothing is shown when nothing is supported. No empty placeholders.
  * The editor approves it with the rest of the card.
"""
