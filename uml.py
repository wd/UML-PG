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
    order by nspname, relname
'''
# SQL_TABLES += ' and pg_class.oid in (34328, 19930423, 35358, 35601, 24474327, 37183, 34864, 34423, 34987)'

SQL_COLUMNS = '''
    select
        a.oid,
        b.table_schema as schema,
        b.table_name,
        b.column_name,
        col_description( a.oid, ordinal_position ) as desc,
        b.udt_name || coalesce( '(' || character_maximum_length || ')', '' ) as column_type,
        case is_nullable when 'YES' then True else False end as is_nullable,
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
        parcla.oid as par_oid,
        parnsp.nspname as par_schemaname,
        parcla.relname as par_tablename,
        chlcla.oid as cll_oid,
        chlnsp.nspname as chl_schemaname,
        chlcla.relname as chl_tablename
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
    {{ table.outputname | replace('.', '_') }} [
        label = <
            <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">
                <TR><TD BGCOLOR="yellow" ALIGN="center" COLSPAN="3">{{ table.outputname }}</TD></TR>
                <tr><td colspan="3" height="1"></td></tr>
              {% for column in table.columns -%}

                {%- set show_col = False -%}
                {%- if oid in key_columns -%}
                  {%- if column.colname in key_columns[oid] -%}
                    {%- set show_col = True -%}
                  {%- endif -%}
                {%- else -%}
                  {%- set show_col = True -%}
                {%- endif -%}

                {%- if show_col %}
                <TR>
                    <TD ALIGN="LEFT" PORT="{{ column.colname }}">
                        {%- if column.colname == table.pk %}#{% elif not column.is_nullable %}*{% endif -%}
                    </TD>
                    <TD ALIGN="LEFT">{{ column.colname }}</TD>
                    <TD ALIGN="LEFT">{{ column.coltype }}</TD>
                </TR>
                {% endif -%}

              {%- endfor %}
              {%- if table.uk -%}
                <tr><td colspan="3" height="1"></td></tr>
              {%- endif -%}
              {%- for uk in table.uk %}
                <tr><td colspan="3">Unique({{ uk.columns }})</td></tr>
              {%- endfor %}

              {%- if show_constraint -%}
              {%- if table.checks -%}
                <tr><td colspan="3" height="1"></td></tr>
              {%- endif -%}
              {%- for check in table.checks %}
                <tr><td colspan="3">{{ check.cons_src }}</td></tr>
              {%- endfor -%}
              {%- endif %}
            </TABLE>
        >
    ];
    {% endif -%}
    {%- endfor %}

    {% for from_table_col, to_table_col in fks.items() -%}
        {{ from_table_col }} -> {{ to_table_col }};
    {% endfor -%}

    {% for ih in table_inherits -%}
        {{ ih.par_outputname|replace('.', '_') }}
           -> {{ ih.chl_outputname|replace('.', '_') }}[color="blue" style="dashed"];
    {% endfor %}
}
'''

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN" class="">
<head>
<meta charset="utf-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1" />
<meta name="renderer" content="webkit" />
<title>UML-PG</title>
<script
  src="https://code.jquery.com/jquery-3.1.1.min.js"
  integrity="sha256-hVVnYaiADRTO2PzUGmuLJr8BLUSjGIZsDYGmIJLv2b8="
  crossorigin="anonymous"></script>
<style type="text/css">
table {
    border-collapse:collapse;
    position:relative;
    margin-top:1em;
    margin-bottom:1em;
    border:0;
}

table th,table td {
    line-height:18px;
    padding:8px 12px;
}

table td {
    text-align:left;
}

table th {
    background-color:#2A7AD2 !important;
    color:#fff;
    text-align:center;
}

table tbody th,table tbody td,table tfoot th,table tfoot td {
    border-bottom:solid 1px #eee;
}

table tbody tr:nth-child(odd) th,table tbody tr:nth-child(odd) td {
    background:#FAFDFE;
}

a {
    margin:0;
    padding:0;
    border:0;
    font-size:100%;
    vertical-align:baseline;
    background:transparent;
    outline:none;
    color: #329ECC;
    text-decoration:none;
    border-bottom:1px solid #A1CFD4;
}

a:hover, a:focus, a:active {
    background-color:#E2EFFF;
    border-bottom:1px solid #329ECC;
}

.menu {
    position:fixed;
    float:right;
    right:0;
    top:0;
    z-index:10000;
    background-color:#f0f0f0;
}
</style>
</head>
<body>
<div class='menu'>
<div style='float:right' onclick='toggle_menu(this)'>close</div>
<div style='float:left'>


    {% for oid, table in tables.items() -%}
        {%- set curr_schema = table.schema -%}
        {%- if curr_schema != prev_schema -%}
        {%- if prev_schema != '' -%}</ul>{%- endif -%}
    <span>{{ curr_schema }}</span>
    <ul>
        {%- endif -%}
        <li><a href='#{{ table.outputname | replace('.', '_') }}'>{{ table.tablename }}</a></li>
        {%- set prev_schema = curr_schema -%}
    {% endfor %}
    {%- if prev_schema != '' -%}</ul>{%- endif -%}
</div>
</div>

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
        <div class="tbl">
            <h2 id="{{ table.outputname | replace('.', '_') }}">{{ table.outputname }}</h2>
            <TABLE>
                <tr><th></th><th>Column</th><th>Type</th><th>Description</th></tr>
              {% for column in table.columns -%}

                {%- set show_col = False -%}
                {%- if oid in key_columns -%}
                  {%- if column.colname in key_columns[oid] -%}
                    {%- set show_col = True -%}
                  {%- endif -%}
                {%- else -%}
                  {%- set show_col = True -%}
                {%- endif -%}

                {%- if show_col -%}
                {%- set from_table_col = table.outputname.replace('.', '_') ~ ":" ~ column.colname %}
                <TR>
                    <TD>
                        {%- if column.colname == table.pk %}#{% elif not column.is_nullable %}*{% endif -%}
                    </TD>
                    <TD id="{{ from_table_col }}">
                        {%- if from_table_col in fks -%}
                          {%- set to_table_col = fks[from_table_col] -%}
                          <a href="#{{ to_table_col }}" title="{{ to_table_col }}">{{ column.colname }}</a>
                        {%- else -%}
                          {{ column.colname }}</TD>
                        {%- endif %}
                    <TD>{{ column.coltype }}</TD>
                    <TD>{{ column.coldesc }}</TD>
                </TR>
                {% endif -%}

              {%- endfor %}
              {%- if table.uk -%}
                <tr><td colspan="4" height="1"></td></tr>
              {%- endif -%}
              {%- for uk in table.uk %}
                <tr><td colspan="4">Unique({{ uk.columns }})</td></tr>
              {%- endfor %}

              {%- if show_constraint -%}
              {%- if table.checks -%}
                <tr><td colspan="4" height="1"></td></tr>
              {%- endif -%}
              {%- for check in table.checks %}
                <tr><td colspan="4">{{ check.cons_src }}</td></tr>
              {%- endfor -%}
              {%- endif %}
            </TABLE>
        </div>
    {% endif -%}
    {%- endfor %}
</body>
<script type = "text/javascript">
    function toggle_menu(me) {
        $(".menu ul").toggle();
        if ( $(me).text() == 'close' ) {
            $(me).text('open');
        } else{
            $(me).text('close');
        }
    }

    $('a').click(function() {
        var arr = this.href.split('#');
        var id = arr[arr.length-1];
        var par = $(document.getElementById(id)).parent();
        par.fadeOut();
        par.fadeIn();
    });
</script>
</html>
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
            if oid not in self.uml_tables:
                continue
            columns = self.uml_tables[oid]['columns']
            columns.append({
                'colname': colname,
                'coldesc': coldesc or '',
                'coltype': coltype,
                'is_nullable': is_nullable,
                'coldefault': coldefault
            })

    def _process_pk_uk(self):
        rows = self.db.execute_sql(SQL_PK_UK)
        pattern = '.*ON (.*) USING.*\((.*)\)'
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
            dot = self._as_dot()
            print(dot)
        else:
            html = self._as_html()
            print(html)

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
