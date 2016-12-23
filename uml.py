#!/usr/bin/env python
# -*- coding: utf-8 -*-

import psycopg2
import traceback
import argparse
import sys
import logging
import re
from jinja2 import Template

default_logging_level = logging.WARNING

SQL_TABLES = '''
    select
        pg_class.oid,
        nspname as schema,
        relname as tablename,
        pg_catalog.obj_description(pg_class.oid, 'pg_class') as table_description,
        case
           when relkind = 'r' then
             'table'
           when relkind = 'v' then
             'view'
           when relkind = 'm' then
             'materialized view'
           else
             'foreign table'
           end as reltype
    from
        pg_catalog.pg_class
    join
        pg_catalog.pg_namespace on (relnamespace = pg_namespace.oid)
    where
        relkind in ('r', 'v', 'm', 'f')
        and nspname !~ 'pg_catalog|pg_toast|pg_temp_[0-9]+|information_schema'
'''
SQL_TABLES += ' and pg_class.oid in (34328, 19930423, 35358, 35601, 24474327, 37183, 34864, 34423, 34987)'

SQL_COLUMNS = '''
    select
        a.oid,
        b.table_schema as schema,
        b.table_name,
        b.column_name,
        col_description( a.oid, ordinal_position ) as desc,
        b.udt_name || coalesce( '(' || character_maximum_length || ')', '' ) as column_type,
        is_nullable,
        column_default
    from
        pg_catalog.pg_class a
        join information_schema.columns b
    on
        a.relname = b.table_name
        and b.table_schema not in ( 'pg_catalog', 'information_schema')
    join
        pg_catalog.pg_namespace c
    on
        a.relnamespace=c.oid and b.table_schema=c.nspname
    order by
        b.table_schema, b.table_name, b.ordinal_position
'''

SQL_PK_UK = '''
    select
        c.conrelid as oid,
        conname AS constraint_name,
        pg_catalog.pg_get_indexdef(d.objid) AS constraint_definition,
        case
          when contype = 'p' then
            'PK'
          else
            'UK'
          end as constraint_type
    from
        pg_catalog.pg_constraint as c
    join
        pg_catalog.pg_depend as d
    on
        d.refobjid = c.oid
    where
        contype in ('p', 'u')
'''

SQL_FK = '''
    select
        pct.conrelid as oid,
        case when substring(pct.conname from 1 for 1) = '\$' then ''
            else pct.conname
            end as constraint_name,
        pa.attname as constraint_key,
        paf.attname as constraint_fkey,
        confrelid as ref_oid
    from
        pg_catalog.pg_constraint pct
    join pg_catalog.pg_class on (pg_class.oid = conrelid)
    join pg_catalog.pg_class as pc on (pc.oid = confrelid)
    join pg_catalog.pg_attribute as pa on (pa.attnum = pct.conkey[1] and pa.attrelid = conrelid)
    join pg_catalog.pg_attribute as paf on (paf.attnum = pct.confkey[1] and paf.attrelid = confrelid)
'''

SQL_INHERIT = '''
    select
        parnsp.nspname as par_schemaname,
        parcla.relname as par_tablename,
        chlnsp.nspname as chl_schemaname,
        chlcla.relname as chl_tablename,
    from pg_catalog.pg_inherits
    join pg_catalog.pg_class as chlcla on (chlcla.oid = inhrelid)
    join pg_catalog.pg_namespace as chlnsp on (chlnsp.oid = chlcla.relnamespace)
    join pg_catalog.pg_class as parcla on (parcla.oid = inhparent)
    join pg_catalog.pg_namespace as parnsp on (parnsp.oid = parcla.relnamespace)
'''

SQL_CHECKS = '''
    select
        pct.conrelid as oid,
        case when substring(pct.conname from 1 for 1) = '\$' then ''
            else pct.conname
            end as constraint_name,
        consrc
    from
        pg_catalog.pg_constraint pct,
        pg_catalog.pg_class
    where
        pg_class.oid = conrelid and contype = 'c'
'''

