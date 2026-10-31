import os
from pathlib import Path
import dulwich.porcelain as git
from dulwich.repo import Repo
from dulwich.ignore import IgnoreFilterStack

def stage_and_commit():
    repo = Repo('.')
    
    # Files to track
    tracked_files = []
    
    # Custom exclude patterns
    exclude_dirs = {'.venv', '.venv_old', '__pycache__', '.pytest_cache', 'build', 'dist', '.git', 'uploads', 'generated_reports', 'backups'}
    exclude_exts = {'.bak', '.pyc', '.pyd', '.lock'}
    exclude_files = {'finrecon.db-wal', 'finrecon.db-shm', 'secret.key', 'gripher.lock'}

    for root, dirs, files in os.walk('.'):
        # Prune excluded directories
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if f in exclude_files:
                continue
            if any(f.endswith(ext) for ext in exclude_exts):
                continue
            rel_path = os.path.relpath(os.path.join(root, f), '.')
            rel_path_posix = rel_path.replace('\\', '/')
            tracked_files.append(rel_path_posix)

    print(f"Staging {len(tracked_files)} files...")
    git.add(repo, tracked_files)

    print("Creating commit...")
    author = "Rohan <admin@finrecon.ai>"
    commit_msg = b"feat: Gripher PS02 hackathon edition - financial reconciliation desktop platform\n\n- Standalone Windows desktop shell using PySide6 and QWebEngineView\n- Multi-pass intelligent reconciliation engine with ambiguity margin\n- Integer-cent and Decimal financial precision\n- Currency incompatibility protection\n- Transparent rule-based discrepancy and anomaly detection\n- Accounts receivable aging intelligence\n- Multi-tab Excel and PDF executive reporting\n- PyInstaller specification and automated build scripts"
    
    try:
        commit_id = git.commit(repo, message=commit_msg, author=author, committer=author)
        print("Commit created successfully:", commit_id.decode() if isinstance(commit_id, bytes) else commit_id)
    except Exception as e:
        print("Commit notice:", e)

    # Configure remote
    remote_url = "https://github.com/dakshcrafts/FinRecon-AI.git"
    config = repo.get_config()
    config.set(('remote', 'origin'), 'url', remote_url.encode())
    config.write_to_path()
    print(f"Remote origin set to {remote_url}")

if __name__ == "__main__":
    stage_and_commit()

