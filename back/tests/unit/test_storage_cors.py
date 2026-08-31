"""Shared-bucket CORS union — laptop seed must not wipe the production origin."""

from __future__ import annotations

from app.storage.cors import merge_cors_origins, origins_from_cors_config


def test_merge_with_no_existing_rules_keeps_configured_origins() -> None:
    assert merge_cors_origins([], ["http://124.223.45.115"]) == ["http://124.223.45.115"]


def test_merge_with_empty_configured_keeps_existing() -> None:
    existing = ["http://localhost:3000"]
    assert merge_cors_origins(existing, []) == existing


def test_merge_unions_localhost_with_the_production_origin() -> None:
    existing = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ]
    assert merge_cors_origins(existing, ["http://124.223.45.115"]) == [
        *existing,
        "http://124.223.45.115",
    ]


def test_merge_drops_blanks_and_duplicates_without_reordering() -> None:
    assert merge_cors_origins(
        ["http://localhost:3000", "", "http://localhost:3000"],
        ["http://124.223.45.115", "http://localhost:3000", "  "],
    ) == ["http://localhost:3000", "http://124.223.45.115"]


def test_origins_from_cos_and_minio_shapes() -> None:
    assert origins_from_cors_config(
        {
            "CORSRule": [
                {
                    "AllowedOrigin": [
                        "http://localhost:3000",
                        "http://124.223.45.115",
                    ]
                }
            ]
        }
    ) == ["http://localhost:3000", "http://124.223.45.115"]
    assert origins_from_cors_config(
        {"CORSRules": [{"AllowedOrigins": ["http://localhost:3000"]}]}
    ) == ["http://localhost:3000"]
    assert origins_from_cors_config({}) == []
    assert origins_from_cors_config(None) == []
