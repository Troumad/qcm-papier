"""État d'une session de l'interface web (une personne, sur sa machine).

Regroupe les actions de l'interface GTK (``ui/app.py``) sans code
d'interface : projet, copies à corriger, pages corrigées, levée d'anonymat,
export Scodoc, alignement manuel, sauvegarde et reprise d'une correction.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .. import editing, generator, pdf_writer, scanner, scodoc, scodoc_api, scodoc_config
from .. import project as project_mod
from ..marking import score_page
from ..model import Project

CLAIR_DEFAULT = 140


@dataclass
class CopyFile:
    """Un fichier de copies (PDF ou image) chargé dans la session."""

    path: str
    name: str
    checked: bool = True
    n_ok: int = 0
    n_err: int = 0
    n_pages: int = 0


@dataclass
class MarkedPage:
    """Une page lue, corrigée ou non."""

    page: scanner.ScannedPage
    file_name: str
    restored: bool = False


@dataclass
class Job:
    """Tâche longue en arrière-plan (correction, rechargement)."""

    kind: str = ""
    running: bool = False
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""


def _safe_name(name: str) -> str:
    base = os.path.basename(name or "fichier")
    return re.sub(r"[^\w.\-]+", "_", base) or "fichier"


def failure_reason(page: scanner.ScannedPage) -> str | None:
    """Raison d'échec affichée pour une page, ou None si elle est corrigée."""
    if page.matrix_inv is not None and page.variant_id is not None and page.student_id is not None:
        return None
    if page.variant_id is not None and page.student_id is None:
        return "N° étudiant non trouvé"
    if page.variant_id is None:
        return "Code-barres non trouvé"
    return "Échec alignement"


def _label_font(size: int = 16):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


