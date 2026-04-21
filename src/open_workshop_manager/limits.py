"""Centralized length and size limits for API validation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PageLimits:
    default: int = 10
    min: int = 1
    max: int = 50


@dataclass(frozen=True)
class ModLimits:
    name_min: int = 1
    name_max: int = 128
    name_edit_max: int = 60
    short_desc_max: int = 256
    desc_max: int = 10000
    source_max: int = 64
    file_max_bytes: int = 838_860_800
    filters_max: int = 90
    public_ids_min: int = 1
    public_ids_max: int = 50


@dataclass(frozen=True)
class ResourceLimits:
    owner_type_max: int = 64
    type_min: int = 2
    type_max: int = 64
    url_min_create: int = 0
    url_min: int = 7
    url_max: int = 256
    filters_max: int = 120


@dataclass(frozen=True)
class GameLimits:
    name_max: int = 128
    short_desc_max: int = 256
    desc_max: int = 10000
    type_max: int = 32
    source_max: int = 64
    filters_max: int = 80


@dataclass(frozen=True)
class TagLimits:
    name_max: int = 128


@dataclass(frozen=True)
class GenreLimits:
    name_max: int = 128


@dataclass(frozen=True)
class AssociationLimits:
    filters_max: int = 80


@dataclass(frozen=True)
class ProfileLimits:
    username_min_form: int = 3
    username_min: int = 2
    username_max: int = 128
    about_max: int = 512
    grade_min_form: int = 3
    grade_min: int = 2
    grade_max: int = 128
    password_min: int = 6
    password_max: int = 100
    avatar_max_bytes: int = 2_097_152


@dataclass(frozen=True)
class SessionLimits:
    login_max: int = 128
    password_min: int = 6
    password_max: int = 100


@dataclass(frozen=True)
class Limits:
    page: PageLimits = field(default_factory=PageLimits)
    mod: ModLimits = field(default_factory=ModLimits)
    resource: ResourceLimits = field(default_factory=ResourceLimits)
    game: GameLimits = field(default_factory=GameLimits)
    tag: TagLimits = field(default_factory=TagLimits)
    genre: GenreLimits = field(default_factory=GenreLimits)
    association: AssociationLimits = field(default_factory=AssociationLimits)
    profile: ProfileLimits = field(default_factory=ProfileLimits)
    session: SessionLimits = field(default_factory=SessionLimits)


LIMITS = Limits()
