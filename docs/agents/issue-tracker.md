# Issue tracker: Local Markdown

Issues and specs for this repo live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are separate files under `.scratch/<feature-slug>/issues/`, numbered `01`, `02`, etc.
- Record triage state as `Status: <label>` near the top of each issue or spec. Label names are in `docs/agents/triage-labels.md`.
- Append conversation history under `## Comments`.

When a skill says "publish to the issue tracker", create the corresponding Markdown file under `.scratch/<feature-slug>/`. When it says "fetch the relevant ticket", read the referenced file.
