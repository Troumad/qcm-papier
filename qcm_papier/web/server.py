"""Serveur FastAPI de l'interface web locale.

Écoute uniquement sur 127.0.0.1 : les copies et les notes ne quittent pas la
machine. Les pages HTML/JS sont servies depuis ``web/static`` sans étape de
compilation.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
import webbrowser
from importlib.metadata import PackageNotFoundError, metadata
from typing import Any
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import editing, pdf_preview, scodoc_config
from ..scodoc_api import ScoDocError
from .session import Session

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
SCODOC_DIR = os.path.join(os.path.dirname(HERE), "data", "scodoc")
SCODOC_IMAGES = {"Scodoc_student_list.png", "Scodoc_eval_get1.png", "Scodoc_eval_get2.png", "Scodoc_eval_send.png"}
DEFAULT_PORT = 8060
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _help_path() -> str:
    pkg = os.path.dirname(HERE)
    for candidate in (os.path.join(pkg, "README.md"), os.path.join(os.path.dirname(pkg), "README.md")):
        if os.path.exists(candidate):
            return candidate
    return ""


def _attachment(data: bytes, filename: str, media_type: str, headers: dict[str, str] | None = None) -> Response:
    all_headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    all_headers.update(headers or {})
    return Response(content=data, media_type=media_type, headers=all_headers)


def create_app(session: Session | None = None) -> FastAPI:
    app = FastAPI(title="QCM-Papier", docs_url="/api/docs", redoc_url=None)
    app.state.session = session or Session()
    request_lock = asyncio.Lock()

    def s() -> Session:
        return app.state.session

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        """Le navigateur local ne doit pas recevoir de commandes d'un autre site."""
        try:
            host = urlsplit(f"//{request.headers.get('host', '')}").hostname
        except ValueError:
            host = None
        origin = request.headers.get("origin")
        if (
            host not in LOCAL_HOSTS
            or (origin is not None and origin != str(request.base_url).rstrip("/"))
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse(status_code=403, content={"detail": "Accès réservé à cette application locale."})
        async with request_lock:
            return await tracked_request(request, call_next)

    async def tracked_request(request: Request, call_next):
        path = request.url.path
        modifying = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if s().job.running and (
            modifying
            and not path.startswith("/api/settings/scodoc")
            and path not in {"/api/scodoc/api/login", "/api/scodoc/api/logout"}
            or path in {"/api/state/save", "/api/generate/bundle"}
        ):
            return JSONResponse(
                status_code=409, content={"detail": "Attendez la fin de la correction avant cette action."}
            )
        changes_subject = modifying and (path == "/api/settings" or path.startswith("/api/structure/"))
        previous = s().project_token() if changes_subject else None
        response = await call_next(request)
        if changes_subject and response.status_code < 400 and previous != s().project_token():
            with s().lock:
                s().variants_stale = bool(s().variant_ids())
                s().preview_pdf = None
        if modifying and response.status_code < 400:
            with s().lock:
                if path in {"/api/project/new", "/api/project/open"}:
                    s().saved_project_token = s().project_token()
                    s().correction_revision += 1
                    s().saved_correction_revision = s().correction_revision
                    s().copies = []
                    s().pages = []
                    s().notes = {}
                elif path.startswith(("/api/copies", "/api/pages/", "/api/correction/")) or path in {
                    "/api/scodoc/students",
                    "/api/scodoc/api/students",
                }:
                    s().correction_revision += 1
        return response

    @app.exception_handler(ScoDocError)
    @app.exception_handler(ValueError)
    @app.exception_handler(RuntimeError)
    async def _bad_request(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(IndexError)
    async def _not_found(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Élément introuvable."})

    async def _save_upload(upload: UploadFile) -> str:
        folder = tempfile.mkdtemp(dir=s().work_dir)
        path = os.path.join(folder, os.path.basename(upload.filename or "fichier"))
        with open(path, "wb") as f:
            f.write(await upload.read())
        return path

    # -- Pages et aide -------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/help", response_class=PlainTextResponse)
    def help_text() -> str:
        path = _help_path()
        if not path:
            # Le README est aussi la description du paquet, disponible après
            # installation d'une wheel hors du dépôt des sources.
            try:
                return metadata("qcm-papier").get_payload() or "Guide README.md indisponible."
            except PackageNotFoundError:
                return "Guide README.md indisponible."
        with open(path, encoding="utf-8") as f:
            return f.read()

    @app.get("/api/scodoc/images/{name}")
    def scodoc_image(name: str) -> FileResponse:
        path = os.path.join(SCODOC_DIR, name)
        if name not in SCODOC_IMAGES or not os.path.exists(path) or os.path.getsize(path) < 100:
            raise HTTPException(status_code=404, detail="Capture d'écran absente.")
        return FileResponse(path)

    @app.get("/api/work")
    def work_state() -> dict[str, Any]:
        return s().work_state()

    @app.post("/api/work/saved")
    def work_saved(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
        s().acknowledge_save(data.get("project_token"), data.get("correction_token"))
        return s().work_state()

    def save_headers(correction: bool = False) -> dict[str, str]:
        state = s().work_state()
        headers = {"X-Project-Token": state["project_token"]}
        if correction:
            headers["X-Correction-Token"] = str(state["correction_token"])
        return headers

    # -- Projet ------------------------------------------------------------
    @app.get("/api/project")
    def project_state() -> dict[str, Any]:
        sess = s()
        with sess.lock:
            return {
                "path": sess.project_path,
                "name": os.path.basename(sess.project_path) if sess.project_path else None,
                "settings": editing.settings_form(sess.project.settings),
                "header_footer": editing.header_footer_view(sess.project.settings),
                "structure": editing.structure_view(sess.project),
                "variants": sess.variant_ids(),
            }

    @app.post("/api/project/new")
    def project_new() -> dict[str, Any]:
        s().new_project()
        return project_state()

    @app.post("/api/project/open")
    async def project_open(file: UploadFile = File(...)) -> dict[str, Any]:
        sess = s()
        sess.load_project(await _save_upload(file))
        sess.project_path = None  # fichier téléversé : pas de chemin d'origine
        return project_state()

    @app.post("/api/project/save")
    def project_save() -> dict[str, str]:
        return {"path": s().save_project()}

    @app.get("/api/project/download")
    def project_download() -> Response:
        sess = s()
        name = sess.project.settings.evaluation_short or "qcm_papier"
        with sess.lock:
            return _attachment(sess.project_json().encode("utf-8"), f"{name}.json", "application/json", save_headers())

    @app.put("/api/settings")
    def settings_update(form: dict[str, Any] = Body(...)) -> dict[str, Any]:
        sess = s()
        with sess.lock:
            editing.apply_settings_form(sess.project.settings, form)
        return project_state()

    # -- Structure -------------------------------------------------------
    @app.post("/api/structure/exercises")
    def exercise_add() -> dict[str, Any]:
        editing.add_exercise(s().project)
        return project_state()

    @app.patch("/api/structure/exercises/{e}")
    def exercise_update(e: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
        editing.update_exercise(s().project.structure[e], data)
        return project_state()

    @app.delete("/api/structure/exercises/{e}")
    def exercise_remove(e: int) -> dict[str, Any]:
        accepted = editing.remove_exercise(s().project, e)
        return {**project_state(), "accepted": accepted}

    @app.post("/api/structure/exercises/{e}/move")
    def exercise_move(e: int, data: dict[str, int] = Body(...)) -> dict[str, Any]:
        accepted = editing.move_exercise(s().project, e, int(data.get("delta", 0)))
        return {**project_state(), "accepted": accepted}

    @app.post("/api/structure/exercises/{e}/questions")
    def question_add(e: int) -> dict[str, Any]:
        editing.add_question(s().project.structure[e])
        return project_state()

    @app.delete("/api/structure/exercises/{e}/questions/{q}")
    def question_remove(e: int, q: int) -> dict[str, Any]:
        accepted = editing.remove_question(s().project.structure[e], q)
        return {**project_state(), "accepted": accepted}

    @app.post("/api/structure/exercises/{e}/questions/{q}/move")
    def question_move(e: int, q: int, data: dict[str, int] = Body(...)) -> dict[str, Any]:
        accepted = editing.move_question(s().project.structure[e], q, int(data.get("delta", 0)))
        return {**project_state(), "accepted": accepted}

    @app.patch("/api/structure/exercises/{e}/questions/{q}")
    def question_update(e: int, q: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
        editing.update_question(s().project.structure[e].questions[q], data)
        return project_state()

    @app.post("/api/structure/exercises/{e}/questions/{q}/choices")
    def choice_add(e: int, q: int) -> dict[str, Any]:
        editing.add_choice(s().project.structure[e].questions[q])
        return project_state()

    @app.delete("/api/structure/exercises/{e}/questions/{q}/choices")
    def choice_remove(e: int, q: int) -> dict[str, Any]:
        editing.remove_choice(s().project.structure[e].questions[q])
        return project_state()

    @app.put("/api/structure/exercises/{e}/questions/{q}/choices/{c}")
    def choice_state(e: int, q: int, c: int, data: dict[str, str] = Body(...)) -> dict[str, Any]:
        question = s().project.structure[e].questions[q]
        accepted = editing.set_choice_state(question, c, data.get("state", ""))
        return {**project_state(), "accepted": accepted}

    # -- Génération ------------------------------------------------------
    @app.post("/api/generate/variants")
    def generate_variants() -> dict[str, Any]:
        success, failed = s().generate_variants()
        message = f"{len(success)} variantes générées."
        if failed:
            message += f" {len(failed)} en échec."
        return {**project_state(), "message": message}

    @app.get("/api/generate/pdf")
    def generate_pdf() -> Response:
        sess = s()
        name = sess.project.settings.evaluation_short or "sujet"
        return _attachment(sess.generate_pdf(), f"{name}.pdf", "application/pdf")

    @app.get("/api/generate/preview")
    def generate_preview() -> dict[str, Any]:
        sizes = s().refresh_preview()
        return {"pages": len(sizes), "sizes": [[w, h] for w, h in sizes]}

    @app.get("/api/generate/preview/{i}")
    def generate_preview_page(i: int, dpi: int = pdf_preview.DPI_DEFAULT) -> Response:
        return Response(content=s().preview_image(i, dpi), media_type="image/png")

    @app.get("/api/generate/bundle")
    def subject_bundle() -> Response:
        with s().lock:
            return _attachment(s().subject_bundle(), "sujet_et_projet.zip", "application/zip", save_headers())

    # -- Correction ------------------------------------------------------
    @app.get("/api/correction")
    def correction_state() -> dict[str, Any]:
        sess = s()
        with sess.lock:
            copies = [
                {"name": c.name, "checked": c.checked, "n_ok": c.n_ok, "n_err": c.n_err, "n_pages": c.n_pages}
                for c in sess.copies
            ]
            return {
                "copies": copies,
                "results": sess.results(),
                "job": vars(sess.job).copy(),
                "clair": sess.clair,
                "notes": len(sess.notes),
                "students": len(sess.project.students),
            }

    @app.post("/api/copies")
    async def copies_add(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        for upload in files:
            s().add_copy(upload.filename or "copie", await upload.read())
        return correction_state()

    @app.patch("/api/copies/{i}")
    def copy_check(i: int, data: dict[str, bool] = Body(...)) -> dict[str, Any]:
        s().set_copy_checked(i, bool(data.get("checked")))
        return correction_state()

    @app.post("/api/copies/remove")
    def copies_remove(data: dict[str, list[int]] = Body(...)) -> dict[str, Any]:
        s().remove_copies(data.get("indices", []))
        return correction_state()

    @app.put("/api/correction/clair")
    def set_clair(data: dict[str, int] = Body(...)) -> dict[str, Any]:
        clair = int(data.get("clair", 140))
        if not 50 <= clair <= 255:
            raise ValueError("Le seuil doit être compris entre 50 et 255.")
        s().clair = clair
        return correction_state()

    @app.post("/api/correction/start")
    def correction_start() -> dict[str, Any]:
        s().start_correction()
        return correction_state()

    @app.get("/api/pages/{i}")
    def page_info(i: int) -> dict[str, Any]:
        return s().page_info(i)

    @app.get("/api/pages/{i}/image")
    def page_image(i: int, raw: bool = False) -> Response:
        return Response(content=s().page_image(i, raw=raw), media_type="image/png")

    @app.post("/api/pages/{i}/student")
    def page_student(i: int, data: dict[str, str] = Body(...)) -> dict[str, Any]:
        s().set_student_id(i, data.get("student_id", ""))
        return s().page_info(i)

    @app.post("/api/pages/{i}/variant")
    def page_variant(i: int, data: dict[str, Any] = Body(...)) -> dict[str, Any]:
        s().set_variant_id(i, str(data.get("variant_id", "")))
        return s().page_info(i)

    @app.post("/api/pages/{i}/align")
    def page_align(i: int, data: dict[str, list[list[float]]] = Body(...)) -> dict[str, Any]:
        points = [(float(x), float(y)) for x, y in data.get("points", [])]
        if len(points) != 5:
            raise ValueError("Il faut exactement 5 repères.")
        ok = s().manual_align(i, points)
        return {**s().page_info(i), "ok": ok}

    # -- Scodoc et sauvegarde --------------------------------------------
    @app.post("/api/scodoc/students")
    async def scodoc_students(file: UploadFile = File(...)) -> dict[str, Any]:
        count, matched = s().load_students(await _save_upload(file))
        return {**correction_state(), "message": f"{count} étudiant(s) chargé(s), {matched} copie(s) identifiée(s)."}

    # -- Réglages du compte ScoDoc dédié (mot de passe dans le trousseau) --
    def _account_view() -> dict[str, Any]:
        account = scodoc_config.load_account()
        return {
            "url": account.url,
            "username": account.username,
            "has_password": account.has_password,
            "complete": account.complete,
            "keyring": scodoc_config.keyring_name(),
        }

    @app.get("/api/settings/scodoc")
    def scodoc_settings() -> dict[str, Any]:
        return _account_view()

    @app.put("/api/settings/scodoc")
    def scodoc_settings_save(data: dict[str, str] = Body(...)) -> dict[str, Any]:
        scodoc_config.save_account(data.get("url", ""), data.get("username", ""), data.get("password") or None)
        s().scodoc_logout()
        return _account_view()

    @app.delete("/api/settings/scodoc")
    def scodoc_settings_delete() -> dict[str, Any]:
        s().scodoc_logout()
        scodoc_config.delete_account()
        return _account_view()

    @app.post("/api/settings/scodoc/test")
    def scodoc_settings_test() -> dict[str, Any]:
        departements = scodoc_config.connect().departements()
        return {"message": f"Connexion réussie : {len(departements)} département(s) visible(s)."}

    # -- Levée d'anonymat via l'API ScoDoc ------------------------------
    @app.get("/api/scodoc/api/status")
    def scodoc_api_status() -> dict[str, Any]:
        account = scodoc_config.load_account()
        return {
            "connected": s().scodoc_client is not None and bool(s().scodoc_client.token),
            "configured": account.complete,
            "url": account.url,
            "username": account.username,
        }

    @app.post("/api/scodoc/api/login")
    def scodoc_api_login() -> dict[str, Any]:
        departements = s().scodoc_login()
        return {**scodoc_api_status(), "departements": departements}

    @app.post("/api/scodoc/api/logout")
    def scodoc_api_logout() -> dict[str, Any]:
        s().scodoc_logout()
        return scodoc_api_status()

    @app.get("/api/scodoc/api/formsemestres")
    def scodoc_api_formsemestres(departement: str) -> list[dict[str, Any]]:
        return s().scodoc_formsemestres(departement)

    @app.post("/api/scodoc/api/students")
    def scodoc_api_students(data: dict[str, int] = Body(...)) -> dict[str, Any]:
        count, matched = s().scodoc_load_students(int(data["formsemestre_id"]))
        message = f"{count} étudiant(s) chargé(s) depuis ScoDoc, {matched} copie(s) identifiée(s)."
        return {**correction_state(), "message": message}

    @app.post("/api/scodoc/export")
    async def scodoc_export(file: UploadFile = File(...), min0: bool = Form(False)) -> Response:
        count, data = s().export_scodoc(await _save_upload(file), min0)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return _attachment(data, "notes_scodoc.xlsx", media, {"X-Notes-Count": str(count)})

    @app.get("/api/state/save")
    def state_save() -> Response:
        with s().lock:
            return _attachment(s().save_state_zip(), "correction.zip", "application/zip", save_headers(True))

    @app.post("/api/state/load")
    async def state_load(file: UploadFile = File(...)) -> dict[str, Any]:
        s().start_load_state_zip(await file.read())
        return correction_state()

    return app


def _exit_when_parent_dies(interval: float = 1.0) -> None:
    """Arrête le serveur si le processus parent (l'application Tauri) disparaît."""
    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(interval)
            if os.getppid() != parent:
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def run(host: str = "127.0.0.1", port: int = DEFAULT_PORT, project_path: str | None = None,
        open_browser: bool = True, exit_with_parent: bool = False) -> int:  # fmt: skip
    import uvicorn

    if host not in LOCAL_HOSTS:
        raise ValueError("Le serveur doit écouter sur une adresse locale (127.0.0.1, localhost ou ::1).")
    if exit_with_parent:
        _exit_when_parent_dies()
    session = Session()
    if project_path:
        session.load_project(project_path)
    app = create_app(session)
    url_host = f"[{host}]" if ":" in host else host
    url = f"http://{url_host}:{port}/"
    print(f"Interface web : {url} (Ctrl+C pour arrêter)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
