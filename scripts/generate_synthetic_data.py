"""
generate_synthetic_data.py
Genera datos sintéticos para la librería:
  - data/books.csv      (120 libros, 10 géneros)
  - data/customers.csv  (300 clientes españoles)
  - data/orders.csv     (~2000 pedidos con preferencias de género por cliente)
"""

import csv
import random
from pathlib import Path

import pandas as pd
from faker import Faker

fake = Faker("es_ES")
random.seed(42)
Faker.seed(42)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


books = pd.read_csv("data/books.csv").to_dict(orient="records")
GENRES = list(set(b["genre"] for b in books))

# --- Clientes ---
customers = []
for i in range(10):
    preferred = random.sample(range(len(GENRES)), k=random.randint(2, 3))
    customers.append(
        {
            "id": i + 1,
            "name": fake.name(),
            "email": fake.unique.email(),
            "phone": fake.phone_number(),
            "street": fake.street_address(),
            "city": fake.city(),
            "zip": fake.postcode(),
            "preferred_genres": "|".join(str(g) for g in preferred),
        }
    )

with open(DATA_DIR / "customers.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=customers[0].keys())
    writer.writeheader()
    writer.writerows(customers)

print(f"Generados {len(customers)} clientes → data/customers.csv")

# --- Pedidos ---
genre_books = {g: [b for b in books if b["genre"] == g] for g in GENRES}

order_rows = []
order_id = 1
for customer in customers:
    preferred_idxs = [int(g) for g in customer["preferred_genres"].split("|")]
    preferred_genres = [GENRES[i] for i in preferred_idxs]
    n_orders = random.randint(1, 12)

    for _ in range(n_orders):
        if random.random() < 0.8:
            genre = random.choice(preferred_genres)
            pool = genre_books.get(genre, books)
        else:
            pool = books

        n_items = random.randint(1, 4)
        chosen = random.sample(pool, min(n_items, len(pool)))
        for book in chosen:
            order_rows.append(
                {
                    "order_id": order_id,
                    "customer_id": customer["id"],
                    "product_id": book["id"],
                    "qty": random.randint(1, 2),
                    "date": fake.date_between(
                        start_date="-2y", end_date="today"
                    ).isoformat(),
                }
            )
        order_id += 1

with open(DATA_DIR / "orders.csv", "w", newline="", encoding="utf-8") as fin:
    writer = csv.DictWriter(
        fin,
        fieldnames=[
            "order_id",
            "customer_id",
            "product_id",
            "qty",
            "date",
        ],
    )
    writer.writeheader()
    writer.writerows(order_rows)

print(f"Generados {order_id - 1} pedidos → data/orders.csv")
