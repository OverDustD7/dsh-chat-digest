"""Resolve writable chat-digest data paths without traversing package junctions."""

import os


def profile_root():
    explicit = os.environ.get("DSH_CHAT_FEED_LOCAL")
    home = os.environ.get("DSH_HOME") or (
        os.path.join(os.environ["USERPROFILE"], ".dsh")
        if os.environ.get("USERPROFILE") else "")
    appdata = os.environ.get("LOCALAPPDATA") or (
        os.path.join(os.environ["USERPROFILE"], "AppData", "Local")
        if os.environ.get("USERPROFILE") else "")
    selected = explicit or (os.path.join(home, "dsh-chat-digest") if home else "") or (
        os.path.join(appdata, "dsh-chat-digest") if appdata else "")
    if not selected or not os.path.isabs(selected):
        raise RuntimeError("私人 profile 需要绝对路径：请设置 DSH_CHAT_FEED_LOCAL 或 DSH_HOME")
    return os.path.realpath(selected)
