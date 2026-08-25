#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
config_file="${WINDOWS_CAN_CONFIG:-${repo_root}/config/windows-host.env}"

if [[ ! -f "${config_file}" ]]; then
    echo "Missing configuration: ${config_file}" >&2
    echo "Copy config/windows-host.example.env to config/windows-host.env." >&2
    exit 2
fi

# shellcheck source=/dev/null
source "${config_file}"

: "${WINDOWS_HOST:?WINDOWS_HOST is required}"
: "${WINDOWS_USER:?WINDOWS_USER is required}"
: "${WINDOWS_REPO:?WINDOWS_REPO is required}"
: "${SSH_KEY:?SSH_KEY is required}"

if [[ ! -f "${SSH_KEY}" ]]; then
    echo "SSH key not found: ${SSH_KEY}" >&2
    exit 2
fi

ssh_target="${WINDOWS_USER}@${WINDOWS_HOST}"
ssh_options=(
    -i "${SSH_KEY}"
    -o BatchMode=yes
    -o ConnectTimeout=5
)

echo "Checking ${ssh_target}..."
ssh "${ssh_options[@]}" "${ssh_target}" \
    "cmd.exe /c \"hostname && whoami && sc query sshd | findstr STATE && git -C ${WINDOWS_REPO} remote -v\""

