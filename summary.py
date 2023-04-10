from __future__ import annotations

import collections
import dataclasses
import json
import pathlib
import re
import string
import sys
from typing import ClassVar, DefaultDict, TypedDict

import jinja2

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self


EPICS_SITE_TOP = pathlib.Path("/cds/group/pcds/epics")
IOC_APPL_TOP = re.compile(r"IOC_APPL_TOP\s*=\s*(.*)$")


class ExpectedFindReleaseFileError(Exception):
    ...


class BashScriptError(ExpectedFindReleaseFileError):
    ...


class BootPathDoesNotExist(ExpectedFindReleaseFileError):
    ...


class BinaryPathDoesNotExist(ExpectedFindReleaseFileError):
    ...


class ReleaseFileNotFoundError(Exception):
    ...


class SourceCodeMissingError(Exception):
    ...


class WhatrecordMetadata(TypedDict):
    """A single bit of IOC metadata from iocs.json."""

    alias: str
    base_version: str
    binary: str
    config_File: str
    dir: str
    history: list[str] | None
    host: str
    name: str
    port: int
    script: str



@dataclasses.dataclass(frozen=True)
class VersionInfo:
    """Version information."""

    name: str = "?"
    base: str = "?"
    tag: str = "?"

    _module_path_regexes_: ClassVar[list[re.Pattern]] = [
        re.compile(
            base_path + "/"
            r"(?P<base>[^/]+)/"
            r"modules/"
            r"(?P<name>[^/]+)/"
            r"(?P<tag>[^/]+)/?",
        )
        for base_path in (
            "/cds/group/pcds/epics",
            "/reg/g/pcds/epics",
            "/reg/g/pcds/package/epics",
        )
    ] + [
        # /reg/g/pcds/epics/modules/xyz/ver
        re.compile(
            r"/reg/g/pcds/epics/modules/"
            r"(?P<name>[^/]+)/" 
            r"(?P<tag>[^/]+)/?",
        ),
        re.compile(
            r"/reg/g/pcds/epics-dev/modules/"
            r"(?P<name>[^/]+)/" 
            r"(?P<tag>[^/]+)/?",
        ),
        re.compile(
            r"/reg/g/pcds/package/epics/"
            r"(?P<base>[^/]+)/"
            r"module/"
            r"(?P<name>[^/]+)/" 
            r"(?P<tag>[^/]+)/?",
        ),
    ]

    @property
    def base_url(self) -> str:
        looks_like_a_branch = self.base.count(".") == 3
        if looks_like_a_branch:
            return f"https://github.com/slac-epics/epics-base/tree/{self.base}.branch"
        return f"https://github.com/slac-epics/epics-base/releases/tag/{self.base}"

    @property
    def url(self) -> str:
        return f"https://github.com/slac-epics/{self.name}/releases/tag/{self.tag}"

    @property
    def path(self) -> pathlib.Path:
        if self.name == "epics-base":
            return EPICS_SITE_TOP / "base" / self.tag
        return EPICS_SITE_TOP / self.tag / "modules"

    @classmethod
    def from_path(cls: type[Self], path: pathlib.Path) -> Self | None:
        path_str = str(path.resolve())
        # TODO some sort of configuration
        for regex in cls._module_path_regexes_:
            match = regex.match(path_str)
            if match is None:
                continue
            return cls(**match.groupdict())
        return None


def get_variables(contents: str) -> dict[str, str]:
    """Get all variables and values in a given Makefile."""

    variables = {}
    for line in contents.splitlines():
        line = line.rstrip()
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        var, value = line.split("=", 1)
        variables[var.strip()] = value.strip()
    return variables


def expand(line: str, variables: dict[str, str]) -> str:
    """Expand Makefile variables in a given line."""
    line = line.replace("$(", "${")
    line = line.replace(")", "}")
    assert line.count("{") == line.count("}")
    return string.Template(line).substitute(variables)


