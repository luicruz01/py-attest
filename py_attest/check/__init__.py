"""Deterministic checks that execute the reviewed repo's own tooling.

The only part of py-attest that runs code from the reviewed repo: ruff, pytest+coverage,
and gitleaks over the working tree. Always runs without secrets.
"""
