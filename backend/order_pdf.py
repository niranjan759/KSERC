"""The draft order as a PDF: the Word draft (order_draft) converted by
LibreOffice, run headless - free, open-source and offline, like the rest of
the pipeline. Word's own PDF export would need Microsoft Office.

LibreOffice is found on the PATH, at SOFFICE_PATH, or where its installer
puts it on Windows, macOS and Linux."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

INSTALL_HINT = ("The PDF download needs LibreOffice (free, from libreoffice.org; on Windows: "
                "winget install TheDocumentFoundation.LibreOffice). Install it and try again, "
                "or set SOFFICE_PATH to its soffice program.")


class NoConverter(RuntimeError):
    pass


def find_soffice():
    candidates = [os.environ.get("SOFFICE_PATH"), shutil.which("soffice"), shutil.which("libreoffice")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 r"C:\Program Files", r"C:\Program Files (x86)"):
        if base:
            candidates.append(str(Path(base) / "LibreOffice" / "program" / "soffice.exe"))
    candidates += ["/Applications/LibreOffice.app/Contents/MacOS/soffice", "/usr/bin/soffice", "/usr/local/bin/soffice"]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def docx_to_pdf(docx_bytes, timeout=600):
    """PDF bytes for a .docx. A 240-page order takes LibreOffice about a
    minute."""
    soffice = find_soffice()
    if not soffice:
        raise NoConverter(INSTALL_HINT)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "order.docx"
        src.write_bytes(docx_bytes)
        # its own profile, so a conversion works while the reviewer has
        # LibreOffice open (a second instance would otherwise just hand the
        # file to the first and return at once, converting nothing)
        profile = (tmp / "profile").as_uri()
        try:
            run = subprocess.run([soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                                  "--convert-to", "pdf", "--outdir", str(tmp), str(src)],
                                 capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"LibreOffice took more than {timeout // 60} minutes to convert the draft.")
        out = tmp / "order.pdf"
        if not out.is_file():
            detail = (run.stderr or run.stdout or b"").decode(errors="replace").strip()
            raise RuntimeError("LibreOffice could not convert the draft" + (f": {detail}" if detail else "."))
        return out.read_bytes()
