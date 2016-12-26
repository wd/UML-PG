drop table products_uselsss cascade;
drop table customers cascade;
drop table products cascade;
drop table orders cascade;

drop table others.products cascade;
drop schema schema_test cascade;

create schema others;

create table customers (
    customer_id bigserial primary key,
    name varchar(20) default '',
    name_ldap varchar(20) not null,
    card_no varchar(11) not null,
    sex char check(sex IN ('M', 'F')),
    unique(name_ldap),
    unique(card_no)
);

comment on column customers.sex is 'Sex type for customer, Female or Male';
comment on column customers.name_ldap is 'User id in LDAP, everyone should be have a unique LDAP name';


create table products (
    product_id bigserial primary key,
    name varchar(100) not null
);

create table orders (
    order_id serial primary key,
    product_id bigint references products(product_id),
    customer_id bigint references customers(customer_id)
);

create table products_useless (
    useless boolean default true
) inherits (products);

create table others.products (
    product_id bigserial primary key,
    name varchar(100) not null,
    customer_id bigint references customers(customer_id)
);
