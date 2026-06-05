"""
populate_pg.py
Bulk-loads CSV data directly into PostgreSQL, bypassing Odoo ORM.
Assumes a cold-start database (no prior data), so no existence checks needed.
- Genres: XML-RPC (custom model)
- Books, customers, orders: psycopg2 batch inserts, state='sale' directly
"""
import csv
import json
import time
import xmlrpc.client
from collections import defaultdict
from pathlib import Path

import psycopg2
import psycopg2.extras

DATA_DIR = Path(__file__).parent.parent / 'data'
PG_DSN   = "host=mydb dbname=mydb user=odoo password=myodoo"
URL      = 'http://web:8069'
DB       = 'mydb'
PASSWORD = 'admin'

# ---------- Load CSVs ----------
books      = list(csv.DictReader(open(DATA_DIR / 'books.csv',     encoding='utf-8')))
customers  = list(csv.DictReader(open(DATA_DIR / 'customers.csv', encoding='utf-8')))
orders_raw = list(csv.DictReader(open(DATA_DIR / 'orders.csv',    encoding='utf-8')))
print(f'CSV: {len(books)} libros, {len(customers)} clientes, {len(orders_raw)} líneas')

# ---------- XML-RPC (genres only) ----------
print('Conectando a Odoo...')
common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
uid = None
for attempt in range(30):
    try:
        uid = common.authenticate(DB, 'admin', PASSWORD, {})
        if uid:
            print(f'Autenticado como uid={uid}')
            break
    except Exception as e:
        print(f'  intento {attempt + 1}: {e}')
    time.sleep(10)
if not uid:
    raise SystemExit('No se pudo autenticar con Odoo.')

mp = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')

def rpc(model, method, args=None, kw=None, retries=3):
    for i in range(retries):
        try:
            return mp.execute_kw(DB, uid, PASSWORD, model, method, args or [], kw or {})
        except ConnectionResetError:
            if i == retries - 1:
                raise
            time.sleep(5)

# ---------- PostgreSQL ----------
conn = psycopg2.connect(PG_DSN)
cur  = conn.cursor()

# System defaults
cur.execute("SELECT id FROM res_company ORDER BY id LIMIT 1")
company_id = cur.fetchone()[0]

cur.execute("SELECT uom_id FROM product_template WHERE uom_id IS NOT NULL LIMIT 1")
uom_id = cur.fetchone()[0]

cur.execute("SELECT id, currency_id FROM product_pricelist WHERE active = true ORDER BY id LIMIT 1")
row = cur.fetchone()
if row is None:
    cur.execute("SELECT currency_id FROM res_company ORDER BY id LIMIT 1")
    currency_id = cur.fetchone()[0]
    cur.execute("""
        INSERT INTO product_pricelist
            (name, active, currency_id, company_id, create_uid, write_uid, create_date, write_date)
        VALUES (%s::jsonb, true, %s, %s, %s, %s, NOW(), NOW())
        RETURNING id
    """, (json.dumps({'en_US': 'Tarifa pública'}), currency_id, company_id, uid, uid))
    pricelist_id = cur.fetchone()[0]
else:
    pricelist_id, currency_id = row

cur.execute("SELECT code FROM res_lang WHERE active = true ORDER BY id LIMIT 1")
lang = cur.fetchone()[0]

cur.execute("SELECT id FROM product_category WHERE name = 'Libros' LIMIT 1")
book_categ_id = cur.fetchone()[0]

cur.execute("SELECT id FROM product_public_category WHERE name::jsonb->>'en_US' = 'Libros' LIMIT 1")
pub_categ_books_id = cur.fetchone()[0]

# ---------- Genres via XML-RPC ----------
print('Creando géneros...')
GENRE_HIERARCHY = {}
for b in books:
    parent = b['parent_genre']
    genre  = b['genre']
    sub    = b.get('sub_genre', '').strip()
    GENRE_HIERARCHY.setdefault(parent, {})
    GENRE_HIERARCHY[parent].setdefault(genre, [])
    if sub and sub not in GENRE_HIERARCHY[parent][genre]:
        GENRE_HIERARCHY[parent][genre].append(sub)

genre_ids         = {}  # name -> book.genre id
pub_categ_ids_map = {}  # name -> product.public.category id

