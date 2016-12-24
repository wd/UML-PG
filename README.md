## Intro

A tool which can auto run through PostgreSQL system tables and returns HTML, DOT, which describe the database.

![sample2.png](https://github.com/wd/UML-PG/raw/master/sample2.png)

![sample3.png](https://github.com/wd/UML-PG/raw/master/sample3.png)

![sample1.png](https://github.com/wd/UML-PG/raw/master/sample1.png)

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

You also need a user to connect to the database, the use should be the database and all the table's owner at least. To make it more easyer, you can use a super user to run this script.

## Usage

```
$ ./uml.py -h
usage: uml.py [-h] [--host HOST] [--port PORT] [--dbname DBNAME] [--user USER]
              [--password PASSWORD] [--only-key-columns] [--only-related]
              [--show-constraint] [--dot-rankdir {TB,LR,BT,RL}]
              [--format {dot,html}] [--verbose]

optional arguments:
  -h, --help            show this help message and exit
  --host HOST           Database hostname (default: 127.0.0.1)
  --port PORT           Database port (default: 5432)
  --dbname DBNAME       Database name (default: postgres)
  --user USER           Database user (default: user)
  --password PASSWORD   Database passowrd (default: )
  --only-key-columns    Only show fk and pk columns for table (default: False)
  --only-related        Only show related tables (default: False)
  --show-constraint     Show constraint (default: False)
  --dot-rankdir {TB,LR,BT,RL}
                        Rank direction for dot output (default: LR)
  --format {dot,html}   Output format (default: dot)
  --verbose             Output more info (default: False)
```

Run command like `./uml.py --host 10.10.8.1 --only-key-columns --only-related | dot -T png -o mydb.png`, and then open `mydb.png`.

## TODO

* Need to improve HTML output

## Ref

* https://github.com/cbbrowne/autodoc
* https://github.com/chebizarro/postdia
* http://search.cpan.org/dist/UML-Class-Simple/lib/UML/Class/Simple.pm
* http://www.graphviz.org/content/dot-language

## Author

* wd ( https://wdicc.com )
