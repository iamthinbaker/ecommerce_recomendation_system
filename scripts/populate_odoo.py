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


def execute(model, method, args=None, kwargs=None, retries=3):
    for attempt in range(retries):
        try:
            return models.execute_kw(DB, uid, PASSWORD, model, method, args or [], kwargs or {})
        except ConnectionResetError:
            if attempt == retries - 1:
                raise
            time.sleep(5)


# --- Cargar CSVs ---
books = list(csv.DictReader(open(DATA_DIR / 'books.csv', encoding='utf-8')))
customers = list(csv.DictReader(open(DATA_DIR / 'customers.csv', encoding='utf-8')))
orders_raw = list(csv.DictReader(open(DATA_DIR / 'orders.csv', encoding='utf-8')))

print(f'CSV cargados: {len(books)} libros, {len(customers)} clientes, {len(orders_raw)} líneas de pedido')

# Jerarquía 3 niveles: parent_genre → genre → [sub_genre]
GENRE_HIERARCHY = {}
for b in books:
    parent = b['parent_genre']
    genre = b['genre']
    sub = b.get('sub_genre', '').strip()
    GENRE_HIERARCHY.setdefault(parent, {})
    GENRE_HIERARCHY[parent].setdefault(genre, [])
    if sub and sub not in GENRE_HIERARCHY[parent][genre]:
        GENRE_HIERARCHY[parent][genre].append(sub)

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

for seq, (parent_name, genres) in enumerate(GENRE_HIERARCHY.items(), start=1):
    parent_gid = get_or_create_genre(parent_name, sequence=seq * 10)
    parent_pub_id = pub_categ_ids_map[parent_name]
    for child_seq, (genre_name, sub_genres) in enumerate(genres.items(), start=1):
        genre_gid = get_or_create_genre(
            genre_name,
            parent_id=parent_gid,
            pub_parent_id=parent_pub_id,
            sequence=child_seq * 10,
        )
        genre_pub_id = pub_categ_ids_map[genre_name]
        for sub_seq, sub_name in enumerate(sub_genres, start=1):
            get_or_create_genre(
                sub_name,
                parent_id=genre_gid,
                pub_parent_id=genre_pub_id,
                sequence=sub_seq * 10,
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

# Fetch all existing books in one batch to avoid per-book XML-RPC calls
all_isbns = [b['isbn'] for b in books]
existing_books = execute(
    'product.template', 'search_read',
    [[['book_isbn', 'in', all_isbns]]],
    {'fields': ['id', 'book_isbn']}
)
existing_isbn_map = {r['book_isbn']: r['id'] for r in existing_books}
# Pre-fill ids for books that already exist
for book in books:
    if book['isbn'] in existing_isbn_map:
        book_product_ids[book['id']] = existing_isbn_map[book['isbn']]

books_to_create = []
book_ids_pending = []
for book in books:
    if book['id'] in book_product_ids:
        continue
    genre_name = book['genre']
    sub_genre_name = book.get('sub_genre', '').strip()
    child_pub_id = pub_categ_ids_map.get(genre_name)
    pub_cats = list({pub_categ_books_id, child_pub_id} - {None})
    books_to_create.append({
        'name': book['title'],
        'type': 'consu',
        'list_price': float(book['price']),
        'categ_id': book_categ_id,
        'public_categ_ids': [[6, 0, pub_cats]],
        'book_author': book['author'],
        'book_isbn': book['isbn'],
        'book_genre_id': genre_ids.get(genre_name),
        'book_sub_genre_id': genre_ids.get(sub_genre_name) if sub_genre_name else None,
        'book_pages': int(book['pages']),
        'book_publisher': book['publisher'],
        'book_year': int(book['year']),
        'description_sale': book['description'],
        'website_published': True,
        'is_published': True,
    })
    book_ids_pending.append(book['id'])

for i in range(0, len(books_to_create), BATCH_SIZE):
    chunk_vals = books_to_create[i:i + BATCH_SIZE]
    chunk_ids = book_ids_pending[i:i + BATCH_SIZE]
    new_pids = execute('product.template', 'create', [chunk_vals])
    if isinstance(new_pids, int):
        new_pids = [new_pids]
    for book_id, pid in zip(chunk_ids, new_pids):
        book_product_ids[book_id] = pid

print(f'  {len(book_product_ids)} libros creados/existentes')

# --- Clientes (res.partner) ---
print('Creando clientes...')
customer_partner_ids = {}

all_emails = [c['email'] for c in customers]
existing_partners = execute(
    'res.partner', 'search_read',
    [[['email', 'in', all_emails]]],
    {'fields': ['id', 'email']}
)
existing_email_map = {r['email']: r['id'] for r in existing_partners}
for customer in customers:
    if customer['email'] in existing_email_map:
        customer_partner_ids[customer['id']] = existing_email_map[customer['email']]

customers_to_create = []
customer_ids_pending = []
for customer in customers:
    if customer['id'] in customer_partner_ids:
        continue
    customers_to_create.append({
        'name': customer['name'],
        'email': customer['email'],
        'phone': customer['phone'],
        'street': customer['street'],
        'city': customer['city'],
        'zip': customer['zip'],
        'customer_rank': 1,
    })
    customer_ids_pending.append(customer['id'])

for i in range(0, len(customers_to_create), BATCH_SIZE):
    chunk_vals = customers_to_create[i:i + BATCH_SIZE]
    chunk_ids = customer_ids_pending[i:i + BATCH_SIZE]
    new_pids = execute('res.partner', 'create', [chunk_vals])
    if isinstance(new_pids, int):
        new_pids = [new_pids]
    for customer_id, pid in zip(chunk_ids, new_pids):
        customer_partner_ids[customer_id] = pid

print(f'  {len(customer_partner_ids)} clientes creados/existentes')

# --- Variantes de producto (product.product) ---
print('Resolviendo variantes de producto...')
product_variant_ids = {}
book_price_map = {b['id']: float(b['price']) for b in books}
tmpl_id_to_book_id = {tmpl_id: book_id for book_id, tmpl_id in book_product_ids.items()}
all_tmpl_ids = list(book_product_ids.values())
all_variants = execute(
    'product.product', 'search_read',
    [[['product_tmpl_id', 'in', all_tmpl_ids]]],
    {'fields': ['id', 'product_tmpl_id']}
)
for v in all_variants:
    book_id = tmpl_id_to_book_id.get(v['product_tmpl_id'])
    if book_id and book_id not in product_variant_ids:
        product_variant_ids[book_id] = v['id']

# --- Pedidos (sale.order) ---
print('Creando pedidos...')
order_groups = defaultdict(list)
for row in orders_raw:
    order_groups[row['order_id']].append(row)

BATCH_SIZE = 500
all_order_vals = []
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

    all_order_vals.append({
        'partner_id': partner_id,
        'date_order': lines[0]['date'] + ' 12:00:00',
        'order_line': order_lines,
    })

created = 0
for i in range(0, len(all_order_vals), BATCH_SIZE):
    chunk = all_order_vals[i:i + BATCH_SIZE]
    oids = execute('sale.order', 'create', [chunk])
    execute('sale.order', 'action_confirm', [oids])
    created += len(oids)
    print(f'  {created}/{len(all_order_vals)} pedidos creados...')

print(f'Población completa: {created} pedidos creados, {skipped} omitidos.')
print('Ahora ve a Librería → Entrenar Modelos en el backend de Odoo.')
