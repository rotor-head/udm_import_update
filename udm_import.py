#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright 2019 Univention GmbH
#
# http://www.univention.de/
#
# All rights reserved.
#
# The source code of this program is made available
# under the terms of the GNU Affero General Public License version 3
# (GNU AGPL V3) as published by the Free Software Foundation.
#
# Binary versions of this program provided by Univention to you as
# well as other copyrighted, protected or trademarked materials like
# Logos, graphics, fonts, specific documentations and configurations,
# cryptographic keys etc. are subject to a license agreement between
# you and Univention.
#
# This program is provided in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License with the Debian GNU/Linux or Univention distribution in file
# /usr/share/common-licenses/AGPL-3; if not, see
# <http://www.gnu.org/licenses/>.

"""
Command line tool to import (create/modify/remove) UDM objects defined in a
CSV file in UCS.

https://github.com/univention/udm_import

Dependencies:
- python3-univention-directory-manager (for univention.udm)
- python3-click (install with: univention-install python3-click)
- python3-magic (install with: univention-install python3-magic)

Version: 2025-08-08 (Fixes ImportError for TextIO, supports univentionPasswordRecoveryEmail)
"""

import csv
import sys
import codecs
import io

try:
    from univention.udm import UDM, CreateError, ModifyError, NoObject, NoSuperordinate, UnknownModuleType, UnknownProperty
except ImportError:
    print('This script requires UCS version 4.3 erratum 313 or higher with python3-univention-directory-manager.')
    print('Run "lsb_release -a" to get Linux distribution and version information.')
    sys.exit(1)

try:
    import magic
except ImportError:
    print('The Python library "python3-magic" is required.')
    print('Run "univention-install python3-magic" to install it.')
    sys.exit(1)

try:
    import click
except ImportError:
    print('The Python library "python3-click" is required.')
    print('Run "univention-install python3-click" to install it.')
    sys.exit(1)

try:
    from typing import Any, BinaryIO, Callable, Dict, Iterable, Iterator, List, Optional, Union, TextIO
    from io import TextIOWrapper
    from univention.udm import BaseModuleTV, BaseObjectTV
except ImportError as exc:
    print(f'Warning: Failed to import typing or univention.udm types: {exc}. Using Any for type hints.')
    from typing import Any, BinaryIO, Callable, Dict, Iterable, Iterator, List, Optional, Union, TextIO
    from io import TextIOWrapper
    BaseModuleTV = Any
    BaseObjectTV = Any


@click.command()
@click.argument('udm_module')
@click.argument('action', type=click.Choice(['create', 'modify', 'remove']))
@click.argument('filename', type=click.Path(exists=True))
@click.pass_context
def main(ctx, udm_module: str, action: str, filename: str) -> None:
    """
    UDM_MODULE is the name of a UDM module like "users/user", "groups/group" etc.
    To see all possible values run "udm modules" on the command line.

    ACTION is "create", "modify" or "remove".

    FILENAME is the CSV file to read.
    """
    print('Running udm_import.py version 2025-08-08')
    res = UdmImport(udm_module, action, filename).do_import()
    ctx.exit(res)


