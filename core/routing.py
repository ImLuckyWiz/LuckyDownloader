"""
Provider folder routing and directory resolution.
"""

from __future__ import annotations

from pathlib import Path

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "youtube": "YouTube",
    "twitch": "Twitch",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "twitter": "Twitter",
    "x": "X",
    "reddit": "Reddit",
    "generic": "Downloads",
}


def provider_folder_name(site_or_provider: str) -> str:
    """Format provider name for directory naming (e.g. 'youtube' -> 'YouTube')."""
    s = (site_or_provider or "generic").strip().lower()
    return PROVIDER_DISPLAY_NAMES.get(s, s.capitalize() or "Downloads")


def resolve_provider_base_dir(
    base_out_dir: str | Path,
    site_or_provider: str | None = None,
    provider_subfolders: bool = False,
    provider_out_dirs: dict[str, str] | None = None,
) -> Path:
    """
    Resolve the base output directory for a specific provider/site:
    1. If `provider_out_dirs` contains a non-empty override for this provider, that directory is used.
    2. Otherwise, `base_out_dir` is used.
    3. If `provider_subfolders` is True (and no custom override for this provider was used),
       the provider subfolder is appended (e.g. `base_out_dir / 'YouTube'`).
    """
    site = (site_or_provider or "").strip().lower()
    if provider_out_dirs and site and site in provider_out_dirs:
        custom_path = str(provider_out_dirs[site]).strip()
        if custom_path:
            return Path(custom_path)

    base = Path(base_out_dir) if base_out_dir else Path(".")
    if provider_subfolders and site and site != "generic":
        return base / provider_folder_name(site)
    return base
