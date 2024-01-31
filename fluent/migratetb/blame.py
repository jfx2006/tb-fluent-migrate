from __future__ import annotations
from typing import Dict, Iterable, Tuple, TypedDict, cast

import argparse
import json
import os

from compare_locales.parser import getParser, Junk
from compare_locales.parser.fluent import FluentEntity
from compare_locales import mozpath
import hglib
from hglib.util import b, cmdbuilder

BlameData = Dict[str, Dict[str, Tuple[int, float]]]
"File path -> message key -> [userid, timestamp]"


class BlameResult(TypedDict):
    authors: list[str]
    blame: BlameData


class LineBlame(TypedDict):
    date: tuple[float, float]
    line: str
    user: str


class FileBlame(TypedDict):
    lines: list[LineBlame]
    path: str


class Blame:
    def __init__(self, client: hglib.client.hgclient, cwd=None):
        self.client = client
        self._cwd = cwd
        self.users: list[str] = []
        self.blame: BlameData = {}

    @property
    def cwd(self):
        if self._cwd is None:
            return self.client.root()
        else:
            return mozpath.join(self.client.root(), self._cwd.encode("utf-8"))

    def file_path_relative(self, file_path):
        if self._cwd is None:
            return file_path
        check_val = f"{self._cwd}"
        if file_path.startswith(check_val):
            return file_path[len(check_val) + 1 :]
        return file_path

    def attribution(self, file_paths: Iterable[str]) -> BlameResult:
        args = cmdbuilder(
            b"annotate",
            *[b(p) for p in file_paths],
            template="json",
            date=True,
            user=True,
            cwd=self.cwd,
        )
        blame_json = self.client.rawcommand(args)
        file_blames = json.loads(blame_json)

        for file_blame in file_blames:
            self.handleFile(file_blame)

        return {"authors": self.users, "blame": self.blame}

    def handleFile(self, file_blame: FileBlame):
        path = mozpath.normsep(self.file_path_relative(file_blame["path"]))

        try:
            parser = getParser(path)
        except UserWarning:
            return

        self.blame[path] = {}

        self.readFile(parser, path)
        entities = parser.parse()
        for e in entities:
            if isinstance(e, Junk):
                continue
            if e.val_span:
                key_vals: list[tuple[str, str]] = [(e.key, e.val_span)]
            else:
                key_vals = []
            if isinstance(e, FluentEntity):
                key_vals += [
                    (f"{e.key}.{attr.key}", cast(str, attr.val_span))
                    for attr in e.attributes
                ]
            for key, (val_start, val_end) in key_vals:
                entity_lines = file_blame["lines"][
                    (e.ctx.linecol(val_start)[0] - 1) : e.ctx.linecol(val_end)[0]
                ]
                # ignore timezone
                entity_lines.sort(key=lambda blame: -blame["date"][0])
                line_blame = entity_lines[0]
                user = line_blame["user"]
                timestamp = line_blame["date"][0]  # ignore timezone
                if user not in self.users:
                    self.users.append(user)
                userid = self.users.index(user)
                self.blame[path][key] = cast(Tuple[int, float], [userid, timestamp])

    def readFile(self, parser, path: str):
        parser.readFile(os.path.join(self.cwd.decode("utf-8"), path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("file_path", nargs="+")
    args = parser.parse_args()
    blame = Blame(hglib.open(args.repo_path))
    attrib = blame.attribution(args.file_path)
    print(json.dumps(attrib, indent=4, separators=(",", ": ")))
