#!/usr/bin/env python
# -*- coding: utf-8 -*-

import psycopg2
import traceback
import argparse
import sys
import logging
import re
from collections import OrderedDict
from jinja2 import Template

from constants import SQL_TABLES, SQL_PK_UK, SQL_FK, SQL_CHECKS, SQL_COLUMNS, SQL_INHERIT, HTML_TEMPLATE, DOT_TEMPLATE

default_logging_level = logging.WARNING


class Logger():
    def __init__(self, name):
        logformat = 'uml(%(name)s): [%(levelname)s] %(message)s'

        self.logger = logging.getLogger(name or __name__)
        self.logger.setLevel(default_logging_level)
        myhandler = logging.StreamHandler(stream=sys.stdout)
        myhandler.setFormatter(logging.Formatter(logformat))
        self.logger.addHandler(myhandler)


class DB():
    def __init__(self, port, dbname, host, user, password):
        self.logger = Logger('DB').logger
        self.conn_str = "host='{}' dbname='{}' user='{}' port='{}' password='{}'".format(
            host, dbname, user, port, password)
        self.connect()

    def connect(self):
        try:
            self.conn = psycopg2.connect(self.conn_str)
            self.conn.autocommit = True
        except Exception as err:
            errmsg = 'Connect to postgres "{}" failed: {}'.format(self.conn_str, err)
            self.logger.error(errmsg)
            raise err

    def execute_sql(self, sql):
        """execute sql and return"""
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            rows = cur.fetchall()
        except Exception as err:
            msg = "select failed: {}".format(traceback.format_exc())
            self.logger.error(msg)
            raise err

        return rows

    def close(self):
        self.conn.close()


