"""Shared public PDF archive backed by Supabase Storage, without elevated keys."""
from dataclasses import dataclass
from hashlib import sha256
import re
from time import time
from urllib.parse import quote
from uuid import UUID
import unicodedata

import requests

from .document_desk import MAX_TOTAL_BYTES, extend_uploads
from .regulatory import MAX_DOCUMENTS, MAX_PDF_BYTES

BUCKET="gasops-documents"


class ArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchiveConfig:
    url: str
    publishable_key: str
    admin_id: str = ""

    def __post_init__(self):
        if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co",self.url):
            raise ValueError("URL Supabase non valida.")
        if not self.publishable_key.startswith("sb_publishable_"):
            raise ValueError("Usa una chiave publishable, non una chiave segreta.")
        if self.admin_id:
            UUID(self.admin_id)


@dataclass(frozen=True)
class AdminSession:
    token: str
    expires: float
    user_id: str

    def valid(self,config):
        return bool(self.token and self.user_id==config.admin_id and self.expires>time()+15)


def object_name(name,data):
    name=unicodedata.normalize("NFKD",name).encode("ascii","ignore").decode()
    name=re.sub(r"[^a-zA-Z0-9._-]+","_",name.rsplit("/",1)[-1]).strip("._")[:100]
    name=re.sub(r"\.pdf$","",name,flags=re.I) or "documento"
    return sha256(data).hexdigest()+"--"+name+".pdf"


def display_name(key):
    match=re.fullmatch(r"[a-f0-9]{64}--(.+\.pdf)",key,re.I)
    return match.group(1) if match else key


class Archive:
    def __init__(self,config):
        self.config=config

    def _request(self,method,path,*,session=None,**kwargs):
        headers={"apikey":self.config.publishable_key,**kwargs.pop("headers",{})}
        if session is not None:
            if not session.valid(self.config):
                raise ArchiveError("Sessione amministratore scaduta. Accedi nuovamente.")
            headers["Authorization"]="Bearer "+session.token
        try:
            response=requests.request(method,self.config.url+path,headers=headers,
                                      timeout=(5,45),allow_redirects=False,**kwargs)
            if not 200<=response.status_code<300:
                response.close()
                raise ArchiveError("Archivio remoto: operazione non riuscita (HTTP "+str(response.status_code)+").")
            return response
        except requests.RequestException:
            raise ArchiveError("Archivio remoto temporaneamente non raggiungibile.") from None

    def login(self,email,password):
        if not self.config.admin_id:
            raise ArchiveError("Gestione amministratore non configurata.")
        try:
            with self._request("POST","/auth/v1/token",params={"grant_type":"password"},
                               json={"email":email,"password":password}) as response:
                obj=response.json()
            user_id=obj["user"]["id"]
            token=obj["access_token"]
            result=AdminSession(token,time()+min(float(obj["expires_in"]),3600),user_id)
            if not result.valid(self.config):
                raise ValueError("not administrator")
            return result
        except (ArchiveError,ValueError,KeyError,TypeError):
            raise ArchiveError("Accesso amministratore non riuscito.") from None

    def list_keys(self,session=None):
        try:
            with self._request("POST","/storage/v1/object/list/"+BUCKET,session=session,
                               json={"prefix":"","limit":MAX_DOCUMENTS+1,"offset":0,
                                     "sortBy":{"column":"name","order":"asc"}}) as response:
                items=response.json()
            if not isinstance(items,list) or len(items)>MAX_DOCUMENTS:
                raise ValueError("limit")
            keys=[]
            size=0
            for item in items:
                name=item["name"]
                count=int(item["metadata"]["size"])
                if (not isinstance(name,str) or "/" in name or "\\" in name or
                    not name.lower().endswith(".pdf") or not 0<count<=MAX_PDF_BYTES):
                    raise ValueError("invalid object")
                size+=count
                if size>MAX_TOTAL_BYTES or name in keys:
                    raise ValueError("archive limit")
                keys.append(name)
            return tuple(keys)
        except (ValueError,KeyError,TypeError):
            raise ArchiveError("Archivio remoto non conforme: verifica PDF e limiti nel bucket.") from None

    def read(self,session=None):
        result=[]
        total=0
        for key in self.list_keys(session):
            data=bytearray()
            with self._request("GET","/storage/v1/object/public/"+BUCKET+"/"+quote(key,safe=""),
                               stream=True) as response:
                try:
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data)>MAX_PDF_BYTES or total+len(data)>MAX_TOTAL_BYTES:
                            raise ArchiveError("Limiti dell’archivio remoto superati.")
                except requests.RequestException:
                    raise ArchiveError("Download archivio interrotto.") from None
            total+=len(data)
            raw=bytes(data)
            if not raw.startswith(b"%PDF-"):
                raise ArchiveError("Documento remoto non valido.")
            if re.match(r"^[a-f0-9]{64}--",key) and sha256(raw).hexdigest()!=key[:64]:
                raise ArchiveError("SHA-256 non corrispondente al documento remoto.")
            result.append((key,raw))
        return tuple(result)

    def publish(self,session,additions,local=()):
        if not session.valid(self.config):
            raise ArchiveError("Accesso amministratore richiesto.")
        current=self.read(session)
        existing=tuple((display_name(k),v) for k,v in current)
        retained,library,notices=extend_uploads(existing,additions,local)
        # Do not crowd out an existing bundled document or accept an unindexed file.
        accepted={p.digest for p in library.documents.values()}
        if any(sha256(raw).hexdigest() not in accepted for _,raw in local):
            raise ArchiveError("Spazio insufficiente: un PDF già disponibile verrebbe escluso.")
        known={sha256(v).hexdigest() for _,v in current}
        count=0
        for name,data in retained:
            if sha256(data).hexdigest() in known:
                continue
            key=object_name(name,data)
            with self._request("POST","/storage/v1/object/"+BUCKET+"/"+quote(key,safe=""),
                               session=session,data=data,headers={"Content-Type":"application/pdf",
                               "x-upsert":"false","Cache-Control":"max-age=60"}):
                count+=1
        return count,notices+library.errors

    def remove(self,session,key):
        if not session.valid(self.config):
            raise ArchiveError("Accesso amministratore richiesto.")
        if key not in self.list_keys(session):
            raise ArchiveError("Documento non più presente.")
        with self._request("DELETE","/storage/v1/object/"+BUCKET,session=session,json={"prefixes":[key]}):
            pass
