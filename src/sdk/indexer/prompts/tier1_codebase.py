"""Codebase-pass prompt.

The Claude CLI is invoked with ``cwd`` set to the event workspace directory
(the per-event temp dir created by ``IndexCloneWorkspace``). New repos for
this event are cloned as siblings under that dir using flattened safe
names like ``org__name``. Existing-repo facts come from the input JSON so
Claude does not need them re-cloned.
"""

INPUT_FILENAME = "__codebase_input.json"
OUTPUT_FILENAME = "__codebase_output.json"

TIER1_PROMPT = f"""You are indexing a multi-repository codebase belonging to a single user.

Read the file ``{INPUT_FILENAME}`` in the current directory. It contains:

  - ``vocab``: the controlled vocabulary you must use. When you tag a
    framework, platform, language, or runtime, pick from this list.
  - ``existing_repos``: repositories already indexed. Each card has the
    repository name, top languages, frameworks, platforms, top
    dependencies, and an optional ``repo_summary_snippet``. Treat these as
    ground truth — do not re-derive them.
  - ``new_repos``: repositories cloned for this run. Each entry has
    ``name`` and ``dir``. The dir is a sibling directory in the current
    directory; you may inspect its files directly (``Read`` and ``Glob``
    tools) to derive your understanding.

Your task is to produce a codebase-wide synthesis. Inspect new repos as
needed, but stay efficient: read manifest files (package.json,
pyproject.toml, go.mod, Cargo.toml, Chart.yaml, etc.), READMEs, top-level
entry points, and CI files. Do **not** read every source file.

Then write a single file ``{OUTPUT_FILENAME}`` in the current directory
containing exactly these top-level keys, all required:

  - ``codebase_summary``: one to three paragraphs describing what this
    codebase is for, what kinds of things it does, and who uses it.
  - ``codebase_architecture``: how the repositories fit together —
    services, libraries, dashboards, infra. Mention monorepos and shared
    packages if any.
  - ``cross_repo_relationships``: explicit edges between repos (e.g.
    ``foo`` depends on ``shared/bar``, ``api`` is deployed by ``infra``,
    ``frontend`` calls ``backend``).
  - ``tech_stack_overview``: the tech inventory grouped by concern
    (languages, frameworks, runtimes, package managers, platforms,
    deployment tooling). Use vocabulary terms.
  - ``codebase_terminology``: domain terms that recur across repos (e.g.
    ``tenant``, ``batch session``, ``installation``, ``user_id``). Each
    term should have a one-sentence definition grounded in code.
  - ``query_refinement_hints``: concrete advice for translating natural
    language queries into structured filters. For example, if users
    typically say "deploy" when they mean a Helm chart, document that
    here. Aim for 3-8 actionable hints.

Each value must be an object of the shape:
{{
  "content": "<markdown string, no trailing whitespace>",
  "tags": ["<short kebab-case tag>", ...],
  "referenced_repositories": ["<repo name>", ...]
}}

Keep the JSON valid (no comments, no trailing commas). After writing
``{OUTPUT_FILENAME}``, stop. Do not modify any other files.

Conventions:
  - Repository names use the ``owner/name`` form, never the on-disk
    ``owner__name`` form.
  - When a card under ``existing_repos`` and a fresh inspection of
    ``new_repos`` disagree, treat the existing card as canonical and
    revise only when you have explicit on-disk evidence.
  - If only one repository exists (degenerate case), still emit all six
    keys; values may be short but must be present.
"""
