"""Validated request contracts. Validation details never include request values."""

import base64
import ipaddress
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def reject_secret_mask(value):
    if value and (
        value.strip() in ("********", "••••••••", "***") or set(value) == {"*"}
    ):
        raise ValueError("masked values cannot replace secrets")
    return value


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def public_url(value: str, allow_http=False):
    try:
        u = urlsplit(value)
        if (
            u.scheme not in (("https", "http") if allow_http else ("https",))
            or not u.hostname
            or u.username
            or u.password
            or u.fragment
        ):
            raise ValueError()
        if u.hostname.lower() in (
            "localhost",
            "worker",
            "app",
            "host.docker.internal",
        ) or u.hostname.lower().endswith((".localhost", ".local", ".internal")):
            raise ValueError()
        try:
            ip = ipaddress.ip_address(u.hostname)
        except ValueError:
            ip = None
        if ip and not ip.is_global:
            raise ValueError()
        if u.port == 0:
            raise ValueError()
    except Exception:
        raise ValueError("invalid public mailbox URL") from None
    return value


class Proxy(Model):
    server: str = Field(max_length=2048)
    username: str | None = Field(default=None, max_length=256)
    password: str | None = Field(default=None, max_length=1024)

    @field_validator("password")
    @classmethod
    def secret(cls, v):
        return reject_secret_mask(v)

    @field_validator("server")
    @classmethod
    def check_server(cls, v):
        try:
            u = urlsplit(v)
            if (
                u.scheme not in ("http", "https", "socks5")
                or not u.hostname
                or not u.port
                or u.username
                or u.password
                or u.path not in ("", "/")
                or u.query
                or u.fragment
            ):
                raise ValueError()
        except Exception:
            raise ValueError("invalid proxy server") from None
        return v


class AccountPatch(Model):
    username: str | None = Field(default=None, min_length=1, max_length=320)
    password: str | None = Field(default=None, min_length=1, max_length=4096)
    totp: str | None = Field(default=None, max_length=256)
    mailbox_url: str | None = Field(default=None, max_length=4096)
    allow_http_mailbox: bool | None = None
    route_type: Literal["unset", "direct", "proxy"] | None = None
    proxy: Proxy | None = None
    target_ids: list[int] | None = Field(default=None, max_length=100)

    @field_validator("password", "totp", "mailbox_url")
    @classmethod
    def reject_mask(cls, v):
        if v and (v.strip() in ("********", "••••••••", "***") or set(v) == {"*"}):
            raise ValueError("masked values cannot replace secrets")
        return v

    @field_validator("totp")
    @classmethod
    def validate_totp(cls, v):
        if v:
            try:
                raw = v.replace(" ", "").upper()
                decoded = base64.b32decode(raw + "=" * ((-len(raw)) % 8))
                if len(decoded) < 10:
                    raise ValueError()
            except Exception:
                raise ValueError("invalid TOTP secret") from None
        return v

    @field_validator("username")
    @classmethod
    def clean_username(cls, v):
        if v is not None and (not v.strip() or any(ord(c) < 32 for c in v)):
            raise ValueError("invalid account identity")
        return v.strip() if v else v


class AccountCreate(AccountPatch):
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=4096)


class TargetConfig(Model):
    base_url: str = Field(max_length=2048)
    allow_http: bool = False
    compatibility: Literal["cpa-auth-files-v1", "cpa-native-oauth-v1", "bridge-v1"] | None = None

    @model_validator(mode="after")
    def url(self):
        try:
            u = urlsplit(self.base_url)
            if (
                u.scheme not in (("http", "https") if self.allow_http else ("https",))
                or not u.hostname
                or u.username
                or u.password
                or u.query
                or u.fragment
            ):
                raise ValueError()
            _ = u.port
        except Exception:
            raise ValueError("invalid target URL") from None
        return self


class CPAConfig(TargetConfig):
    management_key: str = Field(min_length=1, max_length=4096)

    @field_validator("management_key")
    @classmethod
    def secret(cls, v):
        return reject_secret_mask(v)


class VoiceConfig(TargetConfig):
    admin_username: str = Field(min_length=1, max_length=320)
    admin_password: str = Field(min_length=1, max_length=4096)

    @field_validator("admin_password")
    @classmethod
    def secret(cls, v):
        return reject_secret_mask(v)


class TargetBody(Model):
    kind: Literal["cliproxyapi", "chatgpt-web-voice"]
    name: str = Field(min_length=1, max_length=200)
    config: dict

    @model_validator(mode="after")
    def validate_config(self):
        self.config = (
            (CPAConfig if self.kind == "cliproxyapi" else VoiceConfig)
            .model_validate(self.config)
            .model_dump()
        )
        return self


class LoginBody(Model):
    password: str = Field(min_length=1, max_length=4096)


class PasswordBody(Model):
    current_password: str = Field(min_length=1, max_length=4096)
    new_password: str = Field(min_length=12, max_length=4096)


class ImportBody(Model):
    text: str = Field(min_length=1, max_length=2_000_000)


class TaskBody(Model):
    target_id: int = Field(gt=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class CodeBody(Model):
    code: str = Field(pattern=r"^[A-Za-z0-9 -]{4,32}$")
    submission_id: str = Field(min_length=8, max_length=128)


class SettingsBody(Model):
    maintenance_enabled: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class DiscardBody(Model):
    confirmation: str = Field(min_length=1, max_length=320)
