#!/usr/bin/env python3
"""
Seed demo sale orders for the recommendation engine.
Creates 10 customers and confirmed sale orders with varied book purchases.
Run with:  python3 /workspace/seed_demo_orders.py
"""
import xmlrpc.client
import random

URL = "http://localhost:8069"
DB = "mydb"
USER = "admin"
PASSWORD = "admin"

# ── connect ──────────────────────────────────────────────────────────────────
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USER, PASSWORD, {})
if not uid:
    raise SystemExit("Authentication failed — check URL/credentials")

models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, PASSWORD, model, method, list(args), kw)


# ── product variants (skip delivery product id=1) ────────────────────────────
product_ids = call(
    "product.product",
    "search_read",
    [["product_tmpl_id.active", "=", True], ["product_tmpl_id.id", "!=", 1]],
    fields=["id"],
    limit=80,
)
product_ids = [p["id"] for p in product_ids]
print(f"Found {len(product_ids)} product variants")

# ── create customers ─────────────────────────────────────────────────────────
CUSTOMERS = [
    "Alice Morera",
    "Bruno Fernández",
    "Clara Vidal",
    "Diego Sanz",
    "Elena Ruiz",
    "Francesc Puig",
    "Gemma Torres",
    "Hector Gil",
    "Irene Blanco",
    "Jordi Mas",
    "Karim Benali",
    "Laura Soler",
]

partner_ids = []
for name in CUSTOMERS:
    existing = call("res.partner", "search", [[["name", "=", name]]])
    if existing:
        partner_ids.append(existing[0])
        print(f"  Reusing partner: {name}")
    else:
        pid = call("res.partner", "create", {"name": name, "customer_rank": 1})
        partner_ids.append(pid)
        print(f"  Created partner: {name} (id={pid})")

# ── order patterns — each customer buys a cluster of books ───────────────────
random.seed(42)
groups = [product_ids[i : i + 15] for i in range(0, len(product_ids), 10)]

def make_order(partner_id, prods):
    order_id = call(
        "sale.order",
        "create",
        {
            "partner_id": partner_id,
            "date_order": "2025-10-01 10:00:00",
        },
    )
    for prod_id in prods:
        call(
            "sale.order.line",
            "create",
            {
                "order_id": order_id,
                "product_id": prod_id,
                "product_uom_qty": 1,
            },
        )
    # confirm the order → state = 'sale'
    call("sale.order", "action_confirm", [[order_id]])
    return order_id


order_count = 0
for i, partner_id in enumerate(partner_ids):
    # Primary cluster
    g1 = groups[i % len(groups)]
    # Overlap cluster (shared purchases create the collaborative signal)
    g2 = groups[(i + 1) % len(groups)]
    pool = list(set(g1 + g2))
    random.shuffle(pool)
    picks = pool[: random.randint(4, 8)]

    oid = make_order(partner_id, picks)
    order_count += 1
    print(f"  Order {oid} for partner {partner_id} — {len(picks)} lines")

    # Some customers have a second order for stronger signal
    if i % 3 == 0:
        picks2 = random.sample(product_ids, random.randint(3, 6))
        oid2 = make_order(partner_id, picks2)
        order_count += 1
        print(f"  Order {oid2} for partner {partner_id} (2nd) — {len(picks2)} lines")

print(f"\nDone — created {order_count} confirmed orders for {len(partner_ids)} customers.")
