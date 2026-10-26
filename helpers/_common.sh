#!/bin/sh

shell_quote() {
    printf "'"
    printf '%s' "$1" | sed "s/'/'\\\\''/g"
    printf "'"
}

activate_export() {
    printf 'export %s=%s\n' "$1" "$(shell_quote "$2")" >&3
}

print_path_activation() {
cat <<SH
case ":\$PATH:" in
    *:$1:*) ;;
    *) PATH=$1:"\$PATH" ;;
esac

export PATH
SH
}

activate_path() {
    print_path_activation "$(shell_quote "$1")" >&3
}