class UdmImport:
    obj_non_props = ['dn', 'options', 'policies', 'position', 'superordinate']

    def __init__(self, udm_module_name: str, action: str, filename: str) -> None:
        self.udm_module_name = udm_module_name
        self.action = action
        self.filename = filename
        udm = UDM.admin().version(2)
        try:
            self.mod: Any = udm.get(self.udm_module_name)
        except UnknownModuleType as exc:
            Log.fatal(f'Could not load UDM module {self.udm_module_name!r}. Error: {exc}')
        Log.good(f'Loaded UDM module {self.udm_module_name!r}.')

    def do_import(self) -> int:
        reader = CsvReader(self.filename)
        rows = list(reader.read())
        # Log.debug(f'rows=\n{"\n".join([repr(row) for row in rows])}')

        if not rows:
            Log.fatal('File contains no data.')
        Log.info(f'Found {len(rows)!r} rows in {self.filename!r}.')

        self.check_preconditions(rows)
        labels = {
            'create': ('Creating', 'Created'),
            'modify': ('Modifying', 'Modified'),
            'remove': ('Removing', 'Removed'),
        }[self.action]
        errors = 0
        with click.progressbar(rows, label=f'{labels[0]} {self.udm_module_name} objects', show_pos=True) as bar:
            for row in bar:
                try:
                    dn = self.exec_admin(row)
                    Log.good(f' -> {dn!r}', lb=True)
                except (CreateError, ModifyError, NoObject) as exc:
                    errors += 1
                    Log.error(f'{exc}', lb=True)
                    continue
                except UnknownProperty as exc:
                    Log.fatal(f'{exc}. Use "udm {self.udm_module_name}" to see known attributes.\nRow: {row!r}')

        # TODO: wait_for_replication:
        # import /usr/lib/nagios/plugins/check_univention_replication
        # run its main() while returns != 0 and timeout not hit
        log = Log.error if errors else Log.good
        log(f'{labels[1]} {len(rows) - errors} {self.udm_module_name} objects. {errors} errors.')
        return 1 if errors else 0

    def check_preconditions(self, rows: List[Dict[str, str]]) -> None:
        if self.action == 'create' and 'dn' in rows[0].keys():
            Log.fatal(f'Column "dn" not allowed with operation {self.action!r}.')
        if self.action in ('modify', 'remove'):
            id_prop = self.mod.meta.identifying_property
            if id_prop not in rows[0].keys() and 'dn' not in rows[0].keys():
                Log.fatal(f'Column {id_prop!r} or "dn" required with operation {self.action!r}.')
        if self.action in ('create', 'modify'):
            try:
                known_props = self.obj_non_props + list(self.mod.new().props.__dict__.keys())
            except NoSuperordinate:
                # handle UnknownProperty during import
                pass
            else:
                unknown_columns = [key for key in rows[0].keys() if key not in known_props]
                if unknown_columns:
                    Log.fatal(
                        f'Unknown properties: {unknown_columns!r}. Use "udm {self.udm_module_name}" to see known attributes.')

    @classmethod
    def set_attrs(cls, obj: Any, row: Dict[str, str]) -> None:
        for k, v in row.items():
            if k in cls.obj_non_props:
                setattr(obj, k, v)
            else:
                setattr(obj.props, k, v)

    def get_obj(self, row: Dict[str, str]) -> Any:
        if 'dn' in row:
            return self.mod.get(row['dn'])
        else:
            id_prop = self.mod.meta.identifying_property
            return self.mod.get_by_id(row[id_prop])

    def create(self, row: Dict[str, str]) -> str:
        obj = self.mod.new()
        self.set_attrs(obj, row)
        obj.save()
        return obj.dn

    def modify(self, row: Dict[str, str]) -> str:
        obj = self.get_obj(row)
        self.set_attrs(obj, row)
        obj.save()
        return obj.dn

    def remove(self, row: Dict[str, str]) -> str:
        obj = self.get_obj(row)
        dn = obj.dn
        obj.delete()
        return obj.dn

    def exec_admin(self, row: Dict[str, str]) -> str:
        meth = {
            'create': self.create,
            'modify': self.modify,
            'remove': self.remove
        }[self.action]
        return meth(row)


class Log:
    @staticmethod
    def _log(msg: str, color: str, lb: bool = False) -> None:
        message = f'\n{msg}' if lb else msg
        click.secho(message, fg=color)

    @classmethod
    def debug(cls, msg: str, lb: bool = False) -> None:
        cls._log(msg, 'blue', lb)

    @classmethod
    def info(cls, msg: str, lb: bool = False) -> None:
        cls._log(msg, 'reset', lb)

    @classmethod
    def error(cls, msg: str, lb: bool = False) -> None:
        cls._log(msg, 'red', lb)

    @classmethod
    def fatal(cls, msg: str, exit_code: int = 1) -> None:
        cls._log(msg, 'red', True)
        sys.exit(exit_code)

    @classmethod
    def good(cls, msg: str, lb: bool = False) -> None:
        cls._log(msg, 'green', lb)


