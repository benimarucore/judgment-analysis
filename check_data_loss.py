import glob, json, re, os

md_files = sorted(glob.glob("analysis_documents/*_analysis.md"))

issues = []

for md_path in md_files:
    json_path = md_path.replace('.md', '.json')
    if not os.path.exists(json_path):
        issues.append(f"{os.path.basename(md_path)}: Missing JSON file")
        continue
        
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
        
    with open(json_path, 'r', encoding='utf-8') as f:
        try:
            json_data = json.load(f)
        except:
            issues.append(f"{os.path.basename(json_path)}: Invalid JSON")
            continue
            
    sections_json = json_data.get('sections', {})
    
    # 1. Check Metadata
    md_meta_match = re.search(r'## Metadata Extraction\n(.*?)\n---', md_content, re.DOTALL)
    if md_meta_match:
        md_meta = md_meta_match.group(1).strip()
        json_meta = sections_json.get('Metadata Extraction', {}).get('content', '').strip()
        if md_meta and not json_meta:
            issues.append(f"{os.path.basename(md_path)}: Metadata missing in JSON but present in MD")
            
    # 2. Check Witnesses
    md_wit_match = re.search(r'## Principal Witnesses & Ex\.PW Extraction\n(.*?)\n---', md_content, re.DOTALL)
    if md_wit_match:
        md_wit = md_wit_match.group(1).strip()
        json_wit = sections_json.get('Principal Witnesses & Ex.PW Extraction', {}).get('content', '').strip()
        if md_wit and not json_wit:
            issues.append(f"{os.path.basename(md_path)}: Witnesses missing in JSON but present in MD")

    # 3. Check Audit Headings (for heading format mismatches)
    json_audit = sections_json.get('Investigation Quality Audit', {}).get('content', '')
    if json_audit:
        h5_headings = re.findall(r'^#####\s+(.*)', json_audit, re.MULTILINE)
        if h5_headings:
            issues.append(f"{os.path.basename(json_path)}: Uses ##### headings in Audit, which UI doesn't parse.")

if not issues:
    print("ALL OK! No data loss detected between MD and JSON files.")
else:
    print("Found discrepancies:")
    for issue in issues:
        print(f" - {issue}")