class PGUML():
    def __init__(self, opts):
        self.db = DB(dbname=opts.dbname, port=opts.port, host=opts.host, user=opts.user, password=opts.password)
        self.db_name = "{}_{}_{}".format(opts.host, opts.port, opts.dbname)
        self.uml_tables = OrderedDict()
        self.uml_fks = {}
        self.uml_key_columns = {}
        self.uml_related_tables = set()
        self.uml_table_inherits = []

        self.only_key_columns = opts.only_key_columns
        self.only_related = opts.only_related
        self.dot_rankdir = opts.dot_rankdir
        self.format = opts.format
        self.show_constraint = opts.show_constraint

    def _collect_data(self):
        self._process_tables()
        self._process_columns()
        self._process_pk_uk()
        self._process_fk()
        self._process_checks()
        self._process_inherits()

    def _process_tables(self):
        rows = self.db.execute_sql(SQL_TABLES)
        for row in rows:
            oid, schema, tablename, tabledesc, reltype = row
            self.uml_key_columns[oid] = set()
            self.uml_tables[oid] = {
                'schema': schema,
                'tablename': tablename,
                'outputname': "{}.{}".format(schema, tablename) if schema != 'public' else tablename,
                'tabledesc': tabledesc if tabledesc is not None else '',
                'reltype': reltype,
                'columns': [],
                'checks': [],
                'pk': '',
                'uk': []
            }

    def _process_columns(self):
        rows = self.db.execute_sql(SQL_COLUMNS)
        for row in rows:
            oid, schema, _, colname, coldesc, coltype, is_nullable, coldefault = row
            if oid not in self.uml_tables:
                continue
            columns = self.uml_tables[oid]['columns']
            columns.append({
                'colname': colname,
                'coldesc': coldesc if coldesc is not None else '',
                'coltype': coltype,
                'is_nullable': is_nullable,
                'coldefault': coldefault
            })

    def _process_pk_uk(self):
        rows = self.db.execute_sql(SQL_PK_UK)
        pattern = r'.*ON (.*) USING.*\((.*)\)'
        for row in rows:
            oid, cons_name, cons_def, cons_type = row
            if oid not in self.uml_tables:
                continue
            match = re.match(pattern, cons_def)
            if not match:
                raise "Can't pase index define: {}".format(cons_def)

            columns = match.group(2)
            if cons_type == 'PK':
                self.uml_tables[oid]['pk'] = columns  # one pk in one table
            else:
                self.uml_tables[oid]['uk'].append({
                    'cons_name': cons_name,
                    'columns': columns
                })

            for col in columns.split(', '):
                self.uml_key_columns[oid].add(col)

    def _process_fk(self):
        rows = self.db.execute_sql(SQL_FK)
        for row in rows:
            from_oid, _, from_col_name, to_col_name, to_oid = row
            if from_oid not in self.uml_tables:
                continue

            from_table_col = "{}:{}".format(self.uml_tables[from_oid]['outputname'].replace('.', '_'), from_col_name)
            to_table_col = "{}:{}".format(self.uml_tables[to_oid]['outputname'].replace('.', '_'), to_col_name)

            self.uml_fks[from_table_col] = to_table_col
            self.uml_key_columns[from_oid].add(from_col_name)
            self.uml_key_columns[to_oid].add(to_col_name)
            self.uml_related_tables.add(from_oid)
            self.uml_related_tables.add(to_oid)

    def _process_inherits(self):
        rows = self.db.execute_sql(SQL_INHERIT)
        for row in rows:
            par_oid, par_schema, par_table, chl_oid, chl_schema, chl_table = row
            if par_oid not in self.uml_tables:
                continue
            self.uml_table_inherits.append({
                'par_oid': par_oid,
                'par_schema': par_schema,
                'par_table': par_table,
                'par_outputname': "{}.{}".format(par_schema, par_table) if par_schema != 'public' else par_table,
                'chl_oid': chl_oid,
                'chl_schema': chl_schema,
                'chl_table': chl_table,
                'chl_outputname': "{}.{}".format(chl_schema, chl_table) if chl_schema != 'public' else chl_table,
            })

            self.uml_related_tables.add(par_oid)
            self.uml_related_tables.add(chl_oid)

    def _process_checks(self):
        rows = self.db.execute_sql(SQL_CHECKS)
        for row in rows:
            oid, cons_name, consrc = row
            if oid not in self.uml_tables:
                continue
            checks = self.uml_tables[oid]['checks']
            checks.append({
                'cons_name': cons_name,
                'cons_src': consrc
            })

    def _as_dot(self):
        template = Template(DOT_TEMPLATE)
        dot = template.render(
            tables=self.uml_tables,
            fks=self.uml_fks,
            key_columns=self.uml_key_columns if self.only_key_columns else set(),
            related_tables=self.uml_related_tables if self.only_related else None,
            rankdir=self.dot_rankdir,
            show_constraint=self.show_constraint,
            table_inherits=self.uml_table_inherits
        )
        return dot

    def _as_html(self):
        template = Template(HTML_TEMPLATE)
        html = template.render(
            db_name=self.db_name,
            tables=self.uml_tables,
            fks=self.uml_fks,
            key_columns=self.uml_key_columns if self.only_key_columns else set(),
            related_tables=self.uml_related_tables if self.only_related else None,
            rankdir=self.dot_rankdir,
            show_constraint=self.show_constraint,
            table_inherits=self.uml_table_inherits
        )
        return html

    def _out_digraph(self):
        if self.format == 'dot':
            output = self._as_dot()
        else:
            output = self._as_html()

        print(output)

    def go(self):
        self._collect_data()
        self._out_digraph()


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--host', help='Database hostname', type=str, default='127.0.0.1')
    parser.add_argument('--port', help='Database port', type=str, default='5432')
    parser.add_argument('--dbname', help='Database name', type=str, default='postgres')
    parser.add_argument('--user', help='Database user', type=str, default='user')
    parser.add_argument('--password', help='Database passowrd', type=str, default='')
    parser.add_argument('--only-key-columns', help='Only show fk and pk columns for table', action="store_true")
    parser.add_argument('--only-related', help='Only show related tables', action="store_true")
    parser.add_argument('--show-constraint', help='Show constraint', action="store_true")
    parser.add_argument('--dot-rankdir', help='Rank direction for dot output', type=str,
                        default='LR', choices=["TB", "LR", "BT", "RL"])
    parser.add_argument('--format', help='Output format', type=str, default='dot', choices=['dot', 'html'])
    parser.add_argument('--verbose', help='Output more info', action="store_true")

    opts = parser.parse_args()
    if opts.verbose:
        global default_logging_level
        default_logging_level = logging.DEBUG

    uml = PGUML(opts)
    uml.go()


if __name__ == '__main__':
    main()
