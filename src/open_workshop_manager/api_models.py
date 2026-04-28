from __future__ import annotations

import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


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
    name: str
    short_description: str | None = None
    description: str | None = None
    type: str = "game"


class GamePatch(ApiModel):
    name: str | None = None
    short_description: str | None = None
    description: str | None = None
    type: str | None = None
    source: str | None = None
    source_id: int | None = None


class GameListResponse(ListResponse[GameRead]):
    pass


class GenreRead(ReadModel):
    id: int
    name: str


class GenreCreate(ApiModel):
    name: str


class GenrePatch(ApiModel):
    name: str | None = None


class GenreListResponse(ListResponse[GenreRead]):
    pass


class TagRead(ReadModel):
    id: int
    name: str


class TagCreate(ApiModel):
    name: str


class TagPatch(ApiModel):
    name: str | None = None


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
    owner_type: str
    owner_id: int
    type: str
    url: str


class ResourcePatch(ApiModel):
    type: str | None = None
    url: str | None = None


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
    dependencies: list[int] | None = None
    authors: dict[int, dict[str, bool]] | None = None
    resources: list[ResourceRead] | None = None


class ModCreate(ApiModel):
    name: str
    short_description: str | None = None
    description: str | None = None
    source: str = "local"
    source_id: int | None = None
    game_id: int
    public: int = 0
    adult: bool = False
    without_author: bool = False


class ModPatch(ApiModel):
    name: str | None = None
    short_description: str | None = None
    description: str | None = None
    source: str | None = None
    source_id: int | None = None
    game_id: int | None = None
    public: int | None = None
    adult: bool | None = None


class ModListResponse(ListResponse[ModRead]):
    pass


class IntListResponse(ListResponse[int]):
    pass


class ModDownloadRead(ApiModel):
    id: str
    mod_id: int
    download_url: str
    filename: str
    expires_at: datetime.datetime | None = None


class UploadRead(ApiModel):
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


class UploadCreate(ApiModel):
    kind: str
    owner_type: str
    owner_id: int | None = None
    mode: str
    format: str | None = None
    compression_level: int | None = None
    resource_owner_type: str | None = None
    resource_owner_id: int | None = None
    resource_type: str | None = None


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


class ProfileRead(ApiModel):
    general: ProfileGeneralRead | None = None
    rights: ProfileRightsRead | None = None
    private: ProfilePrivateRead | None = None


class ProfilePatch(ApiModel):
    username: str | None = None
    about: str | None = None
    grade: str | None = None
    mute_until: datetime.datetime | None = None


class ProfilePasswordPatch(ApiModel):
    new_password: str


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
    method: str = "password"
    login: str
    password: str


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
