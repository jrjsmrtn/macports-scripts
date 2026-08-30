#!/bin/bash
#
# mp -- dispatcher for the mp-* helper scripts in this directory.
#
#   mp up            runs mp-up
#   mp check foo     runs mp-check foo
#
# With no command, or an unknown one, it lists what it can reach. It resolves
# its own symlinks first, so a single link into ~/.local/bin is enough to put
# every subcommand on PATH.

set -euo pipefail

# Resolve $0 through any chain of symlinks to find the directory the mp-*
# scripts actually live in. `readlink -f` is not portable to older BSD
# userlands, so walk the chain by hand.
self=$0
hops=0
while [[ -L "${self}" ]]; do
	hops=$((hops + 1))
	if [[ ${hops} -gt 40 ]]; then
		printf 'mp: symlink loop while resolving %s\n' "$0" >&2
		exit 1
	fi
	target=$(readlink "${self}")
	case "${target}" in
	/*) self=${target} ;;
	*) self=$(dirname "${self}")/${target} ;;
	esac
done
bindir=$(cd -P "$(dirname "${self}")" >/dev/null 2>&1 && pwd -P)

subcommands() {
	find "${bindir}" -maxdepth 1 -type f -perm -u+x -name 'mp-*' \
		-exec basename {} \; |
		sed 's/^mp-//' |
		sort
}

usage() {
	printf 'usage: mp <command> [args...]\n\ncommands:\n'
	subcommands | sed 's/^/  /'
}

if [[ $# -eq 0 ]]; then
	usage
	exit 2
fi

case "$1" in
-h | --help | help)
	usage
	exit 0
	;;
esac

cmd=${bindir}/mp-$1
shift

if [[ ! -x "${cmd}" ]]; then
	printf 'mp: no such command: %s\n\n' "$(basename "${cmd}" | sed 's/^mp-//')" >&2
	usage >&2
	exit 2
fi

exec "${cmd}" "$@"
