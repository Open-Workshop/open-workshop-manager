from __future__ import annotations

import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from open_workshop_manager.limits import LIMITS


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadModel(ApiModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Pagination(ApiModel):
    page: int = Field(ge=0)
    page_size: int = Field(ge=1)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
    has_next: bool
    has_previous: bool


def stringify_source_id(value: object | None) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


T = TypeVar("T")


class ListResponse(ApiModel, Generic[T]):
    items: list[T]
    pagination: Pagination


class GameRead(ReadModel):
    id: int
    name: str
    short_description: str | None = None
    description: str | None = None
    type: str
    source: str
    source_id: str | None = Field(
        default=None,
        max_length=LIMITS.game.source_id_max,
        description="Opaque source-specific identifier for the game.",
    )
    mods_count: int | None = None
    mods_downloads: int | None = None
    created_at: datetime.datetime | None = None
    genres: list["GenreRead"] | None = None
    tags: list["TagRead"] | None = None
    resources: list["ResourceRead"] | None = None

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: object | None) -> str | None:
        return stringify_source_id(value)


class GameCreate(ApiModel):
    name: str = Field(min_length=1, max_length=LIMITS.game.name_max)
    short_description: str | None = Field(default=None, max_length=LIMITS.game.short_desc_max)
    description: str | None = Field(default=None, max_length=LIMITS.game.desc_max)
    type: Literal["game", "app"] = "game"


class GamePatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=LIMITS.game.name_max)
    short_description: str | None = Field(default=None, max_length=LIMITS.game.short_desc_max)
    description: str | None = Field(default=None, max_length=LIMITS.game.desc_max)
    type: Literal["game", "app"] | None = None
    source: str | None = Field(default=None, min_length=1, max_length=LIMITS.game.source_max)
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=LIMITS.game.source_id_max,
        description="Opaque source-specific identifier for the game.",
    )

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: object | None) -> str | None:
        return stringify_source_id(value)


class GameListResponse(ListResponse[GameRead]):
    pass


class GenreRead(ReadModel):
    id: int
    name: str


class GenreCreate(ApiModel):
    name: str = Field(min_length=1, max_length=LIMITS.genre.name_max)


class GenrePatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=LIMITS.genre.name_max)


class GenreListResponse(ListResponse[GenreRead]):
    pass


class TagRead(ReadModel):
    id: int
    name: str


class TagCreate(ApiModel):
    name: str = Field(min_length=1, max_length=LIMITS.tag.name_max)


class TagPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=LIMITS.tag.name_max)


class TagListResponse(ListResponse[TagRead]):
    pass


class ResourceRead(ReadModel):
    id: int
    owner_type: str
    owner_id: int
    type: str
    sort_order: int
    url: str
    size: int | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class ResourceCreate(ApiModel):
    owner_type: Literal["mods", "games", "modpacks"]
    owner_id: int = Field(ge=1)
    type: str = Field(min_length=LIMITS.resource.type_min, max_length=LIMITS.resource.type_max)
    sort_order: int = Field(
        default=0,
        ge=LIMITS.resource.sort_order_min,
        le=LIMITS.resource.sort_order_max,
        description="Manual ordering key for resource lists.",
    )
    url: str = Field(min_length=LIMITS.resource.url_min, max_length=LIMITS.resource.url_max)


class ResourcePatch(ApiModel):
    type: str | None = Field(
        default=None,
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
    )
    url: str | None = Field(
        default=None,
        min_length=LIMITS.resource.url_min,
        max_length=LIMITS.resource.url_max,
    )
    sort_order: int | None = Field(
        default=None,
        ge=LIMITS.resource.sort_order_min,
        le=LIMITS.resource.sort_order_max,
        description="Manual ordering key for resource lists.",
    )


class ResourceListResponse(ListResponse[ResourceRead | str]):
    pass


