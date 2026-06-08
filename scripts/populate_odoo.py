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
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"

URL = "http://web:8069"
DB = "mydb"
USERNAME = "admin"
PASSWORD = "admin"
BATCH_SIZE = 500

# --- Conexión con retry ---
print("Conectando a Odoo...")
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = None
for attempt in range(30):
    try:
        uid = common.authenticate(DB, USERNAME, PASSWORD, {})
        if uid:
            print(f"Autenticado como uid={uid}")
            break
    except Exception as e:
        print(f"Intento {attempt + 1}/30 fallido: {e}")
    time.sleep(10)

if not uid:
    raise SystemExit("No se pudo autenticar con Odoo después de 30 intentos.")

models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def execute(
    model,
    method,
    args=None,
    kwargs=None,
    retries=3,
) -> Any:
    for attempt in range(retries):
        try:
            return models.execute_kw(
                DB,
                uid,
                PASSWORD,
                model,
                method,
                args or [],
                kwargs or {},
            )
        except ConnectionResetError:
            if attempt == retries - 1:
                raise
            time.sleep(5)


# --- Cargar CSVs ---
books = list(csv.DictReader(open(DATA_DIR / "books.csv", encoding="utf-8")))
customers = list(csv.DictReader(open(DATA_DIR / "customers.csv", encoding="utf-8")))
orders_raw = list(csv.DictReader(open(DATA_DIR / "orders.csv", encoding="utf-8")))

# Jerarquía 3 niveles: parent_genre → genre → [sub_genre]
GENRE_HIERARCHY = {}
for b in books:
    parent = b["parent_genre"]
    genre = b["genre"]
    sub = b.get("sub_genre", "").strip()
    GENRE_HIERARCHY.setdefault(parent, {})
    GENRE_HIERARCHY[parent].setdefault(genre, [])
    if sub and sub not in GENRE_HIERARCHY[parent][genre]:
        GENRE_HIERARCHY[parent][genre].append(sub)

# --- Categorías base ---
existing_categ = execute(
    "product.category", "search", [[["name", "=", "Libros"]]], {"limit": 1}
)
book_categ_id = existing_categ[0] if existing_categ else execute(
    "product.category", "create", [{"name": "Libros"}]
)

existing_pub_categ = execute(
    "product.public.category", "search", [[["name", "=", "Libros"]]], {"limit": 1}
)
pub_categ_books_id = existing_pub_categ[0] if existing_pub_categ else execute(
    "product.public.category", "create", [{"name": "Libros"}]
)

# --- Géneros y categorías públicas con jerarquía ---
print("Creando jerarquía de géneros...")
genre_ids = {}
pub_categ_ids_map = {}


def create_genre(
    name,
    parent_id=None,
    pub_parent_id=None,
    sequence=10,
):
    pub_vals = {"name": name}
    if pub_parent_id:
        pub_vals["parent_id"] = pub_parent_id
    pub_id = execute("product.public.category", "create", [pub_vals])
    pub_categ_ids_map[name] = pub_id

    genre_vals = {
        "name": name,
        "website_published": True,
        "sequence": sequence,
        "public_categ_id": pub_id,
    }
    if parent_id:
        genre_vals["parent_id"] = parent_id
    gid = execute("book.genre", "create", [genre_vals])
    genre_ids[name] = gid
    return gid


for seq, (parent_name, genres) in enumerate(GENRE_HIERARCHY.items(), start=1):
    parent_gid = create_genre(parent_name, sequence=seq * 10)
    parent_pub_id = pub_categ_ids_map[parent_name]
    for child_seq, (genre_name, sub_genres) in enumerate(genres.items(), start=1):
        genre_gid = create_genre(
            genre_name,
            parent_id=parent_gid,
            pub_parent_id=parent_pub_id,
            sequence=child_seq * 10,
        )
        genre_pub_id = pub_categ_ids_map[genre_name]
        for sub_seq, sub_name in enumerate(sub_genres, start=1):
            create_genre(
                sub_name,
                parent_id=genre_gid,
                pub_parent_id=genre_pub_id,
                sequence=sub_seq * 10,
            )

print(f"  {len(genre_ids)} géneros creados")

