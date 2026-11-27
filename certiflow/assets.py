"""Asset Library: templates, stamps, signatures.

Phase 1 stores the library as a JSON manifest next to the files. Phase 3 moves
the same records to PostgreSQL + object storage; the access rules stay here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from .model import StampChoice

AssetType = Literal["template", "stamp_certified", "stamp_office", "signature"]


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    type: AssetType
    path: str                                # relative to the manifest
    active: bool = True
    owner_user: Optional[str] = None         # certified stamp / signature belong to a translator
    owner_company: Optional[str] = None      # office stamp belongs to the company
    width_mm: Optional[float] = None         # physical print width (stamps, signatures)
    language: Optional[str] = None           # templates: bound target language
    pair: Optional[str] = None               # templates: bound pair "en>ar"
    seal_layout: Optional[dict] = None       # templates: {"stamp": {cx_mm, cy_mm}, "signature": {...}} from import
    strip_footer_images: list[str] = Field(default_factory=list)  # templates: sha1 of baked-in seal images
    house_style: Optional[dict] = None       # templates: office house style (certiflow.house.HouseStyle)
    margins_mm: Optional[dict] = None        # templates: page margin overrides, e.g. {"bottom": 60.9}
    source_layout: Optional[dict] = None     # templates: {"mode": "band", "area_mm": {...}, "seal": {...}} for source pages


class User(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    role: Literal["admin", "certified_translator", "reviewer"]
    company: Optional[str] = None


class Library(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str
    users: list[User] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)


class AssetError(PermissionError):
    pass


class AssetLibrary:
    def __init__(self, manifest: Path):
        self.manifest = Path(manifest)
        self.root = self.manifest.parent
        self.lib = Library.model_validate_json(self.manifest.read_text("utf-8"))

    def save(self) -> None:
        self.manifest.write_text(self.lib.model_dump_json(indent=2) + "\n", "utf-8")

    def path(self, a: Asset) -> Path:
        return (self.root / a.path).resolve()

    def user(self, user_id: str) -> User:
        for u in self.lib.users:
            if u.id == user_id:
                return u
        raise AssetError(f"unknown user '{user_id}'")

    def add(self, asset: Asset) -> Asset:
        if any(a.id == asset.id for a in self.lib.assets):
            raise ValueError(f"asset id '{asset.id}' exists")
        p = self.root / asset.path
        if asset.type != "template":
            validate_transparent_png(p)
        self.lib.assets.append(asset)
        return asset

    # ------------------------------------------------------------- selection

    def can_use(self, user: User, a: Asset) -> bool:
        if user.role == "admin":
            return True
        if a.type in ("stamp_certified", "signature"):
            return a.owner_user == user.id
        if a.type == "stamp_office":
            return user.role == "certified_translator" and a.owner_company in (user.company, self.lib.company)
        return True

    def stamp_for(self, choice: StampChoice, user_id: str) -> tuple[Asset, Asset]:
        """Resolve (stamp, signature) for a job. Raises if the user may not use them."""
        u = self.user(user_id)
        stype = "stamp_certified" if choice == StampChoice.certified else "stamp_office"
        stamps = [a for a in self.lib.assets if a.type == stype and a.active]
        if choice == StampChoice.certified:
            stamps = [a for a in stamps if a.owner_user == user_id] or [a for a in stamps if u.role == "admin"]
        stamps = [a for a in stamps if self.can_use(u, a)]
        if not stamps:
            raise AssetError(f"no active {stype} that user '{user_id}' is authorised to apply")
        sigs = [a for a in self.lib.assets if a.type == "signature" and a.active and a.owner_user == user_id]
        if not sigs:
            raise AssetError(f"no active signature registered for user '{user_id}'")
        return stamps[0], sigs[0]

    def template_for(self, target: str, source: str | None = None, template_id: str | None = None) -> Asset:
        ts = [a for a in self.lib.assets if a.type == "template" and a.active]
        if template_id:
            for a in ts:
                if a.id == template_id:
                    return a
            raise AssetError(f"template '{template_id}' not found")
        for pred in (lambda a: source and a.pair == f"{source}>{target}",
                     lambda a: a.language == target,
                     lambda a: a.pair is None and a.language is None):
            for a in ts:
                if pred(a):
                    return a
        raise AssetError("no active template")


def validate_transparent_png(p: Path) -> None:
    with Image.open(p) as im:
        if im.format != "PNG":
            raise ValueError(f"{p.name}: stamps and signatures must be PNG")
        if im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
            raise ValueError(f"{p.name}: PNG has no transparency (alpha channel required)")
