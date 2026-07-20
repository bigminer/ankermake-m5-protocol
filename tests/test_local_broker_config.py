from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_chrony_pidfile_is_in_boot_cleared_runtime_directory():
    config = (REPO_ROOT / "deploy/local-broker/chrony.conf").read_text()
    pidfile = next(
        line.split(maxsplit=1)[1]
        for line in config.splitlines()
        if line.startswith("pidfile ")
    )

    assert Path(pidfile).parent == Path("/var/run")
