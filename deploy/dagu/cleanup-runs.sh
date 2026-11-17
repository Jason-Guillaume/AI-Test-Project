#!/usr/bin/env bash
# 每日删除已成功回调且超过七天的运行目录，以及超过三十天且未被使用的依赖环境。
set -euo pipefail

run_root="${AUTOMATION_RUN_ROOT:-/opt/automation-runs}"
if [[ -d "$run_root" && ! -L "$run_root" ]]; then
  while IFS= read -r -d '' marker; do
    work_dir="${marker%/.callback-ok}"
    [[ -d "$work_dir" && ! -L "$work_dir" ]] || continue
    [[ "$(dirname "$work_dir")" == "$run_root" ]] || continue
    rm -rf -- "$work_dir"
  done < <(find "$run_root" -mindepth 2 -maxdepth 2 -type f -name .callback-ok -mtime +7 -print0)
fi

cache_root="${AUTOMATION_CACHE_ROOT:-/opt/automation-cache}"
venv_root="$cache_root/venvs"
lock_root="$cache_root/locks"
if [[ -d "$venv_root" && ! -L "$venv_root" && -d "$lock_root" && ! -L "$lock_root" ]]; then
  while IFS= read -r -d '' marker; do
    venv_dir="${marker%/.ready}"
    [[ -d "$venv_dir" && ! -L "$venv_dir" ]] || continue
    [[ "$(dirname "$venv_dir")" == "$venv_root" ]] || continue
    lock_path="$lock_root/$(basename "$venv_dir").lock"
    [[ -f "$lock_path" && ! -L "$lock_path" ]] || continue
    exec {lock_fd}<>"$lock_path"
    if flock -n -x "$lock_fd"; then
      expired_marker="$(find "$marker" -maxdepth 0 -type f -mtime +30 -print -quit)"
      if [[ -n "$expired_marker" ]]; then rm -rf -- "$venv_dir"; fi
      flock -u "$lock_fd"
    fi
    exec {lock_fd}>&-
  done < <(find "$venv_root" -mindepth 2 -maxdepth 2 -type f -name .ready -mtime +30 -print0)
fi
