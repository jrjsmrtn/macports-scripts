"""A quick-and-dirty MacPorts check tool for port maintainers.

Checks are:

    - Livecheck: a `port livecheck` of the maintainer's ports.

    - Tickets: the opened Trac tickets for the maintainer's ports.

    - PullRequests: the opened Pull Requests for the

    - Lint: the opened Trac tickets for the maintainer's ports.

The `~/.macports/mp-check.conf` config file contains the maintainer's name as
well as ports to add or to exclude from the checks.

The Livecheck `exclude-subports` also allow to exclude subports from the
checks.
"""

# FIXME implement exclude-ports support in Tickets
# TODO package the script
# TODO document config file format

import argparse
import configparser
import logging
import logging.config
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd  # type: ignore[import]
from github import Github  # type: ignore[import]
from multidict import MultiDict  # type: ignore[import]
from sh import port  # type: ignore[import]
from yarl import URL  # type: ignore[import]

ConfigParserDefaultsType = dict[str, str] | None
DictConfigType = dict[str, Any]
FilenameType = str | Path
FilenamesType = Sequence[FilenameType]

CONFIG_FILENAMES: FilenamesType = [
    Path(p).expanduser()
    for p in (
        "mp-check.conf",
        "~/.macports/mp-check.conf",
    )
]
LOGGING_CONFIG: DictConfigType = {
    "version": 1,
    "formatters": {
        # "brief": {"format": "%(levelname)s: %(message)s"},
        "brief": {"format": "%(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "brief",
            "stream": "ext://sys.stdout",
        }
    },
    "loggers": {__name__: {"handlers": ["console"]}},
}

log = logging.getLogger(__name__)
port = port.bake("-q")


class Monitor(ABC):
    """An abstract base class for MacPorts monitors."""

    def __init__(self, options: configparser.SectionProxy) -> None:
        log.debug("%s: options are %s", self, dict(options))
        self.options = options
        self.maintainer: str = options.get("maintainer")
        self.include_ports: set[str] = set(options.getlist("include_ports", []))
        self.exclude_ports: set[str] = set(options.getlist("exclude_ports", []))

    def __str__(self) -> str:
        return self.__class__.__name__

    @classmethod
    def monitors(cls):
        return cls.__subclasses__()

    def port_filters(self) -> list[str]:
        """Make a list of port filters."""
        exclude_ports = "".join(f" and not name:{p}" for p in self.exclude_ports)
        filters = [f"maintainer:{self.maintainer}{exclude_ports}"]
        filters.extend(f"name:{p}" for p in self.include_ports)
        return filters

    def ports(self, filters: Iterable[str]) -> set[str]:
        """List the ports matching the given filters."""
        ports = set(
            chain.from_iterable(port.echo(f).split() for f in self.port_filters())
        )
        return ports

    def subports(self, ports: Iterable[str]) -> set[str]:
        """List the subports of given ports."""
        subports = set(
            chain.from_iterable(
                sp.strip().split(", ")
                for sp in port.info("--subports", *ports).split("--")
            )
        )
        return subports

    @abstractmethod
    def check(self) -> Any:
        raise NotImplementedError()


class Lint(Monitor):
    """Lint maintainer's ports."""

    EXCLUDE_SUBPORTS: ClassVar[bool] = True
    NOTOK_RE = re.compile(r"^(?!OK:\s+).+$", re.MULTILINE)

    def __init__(self, options: configparser.SectionProxy) -> None:
        super().__init__(options)
        self.exclude_subports: bool = options.getboolean(
            "exclude_subports", fallback=Lint.EXCLUDE_SUBPORTS
        )

    def check(self) -> None:
        log.warning("---> %s", self)
        filters = self.port_filters()
        log.debug("%s: port filters are %s", self, filters)

        ports = self.ports(filters)
        log.debug("%s: found ports %s", self, ports)
        if self.exclude_subports:
            subports = self.subports(ports)
            log.debug("%s: excluding subports %s", self, subports)
            ports = ports - subports

        for p in sorted(ports):
            lint = port.bake("-v").lint(p).stdout.decode(sys.stdin.encoding)
            if log.isEnabledFor(logging.INFO):
                log.info(lint)
            else:
                notok = self.NOTOK_RE.findall(lint)
                if notok:
                    log.warning("\n".join(notok))


class Livecheck(Monitor):
    """Livecheck maintainer's ports."""

    EXCLUDE_SUBPORTS: ClassVar[bool] = True
    UPDATED_RE = re.compile(r"^.+seems to have been updated.+$", re.MULTILINE)

    def __init__(self, options: configparser.SectionProxy) -> None:
        super().__init__(options)
        self.exclude_subports: bool = options.getboolean(
            "exclude_subports", fallback=Livecheck.EXCLUDE_SUBPORTS
        )

    def check(self) -> None:
        log.warning("---> %s", self)
        filters = self.port_filters()
        log.debug("%s: port filters are %s", self, filters)
        ports = self.ports(filters)
        log.debug("%s: found ports %s", self, ports)
        if self.exclude_subports:
            subports = self.subports(ports)
            log.debug("%s: excluding subports %s", self, subports)
            ports = ports - subports
        log.debug("%s: livechecking ports", self)
        livechecks = (
            port.bake("-v").livecheck(sorted(ports)).stdout.decode(sys.stdin.encoding)
        )
        if log.isEnabledFor(logging.INFO):
            log.info(livechecks)
        else:
            updated = self.UPDATED_RE.findall(livechecks)
            if updated:
                for update in updated:
                    log.warning(update)


