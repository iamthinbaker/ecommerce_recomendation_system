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

from faker import Faker

fake = Faker('es_ES')
random.seed(42)
Faker.seed(42)

DATA_DIR = Path(__file__).parent.parent / 'data'
DATA_DIR.mkdir(exist_ok=True)

# Jerarquía de géneros: padre → lista de hijos
# Un libro pertenece a un género hijo; en la homepage aparecerá
# también bajo la sección del padre (secciones no disjuntas).
GENRE_HIERARCHY = {
    'Ficción': ['Novela', 'Ciencia Ficción', 'Fantasía', 'Misterio'],
    'No Ficción': ['Historia', 'Biografía', 'Autoayuda', 'Poesía'],
    'Para Todos': ['Infantil', 'Cocina'],
}

# Lista plana de géneros hoja (los que se asignan a los libros)
GENRES = [child for children in GENRE_HIERARCHY.values() for child in children]

TITLE_TEMPLATES = {
    'Novela': [
        lambda: f'{fake.last_name()} y el {fake.word()}',
        lambda: f'La {fake.word().capitalize()}',
        lambda: f'El {fake.word().capitalize()} de {fake.city()}',
        lambda: f'Los {fake.word().capitalize()}s perdidos',
    ],
    'Historia': [
        lambda: f'Historia de {fake.country()}',
        lambda: f'La Gran {fake.word().capitalize()}',
        lambda: f'{fake.last_name()}: Una Crónica',
        lambda: f'El Siglo de {fake.last_name()}',
    ],
    'Ciencia Ficción': [
        lambda: f'El {fake.word().capitalize()} del Futuro',
        lambda: f'Galaxia {fake.last_name()}',
        lambda: f'Año {random.randint(2100, 3000)}',
        lambda: f'Los Últimos {fake.word().capitalize()}s',
    ],
    'Fantasía': [
        lambda: f'El Señor de {fake.city()}',
        lambda: f'La Espada de {fake.last_name()}',
        lambda: f'Dragones de {fake.country()}',
        lambda: f'El Reino de {fake.city()}',
    ],
    'Misterio': [
        lambda: f'El Caso {fake.last_name()}',
        lambda: f'La Sombra de {fake.city()}',
        lambda: f'Muerte en {fake.city()}',
        lambda: f'El Secreto de {fake.last_name()}',
    ],
    'Biografía': [
        lambda: f'{fake.name()}: Mi Vida',
        lambda: f'Memorias de {fake.last_name()}',
        lambda: f'El Camino de {fake.first_name()}',
        lambda: f'La Vida de {fake.name()}',
    ],
    'Autoayuda': [
        lambda: f'El Poder de {fake.word().capitalize()}',
        lambda: f'Cambia tu {fake.word().capitalize()}',
        lambda: f'Hábitos de {fake.word().capitalize()}',
        lambda: f'La Mente {fake.word().capitalize()}',
    ],
    'Infantil': [
        lambda: f'El {fake.word().capitalize()} Mágico',
        lambda: f'Aventuras de {fake.first_name()}',
        lambda: f'{fake.first_name()} en el Bosque',
        lambda: f'El Gran {fake.word().capitalize()}',
    ],
    'Poesía': [
        lambda: f'Versos de {fake.city()}',
        lambda: f'Oda a {fake.word().capitalize()}',
        lambda: f'Cantos de {fake.last_name()}',
        lambda: f'El {fake.word().capitalize()} Eterno',
    ],
    'Cocina': [
        lambda: f'La Cocina de {fake.country()}',
        lambda: f'{random.randint(50, 500)} Recetas',
        lambda: f'Sabores de {fake.city()}',
        lambda: f'El Arte de {fake.word().capitalize()}',
    ],
}


def generate_isbn():
    digits = [random.randint(0, 9) for _ in range(12)]
    check = (10 - sum((i % 2 + 1) * d for i, d in enumerate(digits))) % 10
    return '978' + ''.join(str(d) for d in digits[:9]) + str(check % 10)


# --- Libros ---
# Mapa inverso: género hijo → padre
GENRE_PARENT = {
    child: parent
    for parent, children in GENRE_HIERARCHY.items()
    for child in children
}

books = []
for i in range(120):
    genre = GENRES[i % len(GENRES)]
    template_fn = random.choice(TITLE_TEMPLATES[genre])
    books.append({
        'id': i + 1,
        'title': template_fn(),
        'author': fake.name(),
        'isbn': generate_isbn(),
        'genre': genre,
        'parent_genre': GENRE_PARENT[genre],
        'price': round(random.uniform(8.95, 24.95), 2),
        'pages': random.randint(120, 800),
        'publisher': fake.company(),
        'year': random.randint(1990, 2024),
        'description': fake.paragraph(nb_sentences=3),
    })

with open(DATA_DIR / 'books.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=books[0].keys())
    writer.writeheader()
    writer.writerows(books)

print(f'Generados {len(books)} libros → data/books.csv')

# --- Clientes ---
customers = []
for i in range(300):
    preferred = random.sample(range(len(GENRES)), k=random.randint(2, 3))
    customers.append({
        'id': i + 1,
        'name': fake.name(),
        'email': fake.unique.email(),
        'phone': fake.phone_number(),
        'street': fake.street_address(),
        'city': fake.city(),
        'zip': fake.postcode(),
        'preferred_genres': '|'.join(str(g) for g in preferred),
    })

with open(DATA_DIR / 'customers.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=customers[0].keys())
    writer.writeheader()
    writer.writerows(customers)

print(f'Generados {len(customers)} clientes → data/customers.csv')

# --- Pedidos ---
genre_books = {g: [b for b in books if b['genre'] == g] for g in GENRES}

order_rows = []
order_id = 1
for customer in customers:
    preferred_idxs = [int(g) for g in customer['preferred_genres'].split('|')]
    preferred_genres = [GENRES[i] for i in preferred_idxs]
    n_orders = random.randint(3, 12)

    for _ in range(n_orders):
        if random.random() < 0.8:
            genre = random.choice(preferred_genres)
            pool = genre_books.get(genre, books)
        else:
            pool = books

        n_items = random.randint(1, 4)
        chosen = random.sample(pool, min(n_items, len(pool)))
        for book in chosen:
            order_rows.append({
                'order_id': order_id,
                'customer_id': customer['id'],
                'book_id': book['id'],
                'qty': random.randint(1, 2),
                'date': fake.date_between(start_date='-2y', end_date='today').isoformat(),
            })
        order_id += 1

with open(DATA_DIR / 'orders.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['order_id', 'customer_id', 'book_id', 'qty', 'date'])
    writer.writeheader()
    writer.writerows(order_rows)

print(f'Generados {order_id - 1} pedidos → data/orders.csv')
