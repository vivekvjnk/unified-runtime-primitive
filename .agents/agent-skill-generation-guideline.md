## Agent Skill Generation Guideline

**Overview:** Agent Skills are filesystem-based, reusable packages that provide domain-specific expertise. They operate on a "progressive disclosure" model: metadata is loaded at startup, instructions load when triggered, and bundled scripts/resources are accessed on demand via bash commands.

### 1. Directory Structure

Generate the skill as a self-contained directory.

```text
skill-name/
├── SKILL.md             (Required: Metadata and primary instructions)
├── REFERENCE.md         (Optional: Extra context, schemas, or templates)
└── scripts/
    └── utility_script.py (Optional: Executable code)

```

### 2. YAML Metadata (`SKILL.md` Frontmatter)

Every `SKILL.md` **must** begin with YAML frontmatter defining how the agent discovers the skill.

**Strict Field Requirements:**

* **`name`**:
* Maximum 64 characters.
* Lowercase letters, numbers, and hyphens ONLY.
* Cannot contain XML tags.
* Cannot contain reserved words ("anthropic" or "claude").


* **`description`**:
* Maximum 1024 characters (must not be empty).
* Cannot contain XML tags.
* **Crucial:** Must explicitly state *what* the skill does AND *when/under what conditions* the agent should trigger it.



**Template:**

```markdown
---
name: target-skill-name
description: What the skill does. Use this skill when [specific user prompts, file types, or conditions occur].
---
# Skill Name Title
...

```

### 3. Instruction Body (`SKILL.md`)

Below the frontmatter, write the procedural knowledge the agent needs when the skill is triggered.

* **Provide Step-by-Step Guidance:** Outline exact workflows, best practices, and rules.
* **Use Concrete Examples:** Include explicit code snippets, expected inputs, and expected outputs.
* **Reference Bundled Files:** Direct the agent to read external files (e.g., `cat REFERENCE.md`) for deep context rather than dumping all information into `SKILL.md`.
* **Delegate to Scripts:** Direct the agent to execute bundled scripts via bash instead of writing code from scratch.

### 4. Bundling Resources & Code

* **Documentation:** Place large datasets, API references, or templates in separate `.md` or `.txt` files.
* **Executable Scripts:** Package deterministic operations in scripts (e.g., Python, Bash). *Note: The agent reads the output of the script, not the source code.*
* **Environment Constraints:** Ensure code does not require runtime package installations or external network access, as many skill runtime environments are strictly sandboxed. Rely on standard libraries or pre-configured dependencies.

### 5. Security & Safety Rules

* Do not include code that fetches external instructions at runtime.
* Ensure generated scripts do not execute unintended system commands or exfiltrate sensitive data.