# Issue Tracker: Local Markdown

Issues and PRDs for this repo live as markdown files in `.scratch/` when they exist.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The PRD is `.scratch/<feature-slug>/PRD.md`
- Implementation issues are `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## Publishing

When a skill says "publish to the issue tracker", create the relevant file under `.scratch/<feature-slug>/`, creating directories only as needed.

## Fetching

When a skill says "fetch the relevant ticket", read the referenced local markdown file. The user will normally pass the path directly.
