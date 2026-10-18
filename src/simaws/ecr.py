"""Simulated ECR: a local image registry with digest discipline.

When a working Docker CLI is present, push-image builds a real container
image and saves it; otherwise the source tree is packaged into a compressed
archive with identical digest discipline. Either way the artifact's sha256
digest is recorded, and run-task refuses to start against an image tag that
was never pushed.
"""

import hashlib
import io
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from simaws.state import ACCOUNT_ID, PARTITION, REGION

class EcrError(RuntimeError):
    """Raised when a registry verb cannot do what was asked."""

# Source-tree directories that never belong in a packaged image artifact.
_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".simaws",
    ".idea",
    ".vscode",
    "dist",
    "pdf-pages",
}


def repository_arn(name: str) -> str:
    """The simulated ARN for a repository."""
    return f"arn:{PARTITION}:ecr:{REGION}:{ACCOUNT_ID}:repository/{name}"


def repository_uri(name: str) -> str:
    """The simulated registry URI for a repository."""
    return f"{ACCOUNT_ID}.dkr.simaws.local/{name}"


def create_repository(state: dict, name: str) -> dict:
    """Create a repository; refuse duplicates so image history stays clean."""
    repositories = state["ecr"]["repositories"]
    if name in repositories:
        raise EcrError(f"repository '{name}' already exists")
    repository = {
        "repository_name": name,
        "repository_arn": repository_arn(name),
        "repository_uri": repository_uri(name),
        "images": {},
    }
    repositories[name] = repository
    return repository


def get_repository(state: dict, name: str) -> dict:
    """Return the repository document; raise when it does not exist."""
    repository = state["ecr"]["repositories"].get(name)
    if repository is None:
        raise EcrError(f"repository '{name}' not found")
    return repository


def resolve_use_docker(flag: bool | None, which=shutil.which) -> bool:
    """Resolve the docker mode: explicit flag wins, None means auto-detect."""
    if flag is None:
        return which("docker") is not None
    return bool(flag)


def package_source(source_dir: Path, dest: Path) -> str:
    """Package a source tree into a gzip tar and return its content digest.

    The digest is computed over sorted relative paths plus file bytes, so it
    is deterministic for identical trees and independent of mtimes. Junk
    directories (virtualenvs, caches, VCS internals) are excluded.
    """
    source_dir = Path(source_dir)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with tarfile.open(dest, "w:gz") as tar:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source_dir)
            if any(part in _EXCLUDED_DIRS for part in relative.parts):
                continue
            data = path.read_bytes()
            arcname = relative.as_posix()
            digest.update(arcname.encode("utf-8"))
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    """Stream a file through sha256 without loading it whole."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def push_image(
    state: dict,
    repository: str,
    tag: str,
    source_dir: Path,
    images_dir: Path,
    use_docker: bool | None = None,
    runner=subprocess.run,
) -> dict:
    """Build and push one image tag; returns the recorded image document.

    Docker mode builds a real container image and saves it; source-archive
    mode packages the tree with the same digest discipline. The digest is the
    content identity run-task later verifies against. The runner parameter
    exists for tests: it substitutes the docker subprocess calls.
    """
    repo = get_repository(state, repository)
    docker_mode = resolve_use_docker(use_docker)
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    image_ref = f"{repo['repository_uri']}:{tag}"
    if docker_mode:
        # Deliberately uncaptured: the build output is part of the deploy
        # transcript, and tests always inject a fake runner or use archives.
        try:
            build = runner(
                ["docker", "build", "-t", image_ref, str(source_dir)],
                check=False,
            )
            if build.returncode != 0:
                raise EcrError(
                    f"docker build failed with exit code {build.returncode}"
                )
            artifact = images_dir / f"{repository}-{tag}.tar"
            save = runner(
                ["docker", "save", "-o", str(artifact), image_ref],
                check=False,
            )
            if save.returncode != 0:
                raise EcrError(
                    f"docker save failed with exit code {save.returncode}"
                )
            digest = _sha256_file(artifact)
            packaging = "docker"
        except EcrError:
            if use_docker is True:
                # Explicitly forced docker must fail loudly.
                raise
            # Auto-detected docker that does not work (daemon down, build
            # error): degrade to the archive path so the deployment proceeds.
            print(
                "  docker packaging unavailable; falling back to source-archive "
                "packaging with the same digest discipline"
            )
            docker_mode = False
    if not docker_mode:
        artifact = images_dir / f"{repository}-{tag}.tar.gz"
        digest = package_source(Path(source_dir), artifact)
        packaging = "source-archive"
    image = {
        "tag": tag,
        "digest": f"sha256:{digest}",
        "artifact": artifact.name,
        "size_bytes": artifact.stat().st_size,
        "packaging": packaging,
        "pushed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    repo["images"][tag] = image
    return image


def get_image(state: dict, repository: str, tag: str) -> dict:
    """Return the image document; raise when the tag was never pushed."""
    repo = get_repository(state, repository)
    image = repo["images"].get(tag)
    if image is None:
        raise EcrError(f"image {repository}:{tag} not found in registry")
    return image


def describe_images(state: dict, repository: str) -> str:
    """Render a repository's images as human-readable evidence lines."""
    repo = get_repository(state, repository)
    lines = [f"repository {repo['repository_name']} ({repo['repository_uri']})"]
    if not repo["images"]:
        lines.append("  no images pushed")
    for image in repo["images"].values():
        lines.append(
            f"  {repo['repository_name']}:{image['tag']}  {image['digest']}  "
            f"{image['size_bytes']} bytes  {image['packaging']}  "
            f"pushed {image['pushed_at']}"
        )
    return "\n".join(lines)
