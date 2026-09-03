"""Minimized egress (ADR-004 SS2(c)/SS3): fail-closed minimization for data crossing the
provider boundary -- path aliasing, literal/value elimination, residual validation.
Ported from Seed B's ``quality_gate/egress.py`` (payload format ``MINIMIZED_PATCH_V2``);
selected by ``config.egress == "minimized"``.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath

from py_attest.review.egress import EgressResult
from py_attest.review.redaction import contains_sensitive_text, redact

_PATCH_CONTENT_PREFIXES = ("+", "-", " ")
_PATCH_METADATA_PREFIXES = (
    "diff --git ",
    "index ",
    "--- ",
    "+++ ",
    "@@ ",
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "similarity index ",
    "dissimilarity index ",
    "rename from ",
    "rename to ",
    "Binary files ",
    "GIT binary patch",
    "literal ",
    "delta ",
    "\\ No newline at end of file",
)
_PLAIN_TEXT_SUFFIXES = {".csv", ".env", ".log", ".md", ".rst", ".tsv", ".txt"}
_SCALAR_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}
_SAFE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}")
_NUMBER = re.compile(r"(?<![\w])\d(?:[\d._:/-]*\d)?(?![\w])")
_DATE = re.compile(r"(?<![A-Za-z0-9-])(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}(?![A-Za-z0-9-])")
_OPAQUE = re.compile(
    r"\b(?=[A-Za-z0-9_+/=.-]{16,}\b)(?=[A-Za-z0-9_+/=.-]*[A-Za-z])"
    r"(?=[A-Za-z0-9_+/=.-]*\d)[A-Za-z0-9_+/=.-]+\b"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PRIVATE_BEGIN = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.IGNORECASE
)
_PRIVATE_END = re.compile(r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.IGNORECASE)


class EgressError(RuntimeError):
    """Provider input could not be minimized and validated safely."""


@dataclass(frozen=True)
class MinimizedPayload:
    patch: str
    title: str
    description: str
    counts: dict[str, int]
    path_aliases: dict[str, str]


def _add_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def _minimize_quoted(value: str, counts: dict[str, int], removed: list[str]) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        quote = value[index]
        if quote not in {'"', "'", "`"}:
            output.append(quote)
            index += 1
            continue
        cursor = index + 1
        escaped = False
        while cursor < len(value):
            character = value[cursor]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                break
            cursor += 1
        closed = cursor < len(value)
        content = value[index + 1 : cursor]
        following = value[cursor + 1 :] if closed else ""
        is_key = bool(
            closed and _SAFE_KEY.fullmatch(content) and following.lstrip().startswith(":")
        )
        if is_key or (content.startswith("[") and content.endswith("]")):
            replacement = content
        else:
            replacement = "[MINIMIZED_TEXT]"
            if content:
                removed.append(content)
                counts["literal"] += 1
        output.extend((quote, replacement))
        if closed:
            output.append(quote)
            index = cursor + 1
        else:
            index = len(value)
    return "".join(output)


def _minimize_comments(value: str, suffix: str, counts: dict[str, int], removed: list[str]) -> str:
    markers = ("#",) if suffix in {".py", ".rb", ".sh"} else ("#", "//")
    positions = [position for marker in markers if (position := value.find(marker)) >= 0]
    if not positions:
        return value
    position = min(positions)
    removed.append(value[position:])
    counts["comment"] += 1
    marker = "//" if value.startswith("//", position) else "#"
    return value[:position] + marker + " [MINIMIZED_COMMENT]"


def _minimize_source_line(
    body: str, suffix: str, counts: dict[str, int], removed: list[str]
) -> str:
    if not body:
        return body
    if suffix in _PLAIN_TEXT_SUFFIXES:
        removed.append(body)
        counts["scalar"] += 1
        indentation = body[: len(body) - len(body.lstrip())]
        return indentation + "[MINIMIZED_TEXT]"
    if suffix in _SCALAR_SUFFIXES:
        removed.append(body)
        counts["scalar"] += 1
        indentation = body[: len(body) - len(body.lstrip())]
        return indentation + "[MINIMIZED_VALUE]"

    redacted = redact(body)
    _add_counts(counts, redacted.counts)
    minimized = _minimize_quoted(redacted.text, counts, removed)
    minimized = _minimize_comments(minimized, suffix, counts, removed)

    def replace_number(match: re.Match[str]) -> str:
        if re.fullmatch(r"\d{1,3}", match.group(0)):
            return match.group(0)
        removed.append(match.group(0))
        counts["number"] += 1
        return "[NUMBER]"

    minimized = _NUMBER.sub(replace_number, minimized)

    def replace_opaque(match: re.Match[str]) -> str:
        removed.append(match.group(0))
        counts["opaque"] += 1
        return "[MINIMIZED_VALUE]"

    return _OPAQUE.sub(replace_opaque, minimized)


def _diff_paths(line: str) -> tuple[str, str] | None:
    if not line.startswith("diff --git "):
        return None
    try:
        parts = shlex.split(line[len("diff --git ") :])
    except ValueError as exc:
        raise EgressError("provider input minimization failed") from exc
    if len(parts) != 2:
        raise EgressError("provider input minimization failed")
    old_path = parts[0][2:] if parts[0].startswith("a/") else parts[0]
    new_path = parts[1][2:] if parts[1].startswith("b/") else parts[1]
    return old_path, new_path


def _safe_suffix(path: str) -> str:
    suffix = PurePosixPath(path).suffix.casefold()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""


def _metadata_path(value: str) -> str:
    if value.startswith(('"', "'")):
        try:
            parts = shlex.split(value)
        except ValueError as exc:
            raise EgressError("provider input minimization failed") from exc
        if len(parts) != 1:
            raise EgressError("provider input minimization failed")
        return parts[0]
    return value


def minimize_patch(raw_patch: str) -> tuple[str, dict[str, int], tuple[str, ...], dict[str, str]]:
    counts = {
        "secret": 0,
        "pii": 0,
        "private_key": 0,
        "literal": 0,
        "number": 0,
        "comment": 0,
        "scalar": 0,
        "opaque": 0,
        "metadata": 0,
    }
    removed: list[str] = []
    output = ["MINIMIZED_PATCH_V2"]
    suffix = ""
    private_block = False
    real_to_alias: dict[str, str] = {}

    def alias(real_path: str) -> str:
        if real_path not in real_to_alias:
            real_to_alias[real_path] = f"file_{len(real_to_alias) + 1:04d}{_safe_suffix(real_path)}"
        return real_to_alias[real_path]

    for line in raw_patch.splitlines():
        if paths := _diff_paths(line):
            old_path, new_path = paths
            old_alias, new_alias = alias(old_path), alias(new_path)
            output.append(f"diff --git a/{old_alias} b/{new_alias}")
            suffix = PurePosixPath(new_path).suffix.casefold()
            private_block = False
            continue
        if line.startswith(("--- ", "+++ ")):
            marker, value = line[:4], _metadata_path(line[4:])
            if value == "/dev/null":
                output.append(marker + value)
            else:
                prefix = value[:2] if value.startswith(("a/", "b/")) else ""
                real_path = value[2:] if prefix else value
                output.append(marker + prefix + alias(real_path))
            continue
        if line.startswith(("rename from ", "rename to ")):
            marker = "rename from " if line.startswith("rename from ") else "rename to "
            real_path = _metadata_path(line[len(marker) :])
            output.append(marker + alias(real_path))
            continue
        if line.startswith("Binary files "):
            output.append("Binary files [MINIMIZED_PATHS] differ")
            counts["metadata"] += 1
            continue
        if line.startswith(_PATCH_METADATA_PREFIXES):
            output.append(line)
            continue
        if not line.startswith(_PATCH_CONTENT_PREFIXES):
            raise EgressError("provider input minimization failed")
        prefix, body = line[0], line[1:]
        if _PRIVATE_BEGIN.search(body):
            private_block = True
            counts["private_key"] += 1
        if private_block:
            removed.append(body)
            minimized = "[REDACTED_SECRET]"
            if _PRIVATE_END.search(body):
                private_block = False
        else:
            minimized = _minimize_source_line(body, suffix, counts, removed)
        output.append(prefix + minimized)
    path_aliases = {value: key for key, value in real_to_alias.items()}
    return "\n".join(output) + "\n", counts, tuple(removed), path_aliases


def _minimize_metadata(value: str, counts: dict[str, int], removed: list[str]) -> str:
    lines = value.splitlines() or [""]
    minimized: list[str] = []
    for line in lines:
        if line:
            removed.append(line)
            counts["metadata"] += 1
            minimized.append("[MINIMIZED_TEXT]")
        else:
            minimized.append("")
    return "\n".join(minimized)


def _sensitive_removed_value(value: str) -> bool:
    return bool(
        len(value) >= 4
        and (
            any(character.isspace() for character in value)
            or "@" in value
            or _DATE.search(value)
            or (len(value) >= 12 and any(character.isdigit() for character in value))
        )
    )


def validate_minimized_payload(
    raw_patch: str,
    raw_title: str,
    raw_description: str,
    payload: MinimizedPayload,
    removed: tuple[str, ...],
) -> None:
    combined = "\n".join((payload.patch, payload.title, payload.description))
    if (
        payload.patch == raw_patch
        or payload.title == raw_title
        or payload.description == raw_description
        or not payload.patch.startswith("MINIMIZED_PATCH_V2\n")
        or "\ufffd" in combined
        or _CONTROL.search(combined)
        or _DATE.search(combined)
        or _PRIVATE_BEGIN.search(combined)
        or _PRIVATE_END.search(combined)
        or contains_sensitive_text(combined)
    ):
        raise EgressError("provider input residual validation failed")
    if any(real_path in combined for real_path in payload.path_aliases.values()):
        raise EgressError("provider input residual validation failed")
    if any(value in combined for value in removed if _sensitive_removed_value(value)):
        raise EgressError("provider input residual validation failed")


def prepare_provider_payload(
    raw_patch: str, title: str | None, description: str | None
) -> MinimizedPayload:
    raw_title = title or "(not provided)"
    raw_description = description or "(not provided)"
    combined_raw = "\n".join((raw_patch, raw_title, raw_description))
    if "\ufffd" in combined_raw or _CONTROL.search(combined_raw):
        raise EgressError("provider input contains unsupported text")
    patch, counts, patch_removed, path_aliases = minimize_patch(raw_patch)
    removed = list(patch_removed)
    minimized_title = _minimize_metadata(raw_title, counts, removed)
    minimized_description = _minimize_metadata(raw_description, counts, removed)
    payload = MinimizedPayload(
        patch=patch,
        title=minimized_title,
        description=minimized_description,
        counts=counts,
        path_aliases=path_aliases,
    )
    validate_minimized_payload(raw_patch, raw_title, raw_description, payload, tuple(removed))
    return payload


def build_minimized_egress(
    diff: str,
    *,
    title: str | None = None,
    description: str | None = None,
    rules_block: str | None = None,
) -> EgressResult:
    payload = prepare_provider_payload(diff, title, description)
    sections = []
    if rules_block is not None:
        sections.append(rules_block.rstrip())
    sections.append(f"<unified-diff>\n{payload.patch.rstrip()}\n</unified-diff>")
    sections.append(f"<title>\n{payload.title}\n</title>")
    sections.append(f"<description>\n{payload.description}\n</description>")
    user_content = "\n\n".join(sections) + "\n"
    return EgressResult(
        mode="minimized",
        user_content=user_content,
        report_block={"mode": "minimized", "payload_version": "MINIMIZED_PATCH_V2"},
        path_aliases=payload.path_aliases,
    )
