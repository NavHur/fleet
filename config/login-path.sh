# Sourced by login profiles (fleet bin/sync) and by bin/sync itself, so
# `ssh HOST bash -lc …` (bin/sync --all) gets the PATH an interactive shell has.

# macOS: a login shell's path_helper puts the system folders first; put
# ~/.local/bin back first.
case ${OSTYPE:-} in
  darwin*) PATH="$HOME/.local/bin:$PATH" ;;
esac

# nvm loads from ~/.bashrc after its interactive guard, so a non-interactive
# login shell on an nvm host has no npx. Load nvm's default node then. nvm.sh
# needs bash or zsh; dash also reads ~/.profile.
if [ -n "${BASH_VERSION:-}${ZSH_VERSION:-}" ] && ! command -v npx >/dev/null 2>&1 &&
  [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
  NVM_DIR=${NVM_DIR:-$HOME/.nvm}
  export NVM_DIR
  . "$NVM_DIR/nvm.sh"
fi
export PATH
