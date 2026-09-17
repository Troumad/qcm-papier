"""Rendu des pages d'un PDF en images PNG, pour l'aperçu intégré.

L'interface web affiche le sujet sans le télécharger ni dépendre de la
visionneuse du navigateur : le serveur rend chaque page à la demande, comme il
le fait déjà pour les copies corrigées. Le même rendu fonctionne donc dans
toutes les fenêtres, y compris celle de l'application Tauri sous Linux, où un
PDF placé dans un cadre reste blanc.

**PyMuPDF** est déjà utilisé par le lecteur de copies (``scanner.py``).
"""

from __future__ import annotations

# Bornes du rendu : en dessous l'image est illisible, au-dessus elle pèse
# lourd pour rien à l'écran.
DPI_MIN = 24
DPI_MAX = 600
DPI_DEFAULT = 110


def _open(pdf: bytes):
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - PyMuPDF est une dépendance
        raise RuntimeError("PyMuPDF est nécessaire pour l'aperçu du PDF.") from exc
    try:
        return pymupdf.open(stream=pdf, filetype="pdf")
    except Exception as exc:
        raise ValueError("Document PDF illisible.") from exc


def page_sizes(pdf: bytes) -> list[tuple[float, float]]:
    """Largeur et hauteur de chaque page, en points PostScript (1/72 pouce)."""
    doc = _open(pdf)
    try:
        return [(page.rect.width, page.rect.height) for page in doc]
    finally:
        doc.close()


def render_page(pdf: bytes, index: int, dpi: int = DPI_DEFAULT) -> bytes:
    """Rend une page en PNG. ``index`` part de 0."""
    if not DPI_MIN <= dpi <= DPI_MAX:
        raise ValueError(f"Résolution attendue entre {DPI_MIN} et {DPI_MAX} points par pouce : {dpi}")
    doc = _open(pdf)
    try:
        if not 0 <= index < doc.page_count:
            raise IndexError(f"Page hors du document : {index}")
        return doc.load_page(index).get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()
