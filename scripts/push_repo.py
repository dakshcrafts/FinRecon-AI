"""
Push local Git repository to remote GitHub repository using Dulwich.
Supports GitHub Personal Access Token (PAT).
"""

import os
import sys
from dulwich import porcelain

REMOTE_REPO = "github.com/dakshcrafts/FinRecon-AI.git"


def main():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if len(sys.argv) > 1 and sys.argv[1].strip():
        token = sys.argv[1].strip()

    if not token:
        print("=" * 60)
        print("GitHub Personal Access Token (PAT) Required")
        print("=" * 60)
        print("To push to https://github.com/dakshcrafts/FinRecon-AI:")
        print("1. Generate a token at: https://github.com/settings/tokens")
        print("   (Select scope: 'repo')")
        print("2. Run:")
        print("   python scripts/push_repo.py <YOUR_GITHUB_TOKEN>")
        print("   OR")
        print("   .\\scripts\\push_repo.ps1 -Token <YOUR_GITHUB_TOKEN>")
        print("=" * 60)
        token = input("Enter your GitHub PAT (or press Enter to cancel): ").strip()
        if not token:
            print("Cancelled.")
            sys.exit(1)

    auth_url = f"https://{token}@{REMOTE_REPO}"
    print(f"Pushing to https://***@{REMOTE_REPO}...")

    try:
        # Push main branch
        porcelain.push(".", auth_url, "refs/heads/main:refs/heads/main")
        print("[SUCCESS] Pushed refs/heads/main to remote.")
    except Exception as e:
        print(f"[NOTE] Push to refs/heads/main returned: {e}")
        try:
            porcelain.push(".", auth_url, "refs/heads/master:refs/heads/master")
            print("[SUCCESS] Pushed refs/heads/master to remote.")
        except Exception as e2:
            print(f"[ERROR] Failed to push: {e2}")
            sys.exit(1)

    print("\nRepository successfully pushed to https://github.com/dakshcrafts/FinRecon-AI")


if __name__ == "__main__":
    main()
