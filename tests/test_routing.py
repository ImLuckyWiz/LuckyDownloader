from pathlib import Path
from core.routing import (
    provider_folder_name,
    resolve_provider_base_dir,
)


def test_provider_folder_name():
    assert provider_folder_name("youtube") == "YouTube"
    assert provider_folder_name("YouTube") == "YouTube"
    assert provider_folder_name("twitch") == "Twitch"
    assert provider_folder_name("tiktok") == "TikTok"
    assert provider_folder_name("instagram") == "Instagram"
    assert provider_folder_name("twitter") == "Twitter"
    assert provider_folder_name("x") == "X"
    assert provider_folder_name("reddit") == "Reddit"
    assert provider_folder_name("vimeo") == "Vimeo"
    assert provider_folder_name("generic") == "Downloads"
    assert provider_folder_name("") == "Downloads"


def test_resolve_provider_base_dir_defaults():
    # When provider_subfolders is False and no custom overrides
    res = resolve_provider_base_dir("D:/Downloads", "youtube", provider_subfolders=False)
    assert res == Path("D:/Downloads")

    res_twitch = resolve_provider_base_dir("D:/Downloads", "twitch", provider_subfolders=False)
    assert res_twitch == Path("D:/Downloads")


def test_resolve_provider_base_dir_subfolders():
    # When provider_subfolders is True
    res_yt = resolve_provider_base_dir("D:/Downloads", "youtube", provider_subfolders=True)
    assert res_yt == Path("D:/Downloads/YouTube")

    res_twitch = resolve_provider_base_dir("D:/Downloads", "twitch", provider_subfolders=True)
    assert res_twitch == Path("D:/Downloads/Twitch")

    res_tiktok = resolve_provider_base_dir("D:/Downloads", "tiktok", provider_subfolders=True)
    assert res_tiktok == Path("D:/Downloads/TikTok")

    # Generic provider does not create a subfolder
    res_gen = resolve_provider_base_dir("D:/Downloads", "generic", provider_subfolders=True)
    assert res_gen == Path("D:/Downloads")


def test_resolve_provider_base_dir_custom_override():
    custom_dirs = {
        "youtube": "E:/Videos/YouTube_Archive",
        "twitch": "F:/TwitchVODs",
    }

    # YouTube uses custom override even if provider_subfolders is True
    res_yt = resolve_provider_base_dir("D:/Downloads", "youtube", provider_subfolders=True, provider_out_dirs=custom_dirs)
    assert res_yt == Path("E:/Videos/YouTube_Archive")

    # Twitch uses custom override
    res_tw = resolve_provider_base_dir("D:/Downloads", "twitch", provider_subfolders=False, provider_out_dirs=custom_dirs)
    assert res_tw == Path("F:/TwitchVODs")

    # TikTok has no override in custom_dirs -> falls back to D:/Downloads/TikTok when subfolders=True
    res_tk = resolve_provider_base_dir("D:/Downloads", "tiktok", provider_subfolders=True, provider_out_dirs=custom_dirs)
    assert res_tk == Path("D:/Downloads/TikTok")

    # TikTok falls back to D:/Downloads when subfolders=False
    res_tk_off = resolve_provider_base_dir("D:/Downloads", "tiktok", provider_subfolders=False, provider_out_dirs=custom_dirs)
    assert res_tk_off == Path("D:/Downloads")
