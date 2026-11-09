# Git Release & Tagging Protocol

## Release Workflow Execution Rules
The Agent MUST execute the scripts defined below directly using the Bash tool in sequence.
MANDATORY: Do NOT run exploratory, read, or tag inspection commands (`ls`, `git status`, `git tag`, `read`, etc.) prior to Step 2 confirmation.

## Step 1: Log Retrieval & Version Evaluation
Before modifying any files:
1. Execute the log retrieval script ONLY:
   `./scripts/git/get_tag_logs.sh`
2. Evaluate the semantic level strictly from the output:
   - `fix:`, `perf:`, `refactor:` -> use `SUGGESTED_PATCH`
   - `feat:` -> use `SUGGESTED_MINOR`
   - `BREAKING CHANGE:` or `feat!:` -> use `SUGGESTED_MAJOR`
3. Synthesize a concise release summary based on all retrieved commits.

   **Filtering rules for the summary — when a commit message references
   forbidden paths, EXCLUDE those lines from the synthesized summary:**

   - `.sdd/` — SDD protocol/infra files (not functional)
   - `.pi/` — PI agent config files (not functional)
   - `./scripts/git/` — build/dev scripts (not functional)
   - `./tests/` — test files (not functional)
   - Root config files: `config.json`, `models.yaml`, `.env*`, `pytest.ini`,
     `pyproject.toml`, `requirements*.txt`, `*.cfg`, `.gitignore`
   - `./folder_name` or similar infra-only directories at project root
   -  References to the use of git_cai internal infraestructura tool.

   Strategy: strip lines/bullets that mention only excluded paths. If a commit
   mixes them with functional changes, KEEP the functional part and DROP the
   excluded references.


## Step 2: User Confirmation
Ask the user for confirmation showing:
- Suggested semantic level (`patch | minor | major`).
- Target version tag extracted from context.
- The synthesized release summary.

## Step 3: Changelog Update & Commit on Main
ONLY after explicit user confirmation:
1. Execute the update script (which modifies and commits `CHANGELOG.md` automatically):
   `./scripts/git/update_changelog.sh <TAG_NAME> "<SYNTHESIZED_SUMMARY>"`
   
   > **MANDATORY ERROR HANDLING:** If the script fails with `Permission denied` or any other error, the Agent MUST STOP immediately. Do NOT run `chmod` or attempt to auto-fix permissions; ask the user to resolve it.

## Step 4: Sync Stable Branch
Now that `main` contains the committed changelog, synchronize `stable`:
1. Execute the synchronization script:
   `./scripts/git/sync_stable.sh`
2. **Error & Conflict Handling:**
   - If `./scripts/git/sync_stable.sh` fails, STOP immediately and inform the user.

## Step 5: Tag Execution & Mandatory Remote Push
1. Execute the tag creation tool:
   `./scripts/git/create_tag.sh <patch | minor | major>`
2. Ask the user for confirmation to push:
   *"Release <TAG_NAME> created locally. Push commits and tags to remote?"*
3. Upon user confirmation, execute:
   `git push origin main stable --follow-tags`