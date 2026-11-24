import os
import re
import datetime

def run_code_quality_audit():
    print("━" * 70)
    print("  🎨 RUNNING STATIC CODE QUALITY AND ARCHITECTURE AUDIT")
    print("━" * 70)
    
    workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backend_app_dir = os.path.join(workspace_dir, "backend", "app")
    
    findings = []
    
    # Regex definitions for static analysis
    docstring_pattern = re.compile(r'^\s*def\s+\w+\(.*?\)\s*->?\s*\w*:\s*$')
    try_except_pattern = re.compile(r'^\s*try:\s*$')
    print_pattern = re.compile(r'^\s*print\(.*?\)\s*$')
    
    files_to_check = []
    for root, _, files in os.walk(backend_app_dir):
        for file in files:
            if file.endswith(".py"):
                files_to_check.append(os.path.join(root, file))
                
    # Add main.py
    main_py = os.path.join(workspace_dir, "backend", "app", "main.py")
    if os.path.exists(main_py) and main_py not in files_to_check:
        files_to_check.append(main_py)
        
    for filepath in files_to_check:
        rel_path = os.path.relpath(filepath, workspace_dir)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                lines = content.splitlines()
                
            # Check for lack of docstrings in file
            docstring_count = len(re.findall(r'"""', content)) // 2
            def_count = len(re.findall(r'def\s+\w+\(', content))
            
            if def_count > docstring_count:
                findings.append({
                    "file": rel_path,
                    "line": 1,
                    "category": "MISSING_DOCSTRINGS",
                    "severity": "LOW",
                    "description": f"File has {def_count} function definitions but only {docstring_count} docstrings.",
                    "recommendation": "Document all public routes and core helpers with comprehensive descriptive docstrings (Python PEP 257)."
                })
                
            # Audit line by line
            function_line_count = 0
            in_function = False
            current_func = ""
            
            for line_idx, line in enumerate(lines):
                line_no = line_idx + 1
                
                # Check for direct print statements instead of standardized logs
                if print_pattern.match(line) and "test" not in rel_path:
                    findings.append({
                        "file": rel_path,
                        "line": line_no,
                        "category": "INSECURE_PRINTS",
                        "severity": "MEDIUM",
                        "description": "Standard print statement found. Using direct print output is highly discouraged in production SaaS APIs.",
                        "recommendation": "Replace standard print statements with the app's predefined logger (`logger.info` or `logger.warning`)."
                    })
                    
                # Track massive function sizes to keep code modular
                if line.strip().startswith("def "):
                    in_function = True
                    current_func = line.strip().split("(")[0].replace("def ", "")
                    function_line_count = 0
                elif in_function and (line.startswith(" ") or line.startswith("\t") or line == ""):
                    function_line_count += 1
                elif in_function:
                    if function_line_count > 60:
                        findings.append({
                            "file": rel_path,
                            "line": line_no - function_line_count,
                            "category": "MASSIVE_FUNCTION",
                            "severity": "MEDIUM",
                            "description": f"Function `{current_func}` contains {function_line_count} lines of code, exceeding modular guidelines (max 60 lines).",
                            "recommendation": "Refactor and split massive logical paths into reusable utility helper files or dedicated classes."
                        })
                    in_function = False
                    
        except Exception as e:
            print(f"  ✗ Error auditing {rel_path}: {e}")
            
    # Write beautifully formatted code quality report
    report_path = os.path.join(workspace_dir, "docs", "code_quality_audit_report.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    medium_count = sum(1 for f in findings if f["severity"] == "MEDIUM")
    low_count = sum(1 for f in findings if f["severity"] == "LOW")
    
    with open(report_path, "w", encoding="utf-8") as rf:
        rf.write(f"""# 🎨 Code Quality & Architectural Audit Report

*Generated on: {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}*

---

## 📊 Quality Summary metrics

- **Overall Health Score:** {max(50, 100 - (medium_count * 8 + low_count * 3))}%
- **Total Architectural Concerns:** {len(findings)} issues found
- **Major Gaps (Medium):** {medium_count} items
- **Minor Enhancements (Low):** {low_count} items

---

## 🔍 Detailed Code Quality Findings
""")
        if not findings:
            rf.write("\n### 🎉 Perfect Score! Active codebase follows premium design patterns perfectly.\n")
        else:
            for idx, f in enumerate(findings):
                rf.write(f"""
### Issue #{idx + 1}: [{f['category']}] in `{f['file']}` (Line {f['line']})
- **Severity Level:** {f['severity'] == 'MEDIUM' and '🟡 MEDIUM' or '🟢 LOW'}
- **Observation:** {f['description']}
- **Remediation Recommendation:** {f['recommendation']}
""")
                
        rf.write("""
---

## 📐 General Code and Architecture Guidelines

1. **Modular Principle:** Keep functions short, focused, and single-purpose. Large functions should be factored out.
2. **Standardized Logging:** Always prefer predefined logging blocks (`logger`) over print statements to maintain clean, searchable Docker/Railway container streams.
3. **PEPs Alignment:** Utilize Type hints (`-> List[float]`) across all core calculations to prevent schema misalignments in future upgrades.
""")
        
    print(f"  ✓ Code quality audit completed successfully! Report stored in docs/code_quality_audit_report.md")
    print("━" * 70)

if __name__ == "__main__":
    run_code_quality_audit()
