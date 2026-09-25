"""Probability-of-success priors (config/pos_priors.yml - BIO/Informa/QLS
2011-2020) and a keyword mapping from trial conditions to the report's disease
areas."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

# first match wins - specific areas before broad ones (blood cancers are oncology
# in the report; non-malignant blood disorders are hematology)
AREA_RULES: list[tuple[str, str]] = [
    ("oncology", r"cancer|carcinoma|tumou?r|lymphoma|leuka?emia|myeloma|melanoma|sarcoma|"
                 r"glioma|glioblastoma|neoplas|nsclc|sclc|mesothelioma|myelodysplastic|"
                 r"oncolog|metasta"),
    ("hematology", r"hemophilia|haemophilia|sickle cell|thalass|anemia|anaemia|thrombocytop|"
                   r"\bitp\b|paroxysmal nocturnal|\bpnh\b|von willebrand|neutropenia|"
                   r"hemoglobin|myelofibrosis|polycythemia|cold agglutinin"),
    ("infectious", r"infection|viral|virus|hiv|hepatitis b|hepatitis c|\bhbv\b|\bhcv\b|"
                   r"covid|influenza|\brsv\b|bacterial|fungal|tubercul|malaria|sepsis|"
                   r"pneumonia|cytomegalovirus|\bcmv\b|vaccine|clostridi"),
    ("ophthalmology", r"macular|retin|glaucoma|uveitis|ocular|eye|myopia|keratit|"
                      r"dry eye|geographic atrophy|presbyopia|blephar"),
    ("psychiatry", r"depress|schizophren|bipolar|anxiety|ptsd|post-traumatic|adhd|"
                   r"attention deficit|autism|insomnia|substance use|opioid use|"
                   r"alcohol use|agitation|psychos"),
    ("neurology", r"alzheimer|parkinson|amyotrophic|\bals\b|epilep|seizure|migraine|"
                  r"multiple sclerosis|neuropath|huntington|spinal muscular|duchenne|"
                  r"muscular dystrophy|myasthenia|ataxia|dementia|narcolepsy|"
                  r"essential tremor|rett|angelman|dravet|neuromyelitis|stroke"),
    ("autoimmune", r"lupus|rheumatoid|psoria|atopic dermatitis|eczema|crohn|ulcerative|"
                   r"colitis|inflammatory bowel|sjogren|vasculitis|scleroderma|systemic "
                   r"sclerosis|alopecia|vitiligo|hidradenitis|spondyl|myositis|iga "
                   r"nephropathy|autoimmune|immune thrombocytopenic"),
    ("cardiovascular", r"heart|cardi|hypertension|atrial|arrhythm|coronary|atheroscler|"
                       r"myocard|amyloid cardiomyopathy|thrombo|embol"),
    ("metabolic", r"hypercholesterol|hyperlipid|triglycerid|dyslipid|lipoprotein|\bnash\b|"
                  r"\bmash\b|steatohepatitis|fatty liver|phenylketon|\bpku\b|lysosomal|"
                  r"fabry|gaucher|pompe|mucopolysacchar|hypophosphat|homocystin|urea cycle|"
                  r"wilson|glycogen storage|obesity|weight management"),
    ("endocrine", r"diabet|thyroid|acromegal|cushing|growth hormone|adrenal|hypogonad|"
                  r"hypoparathyroid|congenital adrenal|insulin"),
    ("respiratory", r"asthma|copd|pulmonary|cystic fibrosis|bronchi|idiopathic pulmonary|"
                    r"\bipf\b|lung disease"),
    ("gastroenterology", r"gastro|celiac|eosinophilic esophag|irritable bowel|"
                         r"gastroparesis|short bowel|pancreatitis|cholang|biliary"),
    ("allergy", r"allerg|anaphyla|urticaria|food allergy|rhinitis"),
    ("urology", r"bladder|urinary|prostat(?!e cancer)|overactive|incontinence|"
                r"erectile|kidney stone"),
]
_COMPILED = [(a, re.compile(p, re.I)) for a, p in AREA_RULES]
STAGE_INDEX = {"P1": 0, "EP1": 0, "P1/P2": 0, "P2": 1, "P2/P3": 1, "P3": 2, "NDA": 3,
               "BLA": 3, "FILED": 3}


@lru_cache(maxsize=1)
def priors() -> dict[str, Any]:
    from ..config import _read_yaml

    return _read_yaml("pos_priors.yml") or {}


def area_of(text: str | None) -> str:
    t = str(text or "")
    for area, rx in _COMPILED:
        if rx.search(t):
            return area
    return "all"


def loa(phase: str | None, conditions: str | None = None) -> float | None:
    """Likelihood of approval (0-1) from ``phase`` for the conditions' area."""
    idx = STAGE_INDEX.get(str(phase or "").upper().replace("PHASE", "P").replace(" ", ""))
    if idx is None:
        return None
    table = priors().get("loa") or {}
    row = table.get(area_of(conditions)) or table.get("all")
    return float(row[idx]) / 100 if row else None
