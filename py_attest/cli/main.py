import click

from py_attest import __version__


@click.group()
@click.version_option(__version__, prog_name="attest")
def cli() -> None:
    """attest: CLI + quality-gate engine for Python repos."""
