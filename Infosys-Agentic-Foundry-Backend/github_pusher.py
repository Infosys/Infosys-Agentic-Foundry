import shutil
import os
import stat
import time
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


            log.info("Searching for and removing '.env' files before committing...")
            dotenv_files = list(temp_clone_dir.rglob('.env'))
            if dotenv_files:
                for dotenv_file in dotenv_files:
                    try:
                        dotenv_file.unlink() # unlink() is the pathlib method for deleting a file
                        log.warning(f"  - Removed sensitive file: {dotenv_file}")
                    except OSError as e:
                        log.error(f"  - Error removing .env file at {dotenv_file}: {e}")
            else:
                log.info("No '.env' files found to remove.")

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

def push_backup_to_github(source_backup_dir: Path, server_name: str, GITHUB_USERNAME: str = None, GITHUB_PAT: str = None, GITHUB_EMAIL: str = None, TARGET_REPO_NAME: str = None, TARGET_REPO_OWNER: str = None):
    """Push backup to a single branch with server-specific folders."""

    if not all([GITHUB_USERNAME, GITHUB_PAT, GITHUB_EMAIL, TARGET_REPO_NAME, TARGET_REPO_OWNER]):
        raise ValueError("Required GitHub credentials are not set.")

    def remove_dir(dir_path: Path):
        """Remove directory handling Windows read-only .git files and file locks."""
        def _handle_readonly(func, path, _exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        for attempt in range(3):
            try:
                if dir_path.exists():
                    shutil.rmtree(dir_path, onerror=_handle_readonly)
                return
            except Exception as e:
                if attempt < 2:
                    log.warning(f"Cleanup attempt {attempt + 1} failed: {e}. Retrying...")
                    time.sleep(1)
                else:
                    stale = dir_path.parent / f"_stale_{dir_path.name}_{uuid.uuid4().hex[:6]}"
                    dir_path.rename(stale)
                    log.info(f"Renamed stale directory to {stale}")

    author = Actor(GITHUB_USERNAME, GITHUB_EMAIL)
    authenticated_repo_url = f"https://{GITHUB_USERNAME}:{GITHUB_PAT}@github.com/{TARGET_REPO_OWNER}/{TARGET_REPO_NAME}.git"
    branch_name = "Backup"
    temp_clone_dir = Path(tempfile.gettempdir()) / "git_clones" / f"backup_{server_name}"

    log.info(f"Preparing to push backup for server '{server_name}' to branch '{branch_name}'")

    remove_dir(temp_clone_dir)
    repo = None
    try:
        g = Git()
        with g.custom_environment(GIT_TERMINAL_PROMPT="0"):
            repo = Repo.clone_from(authenticated_repo_url, temp_clone_dir)
        log.info("Clone successful.")
        repo.config_writer().set_value("user", "name", author.name).release()
        repo.config_writer().set_value("user", "email", author.email).release()
        if branch_name in repo.heads:
            repo.heads[branch_name].checkout()
        elif f"origin/{branch_name}" in [ref.name for ref in repo.remotes.origin.refs]:
            repo.git.checkout("-b", branch_name, f"origin/{branch_name}")
        else:
            try:
                repo.head.commit
            except git_exc.BadName:
                readme_path = temp_clone_dir / "README.md"
                readme_path.write_text(f"# {TARGET_REPO_NAME} Backups\n\nThis repository contains server backups.\n")
                repo.git.add(A=True)
                repo.index.commit("Initial commit", author=author, committer=author)
            repo.create_head(branch_name).checkout()
        log.info(f"On branch: {branch_name}")

        server_folder = temp_clone_dir / server_name
        if server_folder.exists():
            shutil.rmtree(server_folder, ignore_errors=True)
        shutil.copytree(source_backup_dir, server_folder, ignore=shutil.ignore_patterns('.git'))
        log.info(f"Copied backup to {server_name}/ folder")
        for dotenv_file in server_folder.rglob('.env'):
            try:
                dotenv_file.unlink()
                log.warning(f"  - Removed sensitive file: {dotenv_file}")
            except OSError as e:
                log.error(f"  - Error removing .env file: {e}")
        repo.git.add(A=True)

        if not repo.is_dirty(untracked_files=True):
            log.info("No changes to commit. Backup is identical to previous version.")
            return f"https://github.com/{TARGET_REPO_OWNER}/{TARGET_REPO_NAME}/tree/{branch_name}/{server_name}"

        from datetime import datetime
        commit_message = f"Update backup for {server_name} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        repo.index.commit(commit_message, author=author, committer=author)
        log.info(f"Committed: {commit_message}")

        with repo.git.custom_environment(GIT_TERMINAL_PROMPT="0"):
            repo.remotes.origin.push(refspec=f'{branch_name}:{branch_name}', force=True)

        backup_url = f"https://github.com/{TARGET_REPO_OWNER}/{TARGET_REPO_NAME}/tree/{branch_name}/{server_name}"
        log.info(f"Push successful! View backup at: {backup_url}")
        return backup_url

    except Exception as e:
        log.error(f"Git process failed: {e}", exc_info=True)
        raise
    finally:
        if repo is not None:
            try:
                repo.close()
            except Exception:
                pass
        remove_dir(temp_clone_dir)