class PullRequests(Monitor):
    """Check MacPorts Pull Requests."""

    EXCLUDE_SUBPORTS: ClassVar[bool] = True

    def __init__(self, options: configparser.SectionProxy) -> None:
        super().__init__(options)
        self.exclude_subports: bool = options.getboolean(
            "exclude_subports", fallback=PullRequests.EXCLUDE_SUBPORTS
        )
        gh = Github()
        self.repo = gh.get_repo("macports/macports-ports")

    def check(self) -> None:
        log.warning("---> %s", self)
        filters = self.port_filters()
        log.debug("%s: port filters are %s", self, filters)
        ports = self.ports(filters)
        log.debug("%s: found ports %s", self, ports)
        if self.exclude_subports:
            subports = self.subports(ports)
            log.debug("%s: excluding subports %s", self, subports)
            ports = ports - subports

        log.debug("%s: getting pull requests", self)

        SEP_RE = re.compile(r":\s")
        COLS = ("number", "title", "user.login", "labels")

        def getter(port):
            return (
                port.number,
                port.title,
                port.user.login,
                ", ".join(label.name for label in port.get_labels()),
            )

        recs = [
            getter(p)
            for p in self.repo.get_pulls(state="open")
            if (p.user.login == self.maintainer)
            or (set(SEP_RE.split(p.title)[0].split()) & ports)
        ]
        log.warning(recs)

        pulls = pd.DataFrame.from_records(recs, columns=COLS, index=COLS[0])
        log.warning(pulls)


class Tickets(Monitor):
    """Get Trac open tickets for maintainer's ports."""

    TRAC_QUERY_URL: ClassVar[URL] = URL("https://trac.macports.org/query")
    DEFAULT_TRAC_CRITERIA: ClassVar[MultiDict] = MultiDict(
        (
            ("status", "accepted"),
            ("status", "assigned"),
            ("status", "new"),
            ("status", "reopened"),
        )
    )
    TRAC_COLS: ClassVar[Iterable[str]] = (
        "id",
        "port",
        "summary",
        "status",
        "type",
    )
    TRAC_ORDER: ClassVar[str] = "port"
    TRAC_FORMAT: ClassVar[str] = "tab"

    def trac_filters(self) -> list[dict[str, str]]:
        """Make a list of Trac filters."""
        filters = [{"owner": self.maintainer}]
        for p in self.include_ports:
            filters.append({"port": f"~{p}"})
        return filters

    def trac_query(self) -> MultiDict:
        """Make a MultiDict-based Trac query."""
        query: MultiDict = MultiDict()
        for f in self.trac_filters():
            criteria = Tickets.DEFAULT_TRAC_CRITERIA.copy()
            criteria.extend(f)
            if query:
                query.add("or", "")
            query.extend(criteria)
        query.extend(("col", c) for c in Tickets.TRAC_COLS)
        query.add("order", Tickets.TRAC_ORDER)
        query.add("format", Tickets.TRAC_FORMAT)
        return query

    def check(self) -> pd.DataFrame:
        """Query MacPorts Trac tickets based on given filters."""
        log.warning("---> %s", self)
        query = self.trac_query()
        log.debug("%s: Trac query is %s", self, query)
        url = Tickets.TRAC_QUERY_URL.with_query(query)
        log.debug("%s: Trac query url is %s", self, url)
        log.debug("%s: querying Trac", self)
        tickets = pd.read_csv(str(url), delimiter="\t", index_col=0)
        if not tickets.empty:
            log.warning(tickets)
        else:
            log.info("Found no relevant Trac tickets.")


def make_argparser() -> argparse.ArgumentParser:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Check MacPorts port maintainer information."
    )
    monitors_group = parser.add_argument_group("monitors")
    for monitor in Monitor.monitors():
        monitors_group.add_argument(
            "--" + monitor.__name__.lower(),
            action="append_const",
            dest="monitors",
            const=monitor,
        )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        dest="loglevel",
        const=logging.INFO,
        default=logging.WARN,
    )
    verbosity.add_argument(
        "-d",
        "--debug",
        action="store_const",
        dest="loglevel",
        const=logging.DEBUG,
    )
    return parser


def make_configparser(
    defaults: ConfigParserDefaultsType = None,
) -> configparser.ConfigParser:
    """Parse config files."""

    def getlist(option: str, sep: str = ",", chars: str | None = None) -> list[str]:
        """Return a list from a ConfigParser option.

        By default, split on a comma and strip whitespaces.
        """
        # return [chunk.strip(chars) for chunk in option.split(sep)]
        values = [chunk.strip(chars) for chunk in re.compile(sep).split(option)]
        return [v for v in values if v]

    def getset(option: str, sep: str = ",", chars: str | None = None) -> set[str]:
        """Return a set from a ConfigParser option.

        By default, split on a comma and strip whitespaces.
        """
        return set(getlist(option, sep, chars))

    def optionxform(option: str) -> str:
        """Convert a ConfigParser option.

        Lowercase name and replace dashes with underscores.
        """
        return option.lower().replace("-", "_")

    parser = configparser.ConfigParser(
        converters={"list": partial(getset, sep=r"[,\s\n]+")}, defaults=defaults
    )
    parser.optionxform = optionxform  # type: ignore

    return parser


def setup_logging(loglevel: int = logging.WARN) -> None:
    """Configure logging."""
    logging.config.dictConfig(LOGGING_CONFIG)
    log = logging.getLogger(__name__)
    log.setLevel(loglevel)


def main() -> None:
    """Script entry point."""
    args = make_argparser().parse_args()
    setup_logging(args.loglevel)
    log.debug("args are %s", args)
    log.debug("reading config from %s", CONFIG_FILENAMES)
    config = make_configparser()
    config.read(CONFIG_FILENAMES)

    monitors = args.monitors if args.monitors else Monitor.monitors()

    for monitor in monitors:
        monitor(config[monitor.__name__]).check()


if __name__ == "__main__":
    sys.exit(main())


# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
