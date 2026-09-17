#!/usr/bin/env bash
# Installation et lancement de Tauri sur Linux et macOS.
set -euo pipefail

usage() {
    cat <<'HELP'
Usage : bash lancer-tauri.sh [--install-system] [-p projet.json]

Installe les dépendances Python dans .venv-tauri et Rust si nécessaire, puis lance Tauri.
Le premier lancement nécessite Internet et peut être long.
-p, --project       JSON à ouvrir (chemin relatif au répertoire d'appel).
--install-system    Installer les prérequis système avec sudo sur Debian/Ubuntu
                    ou Fedora. Sur macOS, demander les outils Xcode manquants.
-h, --help          Afficher cette aide, sans installation ni lancement.

Sans -p, utiliser le bouton Ouvrir. Les mises à jour Git restent manuelles.
HELP
}
fail() { printf 'Erreur : %s\n' "$*" >&2; exit 1; }
install_system=false
project_file=''
while (($#)); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --install-system) install_system=true; shift ;;
        -p|--project)
            (($# >= 2)) || fail 'Il manque le chemin du JSON après -p.'
            project_file="$2"; shift 2 ;;
        *) fail "Option inconnue : $1 (voir --help)." ;;
    esac
done
if [[ -n "$project_file" ]]; then
    [[ -f "$project_file" ]] || fail "Projet introuvable : $project_file"
    project_file="$(cd -- "$(dirname -- "$project_file")" && pwd -P)/$(basename -- "$project_file")"
fi
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$repo_dir"
case "$(uname -s)" in
    Linux)
        if "$install_system"; then
            if command -v apt-get >/dev/null; then
                sudo apt-get update
                sudo apt-get install build-essential curl pkg-config python3 python3-venv \
                    libwebkit2gtk-4.1-dev libssl-dev libxdo-dev libayatana-appindicator3-dev librsvg2-dev
            elif [[ -f /etc/fedora-release ]] && command -v dnf >/dev/null; then
                sudo dnf install gcc gcc-c++ make curl pkgconf-pkg-config python3 python3-pip \
                    webkit2gtk4.1-devel openssl-devel libxdo-devel libappindicator-gtk3-devel librsvg2-devel
            else
                fail 'Installation système automatique : Debian/Ubuntu ou Fedora. Pour les autres distributions, voir src-tauri/README.md.'
            fi
        fi
        command -v pkg-config >/dev/null && pkg-config --exists gtk+-3.0 webkit2gtk-4.1 openssl \
            || fail 'Bibliothèques manquantes : relancer avec --install-system ou consulter src-tauri/README.md.'
        command -v cc >/dev/null || fail 'Compilateur C manquant : relancer avec --install-system.'
        ;;
    Darwin)
        if ! xcode-select -p >/dev/null 2>&1; then
            if "$install_system"; then xcode-select --install; fi
            fail 'Installer les outils Xcode (xcode-select --install), puis relancer ce script.'
        fi
        ;;
    *) fail 'Script pour Linux et macOS. Pour Windows, voir src-tauri/README.md.' ;;
esac
command -v python3 >/dev/null || fail 'Python 3.10 ou plus récent est nécessaire.'
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || fail 'Python 3.10 ou plus récent est nécessaire.'
export PATH="${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
if ! command -v cargo >/dev/null || ! cargo --version >/dev/null 2>&1; then
    command -v curl >/dev/null || fail 'Installer curl pour télécharger Rust.'
    printf '%s\n' 'Installation de Rust avec le programme officiel rustup…'
    installer="$(mktemp)"
    trap 'rm -f -- "$installer"' EXIT
    curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o "$installer"
    sh "$installer" -y --profile minimal --no-modify-path
    rm -f -- "$installer"
    trap - EXIT
fi
if command -v uv >/dev/null; then
    uv_bin="$(command -v uv)"
else
    tools_dir="$repo_dir/.tauri-tools"
    if [[ ! -x "$tools_dir/bin/python" ]]; then
        python3 -m venv "$tools_dir" || fail 'Impossible de créer le venv : installer python3-venv sur Debian/Ubuntu.'
    fi
    if [[ ! -x "$tools_dir/bin/uv" ]]; then
        "$tools_dir/bin/python" -m pip install uv
    fi
    uv_bin="$tools_dir/bin/uv"
fi
printf '%s\n' 'Installation des dépendances Python verrouillées (uv.lock)…'
export UV_PROJECT_ENVIRONMENT="$repo_dir/.venv-tauri"
"$uv_bin" sync --locked --extra web
export QCM_PAPIER_PYTHON="$UV_PROJECT_ENVIRONMENT/bin/python"
unset QCM_PAPIER_SERVER
export QCM_PAPIER_PROJECT="$project_file"
printf '%s\n' 'Compilation puis lancement de Tauri…'
# Sans surveillance des sources : modifier le dépôt ne ferme pas la session.
exec cargo run --locked --manifest-path "$repo_dir/src-tauri/Cargo.toml"
