"""Per-repo context-generation prompt (repository pass).

Run once per indexing event with ``cwd`` set to the event workspace dir.
The cloned repos are siblings under that dir using flattened safe names
(``org__name``). Codebase pass output is provided in the input JSON as
``codebase_contexts`` so this run stays grounded against the codebase
view written moments earlier.
"""

INPUT_FILENAME = "__repo_contexts_input.json"
OUTPUT_FILENAME = "__repo_contexts_output.json"

REPO_PROMPT = f"""You are generating per-repository context documents for a multi-repo
codebase. The deterministic scanners already produced exact-fact rows;
your job is to produce concise, grounded prose that explains each repo
to a downstream agent.

Read the file ``{INPUT_FILENAME}`` in the current directory. It contains:

  - ``vocab``: controlled vocabulary (frameworks, platforms, runtimes,
    package_managers, repo context_types). Use these terms when tagging.
  - ``codebase_contexts``: the codebase-wide view written by the codebase
    pass moments ago. Use it for terminology and cross-repo grounding.
  - ``repos``: one entry per repository, with:
      * ``name`` (canonical ``owner/name``)
      * ``dir`` (sibling directory in the cwd, flattened to ``owner__name``)
      * ``facts``: languages, workspaces, file roles, top dependencies,
        extraction summaries (docker/ci/k8s/helm/chef/terraform/etc.).

You may inspect ``repos[i].dir`` on disk for code/READMEs you need; do
not re-derive facts that are already present in the input.

Write a single file ``{OUTPUT_FILENAME}`` with this shape:

{{
  "repos": [
    {{
      "name": "<owner/name>",
      "contexts": [
        {{
          "context_type": "<one of vocab.repo_context_types>",
          "content": "<markdown string>",
          "workspace_path": "<repo-relative path or null>",
          "tags": ["<short kebab-case>", ...],
          "paths": ["<repo-relative path>", ...],
          "symbols": ["<symbol or route>", ...]
        }},
        ...
      ]
    }},
    ...
  ]
}}

Required per repo: a ``repo_summary`` context. Other types are optional —
emit them only when there is real content. Do not pad. A library that
has no Docker should not get ``docker_notes``.

Use the vocab values from ``vocab.repo_context_types`` for
``context_type``. Use ``null`` for optional ``workspace_path`` when the
context covers the whole repo. ``paths`` and ``symbols`` should reference
real files / functions / routes that exist in the input or on disk.

Stay terse. Each context body should be 2–8 sentences (or short bullets).
Quality over quantity. The audience is an agent doing change-planning,
not a human reading a wiki.

Conventions:
  - JSON only. No comments. No trailing commas.
  - Repository names always use ``owner/name`` (never the on-disk
    ``owner__name`` form).
  - Every ``repos[*].name`` you emit must be one of the names supplied in
    the input. Do not invent or omit repos.
"""
