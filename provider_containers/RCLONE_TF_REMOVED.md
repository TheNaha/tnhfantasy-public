# rclone_tf.py was removed — DO NOT restore it from git history

This file was deleted on 2026-09-27. It contained **live Google OAuth client
secrets, OAuth access/refresh tokens, and rclone crypt passwords in plaintext**,
committed to the repository and present in git history.

It was also dead code: nothing imported it, no Dockerfile copied it, no compose
service mounted it, and no workflow referenced it.

`git show 19def1be:provider_containers/rclone_tf.py` still works. **Do not run
that.** If you need to know what was in it, ask; the answer is "credentials, and
nothing else".

## What still has to happen, and is not a code change

Removing the file from the working tree does **not** remove the secrets from
history, and it does not invalidate them. In order:

1. **Rotate the Google OAuth client secret** in the Google Cloud console.
2. **Revoke all three OAuth refresh tokens** (Google Cloud console, or
   `gcloud auth revoke`). A leaked refresh token is a permanent credential
   until it is revoked.
3. **Rotate the rclone crypt passwords.** Anything encrypted with the removed
   `password`/`password2` pair is unreadable without them, so decide first
   whether that data still matters.
4. **Purge the file from history**, e.g.
   `git filter-repo --path provider_containers/rclone_tf.py --invert-paths`
   followed by a force-push and a re-clone by every collaborator.
5. **Add a secret scanner to CI.** This is the third time this class of problem
   has to be found by hand. `gitleaks` or `trufflehog` in a pre-commit hook
   and in `.github/workflows/` would have caught it at `19def1be`.

Steps 1-3 are urgent and independent of the code. Step 4 rewrites history, so
it is a maintainer decision.
