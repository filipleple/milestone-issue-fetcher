# GitHub Milestone Exporter

Exports all issues from a GitHub milestone into separate Markdown files, including full metadata and all comments.  
Useful for offline review or AI-based post-processing.

## Requirements

- Python 3.9+
- `requests` library

Install dependency:

```bash
python3 -m pip install requests
````

## Authentication

Create a GitHub Personal Access Token.

Fine-grained token:

* Repository access: select your repository
* Permissions:

  * Issues: Read
  * Pull requests: Read
  * Metadata: Read

Classic token:

* `repo` scope (for private repos)
* `public_repo` scope (for public repos)

Export it:

```bash
export GITHUB_TOKEN=ghp_yourtokenhere
```

Do not commit your token.

## Usage

```bash
./fetch_milestone_issues.py \
  --repo owner/name \
  --milestone "v1.2.3" \
  --out ./issues_md
```

Milestone can be:

* Milestone number (e.g. `42`)
* Milestone title (e.g. `"v1.2.3"`)

Optional flags:

```bash
--state open|closed|all
--include-pull-requests
```

Example:

```bash
./fetch_milestone_issues.py \
  --repo myorg/myrepo \
  --milestone 12 \
  --state all \
  --include-pull-requests \
  --out ./export
```

## Output

The output directory will contain:

* One `.md` file per issue:

  ```
  00042_issue_title_here.md
  ```

* `_index.md` listing all exported issues

Each issue file contains:

* Metadata (author, labels, assignees, timestamps, milestone)
* Full issue body
* All comments
* Direct links to GitHub

## Notes

* Handles pagination automatically.
* Respects GitHub rate limits.
* Does not export timeline events (label changes, cross-references, commits).
* Includes pull requests only if `--include-pull-requests` is specified.
