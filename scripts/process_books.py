import random
import pandas as pd

INR_TO_EUR = 0.011

PUBLISHERS = [
    "Penguin Books",
    "HarperCollins",
    "Random House",
    "Simon & Schuster",
    "Macmillan Publishers",
    "Oxford University Press",
    "Bloomsbury Publishing",
    "Hachette Livre",
    "Scholastic",
    "Vintage Books",
]

DESCRIPTIONS = [
    "Una obra maestra que redefine el género y cautiva al lector desde la primera página.",
    "Un relato profundo y emotivo que explora la condición humana con maestría literaria.",
    "Imprescindible para cualquier amante de la lectura; una historia que perdura en la memoria.",
    "Un viaje apasionante a través de ideas que transforman la manera de ver el mundo.",
    "Narración brillante que combina suspense, emoción y reflexión filosófica.",
    "Una novela que desafía convenciones y ofrece una perspectiva fresca y reveladora.",
    "Escrita con una prosa elegante, esta obra es un referente en la literatura contemporánea.",
    "Repleta de personajes complejos y giros inesperados que no te dejarán soltar el libro.",
    "Un clásico moderno que mezcla aventura, drama y crítica social de forma magistral.",
    "Cautivadora desde el primer capítulo, con un desenlace que sorprende y conmueve.",
]


def random_isbn(rng):
    digits = [rng.randint(0, 9) for _ in range(12)]
    check = (10 - sum((1 if i % 2 == 0 else 3) * d for i, d in enumerate(digits))) % 10
    return "978" + "".join(map(str, digits[:9])) + str(check)


PARENT_GENRE_MAP = {
    "Arts, Film & Photography": "Lifestyle & Leisure",
    "Biographies, Diaries & True Accounts": "Non-Fiction",
    "Business & Economics": "Business & Law",
    "Children's Books": "Children & Young Adult",
    "Comics & Mangas": "Fiction",
    "Computing, Internet & Digital Media": "Science & Technology",
    "Crafts, Home & Lifestyle": "Lifestyle & Leisure",
    "Crime, Thriller & Mystery": "Fiction",
    "Engineering": "Science & Technology",
    "Exam Preparation": "Education",
    "Fantasy, Horror & Science Fiction": "Fiction",
    "Health, Family & Personal Development": "Lifestyle & Leisure",
    "Higher Education Textbooks": "Education",
    "History": "Non-Fiction",
    "Language, Linguistics & Writing": "Education",
    "Law": "Business & Law",
    "Literature & Fiction": "Fiction",
    "Medicine & Health Sciences": "Science & Technology",
    "Politics": "Non-Fiction",
    "Reference": "Education",
    "Religion": "Non-Fiction",
    "Romance": "Fiction",
    "School Books": "Education",
    "Science & Mathematics": "Science & Technology",
    "Sciences, Technology & Medicine": "Science & Technology",
    "Society & Social Sciences": "Non-Fiction",
    "Sports": "Lifestyle & Leisure",
    "Teen & Young Adult": "Children & Young Adult",
    "Textbooks & Study Guides": "Education",
    "Travel": "Non-Fiction",
}

rng = random.Random(42)

raw = pd.read_csv("books_data.csv", index_col=0)

# Limpiar y convertir Price: quitar símbolo ₹ y convertir a euros
price = (
    raw["Price"]
    .astype(str)
    .str.replace("₹", "", regex=False)
    .str.replace(",", "", regex=False)
    .str.strip()
)
price = (pd.to_numeric(price, errors="coerce") * INR_TO_EUR).round(2)

# Popularidad y filtrado
no_rated = pd.to_numeric(raw["No. of People rated"], errors="coerce")
raw = raw.assign(price_eur=price, no_rated=no_rated)
raw = raw.sort_values("no_rated", ascending=False).head(1000)

n = len(raw)

# Construir el dataframe final con el esquema exacto
df = pd.DataFrame(
    {
        "id": range(n),
        "title": raw["Title"].values,
        "author": raw["Author"].values,
        "isbn": [random_isbn(rng) for _ in range(n)],
        "parent_genre": raw["Main Genre"].map(PARENT_GENRE_MAP).values,
        "genre": raw["Main Genre"].values,
        "sub_genre": raw["Sub Genre"].values,
        "price": raw["price_eur"].values,
        "pages": [rng.randint(80, 1200) for _ in range(n)],
        "publisher": [rng.choice(PUBLISHERS) for _ in range(n)],
        "year": [rng.randint(1950, 2023) for _ in range(n)],
        "description": [rng.choice(DESCRIPTIONS) for _ in range(n)],
    }
)

output_path = "data/books.csv"
df.to_csv(output_path, index=False)

print(f"Dataset guardado en '{output_path}'")
print(f"Filas: {len(df)}")
print(f"\nTop 5:")
print(df[["id", "title", "genre", "parent_genre", "price", "isbn"]].head())
