"""Investigate actual use case count in SRS PDF by reassembling text and scanning."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.vector_search import _reassemble_pdf_texts

ORG_ID = "9e934065-0cc0-440f-92c7-534a9a624a5d"
pdf_texts = _reassemble_pdf_texts(ORG_ID)

for fname, (full_text, _) in pdf_texts.items():
    if "srs" not in fname.lower():
        continue
    print(f"PDF: {fname}, text length: {len(full_text)}")
    
    # Find the use case section
    # Look for "Product functions" section and use case listings
    low = full_text.lower()
    
    # Find all numbered use case references
    # Look for patterns like "use case", "UC-", "3.1.X" (specific requirements)
    
    # Method 1: Find section "2.2. Product functions" onwards
    idx = low.find("product functions")
    if idx >= 0:
        section = full_text[idx:idx+5000]
        print(f"\n=== Product functions section ===")
        print(section)
    
    # Method 2: Find use case diagram references
    idx2 = low.find("use case diagram")  
    if idx2 >= 0:
        section2 = full_text[idx2:idx2+3000]
        print(f"\n=== Use case diagram section ===")
        print(section2[:2000])
    
    # Method 3: Find specific requirements section (3.x)
    idx3 = low.find("specific requirements")
    if idx3 >= 0:
        section3 = full_text[idx3:idx3+8000]
        print(f"\n=== Specific requirements section (first 8000 chars) ===")
        print(section3)
    
    # Method 4: Count all "3.1.X" numbered sections (functional requirements / use cases)
    uc_pattern = re.findall(r"3\.1\.\d+[\.\s]+[A-Z][\w\s/()]+", full_text)
    print(f"\n=== All 3.1.X sections found ===")
    for uc in uc_pattern:
        print(f"  {uc.strip()[:100]}")
    print(f"Total 3.1.X sections: {len(uc_pattern)}")

    # Also look for "2.2.X" sections (product functions)
    pf_pattern = re.findall(r"2\.2\.\d+[\.\s]+[A-Z][\w\s/()]+", full_text)
    print(f"\n=== All 2.2.X sections (Product functions) ===")
    for pf in pf_pattern:
        print(f"  {pf.strip()[:100]}")
    print(f"Total 2.2.X sections: {len(pf_pattern)}")
