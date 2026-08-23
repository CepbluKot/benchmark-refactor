import re


_RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _checked_release_id(release_id: str) -> str:
    if not _RELEASE_ID.fullmatch(release_id):
        raise ValueError("invalid release ID")
    return release_id


def core_study_route(core_release_id: str) -> str:
    return f"core.m0.study.{_checked_release_id(core_release_id)}.v1"


def core_finalize_route(core_release_id: str) -> str:
    return f"core.m0.finalize.{_checked_release_id(core_release_id)}.v1"


def toy_measure_route(plugin_release_id: str) -> str:
    return f"plugin.toy.{_checked_release_id(plugin_release_id)}.measure.v1"
