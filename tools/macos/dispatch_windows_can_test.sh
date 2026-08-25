#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
config_file="${WINDOWS_CAN_CONFIG:-${repo_root}/config/windows-host.env}"
firmware_repo="/Users/houhou/udp3900"
requested_commit="HEAD"
seconds="15"

usage() {
    cat <<'EOF'
Usage: dispatch_windows_can_test.sh [options]

Options:
  --firmware-repo PATH  Firmware Git repository (default: /Users/houhou/udp3900)
  --commit REV          Firmware revision to bind to evidence (default: HEAD)
  --seconds N           Capture duration in seconds (default: 15)
  --config PATH         Windows host configuration file
EOF
}

while (($#)); do
    case "$1" in
        --firmware-repo)
            firmware_repo="$2"
            shift 2
            ;;
        --commit)
            requested_commit="$2"
            shift 2
            ;;
        --seconds)
            seconds="$2"
            shift 2
            ;;
        --config)
            config_file="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! "${seconds}" =~ ^[1-9][0-9]*$ ]]; then
    echo "--seconds must be a positive integer" >&2
    exit 2
fi

if [[ ! -f "${config_file}" ]]; then
    echo "Missing configuration: ${config_file}" >&2
    exit 2
fi

# shellcheck source=/dev/null
source "${config_file}"

: "${WINDOWS_HOST:?WINDOWS_HOST is required}"
: "${WINDOWS_USER:?WINDOWS_USER is required}"
: "${WINDOWS_REPO:?WINDOWS_REPO is required}"
: "${SSH_KEY:?SSH_KEY is required}"

if [[ -n "$(git -C "${firmware_repo}" status --porcelain)" ]]; then
    echo "Firmware worktree is dirty; commit and push before hardware validation." >&2
    exit 3
fi

firmware_commit="$(git -C "${firmware_repo}" rev-parse "${requested_commit}^{commit}")"
git -C "${firmware_repo}" fetch origin main --quiet
if ! git -C "${firmware_repo}" merge-base --is-ancestor "${firmware_commit}" origin/main; then
    echo "Firmware commit ${firmware_commit} is not available on origin/main." >&2
    exit 3
fi

bridge_commit="$(git -C "${repo_root}" rev-parse HEAD)"
ssh_target="${WINDOWS_USER}@${WINDOWS_HOST}"
ssh_options=(
    -i "${SSH_KEY}"
    -o BatchMode=yes
    -o ConnectTimeout=5
)

remote_command="git -C ${WINDOWS_REPO} fetch origin main; if (git -C ${WINDOWS_REPO} status --porcelain) { throw 'Windows bridge worktree is dirty' }; git -C ${WINDOWS_REPO} checkout -B main origin/main; & ${WINDOWS_REPO}\\tools\\windows\\run_can_test.ps1 -FirmwareCommit ${firmware_commit} -BridgeCommit ${bridge_commit} -Seconds ${seconds}"

set +e
remote_output="$(
    ssh "${ssh_options[@]}" "${ssh_target}" \
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \"${remote_command}\"" 2>&1
)"
remote_status=$?
set -e
printf '%s\n' "${remote_output}"

zip_path="$(printf '%s\n' "${remote_output}" | sed -n 's/^RESULT_ZIP=//p' | tail -1 | tr -d '\r')"
if [[ -z "${zip_path}" ]]; then
    echo "Windows test did not report RESULT_ZIP." >&2
    exit "${remote_status:-1}"
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
local_base="${repo_root}/artifacts/windows-can/${firmware_commit}/${timestamp}"
mkdir -p "${local_base}"
local_zip="${local_base}/result.zip"
scp "${ssh_options[@]}" "${ssh_target}:/$(printf '%s' "${zip_path}" | sed 's#\\#/#g')" "${local_zip}"
unzip -q "${local_zip}" -d "${local_base}"
rm "${local_zip}"

echo "RESULT_LOCAL=${local_base}"
if ((remote_status != 0)); then
    exit "${remote_status}"
fi