class Session:
    def __init__(self, work_dir: str | None = None):
        self.lock = threading.RLock()
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="qcm-papier-")
        self.project = Project()
        self.project_path: str | None = None
        self.copies: list[CopyFile] = []
        self.pages: list[MarkedPage] = []
        self.notes: dict[str, float] = {}
        self.clair = CLAIR_DEFAULT
        self.job = Job()
        self.scodoc_client: scodoc_api.ScoDocClient | None = None

    # ------------------------------------------------------------------
    # Projet
    # ------------------------------------------------------------------
    def new_project(self) -> None:
        with self.lock:
            self.project = Project()
            self.project_path = None
            self.copies = []
            self.pages = []
            self.notes = {}

    def load_project(self, path: str) -> None:
        project = project_mod.load_project(path)
        editing.apply_info_defaults(project.settings)
        with self.lock:
            self.project = project
            self.project_path = path

    def project_json(self) -> str:
        return project_mod.project_to_json(self.project)

    def save_project(self) -> str:
        """Enregistre dans le fichier d'origine (projet ouvert depuis un chemin)."""
        if not self.project_path:
            raise ValueError("Projet sans fichier d'origine : utilisez « Télécharger ».")
        project_mod.save_project(self.project, self.project_path)
        return self.project_path

    def variant_ids(self) -> list[str]:
        return [k for k in self.project.variants if k not in ("p", "l")]

    def generate_variants(self) -> tuple[list[int], list[int]]:
        with self.lock:
            success, failed = generator.generate_all(self.project, retry=True)
            self.project.settings.generate_variants = ";".join(str(i) for i in success + failed)
        return success, failed

    def generate_pdf(self) -> bytes:
        if not self.variant_ids():
            raise ValueError("Aucune variante : générez d'abord les variantes.")
        return pdf_writer.generate_pdf(self.project)

    # ------------------------------------------------------------------
    # Copies
    # ------------------------------------------------------------------
    def add_copy(self, filename: str, data: bytes) -> CopyFile:
        folder = os.path.join(self.work_dir, "copies")
        os.makedirs(folder, exist_ok=True)
        name = _safe_name(filename)
        stem, ext = os.path.splitext(name)
        path = os.path.join(folder, name)
        n = 1
        while os.path.exists(path):
            path = os.path.join(folder, f"{stem}_{n}{ext}")
            n += 1
        with open(path, "wb") as f:
            f.write(data)
        copy = CopyFile(path=path, name=os.path.basename(path))
        with self.lock:
            self.copies.append(copy)
        return copy

    def remove_copies(self, indices: list[int]) -> None:
        with self.lock:
            removed = {self.copies[i].path for i in indices if 0 <= i < len(self.copies)}
            self.copies = [c for c in self.copies if c.path not in removed]
            self.pages = [p for p in self.pages if p.page.copy_path not in removed]
            self.notes = self._collect_notes()

    def set_copy_checked(self, index: int, checked: bool) -> None:
        with self.lock:
            self.copies[index].checked = checked

    # ------------------------------------------------------------------
    # Correction
    # ------------------------------------------------------------------
    def _start_job(self, kind: str, total: int, work: Callable[[], None]) -> None:
        with self.lock:
            if self.job.running:
                raise RuntimeError("Une tâche est déjà en cours.")
            self.job = Job(kind=kind, running=True, total=total)

        def run() -> None:
            try:
                work()
            except Exception as e:  # noqa: BLE001 - l'erreur est affichée dans l'interface
                self.job.error = str(e)
            finally:
                self.job.running = False

        threading.Thread(target=run, daemon=True).start()

    def start_correction(self) -> None:
        if not self.variant_ids():
            raise ValueError("Aucune variante : chargez un projet avec variantes générées.")
        to_correct = [c for c in self.copies if c.checked]
        if not to_correct:
            raise ValueError("Aucune copie à corriger (cochez les fichiers souhaités).")
        self._start_job("correction", len(to_correct), lambda: self._correct(to_correct))

    def _correct(self, to_correct: list[CopyFile]) -> None:
        with self.lock:
            self.pages = []
        n_ok = n_err = 0
        for i, copy in enumerate(to_correct, 1):
            self.job.message = f"Correction {i}/{len(to_correct)} : {copy.name}"
            copy.n_ok = copy.n_err = 0
            try:
                pages = scanner.load_pages_from_file(copy.path, dpi=150)
            except Exception as e:  # noqa: BLE001
                copy.n_err, copy.n_pages = 1, 1
                n_err += 1
                self.job.message = f"{copy.name} : erreur ({e})"
                continue
            copy.n_pages = len(pages)
            for page in pages:
                page.copy_path = copy.path
                if scanner.auto_check(page, self.project, clair=self.clair):
                    copy.n_ok += 1
                    n_ok += 1
                else:
                    copy.n_err += 1
                    n_err += 1
                with self.lock:
                    self.pages.append(MarkedPage(page=page, file_name=copy.name))
            copy.checked = False
            self.job.done = i
        with self.lock:
            self.notes = self._collect_notes()
        self.job.message = f"{n_ok} corrigée(s), {n_err} en erreur sur {len(to_correct)} fichier(s)."

    def _collect_notes(self) -> dict[str, float]:
        """Notes par EID après levée d'anonymat, sinon par n° étudiant."""
        notes: dict[str, float] = {}
        for marked in self.pages:
            page = marked.page
            key = page.student_eid or page.student_id
            if key and page.value is not None and failure_reason(page) is None:
                notes.setdefault(key, float(page.value))
        return notes

    def page_info(self, index: int) -> dict[str, Any]:
        marked = self.pages[index]
        page = marked.page
        reason = "Non lue" if marked.restored and page.variant_id is None and not page.marks else failure_reason(page)
        name = f"{page.student_name or ''} {page.student_firstname or ''}".strip()
        return {
            "index": index,
            "file": marked.file_name,
            "variant": page.variant_id,
            "student_id": page.student_id,
            "student": name or page.student_id or "",
            "note": page.value if page.matrix_inv is not None else None,
            "total": page.total,
            "complete": page.complete,
            "status": reason or ("complète" if page.complete else "incomplète"),
            "failed": reason is not None,
            "aligned": page.matrix_inv is not None,
        }

    def results(self) -> list[dict[str, Any]]:
        with self.lock:
            return [self.page_info(i) for i in range(len(self.pages))]

    # ------------------------------------------------------------------
    # Scodoc
    # ------------------------------------------------------------------
    def load_students(self, path: str) -> tuple[int, int]:
        """Levée d'anonymat depuis la table étudiants Excel de ScoDoc."""
        return self.apply_students(scodoc.load_students_table(path))

    def scodoc_login(self) -> list[dict[str, str]]:
        """Connexion à l'API ScoDoc avec le compte dédié enregistré (voir scodoc_config)."""
        self.scodoc_logout()
        client = scodoc_config.connect()
        departements = [scodoc_api.departement_view(d) for d in client.departements()]
        with self.lock:
            self.scodoc_client = client
        return departements

    def scodoc_logout(self) -> None:
        with self.lock:
            self.scodoc_client = None

    def _scodoc(self) -> scodoc_api.ScoDocClient:
        if self.scodoc_client is None:
            raise ValueError("Non connecté à ScoDoc.")
        return self.scodoc_client

    def scodoc_formsemestres(self, departement: str) -> list[dict[str, Any]]:
        return [scodoc_api.formsemestre_view(s) for s in self._scodoc().formsemestres_courants(departement)]

    def scodoc_load_students(self, formsemestre_id: int) -> tuple[int, int]:
        """Levée d'anonymat avec les étudiants d'un semestre lus sur ScoDoc."""
        etudiants = self._scodoc().formsemestre_etudiants(formsemestre_id)
        return self.apply_students(scodoc_api.students_from_api(etudiants))

    def apply_students(self, students: dict) -> tuple[int, int]:
        """Associe nom, prénom et EID aux pages corrigées. Renvoie (étudiants, copies identifiées)."""
        with self.lock:
            self.project.students = students
            matched = 0
            for marked in self.pages:
                page = marked.page
                student = students.get(page.student_id) if page.student_id else None
                if student is not None:
                    page.student_eid = student.eid
                    page.student_name = student.name
                    page.student_firstname = student.firstname
                    matched += 1
                else:
                    page.student_eid = None
                    page.student_name = None
                    page.student_firstname = None
            self.notes = self._collect_notes()
        return len(students), matched

    def export_scodoc(self, path_in: str, min0: bool) -> tuple[int, bytes]:
        if not self.notes:
            raise ValueError("Aucune note à exporter : corrigez d'abord.")
        path_out = os.path.join(tempfile.mkdtemp(dir=self.work_dir), "notes_scodoc.xlsx")
        count = scodoc.export_scodoc_notes(path_in, path_out, self.notes, min0=min0)
        with open(path_out, "rb") as f:
            return count, f.read()

    # ------------------------------------------------------------------
    # Visionneuse : n° étudiant, alignement manuel, images
    # ------------------------------------------------------------------
    def set_student_id(self, index: int, student_id: str) -> None:
        student_id = student_id.strip()
        if not student_id:
            raise ValueError("N° étudiant vide.")
        with self.lock:
            page = self.pages[index].page
            page.student_id = student_id
            student = self.project.students.get(student_id)
            if student is not None:
                page.student_eid = student.eid
                page.student_name = student.name
                page.student_firstname = student.firstname
            else:
                page.student_eid = None
                page.student_name = None
                page.student_firstname = None
            score = score_page(self.project, page.marks, variant_id=page.variant_id, student_id=page.student_id)
            page.value, page.total, page.complete = score.value, score.total, score.complete
            self.notes = self._collect_notes()

    def manual_align(self, index: int, points: list[tuple[float, float]]) -> bool:
        with self.lock:
            page = self.pages[index].page
            ok = scanner.correct_with_manual_align(page, self.project, points, clair=self.clair)
            if ok:
                page.manual_marks = list(points)  # type: ignore[attr-defined]
                self.notes = self._collect_notes()
            return ok

    def page_image(self, index: int, raw: bool = False) -> bytes:
        """PNG de la page : brute (alignement manuel) ou corrigée avec repères bleus."""
        with self.lock:
            page = self.pages[index].page
            if raw or page.matrix_inv is None and not getattr(page, "manual_marks", None):
                img = page.img.img.convert("RGBA") if page.img is not None else None
            else:
                img = scanner.render_marked_page(page)
            if img is None:
                raise ValueError("Aucune image pour cette page.")
            if not raw:
                img = self._draw_reference_marks(page, img)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _draw_reference_marks(page: scanner.ScannedPage, img: Image.Image) -> Image.Image:
        """Repères d'orientation en bleu numérotés (comme la fenêtre GTK agrandie)."""
        marks = []
        if page.matrix_inv is not None:
            marks = [(float(s["canvas_x"]), float(s["canvas_y"])) for s in page.shapes if "canvas_x" in s]
        if len(marks) != 5:
            marks = list(getattr(page, "manual_marks", []))
        if not marks:
            return img
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = _label_font(16)
        r = 8
        for i, (px, py) in enumerate(marks, 1):
            draw.ellipse((px - r - 3, py - r - 3, px + r + 3, py + r + 3), outline=(255, 255, 255, 255), width=3)
            draw.ellipse((px - r, py - r, px + r, py + r), fill=(0, 120, 255, 230), outline=(255, 255, 255, 255))
            tw, th = draw.textbbox((0, 0), str(i), font=font)[2:]
            bx, by = px + r + 2, py - th / 2 - 2
            draw.rectangle((bx, by, bx + tw + 6, by + th + 4), fill=(0, 120, 255, 230), outline=(255, 255, 255, 255))
            draw.text((bx + 3, by + 1), str(i), font=font, fill=(255, 255, 255, 255))
        return Image.alpha_composite(img.convert("RGBA"), overlay)

    # ------------------------------------------------------------------
    # Sauvegarde et reprise (archive zip : état, images corrigées, copies)
    # ------------------------------------------------------------------
    def save_state_zip(self) -> bytes:
        with self.lock:
            if not self.pages:
                raise ValueError("Aucune correction à sauvegarder.")
            tmp = tempfile.mkdtemp(dir=self.work_dir)
            state_path = os.path.join(tmp, "correction.json")
            pages = [m.page for m in self.pages]
            scanner.save_correction_state(pages, [p.copy_path or "" for p in pages], state_path)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("project.json", self.project_json())
                zf.write(state_path, "correction.json")
                images = os.path.join(tmp, "correction_images")
                for name in sorted(os.listdir(images)):
                    zf.write(os.path.join(images, name), f"correction_images/{name}")
                for copy in self.copies:
                    zf.write(copy.path, f"copies/{copy.name}")
        shutil.rmtree(tmp, ignore_errors=True)
        return buf.getvalue()

    def start_load_state_zip(self, data: bytes) -> None:
        if self.job.running:
            raise RuntimeError("Une tâche est déjà en cours.")
        folder = tempfile.mkdtemp(prefix="reprise-", dir=self.work_dir)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                target = os.path.realpath(os.path.join(folder, member))
                if not target.startswith(os.path.realpath(folder) + os.sep):
                    raise ValueError(f"Chemin interdit dans l'archive : {member}")
            zf.extractall(folder)
        state_path = os.path.join(folder, "correction.json")
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
        copies_dir = os.path.join(folder, "copies")
        for entry in state.get("copies", []):
            entry["file"] = os.path.join(copies_dir, os.path.basename(entry["file"]))
        state["image_dir"] = os.path.join(folder, "correction_images")
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        names = sorted(os.listdir(copies_dir)) if os.path.isdir(copies_dir) else []
        with self.lock:
            project_path = os.path.join(folder, "project.json")
            if os.path.exists(project_path):
                self.project = project_mod.load_project(project_path)
                self.project_path = None
            self.copies = [CopyFile(path=os.path.join(copies_dir, n), name=n, checked=False) for n in names]
        self._start_job("reprise", len(self.copies), lambda: self._load_state(state_path))

    def _load_state(self, state_path: str) -> None:
        with self.lock:
            self.pages = []
        n_ok = n_err = 0
        for i, copy in enumerate(self.copies, 1):
            self.job.message = f"Rechargement {i}/{len(self.copies)} : {copy.name}"
            pages = scanner.load_pages_from_file(copy.path, dpi=150)
            copy.n_pages, copy.n_ok, copy.n_err = len(pages), 0, 0
            for page_index, page in enumerate(pages):
                page.copy_path = copy.path
                if scanner.load_correction_state(copy.path, page, state_path, page_index=page_index):
                    copy.n_ok += 1
                    n_ok += 1
                    with self.lock:
                        self.pages.append(MarkedPage(page=page, file_name=copy.name, restored=True))
                else:
                    copy.n_err += 1
                    n_err += 1
            self.job.done = i
        with self.lock:
            self.notes = self._collect_notes()
        self.job.message = f"{n_ok} page(s) restaurée(s), {n_err} non trouvée(s) dans la sauvegarde."
