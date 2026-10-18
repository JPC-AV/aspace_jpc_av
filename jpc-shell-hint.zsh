# jpc-shell-hint.zsh - says why a jpc command was not found (zsh only).
#
# Optional. To turn it on, add one line to ~/.zshrc with the path of your
# own checkout (the bare `jpc` command prints the exact line):
#
#     [ -f ~/github/jpc/aspace_jpc_av/jpc-shell-hint.zsh ] && source ~/github/jpc/aspace_jpc_av/jpc-shell-hint.zsh
#
# The [ -f ... ] && part skips the line while this file is absent (say, on
# a branch without it), so a new Terminal never opens with an error.
#
# When `jpc` or a `jpc-...` command is not found, it says why: no Python
# environment is active, the active one does not have the commands, which
# environments do, or how to install them. Every other unknown command
# gets zsh's usual message.
#
# Passive: sourcing this file only defines zsh's command_not_found_handler.
# It looks for nothing until a jpc command is not found, and then only
# reads - the environments `conda env list --json` reports, and this
# checkout's jpca_aspace fallback. It never activates, installs or runs
# anything else, and needs no Python to do it. A command_not_found_handler
# that is already defined is left untouched, so sourcing this file again
# changes nothing.

[ -n "$ZSH_VERSION" ] || return 0

# someone's own handler - or this one, sourced before - stays as it is
(( ${+functions[command_not_found_handler]} )) && return 0

typeset -g _JPC_HINT_REPO=${${(%):-%x}:A:h}

# Every jpc command, bare jpc first - the same commands as COMMANDS in
# jpc.py (a test compares them). One list, for both recognizing a name and
# finding an install.
typeset -ga _JPC_HINT_COMMANDS=(jpc jpc-pull jpc-check jpc-fill jpc-import jpc-update
                                jpc-writeback jpc-rename jpc-mads)

command_not_found_handler() {
  emulate -L zsh
  if [[ $1 == jpc || $1 == jpc-* ]]; then
    _jpc_hint "$1"
  else
    print -u2 -r -- "zsh: command not found: $1"
  fi
  return 127  # zsh reports this as the command's own status
}

# How the prompt names an environment: (base), (NAME), or its full path.
# Paths are compared resolved, so a Conda reached through a link still
# counts as Conda's own.
_jpc_hint_name() {
  emulate -L zsh
  local p=$1 root=$2 real=${1:A}
  if [[ -f $p/pyvenv.cfg ]]; then
    print -r -- "($p:t)"
  elif [[ -n $root && $real == "$root" ]]; then
    print -r -- "(base)"
  elif [[ -n $root && $real == "$root/envs/$real:t" ]]; then
    print -r -- "($real:t)"
  else
    print -r -- "$p"
  fi
}

# The command that activates an environment. A name only where Conda is
# sure to know it (its own envs folder); otherwise the quoted path.
_jpc_hint_activate() {
  emulate -L zsh
  local p=$1 root=$2 real=${1:A}
  if [[ -f $p/pyvenv.cfg ]]; then
    print -r -- "source ${(q-):-$p/bin/activate}"
  elif [[ -n $root && $real == "$root" ]]; then
    print -r -- "conda activate base"
  elif [[ -n $root && $real == "$root/envs/$real:t" ]]; then
    print -r -- "conda activate ${(q-)real:t}"
  else
    print -r -- "conda activate ${(q-)p}"
  fi
}

# Whether an environment's bin folder holds any of the jpc commands -
# a partial install may lack some of them, bare `jpc` included.
_jpc_hint_has_any() {
  emulate -L zsh
  local name
  for name in $_JPC_HINT_COMMANDS; do
    [[ -x $1/bin/$name ]] && return 0
  done
  return 1
}

