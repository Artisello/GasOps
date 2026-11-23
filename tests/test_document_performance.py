from pathlib import Path
import pymupdf
from streamlit.testing.v1 import AppTest
from gasops_app import document_page as desk
from gasops_app.document_archive import ArchiveConfig,object_name,Archive


def _pdf(text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40,80),text)
        return doc.tobytes()


def test_shared_repository_index_reused_and_changed_file_reindexed(monkeypatch,tmp_path):
    monkeypatch.delenv("GASOPS_PDF_DIR",raising=False)
    monkeypatch.setattr(desk,"ROOT",tmp_path)
    monkeypatch.setattr(desk,"_archive_config",lambda:None)
    folder=tmp_path/"data"/"public-regulatory"
    folder.mkdir(parents=True)
    path=folder/"test.pdf"
    path.write_bytes(_pdf("Garanzia economica."))
    desk._public_local.clear()
    desk._public_index.clear()
    original=desk.build
    calls=[]
    def counted(inputs):
        if inputs:calls.append(len(inputs))
        return original(inputs)
    monkeypatch.setattr(desk,"build",counted)
    script="from gasops_app.document_page import document_page\ndocument_page()"
    try:
        first=AppTest.from_string(script).run()
        second=AppTest.from_string(script).run()
        assert calls==[]  # Navigation only reads the cheap public manifest.
        first.button(key="document_local_open").click().run()
        second.button(key="document_local_open").click().run()
        assert not first.exception and not second.exception
        assert calls==[1]
        first.radio(key="desk_mode").set_value("Riferimenti salvati").run()
        assert calls==[1]
        documents=first.session_state[desk.STATE]["docs"].documents
        title,pdf=next(iter(documents.items()))
        assert len(documents)==1 and pdf.name=="test.pdf"
        first.session_state[desk.STATE]["reference_list"].append({"document":title,
            "sha256":pdf.digest,"page":1,"excerpt":"Garanzia"})
        assert not second.session_state[desk.STATE]["reference_list"]
        path.write_bytes(_pdf("Nuovo testo normativo revisione."))
        first.run()
        assert not first.exception and calls==[1,1]
        assert not first.session_state[desk.STATE]["reference_list"]
    finally:
        desk._public_local.clear()
        desk._public_index.clear()


def test_personal_scope_never_fetches_or_indexes_public(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(desk,"_archive_config",lambda:ArchiveConfig("https://fixture.supabase.co","sb_publishable_fixture"))
    def forbidden(*args,**kwargs):raise AssertionError("Public archive loaded during personal view")
    monkeypatch.setattr(desk,"_read_remote",forbidden)
    monkeypatch.setattr(desk,"_public_index",forbidden)
    raw=_pdf("Documento personale.")
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()")
    app.session_state[desk.SCOPE]="I miei PDF"
    app.session_state[desk.VISITOR_UPLOADS]=(("privato.pdf",raw),)
    app.run()
    assert not app.exception and desk.STATE not in app.session_state
    documents=app.session_state[desk.VISITOR_STATE]["docs"].documents
    assert len(documents)==1
    pdf=next(iter(documents.values()))
    assert pdf.name=="privato.pdf" and pdf.data==raw


def test_remote_manifest_refresh_reuses_hash_addressed_pdf(monkeypatch):
    cfg=ArchiveConfig("https://fixture.supabase.co","sb_publishable_fixture")
    raw=_pdf("Documento remoto.")
    key=object_name("norme.pdf",raw)
    names=[key]
    downloads=[]
    monkeypatch.setattr(Archive,"list_keys",lambda self,session=None:tuple(names))
    def read(self,name):
        downloads.append(name)
        return raw
    monkeypatch.setattr(Archive,"read_document",read)
    desk._read_remote.clear()
    desk._read_remote_pdf.clear()
    try:
        assert desk._read_remote(cfg)==((key,raw),)
        desk._read_remote.clear()
        assert desk._read_remote(cfg)==((key,raw),)
        assert downloads==[key]
        names[:]=[]
        desk._read_remote.clear()
        assert desk._read_remote(cfg)==()
        assert downloads==[key]
        names[:]=["legacy.pdf"]
        desk._read_remote.clear()
        desk._read_remote(cfg)
        desk._read_remote.clear()
        desk._read_remote(cfg)
        assert downloads==[key,"legacy.pdf","legacy.pdf"]
    finally:
        desk._read_remote.clear()
        desk._read_remote_pdf.clear()