def create_genre(name, parent_id=None, pub_parent_id=None, sequence=10):
    pub_vals = {'name': name}
    if pub_parent_id:
        pub_vals['parent_id'] = pub_parent_id
    pub_id = rpc('product.public.category', 'create', [pub_vals])
    pub_categ_ids_map[name] = pub_id

    genre_vals = {'name': name, 'website_published': True,
                  'sequence': sequence, 'public_categ_id': pub_id}
    if parent_id:
        genre_vals['parent_id'] = parent_id
    gid = rpc('book.genre', 'create', [genre_vals])
    genre_ids[name] = gid
    return gid

for seq, (parent_name, genres) in enumerate(GENRE_HIERARCHY.items(), start=1):
    parent_gid    = create_genre(parent_name, sequence=seq * 10)
    parent_pub_id = pub_categ_ids_map[parent_name]
    for child_seq, (genre_name, sub_genres) in enumerate(genres.items(), start=1):
        genre_gid    = create_genre(genre_name, parent_id=parent_gid,
                                    pub_parent_id=parent_pub_id, sequence=child_seq * 10)
        genre_pub_id = pub_categ_ids_map[genre_name]
        for sub_seq, sub_name in enumerate(sub_genres, start=1):
            create_genre(sub_name, parent_id=genre_gid,
                         pub_parent_id=genre_pub_id, sequence=sub_seq * 10)

print(f'  {len(genre_ids)} géneros')

# ---------- Books via psycopg2 ----------
print('Creando libros...')
books_to_insert = []
book_csv_ids    = []
for book in books:
    genre_name     = book['genre']
    sub_genre_name = book.get('sub_genre', '').strip()
    books_to_insert.append((
        json.dumps({'en_US': book['title']}), 'consu', float(book['price']),
        book_categ_id, uom_id,
        book['author'], book['isbn'],
        genre_ids.get(genre_name),
        genre_ids.get(sub_genre_name) if sub_genre_name else None,
        int(book['pages']), book['publisher'], int(book['year']),
        json.dumps({'en_US': book['description']}),
        True, True, True, True,  # is_published, is_book, active, sale_ok
        f"{book['year']}-01-01",  # publish_date
        uid, uid,
    ))
    book_csv_ids.append(book['id'])

psycopg2.extras.execute_values(
    cur,
    """INSERT INTO product_template
           (name, type, list_price, categ_id, uom_id,
            book_author, book_isbn, book_genre_id, book_sub_genre_id,
            book_pages, book_publisher, book_year, description_sale,
            is_published, is_book, active, sale_ok, service_tracking, tracking,
            base_unit_count,
            publish_date,
            create_uid, write_uid, create_date, write_date)
       VALUES %s RETURNING id""",
    books_to_insert,
    template="(%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,'no','none',1.0,%s,%s,%s,NOW(),NOW())",
)
new_tmpl_ids = [r[0] for r in cur.fetchall()]

psycopg2.extras.execute_values(cur, """
    INSERT INTO product_product
        (product_tmpl_id, active, combination_indices, create_uid, write_uid, base_unit_count, create_date, write_date)
    VALUES %s
""", [(tid, True, '', uid, uid) for tid in new_tmpl_ids],
    template="(%s,%s,%s,%s,%s,1.0,NOW(),NOW())")

# many2many: genre public category + root "Libros"
m2m_rows = []
for book_row, tmpl_id in zip(books, new_tmpl_ids):
    genre_pub_id = pub_categ_ids_map.get(book_row['genre'])
    for pub_id in {pub_categ_books_id, genre_pub_id} - {None}:
        m2m_rows.append((tmpl_id, pub_id))
psycopg2.extras.execute_values(cur, """
    INSERT INTO product_public_category_product_template_rel
        (product_template_id, product_public_category_id)
    VALUES %s
""", m2m_rows)

book_product_ids = dict(zip(book_csv_ids, new_tmpl_ids))
conn.commit()
print(f'  {len(book_product_ids)} libros')

# Variant ids: book_id -> product.product id
cur.execute(
    "SELECT product_tmpl_id, id FROM product_product WHERE product_tmpl_id = ANY(%s)",
    (new_tmpl_ids,)
)
tmpl_to_variant  = {r[0]: r[1] for r in cur.fetchall()}
product_variant_ids = {
    book_id: tmpl_to_variant[tmpl_id]
    for book_id, tmpl_id in book_product_ids.items()
    if tmpl_id in tmpl_to_variant
}
book_price_map = {b['id']: float(b['price']) for b in books}