# The environment folders Conda reports, one per line. Reads conda's JSON
# with zsh alone - no python, no jq. Returns 2 when conda fails, 3 when its
# output is not the expected {"envs": ["/path", ...]}.
_jpc_hint_conda_envs() {
  emulate -L zsh
  setopt extendedglob
  local json rest before list q='"'
  json=$("$1" env list --json 2>/dev/null) || return 2
  rest=${json#*\"envs\"}
  [[ $rest == "$json" ]] && return 3
  before=$rest
  rest=${rest#[[:space:]]#:[[:space:]]#[[]}
  [[ $rest == "$before" ]] && return 3
  list=${rest%%\]*}
  [[ $list == "$rest" ]] && return 3
  # "a", "b" splits on the quotes into: space, a, comma, b, space
  local -a parts=("${(@ps:$q:)list}")
  (( $#parts % 2 )) || return 3
  local i item
  for (( i = 1; i <= $#parts; i++ )); do
    item=$parts[i]
    if (( i % 2 )); then
      if (( i == 1 || i == $#parts )); then
        [[ $item == [[:space:]]# ]] || return 3
      else
        [[ $item == [[:space:]]#,[[:space:]]# ]] || return 3
      fi
    else
      item=${item//\\\//\/}
      item=${item//\\\\/\\}
      [[ $item == *\\* || $item != /* ]] && return 3  # an escape this cannot decode
      print -r -- "$item"
    fi
  done
  return 0
}

_jpc_hint() {
  emulate -L zsh
  local cmd=$1 repo=$_JPC_HINT_REPO
  local -a known=($_JPC_HINT_COMMANDS)
  local active=${VIRTUAL_ENV:-$CONDA_PREFIX}
  local conda=${CONDA_EXE:-$commands[conda]} root=
  [[ -n $conda && -x $conda ]] && root=${conda:A:h:h}
  local here=0 reachable=0 name
  [[ -n $active ]] && _jpc_hint_has_any $active && here=1
  for name in $known; do
    (( ${+commands[$name]} )) && { reachable=1; break; }
  done

  # a name that is not a jpc command, where the commands themselves work
  if (( ! ${known[(Ie)$cmd]} )) && (( reachable || here )); then
    print -u2 -r -- "$cmd: no such command. The jpc- commands are:"
    print -u2 -r -- "  ${(j:  :)known[2,-1]}"
    print -u2 -r -- "  (jpc lists them, one line each)"
    return 0
  fi

  # the active environment has the commands, yet this one was not found
  if (( here )); then
    name=$(_jpc_hint_name $active $root)
    if [[ -x $active/bin/$cmd ]]; then
      if (( ${path[(Ie)$active/bin]} || ${path[(Ie)${active:A}/bin]} )); then
        print -u2 -r -- "$cmd: installed in the active environment, $name, but this"
        print -u2 -r -- "  shell has not picked it up yet. Run:  rehash"
      else
        print -u2 -r -- "$cmd: installed in the active environment, $name, but its bin"
        print -u2 -r -- "  folder is not on PATH. Activate the environment again:"
        print -u2 -r -- "    $(_jpc_hint_activate $active $root)"
      fi
    else
      print -u2 -r -- "$cmd: missing from the active environment, $name, which has the"
      print -u2 -r -- "  other jpc- commands - an older or incomplete install. Reinstall it"
      print -u2 -r -- "  from the checkout:"
      print -u2 -r -- "    cd ${(q-)repo}"
      print -u2 -r -- "    python -m pip install -e ."
    fi
    return 0
  fi

  # look for the commands: Conda's environments, then this checkout's fallback
  local -a envs found checked
  local listing problem= e
  if [[ -z $root ]]; then
    problem="conda was not found"
  else
    listing=$(_jpc_hint_conda_envs $conda)
    case $? in
      0) envs=("${(@f)listing}"); envs=(${envs:#}); checked+=("$#envs from Conda's list") ;;
      2) problem="'conda env list' failed" ;;
      *) problem="'conda env list' gave output that could not be read" ;;
    esac
  fi
  if [[ -d $repo/jpca_aspace ]]; then
    envs+=($repo/jpca_aspace)
    checked+=("this checkout's jpca_aspace")
  fi
  typeset -U envs
  for e in $envs; do
    _jpc_hint_has_any $e && found+=($e)
  done

  print -u2 -r -- "$cmd: not found in this Terminal."
  if [[ -n $active ]]; then
    print -u2 -r -- "  The active environment, $(_jpc_hint_name $active $root), does not have the jpc- commands."
  else
    print -u2 -r -- "  No Python environment is active."
  fi
  [[ -n $problem ]] && print -u2 -r -- "  Conda's environment list could not be read ($problem)."
  local -a partial
  if (( ${known[(Ie)$cmd]} )); then
    for e in $found; do
      [[ -x $e/bin/$cmd ]] || partial+=($e)
    done
  fi
  if (( $#found == 1 )); then
    print -u2 -r -- "  They are installed in $(_jpc_hint_name $found[1] $root). Activate it:"
    print -u2 -r -- "    $(_jpc_hint_activate $found[1] $root)"
  elif (( $#found > 1 )); then
    print -u2 -r -- "  They are installed in several environments - activate the one you use:"
    for e in $found; do
      print -u2 -r -- "    $(_jpc_hint_activate $e $root)"
    done
  fi
  if (( $#partial )); then
    print -u2 -r -- "  $cmd itself is missing from $(_jpc_hint_name $partial[1] $root)${partial[2]:+ and others} -"
    print -u2 -r -- "  an older or incomplete install. After activating, reinstall:"
    print -u2 -r -- "    cd ${(q-)repo}"
    print -u2 -r -- "    python -m pip install -e ."
  fi
  if (( ! $#found )); then
    if (( $#checked )); then
      print -u2 -r -- "  The jpc- commands were not found in the environments checked"
      print -u2 -r -- "  (${(j: and :)checked})."
    else
      print -u2 -r -- "  No environment could be checked."
    fi
    print -u2 -r -- "  To install them, activate your chosen Python environment, then:"
    print -u2 -r -- "    cd ${(q-)repo}"
    print -u2 -r -- "    python -m pip install -e ."
  fi
  (( ${known[(Ie)$cmd]} )) || \
    print -u2 -r -- "  Also: $cmd is not one of the jpc- commands (${(j:, :)known[2,-1]})."
  return 0
}
