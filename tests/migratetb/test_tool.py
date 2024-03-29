import unittest
import os
from os.path import join, relpath
import shutil
import tempfile

from fluent.migratetb.repo_client import git
from fluent.migratetb.tool import Migrator
import hglib


class TestSerialize(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.root = join(self.repo, "de")
        os.makedirs(self.root)
        self.migrator = Migrator(
            "de",
            join(self.root, "reference"),
            join(self.root, "localization"),
            False,
        )

    def tearDown(self):
        self.migrator.close()
        shutil.rmtree(self.root)

    def test_empty(self):
        self.migrator.serialize_changeset({})
        self.assertEqual(os.listdir(self.root), [])

    def test_dry(self):
        self.migrator.dry_run = True
        self.migrator.serialize_changeset(
            {
                "d/f": "a line of text\n",
            }
        )
        self.assertEqual(os.listdir(self.root), [])

    def test_wet(self):
        self.migrator.serialize_changeset(
            {
                "d1/f1": "a line of text\n",
                "d2/f2": "a different line of text\n",
            }
        )
        # Walk our serialized localization dir, but
        # make the directory be relative to our root.
        walked = sorted(
            (relpath(dir, self.root), sorted(dirs), sorted(files))
            for dir, dirs, files in os.walk(self.root)
        )
        self.assertEqual(
            walked,
            [
                (".", ["localization"], []),
                ("localization", ["de"], []),
                ("localization/de", ["d1", "d2"], []),
                ("localization/de/d1", [], ["f1"]),
                ("localization/de/d2", [], ["f2"]),
            ],
        )


class TestHgCommit(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.migrator = Migrator(
            "de",
            join(self.root, "reference"),
            join(self.root, "localization"),
            False,
        )
        loc_dir = join(self.migrator.localization_dir, "d1")
        os.makedirs(loc_dir)
        with open(join(loc_dir, "f1"), "w") as f:
            f.write("first line\n")
        client = hglib.init(join(self.root, "localization"))
        client.open()
        client.commit(
            message="Initial commit",
            user="Jane",
            addremove=True,
        )
        client.close()

    def tearDown(self):
        self.migrator.close()
        shutil.rmtree(self.root)

    def test_wet(self):
        """Hg commit message docstring, part {index}."""
        with open(join(self.migrator.localization_dir, "d1", "f1"), "a") as f:
            f.write("second line\n")
        self.migrator.commit_changeset(self.test_wet.__doc__, "Axel", 2)
        tip = self.migrator.client.hgclient.tip()
        self.assertEqual(tip.rev, b"1")
        self.assertEqual(tip.author, b"Axel")
        self.assertEqual(tip.desc, b"Hg commit message docstring, part 2.")


class TestGitCommit(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.migrator = Migrator(
            "de",
            join(self.root, "reference"),
            join(self.root, "localization"),
            False,
        )

        dir = self.migrator.localization_dir
        loc_dir = join(dir, "d1")
        os.makedirs(loc_dir)
        with open(join(loc_dir, "f1"), "w") as f:
            f.write("first line\n")

        git(dir, "init")
        git(dir, "config", "user.name", "Anon")
        git(dir, "config", "user.email", "anon@example.com")
        git(dir, "add", ".")
        git(
            dir,
            "commit",
            "--author=Jane <jane@example.com>",
            "--message=Initial commit",
        )

    def tearDown(self):
        self.migrator.close()
        shutil.rmtree(self.root)

    def test_wet(self):
        """Git commit message docstring, part {index}."""
        with open(join(self.migrator.localization_dir, "d1", "f1"), "a") as f:
            f.write("second line\n")
        self.migrator.commit_changeset(
            self.test_wet.__doc__, "Axel <axel@example.com>", 2
        )
        stdout = git(
            self.migrator.client.root, "show", "--no-patch", "--pretty=format:%an:%s"
        )
        self.assertEqual(stdout, "Axel:Git commit message docstring, part 2.")