DOT_TEMPLATE = '''
digraph G {
    node [shape=plaintext];
    edge [color=red];
    rankdir={{ rankdir }};

    {% for oid, table in tables.items() -%}

    {%- set show_table = False -%}
    {%- if related_tables -%}
      {%- if oid in related_tables -%}
        {%- set show_table = True -%}
      {%- endif -%}
    {%- else -%}
      {%- set show_table = True -%}
    {%- endif -%}

    {%- if show_table %}
    {{ table.tablename }} [
        label = <
            <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">
                <TR><TD BGCOLOR="yellow" ALIGN="center" COLSPAN="2">{{ table.tablename }}</TD></TR>
                <tr><td colspan="2" height="1"></td></tr>
              {% for column in table.columns -%}

                {%- set show_col = False -%}
                {%- if oid in simple_columns -%}
                  {%- if column.colname in simple_columns[oid] -%}
                    {%- set show_col = True -%}
                  {%- endif -%}
                {%- else -%}
                  {%- set show_col = True -%}
                {%- endif -%}

                {%- if show_col %}
                <TR><TD ALIGN="LEFT" PORT="{{ column.colname }}">
                        {%- if column.colname == table.pk %}* {% endif %}{{ column.colname }}</TD>
                    <TD ALIGN="LEFT">{{ column.coltype }}</TD>
                </TR>
                {% endif -%}

              {%- endfor %}
                <tr><td colspan="2" height="1"></td></tr>
              {%- for uk in table.uk %}
                <tr><td colspan="2">Unique({{ uk.columns }})</td></tr>
              {%- endfor %}
            </TABLE>
        >
    ];
    {% endif -%}
    {%- endfor %}

    {% for fk in fks -%}
        {{ fk.from_table}}:{{ fk.from_col }} -> {{ fk.to_table }}:{{ fk.to_col }};
    {% endfor %}
}
'''


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
        self.uml_tree_tables = {}
        self.uml_fks = []
        self.uml_simple_columns = {}
        self.uml_related_tables = set()

        self.simple = opts.simple
        self.only_related = opts.only_related
        self.dot_rankdir = opts.dot_rankdir
        self.format = opts.format

    def _collect_data(self):
        self._process_tables()
        self._process_columns()
        self._process_pk_uk()
        self._process_fk()

    def _process_tables(self):
        rows = self.db.execute_sql(SQL_TABLES)
        for row in rows:
            oid, schema, tablename, tabledesc, reltype = row
            self.uml_simple_columns[oid] = set()
            self.uml_tree_tables[oid] = {
                'schema': schema,
                'tablename': tablename,
                'tabledesc': tabledesc,
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
            if oid not in self.uml_tree_tables:
                continue
            columns = self.uml_tree_tables[oid]['columns']
            columns.append({
                'colname': colname,
                'coldesc': coldesc,
                'coltype': coltype,
                'is_nullable': is_nullable,
                'coldefault': coldefault
            })

    def _process_pk_uk(self):
        rows = self.db.execute_sql(SQL_PK_UK)
        pattern = '.*ON (.*) USING.*\((.*)\)'
        for row in rows:
            oid, cons_name, cons_def, cons_type = row
            if oid not in self.uml_tree_tables:
                continue
            match = re.match(pattern, cons_def)
            if not match:
                raise "Can't pase index define: {}".format(cons_def)

            columns = match.group(2)
            if cons_type == 'PK':
                self.uml_tree_tables[oid]['pk'] = columns  # one pk in one table
            else:
                self.uml_tree_tables[oid]['uk'].append({
                    'cons_name': cons_name,
                    'columns': columns
                })

            for col in columns.split(', '):
                self.uml_simple_columns[oid].add(col)

    def _process_fk(self):
        rows = self.db.execute_sql(SQL_FK)
        for row in rows:
            from_oid, _, from_col_name, to_col_name, to_oid = row
            if from_oid not in self.uml_tree_tables:
                continue
            self.uml_fks.append({
                'from_table': self.uml_tree_tables[from_oid]['tablename'],
                'from_col': from_col_name,
                'to_table': self.uml_tree_tables[to_oid]['tablename'],
                'to_col': to_col_name
            })
            self.uml_simple_columns[from_oid].add(from_col_name)
            self.uml_simple_columns[to_oid].add(to_col_name)
            self.uml_related_tables.add(from_oid)
            self.uml_related_tables.add(to_oid)

    def _as_dot(self):
        template = Template(DOT_TEMPLATE)
        dot = template.render(
            tables=self.uml_tree_tables,
            fks=self.uml_fks,
            simple_columns=self.uml_simple_columns if self.simple else set(),
            related_tables=self.uml_related_tables if self.only_related else None,
            rankdir=self.dot_rankdir
        )
        return dot

    def _out_digraph(self):
        if self.format == 'dot':
            dot = self._as_dot()
            print(dot)
        else:
            print('Not support yet.')

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
    parser.add_argument('--simple', help='Only show fk and pk columns for table', action="store_true")
    parser.add_argument('--only-related', help='Only show related tables', action="store_true")
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
