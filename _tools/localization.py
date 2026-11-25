"""Read preferred game text and overlay exact English IDs when configured."""
import os
import sqlite3
import struct

from config import LOCALE, REFERENCE_DB

FALLBACKS = ('enUS', 'zhTW', 'zhCN', 'jaJP', 'koKR', 'thTH', 'viVN')
_REFERENCE_CONNECTIONS = {}


def decode_text(value):
    if not isinstance(value, bytes) or len(value) < 4:
        return ''
    length = struct.unpack_from('<I', value)[0]
    return value[4:4 + length].decode('utf-8', 'replace')


def _columns(connection, table):
    table = table.replace('"', '""')
    return {row[1] for row in connection.execute(f'pragma table_info("{table}")')}


def language_column(connection, table):
    cols = _columns(connection, table)
    for locale in dict.fromkeys((LOCALE, *FALLBACKS)):
        col = '__BIN__' + locale
        if col in cols:
            return col
    return None


def _table_exists(connection, table):
    return bool(connection.execute('select 1 from sqlite_master where type="table" and name=?', (table,)).fetchone())


def _read_column(connection, table, column):
    table = table.replace('"', '""')
    column = column.replace('"', '""')
    out = {}
    for key, value in connection.execute(f'select id, "{column}" from "{table}"'):
        text = decode_text(value)
        if text:
            out[key] = text
    return out


def _reference_connection(target_connection):
    if not REFERENCE_DB:
        return None
    target_path = next((row[2] for row in target_connection.execute('pragma database_list') if row[1] == 'main'), '')
    if not target_path:
        return None
    reference_path = os.path.join(REFERENCE_DB, os.path.basename(target_path))
    if not os.path.isfile(reference_path):
        return None
    reference_path = os.path.normcase(os.path.abspath(reference_path))
    if reference_path not in _REFERENCE_CONNECTIONS:
        uri = 'file:' + reference_path.replace('\\', '/') + '?mode=ro'
        _REFERENCE_CONNECTIONS[reference_path] = sqlite3.connect(uri, uri=True)
    return _REFERENCE_CONNECTIONS[reference_path]


def language_texts(connection, table):
    """Return key -> text, preferring configured locale and exact English ID matches.

    The TW client stores zhTW/zhCN. If enUS is requested and a reference English
    client is configured, its enUS values override the TW fallback for matching IDs.
    Unmatched TW-only IDs retain the TW text.
    """
    out = {}
    if _table_exists(connection, table):
        col = language_column(connection, table)
        if col:
            out.update(_read_column(connection, table, col))
    if LOCALE == 'enUS':
        reference = _reference_connection(connection)
        if reference and _table_exists(reference, table) and '__BIN__enUS' in _columns(reference, table):
            out.update(_read_column(reference, table, '__BIN__enUS'))
    return out

