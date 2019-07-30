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

    {%- set show_table = True -%}
    {%- if related_tables and oid not in related_tables -%}
        {%- set show_table = False -%}
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
                <tr><td colspan="3">{{ check.cons_src | replace('>', '&gt;') | replace('<', '&lt;') }}</td></tr>
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
<title>{{ db_name }}</title>
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
    overflow: auto;
    height: 100%;
}
</style>
</head>
<body>
<div class='menu'>
<div style='float:right'>
    <span onClick='toggle_menu(this)'>close</span><span> | </span>
    <span onClick='toggle_pin(this)'>unpin</span>
</div>
<div style='float:left' class='real_menu'>
    {% set ns = namespace(prev_schema='') -%}
    {%- for oid, table in tables.items() -%}
        {%- set show_table = True -%}
        {%- if related_tables and oid not in related_tables -%}
            {%- set show_table = False -%}
        {%- endif -%}

        {% if show_table %}

        {%- set curr_schema = table.schema -%}
        {%- if curr_schema != ns.prev_schema -%}
        {%- if ns.prev_schema != '' -%}</ul>{%- endif -%}
    <span>{{ curr_schema }}</span>
    <ul>
        {%- endif -%}
        <li><a href='#{{ table.outputname | replace('.', '_') }}'>{{ table.tablename }}</a></li>
        {%- set ns.prev_schema = curr_schema -%}{{ prev_schema }}
        {%- endif -%}
    {% endfor %}
    {%- if ns.prev_schema != '' -%}</ul>{%- endif -%}
</div>
</div>

    {% for oid, table in tables.items() -%}

    {%- set show_table = True -%}
    {%- if related_tables and oid not in related_tables -%}
        {%- set show_table = False -%}
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
        $(".menu .real_menu").toggle();
        if ( $(me).text() == 'close' ) {
            $(me).text('open');
        } else{
            $(me).text('close');
        }
    }

    function toggle_pin(me) {
        if ( $(me).text() == 'unpin' ) {
            $(me).text('pin');
            $(".menu").css('position', 'absolute');
        } else{
            $(me).text('unpin');
            $(".menu").css('position', 'fixed');
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