def get_dep_to_version(
    contents: str, defined: dict[str, str]
) -> dict[str, VersionInfo]:
    """
    For a given RELEASE file contents, generate a VersionInfo dictionary.

    Parameters
    ----------
    contents : str
        Contents of the RELEASE file.
    defined : dict[str, str]
        Variables defined externally.

    Returns
    -------
    dict[str, VersionInfo]
    """
    ignore_vars = {
        "MY_MODULES",
        "EPICS_MODULES",
        "EPICS_DEV_MODULES",
        "EPICS_IOC",
        "VACUUMCOMMON",
        "EPICS_SITE_TOP",
        "TEMPLATE_TOP",  # TODO
        "RULES",
        "CONFIG",
    }
    defined.setdefault("BASE_MODULE_VERSION", "R7.0.2-2.?")
    defined.setdefault("EPICS_SITE_TOP", "/reg/g/pcds/epics")
    defined.setdefault("EPICS_BASE", "/reg/g/pcds/epics/base/R7.0.2-2.?")
    defined.setdefault("EPICS_MODULES", "/reg/g/pcds/epics/R7.0.2-2.0/modules")
    defined.setdefault("EPICS_MODULES_DEV", "/reg/g/pcds/epics/R7.0.2-2.0/modules")

    variables = get_variables(contents)
    defined.update(variables)

    for _ in range(5):
        for var in list(variables):
            try:
                variables[var] = expand(variables[var], defined)
            except KeyError:
                # print("keyerror", key, value, str(key).strip("'") in variables)
                ...

    versions = {}
    for var, value in variables.items():
        # print(var, value)
        if value.startswith("/"):
            version = VersionInfo.from_path(pathlib.Path(value))
            if var == "EPICS_BASE":
                ...
            elif var in ignore_vars:
                ...
            elif "SCREENS" in var:
                ...
            elif "/home" in value:
                print("Found home path", var, value, file=sys.stderr)
            elif "/epics-dev/bosum123/ek" in value:
                print("weird dev path", var, value, file=sys.stderr)
            elif version is None:
                print("Found unhandled path semantics?", var, value, version, file=sys.stderr)
                # raise
            else:
                # print("->", version)
                versions[var] = version

    return versions


@dataclasses.dataclass
class ReleaseFile:
    """Represents a single RELEASE file with its module dependencies."""

    filename: pathlib.Path
    dep_to_version: dict[str, VersionInfo]

    def __hash__(self):
        return hash(self.filename)

    @classmethod
    def parse(cls: type[Self], filename: pathlib.Path) -> Self:
        with open(filename) as fp:
            contents = fp.read()

        return ReleaseFile(
            filename=filename,
            dep_to_version=get_dep_to_version(contents, {}),
        )


@dataclasses.dataclass
class Dependency:
    """A dependency tracked in the Statistics class."""

    name: str = ""
    by_ioc_name: set[str] = dataclasses.field(default_factory=set)
    by_release_file: set[ReleaseFile] = dataclasses.field(default_factory=set)
    by_version: DefaultDict[VersionInfo, set[ReleaseFile]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(set)
    )


@dataclasses.dataclass
class Statistics:
    """Statistics tracker for all module dependencies."""

    deps: DefaultDict[str, Dependency] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(Dependency)
    )

    @property
    def num_iocs(self) -> int:
        """Total number of IOCs tracked in the statistics."""
        return len(
            {
                ioc
                for dep in self.deps.values()
                for ioc in dep.by_ioc_name
            }
        )

    @property
    def num_release_files(self) -> int:
        """Total number of release files tracked in the statistics."""
        return len(
            {
                rel.filename
                for dep in self.deps.values()
                for rel in dep.by_release_file
            }
        )


def add_to_stats(stats: Statistics, release_file: ReleaseFile, ioc_name: str):
    """
    Add release file/IOC information to the statistics.

    Parameters
    ----------
    stats : Statistics
    release_file : ReleaseFile
    ioc_name : str
    """
    for var, version in release_file.dep_to_version.items():
        stats.deps[var].name = var
        stats.deps[var].by_ioc_name.add(ioc_name)
        stats.deps[var].by_release_file.add(release_file)
        stats.deps[var].by_version[version].add(release_file)


def by_release_file_count(dep: Dependency) -> int:
    """Sort helper - sort by release file count."""
    return len(dep.by_release_file)


def by_total_version_count(item: tuple[VersionInfo, set[ReleaseFile]]) -> tuple[int, str]:
    """Sort helper - sort by total version count."""
    version, release_files = item
    return (len(release_files), version.tag)


def load_iocs(filename: str = "iocs.json"):
    """Load all IOCs from the given JSON file."""
    with open(filename) as fp:
        return json.load(fp)


def get_release_file_from_ioc_appl_top(appl_top_file: pathlib.Path) -> pathlib.Path:
    """
    Find a RELEASE file given a templated IOC_APPL_TOP path.

    Parameters
    ----------
    appl_top_file : pathlib.Path

    Returns
    -------
    pathlib.Path
    """
    with open(appl_top_file) as fp:
        contents = fp.read()

    match = IOC_APPL_TOP.match(contents)
    if match is None:
        raise ValueError("IOC application top not found in IOC_APPL_TOP")

    ioc_appl_top = pathlib.Path(match.groups()[0])
    if not ioc_appl_top.exists():
        raise SourceCodeMissingError(f"No IOC application top: {ioc_appl_top}")

    return ioc_appl_top / "configure" / "RELEASE"


