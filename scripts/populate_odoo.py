"""
populate_odoo.py
Carga los CSVs generados en Odoo vía XML-RPC.
Se ejecuta desde dentro del contenedor Docker (accede a http://web:8069).
"""
import csv
import time
import xmlrpc.client
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'

URL = 'http://web:8069'
DB = 'mydb'
USERNAME = 'admin'
PASSWORD = 'admin'

# --- Conexión con retry ---
print('Conectando a Odoo...')
common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
uid = None
for attempt in range(30):
    try:
        uid = common.authenticate(DB, USERNAME, PASSWORD, {})
        if uid:
            print(f'Autenticado como uid={uid}')
            break
    except Exception as e:
        print(f'Intento {attempt + 1}/30 fallido: {e}')
    time.sleep(10)

if not uid:
    raise SystemExit('No se pudo autenticar con Odoo después de 30 intentos.')

models = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')


def execute(model, method, args=None, kwargs=None):
    return models.execute_kw(DB, uid, PASSWORD, model, method, args or [], kwargs or {})


# --- Cargar CSVs ---
books = list(csv.DictReader(open(DATA_DIR / 'books.csv', encoding='utf-8')))
customers = list(csv.DictReader(open(DATA_DIR / 'customers.csv', encoding='utf-8')))
orders_raw = list(csv.DictReader(open(DATA_DIR / 'orders.csv', encoding='utf-8')))

print(f'CSV cargados: {len(books)} libros, {len(customers)} clientes, {len(orders_raw)} líneas de pedido')

# Jerarquía de géneros (debe coincidir con generate_synthetic_data.py)
GENRE_HIERARCHY = {
    'Ficción': ['Novela', 'Ciencia Ficción', 'Fantasía', 'Misterio'],
    'No Ficción': ['Historia', 'Biografía', 'Autoayuda', 'Poesía'],
    'Para Todos': ['Infantil', 'Cocina'],
}

# --- Categoría interna de productos ---
categ_ids = execute('product.category', 'search', [[['name', '=', 'Libros']]])
book_categ_id = categ_ids[0] if categ_ids else execute(
    'product.category', 'create', [{'name': 'Libros'}]
)

# --- Géneros y categorías públicas con jerarquía ---
# Creamos primero los géneros padre con sus public.category padre,
# luego los géneros hijo enlazados al padre.
print('Creando jerarquía de géneros...')
genre_ids = {}           # nombre → book.genre id
pub_categ_ids_map = {}   # nombre → product.public.category id

def get_or_create_genre(name, parent_id=None, pub_parent_id=None, sequence=10):
    # Categoría pública de eCommerce
    existing_pub = execute('product.public.category', 'search_read',
                           [[['name', '=', name]]], {'fields': ['id'], 'limit': 1})
    if existing_pub:
        pub_id = existing_pub[0]['id']
    else:
        pub_vals = {'name': name}
        if pub_parent_id:
            pub_vals['parent_id'] = pub_parent_id
        pub_id = execute('product.public.category', 'create', [pub_vals])
    pub_categ_ids_map[name] = pub_id

    # book.genre
    existing = execute('book.genre', 'search_read',
                       [[['name', '=', name]]], {'fields': ['id'], 'limit': 1})
    if existing:
        gid = existing[0]['id']
        execute('book.genre', 'write', [[gid], {'public_categ_id': pub_id}])
    else:
        genre_vals = {
            'name': name,
            'website_published': True,
            'sequence': sequence,
            'public_categ_id': pub_id,
        }
        if parent_id:
            genre_vals['parent_id'] = parent_id
        gid = execute('book.genre', 'create', [genre_vals])
    genre_ids[name] = gid
    return gid

for seq, (parent_name, children) in enumerate(GENRE_HIERARCHY.items(), start=1):
    parent_gid = get_or_create_genre(parent_name, sequence=seq * 10)
    parent_pub_id = pub_categ_ids_map[parent_name]
    for child_seq, child_name in enumerate(children, start=1):
        get_or_create_genre(
            child_name,
            parent_id=parent_gid,
            pub_parent_id=parent_pub_id,
            sequence=child_seq * 10,
        )

print(f'  {len(genre_ids)} géneros creados/existentes')

