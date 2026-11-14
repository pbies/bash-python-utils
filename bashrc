
export LESS="-X"
export PATH=$PATH:~/bin:~/bin2
export DISPLAY=:0.0
export LC_ALL=

uname -a
lsb_release -dc | tee
uptime
# echo -n "IP: "
# hostname -I
alias ls='ls --color=auto'
alias ll='ls -alF'
bell() { printf '\a' >&2; }

__ps1_exit() { echo $?; }
PROMPT_COMMAND='__exit_code=$?'
PS1="\[\e]0;\w\a\][\$(if [ \$__exit_code -eq 0 ]; then echo \"\[\e[1;32m\]0\"; else echo \"\[\e[1;31m\]\$__exit_code\"; fi)\[\e[m\]][\[\e[1;34m\]\A\[\e[m\]][\[\e[1;32m\]\u\[\e[m\]@\[\e[1;36m\]\H\[\e[m\]][\[\e[1;35m\]\w\[\e[m\]] \$ "
# trap 'echo -ne "\033]0;${PWD}: (${BASH_COMMAND})\007"' DEBUG

bind -x '"\C-l":clear'

