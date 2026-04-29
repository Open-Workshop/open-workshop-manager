from __future__ import annotations

import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

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
    source_id: int | None = None
    mods_count: int | None = None
    mods_downloads: int | None = None
    created_at: datetime.datetime | None = None
    genres: list["GenreRead"] | None = None
    tags: list["TagRead"] | None = None
    resources: list["ResourceRead"] | None = None


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
    source_id: int | None = Field(default=None, ge=1)


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
    url: str
    size: int | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class ResourceCreate(ApiModel):
    owner_type: Literal["mods", "games"]
    owner_id: int = Field(ge=1)
    type: str = Field(min_length=LIMITS.resource.type_min, max_length=LIMITS.resource.type_max)
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


class ResourceListResponse(ListResponse[ResourceRead | str]):
    pass


class ModRead(ReadModel):
    id: int
    name: str
    short_description: str | None = None
    description: str | None = None
    source: str
    source_id: int | None = None
    game_id: int | None = None
    public: int
    adult: bool
    condition: str
    downloads: int | None = None
    size: int | None = None
    size_unpacked: int | None = None
    created_at: datetime.datetime | None = None
    file_updated_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    file: dict[str, Any] | str | None = None
    game: GameRead | None = None
    tags: list[TagRead] | None = None
    dependencies: IntCollectionRead | None = None
    authors: dict[int, dict[str, bool]] | None = None
    resources: list[ResourceRead] | None = None


class ModCreate(ApiModel):
    name: str = Field(min_length=1, max_length=LIMITS.mod.name_max)
    short_description: str | None = Field(default=None, max_length=LIMITS.mod.short_desc_max)
    description: str | None = Field(default=None, max_length=LIMITS.mod.desc_max)
    source: str = Field(default="local", min_length=1, max_length=LIMITS.mod.source_max)
    source_id: int | None = Field(default=None, ge=1)
    game_id: int = Field(ge=1)
    public: int = Field(default=0, ge=0, le=2)
    adult: bool = False
    without_author: bool = False


class ModPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=LIMITS.mod.name_max)
    short_description: str | None = Field(default=None, max_length=LIMITS.mod.short_desc_max)
    description: str | None = Field(default=None, max_length=LIMITS.mod.desc_max)
    source: str | None = Field(default=None, min_length=1, max_length=LIMITS.mod.source_max)
    source_id: int | None = Field(default=None, ge=1)
    game_id: int | None = Field(default=None, ge=1)
    public: int | None = Field(default=None, ge=0, le=2)
    adult: bool | None = None


class ModAuthorUpsert(ApiModel):
    owner: bool = False


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


ModRead.model_rebuild()


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
    resource_owner_type: Literal["mods", "games"] | None = None
    resource_owner_id: int | None = Field(default=None, ge=1)
    resource_type: str | None = Field(
        default=None,
        min_length=LIMITS.resource.type_min,
        max_length=LIMITS.resource.type_max,
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
    reputation: int
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
