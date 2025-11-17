import shutil
from git import Repo, Actor, Git, exc as git_exc
from pathlib import Path
from telemetry_wrapper import logger as log
import uuid
import tempfile

def push_project(source_project_dir: Path, agent_name: str | Path,GITHUB_USERNAME:str=None, GITHUB_PAT:str=None, GITHUB_EMAIL:str=None, TARGET_REPO_NAME:str=None, TARGET_REPO_OWNER:str=None):
        if not GITHUB_USERNAME:
            log.error("❌ GITHUB_USERNAME is invalid.")
        if not GITHUB_PAT:
            log.error("❌ GITHUB_PAT is invalid.")
        if not GITHUB_EMAIL:
            log.error("❌ GITHUB_EMAIL is invalid.")
        if not TARGET_REPO_NAME:
            log.error("❌ TARGET_REPO_NAME is invalid.")

        if not all([GITHUB_USERNAME, GITHUB_PAT, GITHUB_EMAIL, TARGET_REPO_NAME]):
            raise ValueError("Required GitHub environment variables are not set.")
        author = Actor(GITHUB_USERNAME, GITHUB_EMAIL)
        authenticated_repo_url = f"https://{GITHUB_USERNAME}:{GITHUB_PAT}@github.com/{TARGET_REPO_OWNER}/{TARGET_REPO_NAME}.git"

        sanitized_agent_name = Path(agent_name).name 
        branch_name = f"agent/{sanitized_agent_name}-{uuid.uuid4().hex[:6]}"
        temp_clone_dir = Path(tempfile.gettempdir()) / "git_clones" / branch_name

        log.info(f"Preparing to push to new branch: {branch_name}")
        log.info(f"Using temporary clone directory: {temp_clone_dir}")

        repo = None
        try:
            # --- Clone the repository ---
            g = Git()
            with g.custom_environment(GIT_TERMINAL_PROMPT="0"):
                repo = Repo.clone_from(authenticated_repo_url, temp_clone_dir)
            log.info("Clone successful.")
            
            # --- Clean the directory and copy new files ---
            # ... (your logic for cleaning the dir and copying files) ...
            shutil.copytree(source_project_dir, temp_clone_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))


            # --- THIS IS THE FIX ---
            # 1. Stage the new files
            repo.git.add(A=True)
            
            # 2. Check if there's anything to commit
            if not repo.is_dirty(untracked_files=True):
                log.info("No changes to commit. Aborting push.")
                return

            # 3. Handle the "empty repo" case by making an initial commit on 'main' first.
            try:
                # This will fail if there are no commits yet (empty repo)
                repo.head.commit
            except git_exc.BadName:
                log.warning("Repository is empty. Creating an initial commit on 'main' branch.")
                # Configure user for the commit
                repo.config_writer().set_value("user", "name", author.name).release()
                repo.config_writer().set_value("user", "email", author.email).release()
                
                # Make the initial commit
                repo.index.commit("Initial commit: Add project structure", author=author, committer=author)
                
                # Now that we have a commit, we can create our new branch
                new_branch = repo.create_head(branch_name)
                new_branch.checkout()
                log.info(f"Checked out new branch: {branch_name}")

            # 4. If the repo was NOT empty, create the branch as usual.
            else:
                log.info("Repository is not empty. Creating new branch.")
                new_branch = repo.create_head(branch_name)
                new_branch.checkout()
                log.info(f"Checked out new branch: {branch_name}")
                # We need to commit the new files on this new branch
                repo.index.commit(f"Add generated agent project: {sanitized_agent_name}", author=author, committer=author)

            # --- Push the new branch to the remote ---
            with repo.git.custom_environment(GIT_TERMINAL_PROMPT="0"):
                log.info(f"Pushing branch '{branch_name}' to origin...")
                repo.remotes.origin.push(refspec=f'{branch_name}:{branch_name}')
            
            pr_url = f"https://github.com/{TARGET_REPO_OWNER}/{TARGET_REPO_NAME}/pull/new/{branch_name}"
            log.info(f"✅ Push successful! Create a pull request at: {pr_url}")

        except Exception as e:
            log.error(f"❌ A critical error occurred during the Git process: {e}", exc_info=True)
            raise
        finally:
            # Cleanup
            if temp_clone_dir.exists():
                shutil.rmtree(temp_clone_dir, ignore_errors=True)
                log.info(f"Cleaned up temporary clone directory.")