class CsvReader:
    """
    Blatantly copied (and adapted) from
    ucs-school-import/modules/ucsschool/importer/reader/csv_reader.py
    """
    encoding = "utf-8"

    def __init__(self, filename: str) -> None:
        """
        :param str filename: Path to file with user data.
        """
        self.filename = filename
        self.fieldnames: Iterable[str] = []

    @staticmethod
    def get_encoding(filename_or_file: Union[str, BinaryIO, TextIO]) -> str:
        """
        Get encoding of file ``filename_or_file``.

        Handles both magic libraries and TextIOWrapper input.

        :param filename_or_file: filename, open binary file, or open text file
        :type filename_or_file: str, BinaryIO, or TextIO
        :return: encoding of filename_or_file
        :rtype: str
        """
        print(f'Debug: Entering get_encoding with {filename_or_file}')
        if isinstance(filename_or_file, str):
            with open(filename_or_file, 'rb') as fp:
                txt = fp.read()
        else:
            # Handle TextIOWrapper or BinaryIO
            if isinstance(filename_or_file, TextIOWrapper):
                # Convert text file to binary by reopening
                with open(filename_or_file.name, 'rb') as fp:
                    txt = fp.read()
            else:
                # Assume BinaryIO
                old_pos = filename_or_file.tell()
                txt = filename_or_file.read()
                filename_or_file.seek(old_pos)
        try:
            if hasattr(magic, 'from_file'):
                encoding = magic.Magic(mime_encoding=True).from_buffer(txt)
            elif hasattr(magic, 'detect_from_filename'):
                encoding = magic.detect_from_content(txt).encoding
            else:
                raise RuntimeError('Unknown version or type of "magic" library.')
            print(f'Debug: python3-magic detected encoding: {encoding}')
        except Exception as exc:
            print(f'Warning: Failed to detect encoding with python3-magic: {exc}. Falling back to utf-8.')
            encoding = 'utf-8'
        # Auto-detect utf-8 with BOM
        if encoding == 'utf-8' and txt.startswith(b'\xef\xbb\xbf'):
            encoding = 'utf-8-sig'
            print('Debug: Detected UTF-8 BOM, using utf-8-sig')
        return encoding

    @staticmethod
    def get_dialect(fp: BinaryIO) -> csv.Dialect:
        """
        Overwrite me to force a certain CSV dialect.

        :param file fp: open file to read from
        :return: CSV dialect
        :rtype: csv.Dialect
        """
        with open(fp.name, 'r', encoding='utf-8') as text_fp:
            return csv.Sniffer().sniff(text_fp.readline())

    def read(self) -> Iterator[Dict[str, str]]:
        """
        Generate dicts from a CSV file.

        :return: iterator over list of dicts
        :rtype: Iterator
        """
        with click.open_file(self.filename, "r", encoding=None) as fp:
            try:
                dialect = self.get_dialect(fp)
            except csv.Error as exc:
                Log.fatal(f'Could not determine CSV dialect. Error: {exc}')
            fp.seek(0)
            encoding = self.get_encoding(fp)
            Log.info(f'Reading {click.format_filename(self.filename)} with encoding {encoding!r}.')
            with open(self.filename, 'r', encoding=encoding) as fpu:
                reader = csv.DictReader(fpu, dialect=dialect)
                self.fieldnames = reader.fieldnames
                for row in reader:
                    yield {
                        key.strip(): (value or "").strip()
                        for key, value in row.items()
                    }


class UTF8Recoder:
    """
    Iterator that reads an encoded stream and reencodes the input to UTF-8.
    Simplified for Python 3.11 using native text file handling.
    """

    def __init__(self, f: BinaryIO, encoding: str) -> None:
        self.reader = open(f.name, 'r', encoding=encoding)

    def __iter__(self) -> 'UTF8Recoder':
        return self

    def __next__(self) -> str:
        return self.reader.readline()


if __name__ == '__main__':
    main()