# Categoría pública raíz "Libros" (para el filtro global en /shop)
existing_root_pub = execute('product.public.category', 'search_read',
                            [[['name', '=', 'Libros']]], {'fields': ['id'], 'limit': 1})
pub_categ_books_id = existing_root_pub[0]['id'] if existing_root_pub else execute(
    'product.public.category', 'create', [{'name': 'Libros'}]
)

# --- Libros (product.template) ---
print('Creando libros...')
book_product_ids = {}
for book in books:
    existing = execute('product.template', 'search_read',
                       [[['book_isbn', '=', book['isbn']]]], {'fields': ['id'], 'limit': 1})
    if existing:
        book_product_ids[book['id']] = existing[0]['id']
        continue

    genre_name = book['genre']
    genre_id = genre_ids.get(genre_name)
    # Assign to genre's public category + root "Libros" category
    child_pub_id = pub_categ_ids_map.get(genre_name)
    pub_cats = list({pub_categ_books_id, child_pub_id} - {None})

    vals = {
        'name': book['title'],
        'type': 'consu',
        'list_price': float(book['price']),
        'categ_id': book_categ_id,
        'public_categ_ids': [[6, 0, pub_cats]],
        'book_author': book['author'],
        'book_isbn': book['isbn'],
        'book_genre_id': genre_id,
        'book_pages': int(book['pages']),
        'book_publisher': book['publisher'],
        'book_year': int(book['year']),
        'description_sale': book['description'],
        'website_published': True,
        'is_published': True,
    }
    pid = execute('product.template', 'create', [vals])
    book_product_ids[book['id']] = pid

print(f'  {len(book_product_ids)} libros creados/existentes')

# --- Clientes (res.partner) ---
print('Creando clientes...')
customer_partner_ids = {}
for customer in customers:
    existing = execute('res.partner', 'search_read',
                       [[['email', '=', customer['email']]]], {'fields': ['id'], 'limit': 1})
    if existing:
        customer_partner_ids[customer['id']] = existing[0]['id']
        continue

    vals = {
        'name': customer['name'],
        'email': customer['email'],
        'phone': customer['phone'],
        'street': customer['street'],
        'city': customer['city'],
        'zip': customer['zip'],
        'customer_rank': 1,
    }
    pid = execute('res.partner', 'create', [vals])
    customer_partner_ids[customer['id']] = pid

print(f'  {len(customer_partner_ids)} clientes creados/existentes')

# --- Variantes de producto (product.product) ---
print('Resolviendo variantes de producto...')
product_variant_ids = {}
book_price_map = {b['id']: float(b['price']) for b in books}
for book_id, tmpl_id in book_product_ids.items():
    variants = execute('product.product', 'search_read',
                       [[['product_tmpl_id', '=', tmpl_id]]], {'fields': ['id'], 'limit': 1})
    if variants:
        product_variant_ids[book_id] = variants[0]['id']

# --- Pedidos (sale.order) ---
print('Creando pedidos...')
order_groups = defaultdict(list)
for row in orders_raw:
    order_groups[row['order_id']].append(row)

created = 0
skipped = 0
for order_id_str, lines in order_groups.items():
    if not lines:
        continue

    customer_id = lines[0]['customer_id']
    partner_id = customer_partner_ids.get(customer_id)
    if not partner_id:
        skipped += 1
        continue

    order_lines = []
    for line in lines:
        variant_id = product_variant_ids.get(line['book_id'])
        if not variant_id:
            continue
        order_lines.append([0, 0, {
            'product_id': variant_id,
            'product_uom_qty': int(line['qty']),
            'price_unit': book_price_map.get(line['book_id'], 10.0),
        }])

    if not order_lines:
        skipped += 1
        continue

    order_vals = {
        'partner_id': partner_id,
        'date_order': lines[0]['date'] + ' 12:00:00',
        'order_line': order_lines,
    }
    oid = execute('sale.order', 'create', [order_vals])
    execute('sale.order', 'action_confirm', [[oid]])
    created += 1

    if created % 100 == 0:
        print(f'  {created} pedidos creados...')

print(f'Población completa: {created} pedidos creados, {skipped} omitidos.')
print('Ahora ve a Librería → Entrenar Modelos en el backend de Odoo.')
