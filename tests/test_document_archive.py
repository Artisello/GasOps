from datetime import datetime
from time import time
import json

import pymupdf
import pytest

from gasops_app.document_archive import Archive, ArchiveConfig, AdminSession, ArchiveError, object_name, display_name

ADMIN="00000000-0000-4000-8000-000000000001"
CONFIG=ArchiveConfig("https://fixture.supabase.co","sb_publishable_fixture",ADMIN)


def pdf(text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40,80),text)
        return doc.tobytes()


class Response:
    def __init__(self,obj=None,data=b"",status=200):
        self.obj=obj
        self.data=data
        self.status_code=status
    def __enter__(self):
        return self
    def __exit__(self,*args):
        self.close()
    def close(self):
        pass
    def json(self):
        return self.obj
    def iter_content(self,n):
        yield self.data


def test_persistence_and_admin_headers(monkeypatch):
    monkeypatch.setattr("gasops_app.document_archive.private_access",lambda:True)
    from gasops_app import document_archive as mod
    objects={}
    def fake(method,url,headers,**kwargs):
        path=url.removeprefix(CONFIG.url)
        assert headers["apikey"]==CONFIG.publishable_key
        assert kwargs["allow_redirects"] is False
        if path=="/auth/v1/token":
            assert "Authorization" not in headers
            return Response({"user":{"id":ADMIN},"access_token":"jwt","expires_in":3600})
        if "/object/list/" in path:
            return Response([{"name":k,"metadata":{"size":len(v)}} for k,v in sorted(objects.items())])
        if "/object/public/" in path:
            return Response(data=objects[path.rsplit("/",1)[-1]])
        assert headers["Authorization"]=="Bearer jwt"
        if method=="POST":
            assert headers["x-upsert"]=="false"
            key=path.rsplit("/",1)[-1]
            assert key not in objects
            objects[key]=kwargs["data"]
        elif method=="DELETE":
            for key in kwargs["json"]["prefixes"]:
                del objects[key]
        return Response({})
    monkeypatch.setattr(mod.requests,"request",fake)
    admin=Archive(CONFIG).login("admin@example.test","password")
    raw=pdf("Garanzia economica.")
    count,notes=Archive(CONFIG).publish(admin,(("norme.pdf",raw),))
    assert count==1 and not notes
    # A fresh instance (distinct from UI/session) reads the same persistent object.
    key=object_name("norme.pdf",raw)
    assert Archive(CONFIG).read()==((key,raw),)
    assert display_name(key)=="norme.pdf"
    assert Archive(CONFIG).publish(admin,(("copia.pdf",raw),))[0]==0
    Archive(CONFIG).remove(admin,key)
    assert Archive(CONFIG).read()==()


def test_admin_and_key_checks_before_network(monkeypatch):
    from gasops_app import document_archive as mod
    monkeypatch.setattr(mod.requests,"request",lambda *a,**k:pytest.fail("Unexpected request"))
    raw=pdf("Test.")
    for session in (AdminSession("jwt",time()-1,ADMIN),AdminSession("jwt",time()+100,"other")):
        with pytest.raises(ArchiveError):
            Archive(CONFIG).publish(session,(("x.pdf",raw),))
        with pytest.raises(ArchiveError):
            Archive(CONFIG).remove(session,"x.pdf")
    with pytest.raises(ValueError):
        ArchiveConfig(CONFIG.url,"sb_secret_fixture",ADMIN)
    with pytest.raises(ValueError):
        ArchiveConfig("https://evil.example",CONFIG.publishable_key,ADMIN)


def test_remote_hash_mismatch_is_rejected(monkeypatch):
    from gasops_app import document_archive as mod
    raw=pdf("Originale.")
    key=object_name("norme.pdf",raw)
    altered=pdf("Diverso.")
    def fake(method,url,**kwargs):
        return Response([{"name":key,"metadata":{"size":len(altered)}}]) if "/list/" in url else Response(data=altered)
    monkeypatch.setattr(mod.requests,"request",fake)
    with pytest.raises(ArchiveError,match="SHA-256"):
        Archive(CONFIG).read()



def test_authorized_contributor_can_publish_but_not_delete(monkeypatch):
    from gasops_app import document_archive as mod
    contributor="00000000-0000-4000-8000-000000000002"
    cfg=ArchiveConfig(CONFIG.url,CONFIG.publishable_key,ADMIN,(contributor,))
    called=[]
    session=AdminSession("jwt",time()+100,contributor)
    assert session.valid(cfg) and not session.is_admin(cfg)
    backend=Archive(cfg)
    monkeypatch.setattr(backend,"read",lambda session:())
    def fake(method,path,**kwargs):
        called.append(method)
        return Response({})
    monkeypatch.setattr(backend,"_request",fake)
    assert backend.publish(session,(("public.pdf",pdf("Documento pubblico.")),))[0]==1
    with pytest.raises(ArchiveError):
        backend.remove(session,"public.pdf")
    assert called==["POST"]
    with pytest.raises(ValueError):
        ArchiveConfig(CONFIG.url,CONFIG.publishable_key,ADMIN,("invalid",))


def test_archive_reads_only_current_manifest_with_optional_reader(monkeypatch):
    raw=pdf("Versione immutabile.")
    key=object_name("a.pdf",raw)
    backend=Archive(CONFIG)
    monkeypatch.setattr(backend,"list_keys",lambda session=None:(key,))
    used=[]
    def reader(name):
        used.append(name)
        return raw
    assert backend.read(reader=reader)==((key,raw),)
    monkeypatch.setattr(backend,"list_keys",lambda session=None:())
    assert backend.read(reader=reader)==()
    assert used==[key]
    with pytest.raises(ArchiveError):
        backend.read(AdminSession("jwt",time()+100,ADMIN),reader=reader)
