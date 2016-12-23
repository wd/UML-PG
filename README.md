## Intro

A tool which can auto run through PostgreSQL system tables and returns HTML, DOT, which describe the database.

## Requirements

* Python 2 or 3
* psycopg2
* jinja2
* [Graphviz](http://www.graphviz.org/) dot command if you want to use dot to generate your UML picture.

Install python modules use `pip` command.
```
$ pip install psycopg2 jinja2
```

Install graphviz use `brew` command in MacOS.
```
$ brew install graphviz
```

## Usage

```
$ ./uml.py -h
usage: uml.py [-h] [--host HOST] [--port PORT] [--dbname DBNAME] [--user USER]
              [--password PASSWORD] [--simple] [--only-related]
              [--dot-rankdir {TB,LR,BT,RL}] [--format {dot,html}] [--verbose]

optional arguments:
  -h, --help            show this help message and exit
  --host HOST           Database hostname (default: 127.0.0.1)
  --port PORT           Database port (default: 5432)
  --dbname DBNAME       Database name (default: postgres)
  --user USER           Database user (default: user)
  --password PASSWORD   Database passowrd (default: )
  --simple              Only show fk and pk columns for table (default: False)
  --only-related        Only show related tables (default: False)
  --dot-rankdir {TB,LR,BT,RL}
                        Rank direction for dot output (default: LR)
  --format {dot,html}   Output format (default: dot)
  --verbose             Output more info (default: False)
```

Run command like `./uml.py --host 10.10.8.1 --simple --only-related | dot -T png -o mydb.png`, and then open `mydb.png`.

## TODO

* Seq, constraint, inheritance, schema test and support
* HTML output
* Sample database for test
* To make clear which permission is needed to run this script
* Support to specify schema and table name to filter output

## Ref

* https://github.com/cbbrowne/autodoc
* https://github.com/chebizarro/postdia
* http://search.cpan.org/dist/UML-Class-Simple/lib/UML/Class/Simple.pm
* http://www.graphviz.org/content/dot-language

## Author

* wd ( https://wdicc.com )
