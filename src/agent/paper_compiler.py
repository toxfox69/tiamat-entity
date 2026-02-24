#!/usr/bin/env python3
"""TIAMAT Academic Paper Compiler — EnergenAI LLC"""

import subprocess
import os
import shutil
from datetime import datetime, timezone

RESEARCH_DIR = "/root/.automaton/research"
DRAFTS_DIR = f"{RESEARCH_DIR}/drafts"
OUTPUT_DIR = f"{RESEARCH_DIR}/output"
TEMPLATES_DIR = f"{RESEARCH_DIR}/templates"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)


def compile_paper(paper_dir: str, main_tex: str = "main.tex") -> dict:
    """Compile a LaTeX paper to PDF.

    Args:
        paper_dir: Directory containing the .tex files
        main_tex: Name of the main .tex file

    Returns:
        dict with success status, pdf_path, and any errors
    """
    tex_path = os.path.join(paper_dir, main_tex)
    if not os.path.exists(tex_path):
        return {"success": False, "error": f"{tex_path} not found"}

    try:
        # Run latexmk for full compilation (handles bibtex, multiple passes)
        result = subprocess.run(
            ["latexmk", "-pdf", "-interaction=nonstopmode",
             "-output-directory=" + paper_dir, main_tex],
            cwd=paper_dir,
            capture_output=True,
            text=True,
            timeout=120
        )

        pdf_name = main_tex.replace(".tex", ".pdf")
        pdf_path = os.path.join(paper_dir, pdf_name)

        if os.path.exists(pdf_path):
            # Copy to output directory with timestamp
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
            output_name = f"{os.path.basename(paper_dir)}_{timestamp}.pdf"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            shutil.copy2(pdf_path, output_path)

            return {
                "success": True,
                "pdf_path": output_path,
                "paper_dir_pdf": pdf_path,
                "log": result.stdout[-2000:] if result.stdout else ""
            }
        else:
            return {
                "success": False,
                "error": "PDF not generated",
                "stdout": result.stdout[-2000:] if result.stdout else "",
                "stderr": result.stderr[-2000:] if result.stderr else ""
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Compilation timed out (120s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def clean_build(paper_dir: str):
    """Clean auxiliary files from a paper directory."""
    extensions = [".aux", ".bbl", ".blg", ".fdb_latexmk", ".fls",
                  ".log", ".out", ".synctex.gz", ".toc"]
    for f in os.listdir(paper_dir):
        if any(f.endswith(ext) for ext in extensions):
            os.remove(os.path.join(paper_dir, f))
    print(f"Cleaned build files in {paper_dir}")


def list_papers():
    """List all paper directories and their status."""
    papers = []
    for d in sorted(os.listdir(DRAFTS_DIR)):
        paper_path = os.path.join(DRAFTS_DIR, d)
        if os.path.isdir(paper_path):
            has_tex = any(f.endswith(".tex") for f in os.listdir(paper_path))
            has_pdf = any(f.endswith(".pdf") for f in os.listdir(paper_path))
            papers.append({
                "name": d,
                "path": paper_path,
                "has_tex": has_tex,
                "has_pdf": has_pdf
            })
    return papers