class ModRead(ReadModel):
    id: int
    name: str
    short_description: str | None = None
    description: str | None = None
    source: str
    source_id: str | None = Field(
        default=None,
        max_length=LIMITS.mod.source_id_max,
        description="Opaque source-specific identifier for the mod.",
    )
    git_url: str | None = None
    game_id: int | None = None
    public: int
    adult: bool
    condition: str
    rating: int = 0
    current_vote: int | None = None
    downloads: int | None = None
    size: int | None = None
    size_unpacked: int | None = None
    created_at: datetime.datetime | None = None
    file_updated_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    file: dict[str, Any] | str | None = None
    game: GameRead | None = None
    tags: list[TagRead] | None = None
    dependencies: ModDependencyCollectionRead | None = None
    conflicts: IntCollectionRead | None = None
    authors: dict[int, dict[str, bool]] | None = None
    resources: list[ResourceRead] | None = None

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: object | None) -> str | None:
        return stringify_source_id(value)


class ModpackRead(ReadModel):
    id: int
    name: str
    short_description: str | None = None
    description: str | None = None
    source: str
    source_id: str | None = Field(
        default=None,
        max_length=LIMITS.mod.source_id_max,
        description="Opaque source-specific identifier for the modpack.",
    )
    game_id: int | None = None
    public: int
    adult: bool
    rating: int = 0
    current_vote: int | None = None
    downloads: int | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    authors: dict[int, dict[str, bool]] | None = None
    tags: list[TagRead] | None = None
    resources: list[ResourceRead] | None = None

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: object | None) -> str | None:
        return stringify_source_id(value)


class ModpackModRead(ReadModel):
    mod_id: int
    sort_order: int = 0
    auto_added: bool = False


class ModpackModsRead(ReadModel):
    modpack_id: int
    items: list[ModpackModRead]


class ModpackModUpsert(ApiModel):
    mod_id: int = Field(ge=1)
    auto_added: bool = False


class ModpackModsUpsert(ApiModel):
    items: list[ModpackModUpsert] = Field(default_factory=list)


class ModCreate(ApiModel):
    name: str = Field(min_length=1, max_length=LIMITS.mod.name_max)
    short_description: str | None = Field(default=None, max_length=LIMITS.mod.short_desc_max)
    description: str | None = Field(default=None, max_length=LIMITS.mod.desc_max)
    source: str = Field(default="local", min_length=1, max_length=LIMITS.mod.source_max)
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=LIMITS.mod.source_id_max,
        description="Opaque source-specific identifier for the mod.",
    )
    git_url: str | None = Field(default=None, min_length=1, max_length=LIMITS.mod.git_url_max)
    game_id: int = Field(ge=1)
    public: int = Field(default=0, ge=0, le=2)
    adult: bool = False
    without_author: bool = False

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: object | None) -> str | None:
        return stringify_source_id(value)


class ModPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=LIMITS.mod.name_max)
    short_description: str | None = Field(default=None, max_length=LIMITS.mod.short_desc_max)
    description: str | None = Field(default=None, max_length=LIMITS.mod.desc_max)
    source: str | None = Field(default=None, min_length=1, max_length=LIMITS.mod.source_max)
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=LIMITS.mod.source_id_max,
        description="Opaque source-specific identifier for the mod.",
    )
    git_url: str | None = Field(default=None, min_length=1, max_length=LIMITS.mod.git_url_max)
    game_id: int | None = Field(default=None, ge=1)
    public: int | None = Field(default=None, ge=0, le=2)
    adult: bool | None = None

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: object | None) -> str | None:
        return stringify_source_id(value)


class ModpackCreate(ApiModel):
    name: str = Field(min_length=1, max_length=LIMITS.mod.name_max)
    short_description: str | None = Field(default=None, max_length=LIMITS.mod.short_desc_max)
    description: str | None = Field(default=None, max_length=LIMITS.mod.desc_max)
    source: str = Field(default="local", min_length=1, max_length=LIMITS.mod.source_max)
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=LIMITS.mod.source_id_max,
        description="Opaque source-specific identifier for the modpack.",
    )
    game_id: int | None = Field(default=None, ge=1)
    public: int = Field(default=0, ge=0, le=2)
    adult: bool = False
    without_author: bool = False

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: object | None) -> str | None:
        return stringify_source_id(value)


class ModpackPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=LIMITS.mod.name_max)
    short_description: str | None = Field(default=None, max_length=LIMITS.mod.short_desc_max)
    description: str | None = Field(default=None, max_length=LIMITS.mod.desc_max)
    source: str | None = Field(default=None, min_length=1, max_length=LIMITS.mod.source_max)
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=LIMITS.mod.source_id_max,
        description="Opaque source-specific identifier for the modpack.",
    )
    game_id: int | None = Field(default=None, ge=1)
    public: int | None = Field(default=None, ge=0, le=2)
    adult: bool | None = None

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: object | None) -> str | None:
        return stringify_source_id(value)


class ModpackListResponse(ListResponse[ModpackRead]):
    pass


class ModpackRatingRead(ReadModel):
    modpack_id: int
    rating: int


class ModAuthorUpsert(ApiModel):
    owner: bool = False


class ModDependencyRead(ReadModel):
    mod_id: int
    optional: bool = False


class ModDependencyCollectionRead(ReadModel):
    count: int
    items: list[ModDependencyRead]


class ModDependencyUpsert(ApiModel):
    optional: bool = False


class ModListResponse(ListResponse[ModRead]):
    pass


class IntRangeRead(ReadModel):
    min: int | None = None
    max: int | None = None


class ModFeedRead(ReadModel):
    count: int
    size: IntRangeRead
    size_unpacked: IntRangeRead


class IntListResponse(ListResponse[int]):
    pass


class IntCollectionRead(ReadModel):
    count: int
    items: list[int]


class ModBuildNodeRead(ReadModel):
    mod_id: int
    mod_name: str
    selected: bool


class ModBuildEdgeRead(ReadModel):
    source_mod_id: int
    target_mod_id: int


class ModBuildConflictGraphRead(ReadModel):
    nodes: list[ModBuildNodeRead]
    edges: list[ModBuildEdgeRead]


class ModBuildDependencyGraphRead(ReadModel):
    nodes: list[ModBuildNodeRead]
    edges: list[ModBuildEdgeRead]


class ModBuildConflictRead(ReadModel):
    mod_id: int
    mod_name: str
    conflict_mod_id: int
    conflict_mod_name: str


class ModBuildConflictListRead(ReadModel):
    count: int
    items: list[ModBuildConflictRead]


class ModBuildMissingDependencyRead(ReadModel):
    mod_id: int
    mod_name: str
    dependency_mod_id: int
    dependency_mod_name: str


class ModBuildMissingDependencyListRead(ReadModel):
    count: int
    items: list[ModBuildMissingDependencyRead]


ModRead.model_rebuild()


class RatingVoteUpsert(ApiModel):
    value: Literal[-1, 0, 1] = Field(
        description="Vote value. `0` clears the current vote."
    )


class ModRatingRead(ReadModel):
    mod_id: int
    rating: int


class ProfileRatingRead(ReadModel):
    profile_id: int
    reputation: float


class RatingHistoryRead(ReadModel):
    id: int
    target_type: Literal["mod", "modpack", "profile"]
    target_id: int
    target_name: str
    previous_value: int
    value: int
    reputation_delta: float
    mod_delta: int
    created_at: datetime.datetime | None = None


class RatingHistoryListResponse(ListResponse[RatingHistoryRead]):
    pass


class ModDownloadUrlRead(ApiModel):
    mod_id: int
    download_url: str
    filename: str
    expires_at: datetime.datetime | None = None


class UploadRead(ReadModel):
    id: str
    kind: str
    status: str
    transfer_url: str
    ws_url: str
    expires_at: datetime.datetime | None = None
    owner_type: str | None = None
    owner_id: int | None = None
    mode: str | None = None
    resource_id: int | None = None


class UploadStatusRead(ReadModel):
    status: str
    expires_at: datetime.datetime | None = None


class UploadCreate(ApiModel):
    kind: Literal["mod_archive", "resource_image", "profile_avatar"]
    owner_type: Literal["mod", "resource", "profile"]
    owner_id: int | None = Field(default=None, ge=1)
    mode: Literal["create", "replace"]
    format: str | None = Field(default=None, min_length=1, max_length=16)
    compression_level: int | None = Field(default=None, ge=0, le=9)
    resource_owner_type: Literal["mods", "games", "modpacks"] | None = None
    resource_owner_id: int | None = Field(default=None, ge=1)
    resource_type: str | None = Field(
        default=None,
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
    )
    resource_sort_order: int | None = Field(
        default=None,
        ge=LIMITS.resource.sort_order_min,
        le=LIMITS.resource.sort_order_max,
        description="Sort order for `resource_image` uploads.",
    )


