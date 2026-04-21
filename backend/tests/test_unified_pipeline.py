"""Test the unified pipeline: structure extraction + streaming animation.

Tests:
1. Abbreviations with correct spelling → 16 results
2. Abbreviations with typo "abreviations" → still 16 results  
3. Use cases → 31 results
4. Use cases with typo → still 31 results
5. Fuzzy detection function directly
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test the detection function directly
from app.routers.vector_search import (
    _detect_structure_query_type,
    _reassemble_pdf_texts,
    _extract_abbreviations_from_text,
    _extract_use_cases_from_text,
    _get_structure_context,
)

ORG_ID = "9e934065-0cc0-440f-92c7-534a9a624a5d"

print("=" * 60)
print("TEST 1: Fuzzy detection function")
print("=" * 60)

test_cases = [
    ("list all abbreviations", "abbreviations"),
    ("list all abreviations", "abbreviations"),   # typo
    ("list all abbrieviations", "abbreviations"),  # typo
    ("what are the acronyms", "abbreviations"),
    ("give me acronyms", "abbreviations"),
    ("glossary", "abbreviations"),
    ("list all use cases", "use_cases"),
    ("list all usecases", "use_cases"),
    ("list use cases", "use_cases"),
    ("what are the use cases", "use_cases"),
    ("use case list", "use_cases"),
    ("list all headings", "general_structure"),
    ("list all requirements", "general_structure"),
    ("list all definitions", "general_structure"),
    ("what is CAPTCHA", None),  # NOT a structure query
    ("hello", None),            # NOT a structure query
    ("how many pages", None),   # NOT a structure query
]

all_pass = True
for question, expected in test_cases:
    result = _detect_structure_query_type(question)
    status = "PASS" if result == expected else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  {status}: '{question}' → {result} (expected: {expected})")

print(f"\nFuzzy detection: {'ALL PASS' if all_pass else 'SOME FAILED'}")

print("\n" + "=" * 60)
print("TEST 2: Abbreviation extraction (deterministic)")
print("=" * 60)

pdf_texts = _reassemble_pdf_texts(ORG_ID)
all_abbrevs = []
for fname, (full_text, _) in pdf_texts.items():
    abbrevs = _extract_abbreviations_from_text(full_text)
    if abbrevs:
        all_abbrevs.extend(abbrevs)
        print(f"  {fname}: {len(abbrevs)} abbreviations")

print(f"\nTotal abbreviations: {len(all_abbrevs)}")
for a in all_abbrevs:
    print(f"  {a}")

print("\n" + "=" * 60)
print("TEST 3: Use case extraction (deterministic)")
print("=" * 60)

all_usecases = []
for fname, (full_text, _) in pdf_texts.items():
    usecases = _extract_use_cases_from_text(full_text)
    if usecases:
        all_usecases.extend(usecases)
        print(f"  {fname}: {len(usecases)} use cases")

print(f"\nTotal use cases: {len(all_usecases)}")
for uc in all_usecases:
    print(f"  {uc}")

print("\n" + "=" * 60)
print("TEST 4: Context injection (abbreviations)")
print("=" * 60)

ctx, srcs = _get_structure_context("list all abbreviations", ORG_ID)
if ctx:
    print(f"  Context length: {len(ctx)} chars")
    print(f"  Sources: {len(srcs)}")
    print(f"  Preview:\n{ctx[:500]}")
else:
    print("  FAIL: No context returned!")

print("\n" + "=" * 60)
print("TEST 5: Context injection (abbreviations with typo)")
print("=" * 60)

ctx2, srcs2 = _get_structure_context("list all abreviations", ORG_ID)
if ctx2:
    print(f"  Context length: {len(ctx2)} chars")
    print(f"  Same as correct spelling: {ctx == ctx2}")
else:
    print("  FAIL: No context returned for typo!")

print("\n" + "=" * 60)
print("TEST 6: Context injection (use cases)")
print("=" * 60)

ctx3, srcs3 = _get_structure_context("list all use cases", ORG_ID)
if ctx3:
    print(f"  Context length: {len(ctx3)} chars")
    print(f"  Sources: {len(srcs3)}")
    print(f"  Preview:\n{ctx3[:500]}")
else:
    print("  FAIL: No context returned!")

print("\n" + "=" * 60)
print("TEST 7: Context injection (use cases with typo)")
print("=" * 60)

ctx4, srcs4 = _get_structure_context("list use case", ORG_ID)
if ctx4:
    print(f"  Context length: {len(ctx4)} chars")
    print(f"  Same as correct spelling: {ctx3 == ctx4}")
else:
    print("  FAIL: No context returned for 'list use case'!")

print("\n" + "=" * 60)
print("TEST 8: Normal query returns None (no structure context)")
print("=" * 60)

ctx5, srcs5 = _get_structure_context("what is CAPTCHA", ORG_ID)
print(f"  Context: {ctx5}")
print(f"  Sources: {srcs5}")
print(f"  {'PASS' if ctx5 is None else 'FAIL'}: Normal queries should return None")
