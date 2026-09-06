"""
Engineering Capability Package (ECP) Ingestion & Validation Service.

An ECP consists of:
<package_name>/
  ├── SKILL.md          # Frontmatter YAML (name, description) + operational guidance
  ├── tools/             # Executable tools/scripts (chmod +x)
  └── references/        # Contextual documentation loaded on demand

This service unpacks or copies ECPs into `<workspace>/.agents/skills/<package_name>/`
and validates compliance with the ECP standard.
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("urp.web.ecp_service")


def parse_skill_md_frontmatter(content: str) -> Dict[str, str]:
    """
    Parses YAML frontmatter from a SKILL.md file:
    ---
    name: package-name
    description: Package description
    ---
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}

    frontmatter_text = match.group(1)
    meta: Dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip().strip("\"'")
    return meta


def validate_and_extract_ecp(
    workspace_path: Path | str,
    archive_bytes: Optional[bytes] = None,
    source_dir: Optional[Path | str] = None,
    package_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extracts or copies an ECP into `<workspace_path>/.agents/skills/<package_name>/`.
    Validates SKILL.md existence and marks any scripts inside `tools/` as executable.
    """
    workspace = Path(workspace_path).resolve()
    target_skills_root = workspace / ".agents" / "skills"
    target_skills_root.mkdir(parents=True, exist_ok=True)

    dest_pkg_name = package_name
    temp_extract_dir: Optional[Path] = None

    try:
        # Case 1: Archive bytes (ZIP upload)
        if archive_bytes:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                # Inspect file list to determine root directory name
                names = zf.namelist()
                if not names:
                    raise ValueError("Uploaded zip archive is empty.")

                first_name = names[0].split("/")[0]
                if not dest_pkg_name:
                    dest_pkg_name = first_name or "custom_skill"

                dest_dir = target_skills_root / dest_pkg_name
                dest_dir.mkdir(parents=True, exist_ok=True)

                # Check if archive has a top-level directory matching first_name
                has_root_dir = all(n.startswith(first_name + "/") or n == first_name for n in names if n)

                for member in zf.infolist():
                    target_rel_path = member.filename
                    if has_root_dir:
                        # Strip top-level directory prefix
                        rel_parts = member.filename.split("/", 1)
                        if len(rel_parts) > 1 and rel_parts[1]:
                            target_rel_path = rel_parts[1]
                        else:
                            continue

                    out_path = dest_dir / target_rel_path
                    if member.is_dir():
                        out_path.mkdir(parents=True, exist_ok=True)
                    else:
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as source, open(out_path, "wb") as target:
                            shutil.copyfileobj(source, target)

        # Case 2: Source directory path on disk
        elif source_dir:
            src = Path(source_dir).resolve()
            if not src.is_dir():
                raise FileNotFoundError(f"Source ECP directory not found: {src}")

            if not dest_pkg_name:
                dest_pkg_name = src.name

            dest_dir = target_skills_root / dest_pkg_name
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(src, dest_dir)

        else:
            raise ValueError("Either archive_bytes or source_dir must be provided.")

        # Validation Step: SKILL.md must exist
        skill_md_path = dest_dir / "SKILL.md"
        if not skill_md_path.is_file():
            # Check lowercase skill.md
            if (dest_dir / "skill.md").is_file():
                skill_md_path = dest_dir / "skill.md"
            else:
                raise ValueError(f"ECP validation failed: '{dest_pkg_name}' is missing SKILL.md")

        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()

        meta = parse_skill_md_frontmatter(content)
        skill_name = meta.get("name") or dest_pkg_name
        skill_description = meta.get("description") or f"Capability package {dest_pkg_name}"

        # Make all tools executable if tools directory exists
        tools_dir = dest_dir / "tools"
        tool_count = 0
        if tools_dir.is_dir():
            for tool_file in tools_dir.rglob("*"):
                if tool_file.is_file():
                    try:
                        current_mode = tool_file.stat().st_mode
                        tool_file.chmod(current_mode | 0o755)
                        tool_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to chmod tool {tool_file}: {e}")

        logger.info(f"[ECP] Successfully ingested skill '{skill_name}' into {dest_dir} ({tool_count} tools)")
        return {
            "package_name": dest_pkg_name,
            "skill_name": skill_name,
            "description": skill_description,
            "path": str(dest_dir),
            "tool_count": tool_count,
            "skill_md": str(skill_md_path),
        }

    except Exception as e:
        logger.error(f"[ECP] Error extracting ECP: {e}")
        raise