# ---------- Customers via psycopg2 ----------
print('Creando clientes...')
customers_to_insert = []
customer_csv_ids    = []
for customer in customers:
    customers_to_insert.append((
        customer['name'], customer['email'], customer['phone'],
        customer['street'], customer['city'], customer['zip'],
        1, True, False, lang,  # customer_rank, active, is_company, lang
        uid, uid,
    ))
    customer_csv_ids.append(customer['id'])

psycopg2.extras.execute_values(
    cur,
    """INSERT INTO res_partner
           (name, email, phone, street, city, zip,
            customer_rank, active, is_company, lang,
            autopost_bills,
            create_uid, write_uid, create_date, write_date)
       VALUES %s RETURNING id""",
    customers_to_insert,
    template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ask',%s,%s,NOW(),NOW())",
)
customer_partner_ids = dict(zip(customer_csv_ids, (r[0] for r in cur.fetchall())))
conn.commit()
print(f'  {len(customer_partner_ids)} clientes')

# ---------- Orders via psycopg2 ----------
print('Creando pedidos...')
order_groups = defaultdict(list)
for row in orders_raw:
    order_groups[row['order_id']].append(row)

orders_vals    = []
orders_lines   = []  # parallel list of line_data per order
skipped = 0

for lines in order_groups.values():
    partner_id = customer_partner_ids.get(lines[0]['customer_id'])
    if not partner_id:
        skipped += 1
        continue

    line_data = [
        (product_variant_ids[line['book_id']],
         int(line['qty']),
         book_price_map[line['book_id']])
        for line in lines
        if line['book_id'] in product_variant_ids
    ]
    if not line_data:
        skipped += 1
        continue

    amount = sum(qty * price for _, qty, price in line_data)
    orders_vals.append((
        partner_id, partner_id, partner_id,  # partner_id, partner_invoice_id, partner_shipping_id
        lines[0]['date'] + ' 12:00:00',
        'sale', company_id, pricelist_id, currency_id, uid,
        amount, 0.0, amount,  # amount_untaxed, amount_tax, amount_total
        'to invoice',
        uid, uid,
    ))
    orders_lines.append(line_data)

psycopg2.extras.execute_values(
    cur,
    """INSERT INTO sale_order
           (name, partner_id, partner_invoice_id, partner_shipping_id,
            date_order, state, company_id, pricelist_id, currency_id, user_id,
            amount_untaxed, amount_tax, amount_total, invoice_status,
            picking_policy,
            create_uid, write_uid, create_date, write_date)
       VALUES %s RETURNING id""",
    orders_vals,
    template="('/',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'direct',%s,%s,NOW(),NOW())",
)
new_order_ids = [r[0] for r in cur.fetchall()]

cur.execute(
    "UPDATE sale_order SET name = 'S' || id::text WHERE id = ANY(%s)",
    (new_order_ids,)
)

lines_vals = []
for order_id, line_data in zip(new_order_ids, orders_lines):
    for seq, (variant_id, qty, price) in enumerate(line_data, start=1):
        subtotal = qty * price
        lines_vals.append((
            order_id, seq * 10, variant_id, qty, price, uom_id,
            subtotal, 0.0, subtotal,  # price_subtotal, price_tax, price_total
            'sale', company_id, 'to invoice',
            uid, uid,
        ))

psycopg2.extras.execute_values(
    cur,
    """INSERT INTO sale_order_line
           (order_id, sequence, product_id, product_uom_qty, price_unit, product_uom_id,
            price_subtotal, price_tax, price_total,
            state, company_id, invoice_status,
            name, customer_lead,
            create_uid, write_uid, create_date, write_date)
       VALUES %s""",
    lines_vals,
    template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'/',0,%s,%s,NOW(),NOW())",
)

cur.execute("""
    UPDATE sale_order_line sol
    SET name = pt.name
    FROM product_product pp
    JOIN product_template pt ON pt.id = pp.product_tmpl_id
    WHERE sol.product_id = pp.id
      AND sol.order_id = ANY(%s)
""", (new_order_ids,))

conn.commit()
conn.close()

print(f'  {len(new_order_ids)} pedidos, {skipped} omitidos, {len(lines_vals)} líneas')
print('Población completa. Ahora ve a Librería → Entrenar Modelos en el backend de Odoo.')