def find_release_file_from_boot_path(boot_path: pathlib.Path) -> pathlib.Path:
    """
    Find a RELEASE file given a specific IOC boot path.

    Parameters
    ----------
    boot_path : pathlib.Path

    Returns
    -------
    pathlib.Path
    """
    path = boot_path.resolve()
    while len(path.parts) > 2:
        release_path = path / "configure" / "RELEASE"
        appl_top_file = path / "IOC_APPL_TOP"
        if release_path.exists():
            return release_path
        if appl_top_file.exists():
            return get_release_file_from_ioc_appl_top(appl_top_file)
        path = path.parent

    raise ValueError(f"Unable to find RELEASE file for boot path {boot_path}")


def get_release_file_from_ioc(info: WhatrecordMetadata) -> pathlib.Path:
    """
    Get the path of the RELEASE file for a provided set of metadata.

    Parameters
    ----------
    info : WhatrecordMetadata
        IOC metadata.

    Returns
    -------
    pathlib.Path
        The RELEASE file path.
    """
    boot_path = pathlib.Path(info["script"]).parent
    if not boot_path.exists():
        raise BootPathDoesNotExist(f"Boot path does not exist; skipping: {boot_path}")

    try:
        release_file = find_release_file_from_boot_path(boot_path)
    except ValueError:
        binary_path = info["binary"]
        try:
            if binary_path is None:
                raise BinaryPathDoesNotExist("No whatrecord metadata for the binary path")
            binary_path = pathlib.Path(binary_path).parent
            if binary_path == pathlib.Path("/usr/bin"):
                raise BashScriptError(f"Bash script for IOC; skipping: {boot_path}")
            release_file = find_release_file_from_boot_path(binary_path)
        except ValueError:
            raise ReleaseFileNotFoundError(f"No release file for IOC: {boot_path} and {binary_path}") from None

    return release_file
    


def print_summary(stats: Statistics, fp=sys.stderr) -> None:
    """
    Parameters
    ----------
    fp :
        The file-like object to write the information to.
    stats : Statistics
        The statistics.
    """
    for dep in sorted(
        stats.deps.values(),
        key=by_release_file_count,
        reverse=True,
    ):
        print(
            (
                f"{dep.name} used by {len(dep.by_release_file)} release files "
                f"(applications) and {len(dep.by_ioc_name)} IOCs "
                f"with a total of {len(dep.by_version)} versions in use")
            ,
            file=fp,
        )
        if len(dep.by_version) > 1:
            for ver, release_files in sorted(
                dep.by_version.items(),
                key=by_total_version_count,
                reverse=True,
            ):
                print(f"    {len(release_files)}x {ver.name} {ver.base} {ver.tag}", file=fp)

    total_versions = sum(len(dep.by_version) for dep in stats.deps.values())
    print(file=fp)
    print(f"{len(stats.deps)} dependencies with a total of {total_versions} distinct versions", file=fp)


def format_template(stats: Statistics, template_filename: pathlib.Path) -> str:
    """
    Format the provided Jinja template with the given statistics.

    Parameters
    ----------
    stats : Statistics
    template_filename : pathlib.Path

    Returns
    -------
    str
    """
    deps_by_release_file_count = sorted(
        stats.deps.values(),
        key=by_release_file_count,
        reverse=True,
    )
    dep_versions = {}
    for dep in stats.deps.values():
        dep_versions[dep.name] = sorted(
            dep.by_version.items(),
            key=by_total_version_count,
            reverse=True,
        )
  
    with open(template_filename) as fp:
        template = jinja2.Template(fp.read())
   
    total_versions = sum(len(dep.by_version) for dep in stats.deps.values())
    return template.render(
        stats=stats,
        deps_by_release_file_count=deps_by_release_file_count,
        dep_versions=dep_versions,
        total_versions=total_versions,
    )


def main() -> tuple[Statistics, str]:
    """Generate statistics from all IOCs found in ``iocs.json``"""
    stats = Statistics()
    release_files = {}

    for ioc in load_iocs():
        try:
            release_file_path = get_release_file_from_ioc(ioc)
        except ExpectedFindReleaseFileError as ex:
            print(ex, file=sys.stderr)
        except ReleaseFileNotFoundError as ex:
            print(ex, file=sys.stderr)
        except SourceCodeMissingError as ex:
            print(ex, file=sys.stderr)
        else:
            release_file = release_files.get(release_file_path, None)
            if release_file is None:
                release_file = ReleaseFile.parse(release_file_path)
                release_files[release_file_path] = release_file
            add_to_stats(stats, release_file, ioc["name"])

    print_summary(stats)

    contents = format_template(stats, pathlib.Path("summary.tpl.html"))
    print(contents)
    return stats, contents


if __name__ == "__main__":
    stats, contents = main()  # noqa: F401
