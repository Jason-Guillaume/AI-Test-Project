# Dagu Automation Runner

1. Copy `runner.py` and the two shared scripts from `scripts/` to `/opt/automation-runner/`.
2. Install `automation-pytest-allure.yaml` in the Dagu DAG directory and merge `config.example.yaml` into the server queue configuration.
3. Prepare `/opt/automation-runs`, `/opt/automation-cache`, the Codeup Deploy Key, trusted `known_hosts`, and one callback credential JSON file per integration. See [deployment and credential details](../../docs/automation-center-dagu.md).
4. Install the cleanup script and systemd units:

   ```bash
   sudo install -o root -g root -m 0755 cleanup-runs.sh /usr/local/libexec/automation-cleanup-runs
   sudo install -o root -g root -m 0644 automation-cleanup.service /etc/systemd/system/
   sudo install -o root -g root -m 0644 automation-cleanup.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now automation-cleanup.timer
   ```

The cleanup process removes only direct run directories containing `.callback-ok` when that marker is older than seven days. It also removes dependency environments older than thirty days only when no Runner holds the environment lock. Failed runs without the marker remain available for recovery.
