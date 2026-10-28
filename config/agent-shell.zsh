# Bash-like options for commands run through `zsh -c`, which is how Claude
# Code, Codex, and OpenCode run every tool call when zsh is the login shell.
# Agents write bash, and zsh's defaults break it in three ways:
#   echo ====          `=cmd` expansion looks up a command `===` and aborts the line
#   --include=*.py     an unmatched glob aborts the line instead of passing through
#   ssh $opts host     an unquoted variable stays one word instead of splitting
# Interactive shells and zsh scripts keep zsh's defaults. ~/.zshenv sources
# this file; bin/sync adds that line where zsh is the login shell.
if [[ -n ${ZSH_EXECUTION_STRING-} && ! -o interactive ]]; then
  setopt no_equals no_nomatch sh_word_split
fi