# --- Libros (product.template) ---
print("Creando libros...")
books_to_create = []
book_ids_pending = []
for book in books:
    genre_name = book["genre"]
    sub_genre_name = book.get("sub_genre", "").strip()
    child_pub_id = pub_categ_ids_map.get(genre_name)
    pub_cats = list({pub_categ_books_id, child_pub_id} - {None})
    books_to_create.append(
        {
            "name": book["title"],
            "type": "consu",
            "list_price": float(book["price"]),
            "categ_id": book_categ_id,
            "public_categ_ids": [[6, 0, pub_cats]],
            "book_author": book["author"],
            "book_isbn": book["isbn"],
            "book_genre_id": genre_ids.get(genre_name),
            "book_sub_genre_id": (
                genre_ids.get(sub_genre_name) if sub_genre_name else None
            ),
            "book_pages": int(book["pages"]),
            "book_publisher": book["publisher"],
            "book_year": int(book["year"]),
            "description_sale": book["description"],
            "website_published": True,
            "is_published": True,
        }
    )
    book_ids_pending.append(book["id"])

book_product_ids = {}
for i in range(0, len(books_to_create), BATCH_SIZE):
    new_pids = execute(
        "product.template", "create", [books_to_create[i : i + BATCH_SIZE]]
    )
    if isinstance(new_pids, int):
        new_pids = [new_pids]
    for book_id, pid in zip(book_ids_pending[i : i + BATCH_SIZE], new_pids):
        book_product_ids[book_id] = pid

print(f"  {len(book_product_ids)} libros creados")

# --- Clientes (res.partner) ---
print("Creando clientes...")
customers_to_create = []
customer_ids_pending = []
for customer in customers:
    customers_to_create.append(
        {
            "name": customer["name"],
            "email": customer["email"],
            "phone": customer["phone"],
            "street": customer["street"],
            "city": customer["city"],
            "zip": customer["zip"],
            "customer_rank": 1,
        }
    )
    customer_ids_pending.append(customer["id"])

customer_partner_ids = {}
for i in range(0, len(customers_to_create), BATCH_SIZE):
    new_pids = execute(
        "res.partner", "create", [customers_to_create[i : i + BATCH_SIZE]]
    )
    if isinstance(new_pids, int):
        new_pids = [new_pids]
    for customer_id, pid in zip(customer_ids_pending[i : i + BATCH_SIZE], new_pids):
        customer_partner_ids[customer_id] = pid

print(f"  {len(customer_partner_ids)} clientes creados")

# --- Variantes de producto (product.product) ---
print("Resolviendo variantes de producto...")
tmpl_id_to_book_id = {tmpl_id: book_id for book_id, tmpl_id in book_product_ids.items()}
all_variants = execute(
    "product.product",
    "search_read",
    [[["product_tmpl_id", "in", list(book_product_ids.values())]]],
    {"fields": ["id", "product_tmpl_id"]},
)
product_variant_ids = {
    tmpl_id_to_book_id[v["product_tmpl_id"][0]]: v["id"]
    for v in all_variants
    if v["product_tmpl_id"][0] in tmpl_id_to_book_id
}

# --- Pedidos (sale.order) ---
print("Creando pedidos...")
book_price_map = {b["id"]: float(b["price"]) for b in books}
order_groups = defaultdict(list)
for row in orders_raw:
    order_groups[row["order_id"]].append(row)

all_order_vals = []
skipped = 0
for lines in order_groups.values():
    partner_id = customer_partner_ids.get(lines[0]["customer_id"])
    if not partner_id:
        skipped += 1
        continue

    order_lines = [
        [
            0,
            0,
            {
                "product_id": product_variant_ids[line["product_id"]],
                "product_uom_qty": int(line["qty"]),
                "price_unit": book_price_map.get(line["product_id"], 10.0),
            },
        ]
        for line in lines
        if line["product_id"] in product_variant_ids
    ]
    if not order_lines:
        skipped += 1
        continue

    all_order_vals.append(
        {
            "partner_id": partner_id,
            "date_order": lines[0]["date"] + " 12:00:00",
            "order_line": order_lines,
        }
    )

created = 0
for i in range(0, len(all_order_vals), BATCH_SIZE):
    chunk = all_order_vals[i : i + BATCH_SIZE]
    oids = execute("sale.order", "create", [chunk])
    execute("sale.order", "action_confirm", [oids])
    created += len(oids)
    print(f"  {created}/{len(all_order_vals)} pedidos creados...")

print(f"Población completa: {created} pedidos creados, {skipped} omitidos.")
print("Ahora ve a Librería → Entrenar Modelos en el backend de Odoo.")
