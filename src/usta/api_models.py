"""HTTP API'nin istek gövdeleri ve kullanıcıya dönük model hata cümleleri."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from usta import attachments, filetree, skills

ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,39}$"


MAX_FILE = 1_000_000

WorkspaceId = Annotated[str, PathParam(pattern=ID_PATTERN)]
ServerName = Annotated[str, PathParam(pattern=r"^[a-z0-9][a-z0-9_-]{0,29}$")]


class WorkspaceIn(BaseModel):
    name: str = Field(pattern=ID_PATTERN)


class AttachIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=attachments.MAX_FILE * 2)


class TaskIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    mode: Literal["manual", "auto", "plan"] = "manual"
    guard: bool | None = None  # None: sunucu varsayılanı
    files: list[AttachIn] = Field(default_factory=list, max_length=attachments.MAX_FILES)
    apply_plan: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{12}$"
    )  # bitmiş plan görevinin kimliği
    phased: bool = (
        False  # planı PLAN.md aşamalarına bölüp her aşamayı taze bağlamla ayrı görev koştur
    )
    design_skill: bool = (
        False  # "Usta'ya yeni bir iş öğret": propose_skill aracı bu görevde verilir
    )


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class ModelIn(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    api: str | None = Field(default=None, max_length=30)


class ApiIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    endpoint: str = Field(min_length=1, max_length=500)
    key: str | None = Field(default=None, max_length=8192)


class KeyIn(BaseModel):
    key: str | None = Field(default=None, max_length=8192)


class ImportFile(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    b64: str = Field(max_length=filetree.MAX_IMPORT_FILE * 2)


class ImportIn(BaseModel):
    files: list[ImportFile] = Field(max_length=filetree.MAX_IMPORT_FILES)
    overwrite: bool = False


class FsOp(BaseModel):
    op: Literal["create_file", "create_dir", "rename", "delete"]
    path: str = Field(min_length=1, max_length=500)
    to: str | None = Field(default=None, max_length=500)


class SkillIn(BaseModel):
    content: str = Field(min_length=1, max_length=skills.MAX_SIZE * 2)


class HarnessToggleIn(BaseModel):
    enabled: bool


class SkillProposalIn(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    instructions: str = Field(max_length=20_000)


class ProfileIn(BaseModel):
    ad: str = Field(default="", max_length=200)
    uslup: str = "sade"
    hakkimda: str = Field(default="", max_length=2000)
    bilgiler: list[str] = Field(default_factory=list, max_length=100)


class OrtakHostIn(BaseModel):
    acik: bool
    ad: str | None = Field(default=None, max_length=40)


class OrtakConnectIn(BaseModel):
    adres: str = Field(min_length=1, max_length=200)
    kod: str = Field(min_length=1, max_length=20)
    ad: str = Field(default="", max_length=40)


class OrtakNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class SettingsIn(BaseModel):
    """Portaldan yalnız görünüm ve mod değiştirilebilir; uç nokta/model/sırlar buradan değişmez."""

    theme: Literal["beyaz", "gri", "siyah"] | None = None
    mode: Literal["manual", "auto", "plan"] | None = None
    guard: bool | None = None
    zoom: Literal["auto", "0.9", "1", "1.1", "1.25", "1.5", "1.75"] | None = None
    accent: Literal["cini", "turkuaz", "nar", "zeytin", "mor"] | None = None
    think: Literal["auto", "off", "low", "medium", "high"] | None = None
    view: Literal["simple", "advanced"] | None = None
    context_window: int | None = Field(default=None, ge=0, le=2_000_000)  # 0: otomatik (sınır yok)


def friendly_model_error(text: str) -> str:
    """Model hatasını kodsuz bir kullanıcıya anlaşılır cümleye çevirir (web/logic.js ile aynı cümleler)."""
    if "HTTP 401" in text or "HTTP 403" in text:
        return (
            "Anahtar kabul edilmedi. Doğru kopyaladığından ve hesabında bakiye olduğundan emin ol."
        )
    if "HTTP 402" in text:
        return "Hesabında bakiye yok görünüyor. Servisin sayfasından bakiye yükle ya da ücretsiz bir model seç."
    if "HTTP 404" in text:
        return "Bu model bulunamadı. Kurulum ekranından başka bir model seç."
    if "HTTP 429" in text:
        return (
            "Bugünkü ücretsiz hakkın doldu ya da çok hızlı istek gönderildi. "
            "Biraz bekle, yarın tekrar dene ya da başka bir servis ekle."
        )
    if re.search(r"HTTP 4\d\d", text):
        return (
            "Model bu isteği kabul etmedi. Konuşma çok uzamış olabilir: "
            "yeni bir görev başlat ya da başka bir model seç."
        )
    if re.search(r"HTTP 5\d\d", text):
        return (
            "Servis şu an cevap veremiyor. Sorun sende değil: "
            "birkaç dakika sonra tekrar dene ya da başka bir model seç."
        )
    if "ConnectError" in text or "ConnectTimeout" in text:
        return (
            "Servise ulaşılamıyor. İnternet bağlantını "
            "(ya da bilgisayarındaki modelin açık olduğunu) kontrol et."
        )
    if "Timeout" in text:
        return "Model zamanında cevap vermedi. Büyük modeller yavaş olabilir; tekrar dene."
    if re.search(r"ReadError|WriteError|RemoteProtocolError|NetworkError", text):
        return "Bağlantı yarıda koptu. İnternet bağlantını kontrol et ve tekrar dene."
    if "protokolü bozdu" in text or "araç çağrısı çözümlenemedi" in text:
        return (
            "Model ne yapacağını düzgün anlatamadı. Küçük modellerde olur: "
            "tekrar dene ya da daha güçlü bir model seç."
        )
    if re.search(r"JSONDecodeError|KeyError|IndexError|ValueError", text):
        return (
            "Servis anlaşılmayan bir cevap gönderdi. Tekrar dene; yine olursa başka bir model seç."
        )
    if "beklenmeyen hata" in text:
        return "Usta'da beklenmeyen bir şey oldu. Tekrar dene; yine olursa Ayarlar'daki \"Yardım iste\" düğmesine bas."
    return "Model cevap vermedi. Ayrıntı: " + text


class LocalScanIn(BaseModel):
    port: int | None = Field(default=None, ge=1, le=65535)


class LocalHostIn(BaseModel):
    host: str = Field(min_length=1, max_length=200)


class SystemInstallIn(BaseModel):
    what: str = Field(min_length=1, max_length=20)


class LocalPullIn(BaseModel):
    port: int = Field(default=11434, ge=1, le=65535)
    model: str = Field(min_length=1, max_length=120)


class LocalCtxIn(BaseModel):
    port: int = Field(ge=1, le=65535)
    model: str = Field(min_length=1, max_length=120)
    num_ctx: int = Field(ge=256, le=2_000_000)


class CodeIn(BaseModel):
    code: str = Field(max_length=200)


class SecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=8192)


class FoundAddIn(BaseModel):
    """Başka bir uygulamada bulunan MCP sunucusunu ekleme isteği (komutu Usta kendisi kurar)."""

    app: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    copy_secrets: bool = False
    workspace: Literal["none", "ro", "rw"] = "none"


class RegistrySearchIn(BaseModel):
    sorgu: str = Field(min_length=2, max_length=300)


class RegistryAddIn(BaseModel):
    name: str = Field(min_length=3, max_length=200, pattern=r"^[\w.-]+/[\w.-]+$")
    version: str = Field(min_length=1, max_length=64, pattern=r"^[\w.+!-]+$")


class EnabledIn(BaseModel):
    enabled: bool


class FileIn(BaseModel):
    content: str = Field(max_length=MAX_FILE)


class ApprovalIn(BaseModel):
    decision: Literal["allow", "deny"]