class ProfileRightsRead(ReadModel):
    admin: bool
    write_comments: bool
    set_reactions: bool
    create_reactions: bool
    publish_mods: bool
    change_authorship_mods: bool
    change_self_mods: bool
    change_mods: bool
    delete_self_mods: bool
    delete_mods: bool
    publish_modpacks: bool
    change_authorship_modpacks: bool
    change_self_modpacks: bool
    change_modpacks: bool
    delete_self_modpacks: bool
    delete_modpacks: bool
    mute_users: bool
    create_forums: bool
    change_authorship_forums: bool
    change_self_forums: bool
    change_forums: bool
    delete_self_forums: bool
    delete_forums: bool
    change_username: bool
    change_about: bool
    change_avatar: bool
    vote_for_reputation: bool


class ProfilePrivateRead(ReadModel):
    last_username_reset: datetime.datetime | None = None
    last_password_reset: datetime.datetime | None = None
    yandex: bool
    google: bool


class ProfileSearchRead(ReadModel):
    id: int
    username: str
    grade: str


class ProfileSearchListResponse(ListResponse[ProfileSearchRead]):
    pass


class ProfileGeneralRead(ReadModel):
    id: int
    username: str
    about: str
    avatar_url: str
    grade: str
    comments: int
    author_mods: int
    registration_date: datetime.datetime
    reputation: float
    mute: bool
    mute_until: datetime.datetime | None = None


class ProfileRead(ApiModel):
    general: ProfileGeneralRead | None = None
    rights: ProfileRightsRead | None = None
    private: ProfilePrivateRead | None = None


class ProfilePatch(ApiModel):
    username: str | None = Field(
        default=None,
        min_length=LIMITS.profile.username_min,
        max_length=LIMITS.profile.username_max,
    )
    about: str | None = Field(default=None, max_length=LIMITS.profile.about_max)
    grade: str | None = Field(
        default=None,
        min_length=LIMITS.profile.grade_min,
        max_length=LIMITS.profile.grade_max,
    )
    mute_until: datetime.datetime | None = None


class ProfilePasswordPatch(ApiModel):
    new_password: str = Field(
        min_length=LIMITS.profile.password_min,
        max_length=LIMITS.profile.password_max,
    )


class ProfileRightsPatch(ApiModel):
    admin: bool | None = None
    write_comments: bool | None = None
    set_reactions: bool | None = None
    create_reactions: bool | None = None
    publish_mods: bool | None = None
    change_authorship_mods: bool | None = None
    change_self_mods: bool | None = None
    change_mods: bool | None = None
    delete_self_mods: bool | None = None
    delete_mods: bool | None = None
    publish_modpacks: bool | None = None
    change_authorship_modpacks: bool | None = None
    change_self_modpacks: bool | None = None
    change_modpacks: bool | None = None
    delete_self_modpacks: bool | None = None
    delete_modpacks: bool | None = None
    mute_users: bool | None = None
    create_forums: bool | None = None
    change_authorship_forums: bool | None = None
    change_self_forums: bool | None = None
    change_forums: bool | None = None
    delete_self_forums: bool | None = None
    delete_forums: bool | None = None
    change_username: bool | None = None
    change_about: bool | None = None
    change_avatar: bool | None = None
    vote_for_reputation: bool | None = None


class SessionCreate(ApiModel):
    method: Literal["password"] = "password"
    login: str = Field(min_length=1, max_length=LIMITS.session.login_max)
    password: str = Field(
        min_length=LIMITS.session.password_min,
        max_length=LIMITS.session.password_max,
    )


class SessionRead(ApiModel):
    user_id: int
    access_expires_at: datetime.datetime
    refresh_expires_at: datetime.datetime


class SessionRefreshRead(ApiModel):
    access_expires_at: datetime.datetime
    refresh_expires_at: datetime.datetime


class AssociationMapItem(ReadModel):
    id: int
    name: str


class BatchMapResponse(ApiModel):
    items_by_id: dict[str, list[Any]]
